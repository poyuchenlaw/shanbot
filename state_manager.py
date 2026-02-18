"""小膳 Bot - SQLite 狀態管理器（12 表 + WAL mode）"""

import json
import sqlite3
import os
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("shanbot.state")

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "shanbot.db"))

_SCHEMA = """
-- 1. 食材主檔
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    brand TEXT DEFAULT '',
    category TEXT NOT NULL,
    account_code TEXT DEFAULT '5110',
    unit TEXT NOT NULL DEFAULT 'kg',
    current_price REAL DEFAULT 0,
    market_ref_price REAL DEFAULT 0,
    prep_waste_rate REAL DEFAULT 0.05,
    cook_loss_rate REAL DEFAULT 0.10,
    synonyms TEXT DEFAULT '[]',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 2. 供應商主檔
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    tax_id TEXT DEFAULT '',
    has_uniform_invoice INTEGER DEFAULT 1,
    phone TEXT DEFAULT '',
    specialty TEXT DEFAULT '',
    payment_terms TEXT DEFAULT '',
    score REAL DEFAULT 70,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 3. 採購暫存表
CREATE TABLE IF NOT EXISTS purchase_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    chat_id TEXT,
    image_message_id TEXT,
    local_image_path TEXT,
    gdrive_path TEXT,
    supplier_id INTEGER REFERENCES suppliers(id),
    supplier_name TEXT DEFAULT '',
    supplier_tax_id TEXT DEFAULT '',
    invoice_prefix TEXT DEFAULT '',
    invoice_number TEXT DEFAULT '',
    invoice_type TEXT DEFAULT '',
    invoice_format_code TEXT DEFAULT '21',
    purchase_date TEXT,
    subtotal REAL DEFAULT 0,
    tax_type TEXT DEFAULT '1',
    tax_rate REAL DEFAULT 0.05,
    tax_amount REAL DEFAULT 0,
    total_amount REAL DEFAULT 0,
    deduction_code TEXT DEFAULT '1',
    raw_ocr_text TEXT,
    ocr_confidence REAL DEFAULT 0,
    handler_name TEXT DEFAULT '',
    handler_note TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    year_month TEXT,
    tax_period TEXT,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    confirmed_at TEXT,
    exported_at TEXT
);

-- 4. 採購明細表
CREATE TABLE IF NOT EXISTS purchase_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staging_id INTEGER REFERENCES purchase_staging(id),
    ingredient_id INTEGER REFERENCES ingredients(id),
    item_name TEXT NOT NULL,
    brand TEXT DEFAULT '',
    quantity REAL DEFAULT 0,
    unit TEXT DEFAULT '',
    unit_price REAL DEFAULT 0,
    amount REAL DEFAULT 0,
    tax_amount REAL DEFAULT 0,
    category TEXT DEFAULT 'other',
    account_code TEXT DEFAULT '5110',
    is_handwritten INTEGER DEFAULT 0,
    original_unit_price REAL,
    confidence REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 5. 價格歷史
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER REFERENCES ingredients(id),
    price_date TEXT NOT NULL,
    source TEXT NOT NULL,
    market_name TEXT DEFAULT '',
    avg_price REAL,
    high_price REAL,
    low_price REAL,
    purchase_price REAL,
    volume REAL,
    UNIQUE(ingredient_id, price_date, source)
);

-- 6. 配方表
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    servings INTEGER DEFAULT 100,
    ingredient_cost REAL DEFAULT 0,
    cost_per_serving REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    last_served_date TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 7. 配方明細（BOM）
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER REFERENCES recipes(id),
    ingredient_id INTEGER REFERENCES ingredients(id),
    role TEXT DEFAULT 'MAIN',
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    line_cost REAL DEFAULT 0,
    notes TEXT DEFAULT ''
);

-- 8. 菜單排程
CREATE TABLE IF NOT EXISTS menu_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT NOT NULL,
    meal_type TEXT DEFAULT 'lunch',
    slot TEXT NOT NULL,
    recipe_id INTEGER REFERENCES recipes(id),
    planned_servings INTEGER,
    UNIQUE(schedule_date, meal_type, slot)
);

-- 9. 月度成本結構
CREATE TABLE IF NOT EXISTS monthly_cost (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT UNIQUE NOT NULL,
    serving_days INTEGER DEFAULT 22,
    daily_servings INTEGER DEFAULT 0,
    ingredient_total REAL DEFAULT 0,
    labor_total REAL DEFAULT 0,
    overhead_total REAL DEFAULT 0,
    budget_amount REAL DEFAULT 0,
    taxable_purchase_total REAL DEFAULT 0,
    input_tax_total REAL DEFAULT 0,
    deductible_tax REAL DEFAULT 0,
    non_deductible_tax REAL DEFAULT 0,
    invoice_count INTEGER DEFAULT 0,
    receipt_count INTEGER DEFAULT 0,
    report_path TEXT,
    export_path TEXT,
    is_locked INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 10. 系統配置
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 11. 稅務匯出記錄
CREATE TABLE IF NOT EXISTS tax_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_period TEXT NOT NULL,
    export_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    record_count INTEGER DEFAULT 0,
    total_amount REAL DEFAULT 0,
    total_tax REAL DEFAULT 0,
    exported_by TEXT DEFAULT 'system',
    verified_by TEXT DEFAULT '',
    verified_at TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 12. 會計科目對照表
CREATE TABLE IF NOT EXISTS account_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    parent_code TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

-- 13. 收入記錄
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    source TEXT DEFAULT '',
    income_date TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 14. 對話狀態
CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id TEXT PRIMARY KEY,
    state TEXT DEFAULT 'idle',
    state_data TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 15. 財務文件
CREATE TABLE IF NOT EXISTS financial_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT,
    user_id TEXT,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    doc_category TEXT NOT NULL,
    doc_subcategory TEXT DEFAULT '',
    local_path TEXT,
    gdrive_path TEXT,
    year_month TEXT,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    confirmed_at TEXT
);
"""

