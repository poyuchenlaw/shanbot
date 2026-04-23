"""小膳 Bot — 一鍵完整做賬流程

完整 Pipeline：
1. 批次確認 pending 單據 → 生成複式分錄
2. 月報表（採購彙總 + 憑證目錄）
3. 會計帳冊（8-sheet Excel）
4. 四大財務報表
5. 期末結帳
6. 稅務匯出（MOF TXT + 會計 Excel + 經手人 PDF）
7. 自動稽核
8. GDrive 歸檔

支援：單月 / 多月 / 全公司 / 單公司
"""

import logging
import os
from datetime import datetime
from typing import Optional

import state_manager as sm

logger = logging.getLogger("shanbot.pipeline")


def run_full_pipeline(
    year_month: str,
    company_id: int = None,
    auto_confirm: bool = False,
    skip_tax_export: bool = False,
    skip_closing: bool = False,
    output_base: str = None,
) -> dict:
    """一鍵跑完整月做賬流程

    Args:
        year_month: 月份，如 "2026-03"
        company_id: 指定公司（None = 全部）
        auto_confirm: 是否自動確認 pending 單據
        skip_tax_export: 跳過稅務匯出（雙月才需要）
        skip_closing: 跳過期末結帳（還在月中不要結）
        output_base: 輸出根目錄（預設 GDrive 路徑）

    Returns:
        {
            "year_month": str,
            "steps": list[dict],  # 每步驟結果
            "files_generated": list[str],
            "audit_result": dict,
            "overall_success": bool,
        }
    """
    logger.info(f"=== Pipeline start: {year_month} company={company_id} ===")

    gdrive_base = os.environ.get("GDRIVE_LOCAL", "/mnt/h/小魚資料/團膳公司資料")
    steps = []
    files = []

    # 決定輸出目錄
    if output_base:
        out_dir = output_base
    else:
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "exports", year_month
        )
    os.makedirs(out_dir, exist_ok=True)

    # ================================================================
    # Step 1: 批次確認 + 生成分錄
    # ================================================================
    step1 = _step_confirm_and_journalize(year_month, company_id, auto_confirm)
    steps.append(step1)

    # ================================================================
    # Step 2: 月報表
    # ================================================================
    step2 = _step_monthly_report(year_month, out_dir)
    steps.append(step2)
    if step2.get("file"):
        files.append(step2["file"])

    # ================================================================
    # Step 3: 採購報告
    # ================================================================
    step3 = _step_purchase_report(year_month, out_dir)
    steps.append(step3)
    if step3.get("file"):
        files.append(step3["file"])

    # ================================================================
    # Step 4: 會計帳冊（8-sheet）
    # ================================================================
    step4 = _step_accounting_excel(year_month)
    steps.append(step4)
    if step4.get("file"):
        files.append(step4["file"])

    # ================================================================
    # Step 5: 四大財務報表
    # ================================================================
    step5 = _step_financial_reports(year_month, out_dir)
    steps.append(step5)
    files.extend(step5.get("files", []))

    # ================================================================
    # Step 6: 自動稽核（結帳前執行，確保數據完整性）
    # ================================================================
    step6 = _step_audit(year_month, out_dir)
    steps.append(step6)
    if step6.get("file"):
        files.append(step6["file"])

    # ================================================================
    # Step 7: 期末結帳（可選，稽核通過後再結帳）
    # ================================================================
    if not skip_closing:
        step7 = _step_period_closing(year_month)
        steps.append(step7)
    else:
        steps.append({"step": "period_closing", "status": "skipped"})

    # ================================================================
    # Step 8: 稅務匯出（可選）
    # ================================================================
    if not skip_tax_export:
        step8 = _step_tax_export(year_month, out_dir)
        steps.append(step8)
        files.extend(step8.get("files", []))
    else:
        steps.append({"step": "tax_export", "status": "skipped"})

    # ================================================================
    # Step 9: 財務分析報告
    # ================================================================
    step9 = _step_financial_analysis(year_month, out_dir, company_id)
    steps.append(step9)
    if step9.get("file"):
        files.append(step9["file"])

    # ================================================================
    # Step 10: GDrive 歸檔
    # ================================================================
    step10 = _step_gdrive_archive(year_month, files, gdrive_base, company_id)
    steps.append(step10)

    # 彙整
    overall = all(s.get("status") in ("success", "skipped", "no_data") for s in steps)
    result = {
        "year_month": year_month,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "steps": steps,
        "files_generated": files,
        "audit_result": step6.get("audit_summary", {}),
        "overall_success": overall,
    }

    logger.info(f"=== Pipeline done: {'SUCCESS' if overall else 'PARTIAL'} ===")
    return result


