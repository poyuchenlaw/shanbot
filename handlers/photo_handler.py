"""照片上傳處理 — 收據/對帳單 OCR 辨識流程"""

import hashlib
import logging
import os
from datetime import date, datetime
from typing import Optional

import state_manager as sm

logger = logging.getLogger("shanbot.photo")

FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "files")


async def handle_photo_received(
    line_service, message_id: str, group_id: str,
    user_id: str, reply_token: str,
) -> Optional[str]:
    """完整照片處理流程：下載 → OCR → 暫存 → 回覆"""

    # 1. 下載圖片
    image_bytes = line_service.get_content(message_id)
    if not image_bytes:
        return "❌ 圖片下載失敗，請重新上傳"

    # 2. SHA256 校驗 + 儲存
    sha256 = hashlib.sha256(image_bytes).hexdigest()[:16]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{sha256}.jpg"
    os.makedirs(FILES_DIR, exist_ok=True)
    local_path = os.path.join(FILES_DIR, filename)

    with open(local_path, "wb") as f:
        f.write(image_bytes)

    logger.info(f"Image saved: {local_path} ({len(image_bytes)} bytes)")

    # 2.5 上傳收據到 GDrive
    gdrive_path = None
    try:
        from services.gdrive_service import upload_receipt
        gdrive_path = await upload_receipt(local_path)
        if gdrive_path:
            logger.info(f"Receipt uploaded to GDrive: {gdrive_path}")
    except Exception as e:
        logger.warning(f"GDrive upload skipped: {e}")

    # 3. 建立暫存記錄
    staging_id = sm.add_purchase_staging(
        user_id=user_id,
        chat_id=group_id,
        image_message_id=message_id,
        local_image_path=local_path,
        purchase_date=date.today().isoformat(),
    )

    # 3.5 更新 GDrive 路徑
    if gdrive_path:
        sm.update_purchase_staging(staging_id, gdrive_path=gdrive_path)

    # 4. OCR 辨識
    try:
        from services.ocr_service import process_image, build_review_flex
        ocr_result = process_image(local_path)
    except ImportError:
        logger.warning("OCR service not available")
        sm.update_purchase_staging(staging_id, status="pending")
        return (
            f"📸 已收到照片（#{staging_id}）\n"
            "OCR 模組尚未安裝，請手動輸入採購資料。\n"
            f"完成後輸入「確認 #{staging_id}」"
        )
    except Exception as e:
        logger.error(f"OCR error: {e}", exc_info=True)
        return f"❌ OCR 辨識發生錯誤：{str(e)}\n請重新上傳或手動記帳"

    # 5. 更新暫存記錄
    sm.update_purchase_staging(
        staging_id,
        supplier_name=ocr_result.supplier_name,
        supplier_tax_id=ocr_result.supplier_tax_id,
        invoice_prefix=ocr_result.invoice_prefix,
        invoice_number=ocr_result.invoice_number,
        invoice_type=ocr_result.invoice_type or "",
        purchase_date=ocr_result.purchase_date or date.today().isoformat(),
        subtotal=ocr_result.subtotal,
        tax_amount=ocr_result.tax_amount,
        total_amount=ocr_result.total_amount,
        raw_ocr_text=ocr_result.raw_text[:2000],
        ocr_confidence=ocr_result.confidence,
    )

    # 判斷發票格式代號 + 稅務扣抵分類
    tax_class = _classify_tax_deduction({
        "supplier_tax_id": ocr_result.supplier_tax_id,
        "invoice_type": ocr_result.invoice_type or "",
    })
    sm.update_purchase_staging(
        staging_id,
        invoice_format_code=tax_class["invoice_format_code"],
        tax_type=tax_class["tax_type"],
        deduction_code=tax_class["deduction_code"],
    )

    # 6. 儲存品項明細
    for item in ocr_result.items:
        # 嘗試匹配食材主檔
        ingredient = sm.find_ingredient(item.name)
        ingredient_id = ingredient["id"] if ingredient else None
        category = ingredient["category"] if ingredient else "其他"
        account_code = ingredient["account_code"] if ingredient else "5110"

        sm.add_purchase_item(
            staging_id=staging_id,
            item_name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            amount=item.amount,
            category=category,
            account_code=account_code,
            confidence=item.confidence,
            is_handwritten=int(item.is_handwritten),
            ingredient_id=ingredient_id,
        )

    # 7. 匹配供應商
    if ocr_result.supplier_name:
        supplier = sm.get_supplier(name=ocr_result.supplier_name)
        if supplier:
            sm.update_purchase_staging(
                staging_id,
                supplier_id=supplier["id"],
                supplier_tax_id=supplier.get("tax_id", ocr_result.supplier_tax_id),
            )

        # 重新上傳收據（帶供應商名稱）
        if not gdrive_path:
            try:
                from services.gdrive_service import upload_receipt
                ym = ocr_result.purchase_date[:7] if ocr_result.purchase_date else None
                gdrive_path = await upload_receipt(
                    local_path, year_month=ym, supplier=ocr_result.supplier_name
                )
                if gdrive_path:
                    sm.update_purchase_staging(staging_id, gdrive_path=gdrive_path)
            except Exception as e:
                logger.warning(f"GDrive re-upload skipped: {e}")

    # 7.5 設定等待確認狀態
    sm.set_state(group_id, "waiting_ocr_confirm", {
        "staging_id": staging_id,
    })

    # 8. 根據信心度回覆
    if ocr_result.result_level == "AUTO_PASS":
        # 高信心度 → 自動入暫存，推送 Flex 確認
        try:
            flex = build_review_flex(ocr_result, staging_id)
            success = line_service.reply_flex(
                reply_token,
                f"📋 採購辨識（信心度 {int(ocr_result.confidence*100)}%）",
                flex,
            )
            if success:
                return None  # 已用 Flex 回覆
            logger.warning(f"Flex reply failed for #{staging_id}, falling back to text")
        except Exception as e:
            logger.warning(f"Flex build error for #{staging_id}: {e}")

        return _build_text_summary(ocr_result, staging_id, "🟢 高信心度，建議確認")

    elif ocr_result.result_level == "REVIEW":
        # 中信心度 → 需人工確認
        try:
            flex = build_review_flex(ocr_result, staging_id)
            success = line_service.reply_flex(
                reply_token,
                f"⚠️ 採購辨識需確認（信心度 {int(ocr_result.confidence*100)}%）",
                flex,
            )
            if success:
                return None
            logger.warning(f"Flex reply failed for #{staging_id}, falling back to text")
        except Exception as e:
            logger.warning(f"Flex build error for #{staging_id}: {e}")

        issues_text = "\n".join(f"  ⚠️ {i}" for i in ocr_result.issues) if ocr_result.issues else ""
        return _build_text_summary(ocr_result, staging_id, "🟡 需要確認") + \
            (f"\n\n問題：\n{issues_text}" if issues_text else "")

    else:
        # 低信心度 → 建議重拍
        issues_text = "\n".join(f"  ❌ {i}" for i in ocr_result.issues)
        return (
            f"❌ 辨識信心度過低（{int(ocr_result.confidence*100)}%）\n"
            f"記錄 #{staging_id} 已暫存\n\n"
            f"問題：\n{issues_text}\n\n"
            "建議重新拍照（確保光線充足、畫面清晰）\n"
            f"或手動修改：輸入「修改 #{staging_id}」"
        )