_SEED_ACCOUNT_MAPPING = """
INSERT OR IGNORE INTO account_mapping (category, account_code, account_name, parent_code) VALUES
('蔬菜', '5110', '進貨—蔬菜類', '5100'),
('肉類', '5110', '進貨—肉類', '5100'),
('水產', '5110', '進貨—水產類', '5100'),
('蛋豆', '5110', '進貨—蛋豆類', '5100'),
('乾貨', '5110', '進貨—乾貨類', '5100'),
('調味料', '5110', '進貨—調味料', '5100'),
('油品', '5110', '進貨—油品類', '5100'),
('米糧', '5110', '進貨—米糧類', '5100'),
('其他', '5110', '進貨—其他', '5100'),
('人力', '5120', '直接人工', '5100'),
('水電', '6180', '水電瓦斯費', '6100'),
('租金', '6120', '租金支出', '6100'),
('設備', '6230', '折舊', '6100'),
('運費', '6150', '運費', '6100'),
('保險', '6190', '保險費', '6100');
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """建立所有表 + 種子資料"""
    conn = _get_conn()
    conn.executescript(_SCHEMA)
    conn.executescript(_SEED_ACCOUNT_MAPPING)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized: {DB_PATH}")


# === 對話狀態 ===

def get_state(chat_id: str) -> tuple[str, dict]:
    conn = _get_conn()
    row = conn.execute("SELECT state, state_data FROM conversation_state WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    if row:
        return row["state"], json.loads(row["state_data"])
    return "idle", {}


def set_state(chat_id: str, state: str, data: dict = None):
    conn = _get_conn()
    data_json = json.dumps(data or {}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO conversation_state (chat_id, state, state_data, updated_at) "
        "VALUES (?, ?, ?, datetime('now','localtime')) "
        "ON CONFLICT(chat_id) DO UPDATE SET state=?, state_data=?, updated_at=datetime('now','localtime')",
        (chat_id, state, data_json, state, data_json),
    )
    conn.commit()
    conn.close()


def clear_state(chat_id: str):
    set_state(chat_id, "idle", {})


# === 供應商 ===

def upsert_supplier(name: str, tax_id: str = "", has_invoice: bool = True,
                    phone: str = "", specialty: str = "") -> int:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO suppliers (name, tax_id, has_uniform_invoice, phone, specialty) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET tax_id=?, has_uniform_invoice=?, phone=?, specialty=?",
        (name, tax_id, int(has_invoice), phone, specialty,
         tax_id, int(has_invoice), phone, specialty),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM suppliers WHERE name=?", (name,)).fetchone()
    conn.close()
    return row["id"]


def get_supplier(name: str = None, supplier_id: int = None) -> Optional[dict]:
    conn = _get_conn()
    if supplier_id:
        row = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    elif name:
        row = conn.execute("SELECT * FROM suppliers WHERE name=?", (name,)).fetchone()
    else:
        row = None
    conn.close()
    return dict(row) if row else None


def get_all_suppliers() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 食材 ===

def upsert_ingredient(code: str, name: str, category: str, unit: str = "kg",
                      account_code: str = "5110") -> int:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO ingredients (code, name, category, unit, account_code) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name=?, category=?, unit=?, account_code=?, "
        "updated_at=datetime('now','localtime')",
        (code, name, category, unit, account_code, name, category, unit, account_code),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM ingredients WHERE code=?", (code,)).fetchone()
    conn.close()
    return row["id"]


def find_ingredient(name: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM ingredients WHERE name=? OR name LIKE ? OR synonyms LIKE ?",
        (name, f"%{name}%", f"%{name}%"),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_ingredient_price(ingredient_id: int, price: float, market_ref: float = None):
    conn = _get_conn()
    if market_ref is not None:
        conn.execute(
            "UPDATE ingredients SET current_price=?, market_ref_price=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (price, market_ref, ingredient_id),
        )
    else:
        conn.execute(
            "UPDATE ingredients SET current_price=?, updated_at=datetime('now','localtime') WHERE id=?",
            (price, ingredient_id),
        )
    conn.commit()
    conn.close()


# === 採購暫存 ===

def add_purchase_staging(
    user_id: str, chat_id: str, image_message_id: str = "",
    local_image_path: str = "", purchase_date: str = None,
) -> int:
    if not purchase_date:
        purchase_date = date.today().isoformat()
    year_month = purchase_date[:7]
    tax_period = _calc_tax_period(purchase_date)
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO purchase_staging (user_id, chat_id, image_message_id, "
        "local_image_path, purchase_date, year_month, tax_period) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, chat_id, image_message_id, local_image_path,
         purchase_date, year_month, tax_period),
    )
    conn.commit()
    staging_id = cur.lastrowid
    conn.close()
    return staging_id


def update_purchase_staging(staging_id: int, **kwargs):
    conn = _get_conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(staging_id)
    conn.execute(f"UPDATE purchase_staging SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def confirm_staging(staging_id: int):
    conn = _get_conn()
    conn.execute(
        "UPDATE purchase_staging SET status='confirmed', confirmed_at=datetime('now','localtime') "
        "WHERE id=?", (staging_id,),
    )
    conn.commit()
    conn.close()


def get_staging(staging_id: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM purchase_staging WHERE id=?", (staging_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_stagings(chat_id: str = None) -> list[dict]:
    conn = _get_conn()
    if chat_id:
        rows = conn.execute(
            "SELECT * FROM purchase_staging WHERE status='pending' AND chat_id=? ORDER BY created_at DESC",
            (chat_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM purchase_staging WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_confirmed_stagings(tax_period: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM purchase_staging WHERE status='confirmed' AND tax_period=? ORDER BY purchase_date",
        (tax_period,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stagings_by_month(year_month: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM purchase_staging WHERE year_month=? AND status IN ('confirmed','reported','exported') "
        "ORDER BY purchase_date",
        (year_month,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 採購明細 ===

def add_purchase_item(staging_id: int, item_name: str, quantity: float = 0,
                      unit: str = "", unit_price: float = 0, amount: float = 0,
                      category: str = "other", account_code: str = "5110",
                      confidence: float = 0, is_handwritten: int = 0,
                      ingredient_id: int = None) -> int:
    conn = _get_conn()
    tax_amount = round(amount * 0.05, 0)
    cur = conn.execute(
        "INSERT INTO purchase_items (staging_id, ingredient_id, item_name, quantity, unit, "
        "unit_price, amount, tax_amount, category, account_code, confidence, is_handwritten) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (staging_id, ingredient_id, item_name, quantity, unit, unit_price,
         amount, tax_amount, category, account_code, confidence, is_handwritten),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def get_purchase_items(staging_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM purchase_items WHERE staging_id=? ORDER BY id", (staging_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 價格歷史 ===

def add_price_history(ingredient_id: int, price_date: str, source: str,
                      avg_price: float = None, high_price: float = None,
                      low_price: float = None, purchase_price: float = None,
                      market_name: str = "", volume: float = None):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO price_history "
        "(ingredient_id, price_date, source, market_name, avg_price, high_price, low_price, purchase_price, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ingredient_id, price_date, source, market_name,
         avg_price, high_price, low_price, purchase_price, volume),
    )
    conn.commit()
    conn.close()


def get_price_history(ingredient_id: int, days: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM price_history WHERE ingredient_id=? "
        "ORDER BY price_date DESC LIMIT ?",
        (ingredient_id, days),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 配方 ===

def add_recipe(name: str, category: str = "", servings: int = 100) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO recipes (name, category, servings) VALUES (?, ?, ?)",
        (name, category, servings),
    )
    conn.commit()
    recipe_id = cur.lastrowid
    conn.close()
    return recipe_id


def add_recipe_ingredient(recipe_id: int, ingredient_id: int,
                          quantity: float, unit: str, role: str = "MAIN") -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO recipe_ingredients (recipe_id, ingredient_id, role, quantity, unit) "
        "VALUES (?, ?, ?, ?, ?)",
        (recipe_id, ingredient_id, role, quantity, unit),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_recipe_bom(recipe_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT ri.*, i.name as ingredient_name, i.current_price, i.unit as ingredient_unit "
        "FROM recipe_ingredients ri JOIN ingredients i ON ri.ingredient_id = i.id "
        "WHERE ri.recipe_id=?",
        (recipe_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 月度成本 ===

def upsert_monthly_cost(year_month: str, **kwargs) -> int:
    conn = _get_conn()
    existing = conn.execute("SELECT id FROM monthly_cost WHERE year_month=?", (year_month,)).fetchone()
    if existing:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(year_month)
        if sets:
            conn.execute(f"UPDATE monthly_cost SET {', '.join(sets)} WHERE year_month=?", vals)
        conn.commit()
        result = existing["id"]
    else:
        cols = ["year_month"] + list(kwargs.keys())
        placeholders = ", ".join(["?"] * len(cols))
        vals = [year_month] + list(kwargs.values())
        cur = conn.execute(f"INSERT INTO monthly_cost ({', '.join(cols)}) VALUES ({placeholders})", vals)
        conn.commit()
        result = cur.lastrowid
    conn.close()
    return result


def get_monthly_cost(year_month: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM monthly_cost WHERE year_month=?", (year_month,)).fetchone()
    conn.close()
    return dict(row) if row else None


# === 稅務匯出 ===

def add_tax_export(tax_period: str, export_type: str, file_path: str,
                   record_count: int = 0, total_amount: float = 0,
                   total_tax: float = 0) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO tax_exports (tax_period, export_type, file_path, "
        "record_count, total_amount, total_tax) VALUES (?, ?, ?, ?, ?, ?)",
        (tax_period, export_type, file_path, record_count, total_amount, total_tax),
    )
    conn.commit()
    export_id = cur.lastrowid
    conn.close()
    return export_id


def get_tax_exports(tax_period: str = None) -> list[dict]:
    conn = _get_conn()
    if tax_period:
        rows = conn.execute(
            "SELECT * FROM tax_exports WHERE tax_period=? ORDER BY created_at DESC",
            (tax_period,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tax_exports ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 會計科目 ===

def get_account_mapping(category: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM account_mapping WHERE category=?", (category,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_account_mappings() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM account_mapping ORDER BY account_code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 系統配置 ===

def get_config(key: str, default: str = "") -> str:
    conn = _get_conn()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_config(key: str, value: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=?",
        (key, value, value),
    )
    conn.commit()
    conn.close()


# === 統計 ===

def get_staging_stats(year_month: str = None) -> dict:
    conn = _get_conn()
    if year_month:
        where = "WHERE year_month=?"
        params = (year_month,)
    else:
        where = ""
        params = ()
    row = conn.execute(
        f"SELECT COUNT(*) as total, "
        f"SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending, "
        f"SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) as confirmed, "
        f"SUM(CASE WHEN status='exported' THEN 1 ELSE 0 END) as exported, "
        f"SUM(CASE WHEN status='confirmed' OR status='exported' THEN total_amount ELSE 0 END) as total_amount, "
        f"SUM(CASE WHEN status='confirmed' OR status='exported' THEN tax_amount ELSE 0 END) as total_tax "
        f"FROM purchase_staging {where}",
        params,
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_deduction_stats(chat_id: str = None, year_month: str = None) -> dict:
    """回傳扣抵統計：可扣抵/不可扣抵筆數和金額。

    Args:
        chat_id: 可選，篩選特定群組
        year_month: 可選，篩選特定月份（如 "2026-01"）

    Returns:
        {"deductible_count", "deductible_amount", "deductible_tax",
         "non_deductible_count", "non_deductible_amount", "non_deductible_tax",
         "total_count", "total_amount", "total_tax"}
    """
    conn = _get_conn()
    conditions = ["status IN ('confirmed', 'exported')"]
    params = []
    if chat_id:
        conditions.append("chat_id=?")
        params.append(chat_id)
    if year_month:
        conditions.append("year_month=?")
        params.append(year_month)
    where = f"WHERE {' AND '.join(conditions)}"

    row = conn.execute(
        f"SELECT "
        f"SUM(CASE WHEN deduction_code='1' THEN 1 ELSE 0 END) as deductible_count, "
        f"SUM(CASE WHEN deduction_code='1' THEN total_amount ELSE 0 END) as deductible_amount, "
        f"SUM(CASE WHEN deduction_code='1' THEN tax_amount ELSE 0 END) as deductible_tax, "
        f"SUM(CASE WHEN deduction_code!='1' OR deduction_code IS NULL THEN 1 ELSE 0 END) as non_deductible_count, "
        f"SUM(CASE WHEN deduction_code!='1' OR deduction_code IS NULL THEN total_amount ELSE 0 END) as non_deductible_amount, "
        f"SUM(CASE WHEN deduction_code!='1' OR deduction_code IS NULL THEN tax_amount ELSE 0 END) as non_deductible_tax, "
        f"COUNT(*) as total_count, "
        f"SUM(total_amount) as total_amount, "
        f"SUM(tax_amount) as total_tax "
        f"FROM purchase_staging {where}",
        params,
    ).fetchone()
    conn.close()
    if row:
        result = dict(row)
        # Ensure no None values
        return {k: (v or 0) for k, v in result.items()}
    return {
        "deductible_count": 0, "deductible_amount": 0, "deductible_tax": 0,
        "non_deductible_count": 0, "non_deductible_amount": 0, "non_deductible_tax": 0,
        "total_count": 0, "total_amount": 0, "total_tax": 0,
    }


def get_ocr_stats() -> dict:
    """取得 OCR 統計（用於動態校準門檻）"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "AVG(ocr_confidence) as avg_confidence, "
        "SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) as confirmed, "
        "SUM(CASE WHEN status='discarded' THEN 1 ELSE 0 END) as discarded "
        "FROM purchase_staging WHERE ocr_confidence > 0"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


