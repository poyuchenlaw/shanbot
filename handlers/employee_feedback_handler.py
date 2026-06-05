"""
employee_feedback_handler.py -- 員工選擇回饋學習迴路

流程：
  員工 LINE 點選「候選 1」-> postback action=supplier_confirm
    -> 寫入 suppliers_alias 表 + 更新 staging row 的 supplier_id
  員工點選「都不是」-> postback action=supplier_new
    -> 進一步問「新供應商？請輸入正式名稱」
    -> 新建 suppliers 條目 + 寫入 alias

下次同模糊字串 -> 先 hit suppliers_alias 跳過 fuzzy match
"""

import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger("shanbot.feedback")

DB_PATH = "data/shanbot.db"


# --- DB helpers ---

def _get_conn():
    return sqlite3.connect(DB_PATH)


def lookup_alias(alias_text: str) -> dict | None:
    """供 ocr_service 呼叫：查 alias 表，命中則回傳 canonical 供應商 dict

    回傳格式: {'supplier_id': int, 'supplier_name': str, 'confidence': int}
    未命中回傳 None
    """
    if not alias_text:
        return None
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT sa.canonical_supplier_id, s.name, sa.confidence
            FROM suppliers_alias sa
            JOIN suppliers s ON sa.canonical_supplier_id = s.id
            WHERE sa.alias_text = ?
        """, (alias_text,))
        row = cur.fetchone()
        if row:
            return {"supplier_id": row[0], "supplier_name": row[1], "confidence": row[2]}
        return None
    finally:
        conn.close()


def write_alias(alias_text: str, canonical_supplier_id: int,
                confidence: int = 100, employee_id: str = "",
                learned_from: str = "employee_feedback") -> bool:
    """新增或更新 alias 對應表"""
    if not alias_text:
        return False
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO suppliers_alias
                (alias_text, canonical_supplier_id, confidence,
                 learned_from, learned_at, employee_id)
            VALUES (?, ?, ?, ?, datetime('now','localtime'), ?)
            ON CONFLICT(alias_text) DO UPDATE SET
                canonical_supplier_id = excluded.canonical_supplier_id,
                confidence = excluded.confidence,
                learned_from = excluded.learned_from,
                learned_at = excluded.learned_at,
                employee_id = excluded.employee_id
        """, (alias_text, canonical_supplier_id, confidence, learned_from, employee_id))
        conn.commit()
        logger.info(f"alias 寫入：{alias_text!r} -> supplier_id={canonical_supplier_id}")
        return True
    except Exception as e:
        logger.error(f"write_alias error: {e}")
        return False
    finally:
        conn.close()


def update_staging_supplier(staging_id: int, supplier_id: int, supplier_name: str) -> bool:
    """更新 purchase_staging 的 supplier_id 與 supplier_name"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE purchase_staging
            SET supplier_id = ?, supplier_name = ?
            WHERE id = ?
        """, (supplier_id, supplier_name, staging_id))
        conn.commit()
        logger.info(f"staging #{staging_id} -> supplier_id={supplier_id} name={supplier_name!r}")
        return True
    except Exception as e:
        logger.error(f"update_staging_supplier error: {e}")
        return False
    finally:
        conn.close()