def _build_text_summary(result, staging_id: int, status_label: str) -> str:
    """建立文字版辨識結果"""
    lines = [
        f"📋 採購辨識結果 #{staging_id}",
        f"狀態：{status_label}（信心度 {int(result.confidence*100)}%）",
        f"供應商：{result.supplier_name or '未識別'}",
        f"日期：{result.purchase_date or '未識別'}",
        "",
    ]

    for i, item in enumerate(result.items[:10], 1):
        hw = "✍️" if item.is_handwritten else ""
        lines.append(f"  {i}. {item.name} {item.quantity}{item.unit} "
                     f"@${item.unit_price:,.0f} = ${item.amount:,.0f} {hw}")

    if len(result.items) > 10:
        lines.append(f"  ... 共 {len(result.items)} 項")

    uncertain = [item for item in result.items
                 if item.is_handwritten or item.confidence < 0.6]
    if uncertain:
        lines.append("")
        lines.append("⚠️ 以下品項請特別確認：")
        for item in uncertain[:5]:
            tag = "✍️手寫" if item.is_handwritten else "❓模糊"
            lines.append(f"  {tag}：{item.name} {item.quantity}{item.unit} "
                         f"@${item.unit_price:,.0f} = ${item.amount:,.0f}")

    lines.extend([
        "",
        f"合計：${result.total_amount:,.0f}",
        f"（未稅 ${result.subtotal:,.0f} + 稅 ${result.tax_amount:,.0f}）",
        "",
        "👉 回覆「OK」或「好」快速確認",
        "✏️ 回覆「修改」進入修改模式",
        "❌ 回覆「捨棄」丟棄此筆",
    ])

    return "\n".join(lines)


def _classify_tax_deduction(ocr_result: dict) -> dict:
    """根據 OCR 結果自動判斷稅務扣抵分類。

    分類規則：
    - 有統編 + 三聯式 → 可扣抵 (deduction_code=1, format=21)
    - 有統編 + 電子發票 → 可扣抵 (deduction_code=1, format=25)
    - 有統編 + 二聯式 → 不可扣抵 (deduction_code=2, format=22)
    - 無統編（收據/免用發票）→ 不可扣抵 (deduction_code=2, format=22)
    - 免稅品項 → 不可扣抵 (deduction_code=2, tax_type=3, format=22)
    """
    has_tax_id = bool(ocr_result.get("supplier_tax_id", "").strip())
    invoice_type = ocr_result.get("invoice_type", "receipt")

    # 免稅品項
    if invoice_type in ("免稅", "tax_exempt"):
        return {"deduction_code": "2", "tax_type": "3", "invoice_format_code": "22"}

    if has_tax_id and invoice_type in ("三聯式", "triplicate"):
        return {"deduction_code": "1", "tax_type": "1", "invoice_format_code": "21"}
    elif has_tax_id and invoice_type in ("電子發票", "electronic"):
        return {"deduction_code": "1", "tax_type": "1", "invoice_format_code": "25"}
    elif has_tax_id:
        # 有統編但非三聯式/電子發票（如二聯式）→ 不可扣抵
        return {"deduction_code": "2", "tax_type": "1", "invoice_format_code": "22"}
    else:
        # 無統編（收據、免用發票等）
        return {"deduction_code": "2", "tax_type": "1", "invoice_format_code": "22"}