# === 輔助函數 ===

def _calc_tax_period(purchase_date: str) -> str:
    """計算歸屬營業稅期（雙月制）"""
    d = date.fromisoformat(purchase_date)
    month = d.month
    if month % 2 == 1:
        start_month = month
    else:
        start_month = month - 1
    end_month = start_month + 1
    return f"{d.year}-{start_month:02d}-{end_month:02d}"


# === 收入 ===

def add_income(year_month: str, amount: float, description: str = "",
               source: str = "", income_date: str = None) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO income (year_month, amount, description, source, income_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (year_month, amount, description, source, income_date),
    )
    conn.commit()
    income_id = cur.lastrowid
    conn.close()
    return income_id


def get_income_summary(year_month: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM income WHERE year_month=? ORDER BY income_date",
        (year_month,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 菜單排程查詢 ===

def get_menu_schedule(year_month: str) -> list[dict]:
    """取得指定月份的菜單排程"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT ms.*, r.name as recipe_name "
        "FROM menu_schedule ms LEFT JOIN recipes r ON ms.recipe_id = r.id "
        "WHERE ms.schedule_date LIKE ? ORDER BY ms.schedule_date, ms.meal_type",
        (f"{year_month}%",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_menu_schedule(schedule_date: str, slot: str, recipe_id: int = None,
                      meal_type: str = "lunch", planned_servings: int = 0) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT OR REPLACE INTO menu_schedule "
        "(schedule_date, meal_type, slot, recipe_id, planned_servings) "
        "VALUES (?, ?, ?, ?, ?)",
        (schedule_date, meal_type, slot, recipe_id, planned_servings),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


# === 價格對照 ===

def get_price_comparisons(year_month: str = None) -> list[dict]:
    """取得食材進貨價 vs 市場均價對照"""
    from datetime import datetime
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    conn = _get_conn()
    rows = conn.execute("""
        SELECT
            i.name,
            i.current_price as purchase_price,
            i.market_ref_price as market_price,
            CASE WHEN i.market_ref_price > 0
                THEN ROUND((i.current_price - i.market_ref_price) / i.market_ref_price * 100, 1)
                ELSE 0
            END as deviation_pct
        FROM ingredients i
        WHERE i.is_active = 1
          AND i.current_price > 0
          AND i.market_ref_price > 0
        ORDER BY ABS((i.current_price - i.market_ref_price) / i.market_ref_price) DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === 所有配方查詢 ===

def get_all_recipes(active_only: bool = True) -> list[dict]:
    conn = _get_conn()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM recipes WHERE is_active=1 ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM recipes ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_table_counts() -> dict:
    """取得所有表的記錄數（健康檢查用）"""
    tables = [
        "ingredients", "suppliers", "purchase_staging", "purchase_items",
        "price_history", "recipes", "recipe_ingredients", "menu_schedule",
        "monthly_cost", "config", "tax_exports", "account_mapping",
        "conversation_state", "income", "financial_documents",
    ]
    conn = _get_conn()
    counts = {}
    for t in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
            counts[t] = row["cnt"]
        except Exception:
            counts[t] = -1
    conn.close()
    return counts


# === 財務文件 ===

def add_financial_document(
    chat_id: str, user_id: str, filename: str, file_type: str,
    doc_category: str, doc_subcategory: str = "", local_path: str = "",
    gdrive_path: str = "", year_month: str = "", description: str = "",
    metadata: dict = None,
) -> int:
    """新增財務文件記錄，回傳 id"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO financial_documents "
        "(chat_id, user_id, filename, file_type, doc_category, doc_subcategory, "
        "local_path, gdrive_path, year_month, description, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, user_id, filename, file_type, doc_category, doc_subcategory,
         local_path, gdrive_path, year_month, description, meta_json),
    )
    conn.commit()
    doc_id = cur.lastrowid
    conn.close()
    return doc_id


def get_financial_documents(
    chat_id: str = None, year_month: str = None, category: str = None,
) -> list[dict]:
    """查詢財務文件（可按 chat_id / year_month / category 篩選）"""
    conn = _get_conn()
    conditions = []
    params = []
    if chat_id:
        conditions.append("chat_id=?")
        params.append(chat_id)
    if year_month:
        conditions.append("year_month=?")
        params.append(year_month)
    if category:
        conditions.append("doc_category=?")
        params.append(category)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM financial_documents {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_financial_document(doc_id: int, **kwargs):
    """更新財務文件欄位"""
    conn = _get_conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k == "metadata" and isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(doc_id)
    conn.execute(f"UPDATE financial_documents SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_financial_doc_summary(year_month: str) -> dict:
    """取得指定月份的財務文件統計（按八大循環分類）"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT doc_category, COUNT(*) as cnt, "
        "SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) as confirmed "
        "FROM financial_documents WHERE year_month=? GROUP BY doc_category",
        (year_month,),
    ).fetchall()
    conn.close()
    result = {"year_month": year_month, "total": 0, "confirmed": 0, "categories": {}}
    for r in rows:
        d = dict(r)
        result["categories"][d["doc_category"]] = {
            "count": d["cnt"], "confirmed": d["confirmed"],
        }
        result["total"] += d["cnt"]
        result["confirmed"] += d["confirmed"]
    return result