def get_or_create_supplier(name: str) -> dict:
    """查找供應商，不存在則新建。回傳 {'id': int, 'name': str, 'created': bool}"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM suppliers WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            return {"id": row[0], "name": row[1], "created": False}
        cur.execute("""
            INSERT INTO suppliers (name, has_uniform_invoice)
            VALUES (?, 0)
        """, (name,))
        conn.commit()
        new_id = cur.lastrowid
        logger.info(f"新建供應商：{name!r} id={new_id}")
        return {"id": new_id, "name": name, "created": True}
    finally:
        conn.close()


# --- Postback 入口（由 postback_handler.py 呼叫）---

def handle_supplier_confirm(postback_data: dict, user_id: str, reply_token: str) -> str:
    """處理員工選擇候選供應商

    postback_data 格式（從 Flex 按鈕解析）：
      action=supplier_confirm, staging_id=<int>, choice=<供應商名>, score=<float>

    回傳：回覆給員工的文字訊息
    """
    staging_id = int(postback_data.get("staging_id", 0))
    choice_name = postback_data.get("choice", "")
    score = float(postback_data.get("score", 0))

    if not choice_name:
        return "我這邊收不到你的選擇，可以再試一次嗎？"

    # 找 canonical supplier_id
    sup = get_or_create_supplier(choice_name)
    supplier_id = sup["id"]

    # 取得 staging 的 ocr 辨識名稱作為 alias
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT supplier_name FROM purchase_staging WHERE id=?", (staging_id,))
        row = cur.fetchone()
        ocr_name = row[0] if row else ""
    finally:
        conn.close()

    # 寫入 alias（OCR 名稱 -> 正確供應商）
    if ocr_name and ocr_name != choice_name:
        write_alias(
            alias_text=ocr_name,
            canonical_supplier_id=supplier_id,
            confidence=int(score),
            employee_id=user_id,
            learned_from="employee_feedback"
        )

    # 更新 staging
    update_staging_supplier(staging_id, supplier_id, choice_name)

    logger.info(f"supplier_confirm: staging={staging_id} choice={choice_name!r} score={score} alias={ocr_name!r}")
    return f"好，這筆款項我記成「{choice_name}」了。下次遇到類似的名字，我會自動對上去。"


def handle_supplier_new(postback_data: dict, user_id: str) -> str:
    """員工點「都不是」-> 進入新供應商詢問流程"""
    staging_id = int(postback_data.get("staging_id", 0))
    ocr_name = postback_data.get("supplier_name", "")

    _set_awaiting_new_supplier(user_id, staging_id, ocr_name)

    return (
        f"了解，這筆的「{ocr_name}」是全新的廠商對嗎？\n"
        "請直接回覆正式的廠商名稱，我幫你建檔。"
    )


def handle_new_supplier_name_input(user_id: str, text: str, reply_token: str) -> str | None:
    """員工在 handle_supplier_new 之後，輸入的正式廠商名稱

    回傳 reply 文字，或 None 表示此訊息不是在等廠商名稱
    """
    state = _get_awaiting_new_supplier(user_id)
    if not state:
        return None

    staging_id = state["staging_id"]
    ocr_name = state["ocr_name"]
    new_name = text.strip()

    if not new_name or len(new_name) < 2:
        return "廠商名稱太短，可以再說一遍嗎？"

    sup = get_or_create_supplier(new_name)
    supplier_id = sup["id"]
    created_msg = "已幫你新建廠商" if sup["created"] else "這個廠商之前就有了，"

    if ocr_name and ocr_name != new_name:
        write_alias(
            alias_text=ocr_name,
            canonical_supplier_id=supplier_id,
            confidence=95,
            employee_id=user_id,
            learned_from="employee_new_supplier"
        )

    update_staging_supplier(staging_id, supplier_id, new_name)
    _clear_awaiting_new_supplier(user_id)

    return (
        f"{created_msg}「{new_name}」。\n"
        "這筆款項我也更新了。下次同樣的名字就能自動認出來。"
    )


# --- Conversation state helpers ---

_awaiting_new_supplier: dict[str, dict] = {}


def _set_awaiting_new_supplier(user_id: str, staging_id: int, ocr_name: str):
    _awaiting_new_supplier[user_id] = {
        "staging_id": staging_id,
        "ocr_name": ocr_name,
        "ts": datetime.now().isoformat()
    }


def _get_awaiting_new_supplier(user_id: str) -> dict | None:
    return _awaiting_new_supplier.get(user_id)


def _clear_awaiting_new_supplier(user_id: str):
    _awaiting_new_supplier.pop(user_id, None)