# =====================================================================
# Step 實作
# =====================================================================

def _step_confirm_and_journalize(year_month: str, company_id: int, auto_confirm: bool) -> dict:
    """Step 1: 批次確認 pending → 生成複式分錄（進貨 + 收入）"""
    from services.accounting_service import (
        generate_journal_entries, verify_balance, generate_income_journal_entries,
    )

    stagings = sm.get_stagings_by_month(year_month, company_id=company_id)
    pending = [s for s in stagings if s.get("status") == "pending"]
    confirmed = [s for s in stagings if s.get("status") in ("confirmed", "exported")]

    confirmed_count = 0
    journal_count = 0
    balance_errors = []

    # 自動確認 pending
    if auto_confirm and pending:
        for s in pending:
            sm.confirm_staging(s["id"])
            confirmed_count += 1

    # 對所有 confirmed 生成進貨分錄
    all_confirmed = sm.get_stagings_by_month(year_month, company_id=company_id)
    all_confirmed = [s for s in all_confirmed if s.get("status") in ("confirmed", "exported")]

    for s in all_confirmed:
        entries = generate_journal_entries(s["id"])
        journal_count += len(entries)

        balance = verify_balance(s["id"])
        if not balance.get("balanced"):
            balance_errors.append({
                "staging_id": s["id"],
                "supplier": s.get("supplier_name"),
                "difference": balance.get("difference"),
            })

    # 生成收入分錄
    income_rows = sm.get_income_summary(year_month)
    income_entry_count = 0
    for inc in income_rows:
        if inc.get("id"):
            entries = generate_income_journal_entries(inc["id"])
            income_entry_count += len(entries)
    journal_count += income_entry_count

    return {
        "step": "confirm_and_journalize",
        "status": "success" if not balance_errors else "warning",
        "pending_found": len(pending),
        "auto_confirmed": confirmed_count,
        "already_confirmed": len(confirmed),
        "journal_entries_created": journal_count,
        "income_entries_created": income_entry_count,
        "balance_errors": balance_errors,
    }


def _step_monthly_report(year_month: str, out_dir: str) -> dict:
    """Step 2: 月報表"""
    from services.report_service import generate_monthly_report

    try:
        filepath = generate_monthly_report(year_month, output_dir=out_dir)
        if filepath:
            return {"step": "monthly_report", "status": "success", "file": filepath}
        return {"step": "monthly_report", "status": "no_data"}
    except Exception as e:
        logger.error(f"Monthly report error: {e}")
        return {"step": "monthly_report", "status": "error", "error": str(e)}


def _step_purchase_report(year_month: str, out_dir: str) -> dict:
    """Step 3: 採購報告"""
    from services.report_service import generate_purchase_report

    try:
        filepath = generate_purchase_report(year_month, output_dir=out_dir)
        if filepath:
            return {"step": "purchase_report", "status": "success", "file": filepath}
        return {"step": "purchase_report", "status": "no_data"}
    except Exception as e:
        logger.error(f"Purchase report error: {e}")
        return {"step": "purchase_report", "status": "error", "error": str(e)}


def _step_accounting_excel(year_month: str) -> dict:
    """Step 4: 會計帳冊（8-sheet）"""
    from services.accounting_service import generate_accounting_excel

    try:
        filepath = generate_accounting_excel(year_month)
        if filepath:
            return {"step": "accounting_excel", "status": "success", "file": filepath}
        return {"step": "accounting_excel", "status": "no_data"}
    except Exception as e:
        logger.error(f"Accounting excel error: {e}")
        return {"step": "accounting_excel", "status": "error", "error": str(e)}


def _step_financial_reports(year_month: str, out_dir: str) -> dict:
    """Step 5: 四大財務報表"""
    from services.financial_report_service import (
        generate_balance_sheet,
        generate_income_statement,
        generate_cash_flow,
        generate_equity_changes,
    )

    generated = []
    errors = []

    for name, func in [
        ("資產負債表", generate_balance_sheet),
        ("損益表", generate_income_statement),
        ("現金流量表", generate_cash_flow),
        ("權益變動表", generate_equity_changes),
    ]:
        try:
            filepath = func(year_month, output_dir=out_dir)
            if filepath:
                generated.append(filepath)
            else:
                errors.append(f"{name}: no output")
        except Exception as e:
            logger.error(f"{name} error: {e}")
            errors.append(f"{name}: {e}")

    return {
        "step": "financial_reports",
        "status": "success" if len(generated) == 4 else "partial",
        "files": generated,
        "errors": errors,
        "count": len(generated),
    }


def _step_period_closing(year_month: str) -> dict:
    """Step 6: 期末結帳"""
    from services.accounting_service import perform_period_end_closing

    try:
        result = perform_period_end_closing(year_month)
        return {
            "step": "period_closing",
            "status": "success",
            "detail": result,
        }
    except Exception as e:
        logger.error(f"Period closing error: {e}")
        return {"step": "period_closing", "status": "error", "error": str(e)}


def _step_tax_export(year_month: str, out_dir: str) -> dict:
    """Step 7: 稅務匯出"""
    from services.tax_export_service import export_mof_txt, export_accounting_excel

    generated = []
    errors = []

    # 判斷稅期（雙月）
    parts = year_month.split("-")
    m = int(parts[1])
    if m % 2 == 0:
        tax_period = f"{parts[0]}-{m-1:02d}-{m:02d}"
    else:
        tax_period = f"{parts[0]}-{m:02d}-{m+1:02d}"

    # MOF TXT
    try:
        filepath = export_mof_txt(tax_period, output_dir=out_dir)
        generated.append(filepath)
    except Exception as e:
        errors.append(f"MOF TXT: {e}")

    # 會計 Excel
    try:
        filepath = export_accounting_excel(tax_period, output_dir=out_dir)
        generated.append(filepath)
    except Exception as e:
        errors.append(f"會計 Excel: {e}")

    return {
        "step": "tax_export",
        "status": "success" if generated else "error",
        "files": generated,
        "errors": errors,
        "tax_period": tax_period,
    }


def _step_audit(year_month: str, out_dir: str) -> dict:
    """Step 8: 自動稽核"""
    from services.audit_service import run_full_audit, generate_audit_excel

    try:
        audit = run_full_audit(year_month)
        filepath = generate_audit_excel(year_month, output_dir=out_dir)

        return {
            "step": "audit",
            "status": "success",
            "overall_pass": audit["overall_pass"],
            "audit_summary": audit["summary"],
            "file": filepath,
        }
    except Exception as e:
        logger.error(f"Audit error: {e}")
        return {"step": "audit", "status": "error", "error": str(e)}


def _step_financial_analysis(year_month: str, out_dir: str,
                             company_id: int = None) -> dict:
    """Step 9: 月度財務分析報告"""
    from services.financial_analysis_service import (
        generate_monthly_analysis, generate_analysis_excel,
    )

    try:
        analysis = generate_monthly_analysis(year_month, company_id)
        filepath = generate_analysis_excel(year_month, output_dir=out_dir,
                                            company_id=company_id)
        return {
            "step": "financial_analysis",
            "status": "success",
            "file": filepath,
            "risk_count": len(analysis["risks"]),
            "recommendation_count": len(analysis["recommendations"]),
            "summary_text": analysis["summary_text"],
        }
    except Exception as e:
        logger.error(f"Financial analysis error: {e}")
        return {"step": "financial_analysis", "status": "error", "error": str(e)}


def _step_gdrive_archive(year_month: str, files: list, gdrive_base: str,
                          company_id: int = None) -> dict:
    """Step 9: GDrive 歸檔"""
    import shutil

    parts = year_month.split("-")
    month_str = f"{int(parts[1]):02d}月"

    # 取得要歸檔的公司列表
    if company_id:
        companies = [sm.get_company(company_id)]
    else:
        companies = sm.get_all_companies()

    archived = []
    errors = []

    for company in companies:
        if not company:
            continue
        short_name = company.get("short_name") or company.get("name") or f"company_{company['id']}"
        company_dir = os.path.join(gdrive_base, short_name, "2026", month_str)

        # 歸檔各類報表到對應子資料夾
        file_dest_map = {
            "月報表": "月報表",
            "採購報告": "採購單據",
            "會計帳冊": "會計資料",
            "資產負債表": "財務報表",
            "損益表": "財務報表",
            "現金流量表": "財務報表",
            "權益變動表": "財務報表",
            "稽核報告": "會計資料",
        }

        for filepath in files:
            if not filepath or not os.path.exists(filepath):
                continue
            filename = os.path.basename(filepath)

            dest_folder = "會計資料"  # 預設
            for keyword, folder in file_dest_map.items():
                if keyword in filename:
                    dest_folder = folder
                    break

            dest_dir = os.path.join(company_dir, dest_folder)
            try:
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                shutil.copy2(filepath, dest_path)
                archived.append(dest_path)
            except Exception as e:
                errors.append(f"{filename} → {dest_dir}: {e}")

    return {
        "step": "gdrive_archive",
        "status": "success" if not errors else "partial",
        "archived_count": len(archived),
        "errors": errors,
    }


# =====================================================================
# 多月批次
# =====================================================================

def run_multi_month_pipeline(
    months: list[str],
    company_id: int = None,
    auto_confirm: bool = False,
) -> dict:
    """批次跑多個月份

    Args:
        months: 月份清單，如 ["2026-03", "2026-04"]
    """
    results = {}
    for ym in months:
        results[ym] = run_full_pipeline(
            year_month=ym,
            company_id=company_id,
            auto_confirm=auto_confirm,
            skip_tax_export=True,  # 多月批次時跳過稅務（最後統一處理）
            skip_closing=ym != months[-1],  # 只結帳最後一個月
        )
    return results


def format_pipeline_summary(result: dict) -> str:
    """格式化 Pipeline 結果為人類可讀摘要"""
    lines = [
        f"📊 {result['year_month']} 做賬流程完成",
        f"🕐 {result['timestamp']}",
        "",
    ]

    for step in result["steps"]:
        name = step.get("step", "unknown")
        status = step.get("status", "unknown")
        icon = {"success": "✅", "partial": "⚠️", "error": "❌",
                "skipped": "⏭️", "no_data": "📭", "warning": "⚠️"}.get(status, "❓")

        step_names = {
            "confirm_and_journalize": "確認入帳 + 生成分錄",
            "monthly_report": "月報表",
            "purchase_report": "採購報告",
            "accounting_excel": "會計帳冊（8 Sheet）",
            "financial_reports": "四大財務報表",
            "audit": "自動稽核",
            "period_closing": "期末結帳",
            "tax_export": "稅務匯出",
            "financial_analysis": "財務分析報告",
            "gdrive_archive": "GDrive 歸檔",
        }

        line = f"  {icon} {step_names.get(name, name)}"

        # 附加細節
        if name == "confirm_and_journalize":
            line += f" — {step.get('auto_confirmed', 0)} 筆確認 / {step.get('journal_entries_created', 0)} 筆分錄"
        elif name == "financial_reports":
            line += f" — {step.get('count', 0)}/4 張"
        elif name == "audit":
            if step.get("overall_pass") is not None:
                line += f" — {'通過' if step['overall_pass'] else '有異常'}"
        elif name == "financial_analysis":
            line += f" — {step.get('risk_count', 0)} 項風險 / {step.get('recommendation_count', 0)} 項建議"
        elif name == "gdrive_archive":
            line += f" — {step.get('archived_count', 0)} 個檔案"

        lines.append(line)

    lines.append("")
    lines.append(f"📁 產出 {len(result['files_generated'])} 個檔案")

    if result.get("audit_result"):
        lines.append("")
        lines.append("--- 稽核摘要 ---")
        lines.append(result["audit_result"] if isinstance(result["audit_result"], str) else "")

    overall = "✅ 全部成功" if result["overall_success"] else "⚠️ 部分步驟有問題"
    lines.append(f"\n{overall}")

    return "\n".join(lines)
