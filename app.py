# -*- coding: utf-8 -*-
"""
Streamlit Bakery Tracker — شامل (حفظ دائم) — متجاوب للموبايل
- RTL محسّن للمس + تكديس أعمدة ثابت على الشاشات الصغيرة
- مراقبة مخزون الدقيق (مشتريات + متوسط تكلفة مرجّح + مخزون على اليد)
- الغاز يُضبط شهريًا ويُوزَّع يوميًا تلقائيًا (يمكن تجاوز التوزيع بإدخال يومي)
- نفس الميزات السابقة (لوحة، عملاء، تقارير، نسخ احتياطي/استرجاع)
- تخزين دائم في (~/.bakery_tracker/bakery_tracker.sqlite) أو المسار في BAKERY_DB_PATH
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

# ====================== إعداد عام (حفظ دائم) ======================
def _default_db_path() -> str:
    env = os.getenv("BAKERY_DB_PATH", "").strip()
    if env:
        return env
    base = os.path.join(os.path.expanduser("~"), ".bakery_tracker")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "bakery_tracker.sqlite")

DB_FILE = _default_db_path()   # حفظ دائم
THOUSAND = 1000
GROWTH_WINDOW_DAYS = 14

st.set_page_config(page_title="متابعة المخبز — شامل (حفظ دائم)", page_icon="📊", layout="wide")

# ====================== تحسينات المظهر والتجاوب ======================
st.markdown(
    """
    <style>
    :root {
      --touch-pad: 12px;
      --font-base: 15px;
      --font-lg: 17px;
      --radius-xl: 14px;
      --shadow-soft: 0 6px 18px rgba(0,0,0,.06);
    }
    html, body, [class*="css"] {
      direction: rtl; font-family: "Tajawal","Segoe UI","Tahoma",Arial,sans-serif;
      font-size: var(--font-base);
    }
    * { -webkit-tap-highlight-color: rgba(0,0,0,0); }
    .block-container { padding-top: 1rem; padding-bottom: 4rem; }
    [data-testid="stMetricLabel"] { direction: rtl; }
    .stMarkdown p { line-height: 1.6; }

    .stButton>button, .stDownloadButton>button {
      width: 100%; border-radius: var(--radius-xl); padding: .9rem 1.1rem; box-shadow: var(--shadow-soft);
    }
    .stTextInput>div>div>input, .stNumberInput input, .stSelectbox>div>div>div, .stDateInput input {
      border-radius: var(--radius-xl) !important;
    }
    .stExpander { border: 1px solid #eee; border-radius: var(--radius-xl); box-shadow: var(--shadow-soft); }
    .stTabs [data-baseweb="tab-list"] { gap: .5rem; }
    .stTabs [data-baseweb="tab"] { padding: .6rem .9rem; border-radius: var(--radius-xl); }
    .stDataFrame { border-radius: var(--radius-xl); overflow: hidden; box-shadow: var(--shadow-soft); }
    .small-note { font-size: 12px; opacity: .75; }

    /* تكديس أعمدة ثابت */
    @media (max-width: 900px) {
      .block-container { padding-left: .6rem; padding-right: .6rem; }
      [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; min-width: unset !important; }
      [data-testid="stHorizontalBlock"] { gap: .6rem !important; }
      .stMetric { margin-bottom: .5rem; }
      .stPlotlyChart { margin-top: .5rem; }
      .stTabs [data-baseweb="tab"] { font-size: 14px; }
    }
    @media (max-width: 600px) {
      .stButton>button, .stDownloadButton>button { font-size: 15px; padding: .95rem 1.1rem; }
      .stExpander { margin-bottom: .6rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 نظام متابعة المخبز — شامل (حفظ دائم)")

# ====================== أدوات مساعدة ======================
def fmt_i(x):
    try:
        return str(int(round(float(x or 0))))
    except Exception:
        return "0"

@st.cache_data(show_spinner=False)
def days_in_month(y: int, m: int) -> int:
    if m == 12:
        d1 = date(y, m, 1); d2 = date(y+1, 1, 1)
    else:
        d1 = date(y, m, 1); d2 = date(y, m+1, 1)
    return (d2 - d1).days

# ====================== قاعدة البيانات (WAL + دوام) ======================
def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE, isolation_level=None, check_same_thread=False)
    # تحسينات أمان/اعتمادية
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    conn = _connect()
    cur = conn.cursor()

    # جداول أساسية
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            units_samoli INTEGER,
            per_thousand_samoli INTEGER,
            units_madour INTEGER,
            per_thousand_madour INTEGER,
            flour_bags INTEGER,
            flour_bag_price INTEGER,   -- يُستخدم كـ fallback فقط
            flour_extra INTEGER,
            yeast INTEGER,
            salt INTEGER,
            oil INTEGER,
            gas INTEGER,                -- إن لم يُدخل، نستخدم توزيع شهري تلقائي
            electricity INTEGER,
            water INTEGER,
            salaries INTEGER,
            maintenance INTEGER,
            petty INTEGER,
            other_exp INTEGER,
            ice INTEGER,
            bags INTEGER,
            daily_meal INTEGER,
            owner_withdrawal INTEGER,
            owner_repayment INTEGER,
            owner_injection INTEGER,
            funding INTEGER,
            returns INTEGER,
            discounts INTEGER,
            branch_id INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            active INTEGER DEFAULT 1,
            branch_id INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            client_id INTEGER,
            bread_type TEXT,
            units INTEGER,
            per_thousand INTEGER,
            revenue INTEGER,
            payment_method TEXT,
            cash_source TEXT,
            branch_id INTEGER DEFAULT 1,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            client_id INTEGER,
            amount INTEGER,
            source TEXT,
            note TEXT,
            branch_id INTEGER DEFAULT 1,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rent_settings (
            year INTEGER,
            month INTEGER,
            monthly_rent INTEGER,
            PRIMARY KEY (year, month)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS money_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            source TEXT,
            amount INTEGER,
            reason TEXT,
            branch_id INTEGER DEFAULT 1
        )
        """
    )

    # فهارس
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_dte ON daily(dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_moves_dte ON money_moves(dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cd_dte ON client_deliveries(dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_dte ON client_payments(dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_branch_date ON daily(branch_id, dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_moves_branch_date ON money_moves(branch_id, dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cd_branch_date ON client_deliveries(branch_id, dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_branch_date ON client_payments(branch_id, dte)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clients_branch ON clients(branch_id)")

    # قيود جودة
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cd_bread_type_ins
        BEFORE INSERT ON client_deliveries
        BEGIN
            SELECT CASE
                WHEN NEW.bread_type NOT IN ('samoli','madour') THEN
                    RAISE(ABORT, 'bread_type must be samoli or madour')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cd_bread_type_upd
        BEFORE UPDATE ON client_deliveries
        BEGIN
            SELECT CASE
                WHEN NEW.bread_type NOT IN ('samoli','madour') THEN
                    RAISE(ABORT, 'bread_type must be samoli or madour')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cd_paymethod_ins
        BEFORE INSERT ON client_deliveries
        BEGIN
            SELECT CASE
                WHEN NEW.payment_method NOT IN ('cash','credit') THEN
                    RAISE(ABORT, 'payment_method must be cash or credit')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cd_paymethod_upd
        BEFORE UPDATE ON client_deliveries
        BEGIN
            SELECT CASE
                WHEN NEW.payment_method NOT IN ('cash','credit') THEN
                    RAISE(ABORT, 'payment_method must be cash or credit')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_mm_source_ins
        BEFORE INSERT ON money_moves
        BEGIN
            SELECT CASE
                WHEN NEW.source NOT IN ('cash','bank') THEN
                    RAISE(ABORT, 'source must be cash or bank')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_mm_source_upd
        BEFORE UPDATE ON money_moves
        BEGIN
            SELECT CASE
                WHEN NEW.source NOT IN ('cash','bank') THEN
                    RAISE(ABORT, 'source must be cash or bank')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cp_source_ins
        BEFORE INSERT ON client_payments
        BEGIN
            SELECT CASE
                WHEN NEW.source NOT IN ('cash','bank') THEN
                    RAISE(ABORT, 'source must be cash or bank')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_cp_source_upd
        BEFORE UPDATE ON client_payments
        BEGIN
            SELECT CASE
                WHEN NEW.source NOT IN ('cash','bank') THEN
                    RAISE(ABORT, 'source must be cash or bank')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_daily_nonneg_ins
        BEFORE INSERT ON daily
        BEGIN
            SELECT CASE
                WHEN IFNULL(NEW.units_samoli,0) < 0 OR
                     IFNULL(NEW.units_madour,0) < 0 OR
                     IFNULL(NEW.flour_bags,0) < 0 OR
                     IFNULL(NEW.flour_bag_price,0) < 0 OR
                     IFNULL(NEW.flour_extra,0) < 0 OR
                     IFNULL(NEW.yeast,0) < 0 OR
                     IFNULL(NEW.salt,0) < 0 OR
                     IFNULL(NEW.oil,0) < 0 OR
                     IFNULL(NEW.gas,0) < 0 OR
                     IFNULL(NEW.electricity,0) < 0 OR
                     IFNULL(NEW.water,0) < 0 OR
                     IFNULL(NEW.salaries,0) < 0 OR
                     IFNULL(NEW.maintenance,0) < 0 OR
                     IFNULL(NEW.petty,0) < 0 OR
                     IFNULL(NEW.other_exp,0) < 0 OR
                     IFNULL(NEW.ice,0) < 0 OR
                     IFNULL(NEW.bags,0) < 0 OR
                     IFNULL(NEW.daily_meal,0) < 0 OR
                     IFNULL(NEW.owner_withdrawal,0) < 0 OR
                     IFNULL(NEW.owner_repayment,0) < 0 OR
                     IFNULL(NEW.owner_injection,0) < 0 OR
                     IFNULL(NEW.returns,0) < 0 OR
                     IFNULL(NEW.discounts,0) < 0
                THEN RAISE(ABORT, 'negative values not allowed in daily fields')
            END;
        END;
        """
    )
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_daily_nonneg_upd
        BEFORE UPDATE ON daily
        BEGIN
            SELECT CASE
                WHEN IFNULL(NEW.units_samoli,0) < 0 OR
                     IFNULL(NEW.units_madour,0) < 0 OR
                     IFNULL(NEW.flour_bags,0) < 0 OR
                     IFNULL(NEW.flour_bag_price,0) < 0 OR
                     IFNULL(NEW.flour_extra,0) < 0 OR
                     IFNULL(NEW.yeast,0) < 0 OR
                     IFNULL(NEW.salt,0) < 0 OR
                     IFNULL(NEW.oil,0) < 0 OR
                     IFNULL(NEW.gas,0) < 0 OR
                     IFNULL(NEW.electricity,0) < 0 OR
                     IFNULL(NEW.water,0) < 0 OR
                     IFNULL(NEW.salaries,0) < 0 OR
                     IFNULL(NEW.maintenance,0) < 0 OR
                     IFNULL(NEW.petty,0) < 0 OR
                     IFNULL(NEW.other_exp,0) < 0 OR
                     IFNULL(NEW.ice,0) < 0 OR
                     IFNULL(NEW.bags,0) < 0 OR
                     IFNULL(NEW.daily_meal,0) < 0 OR
                     IFNULL(NEW.owner_withdrawal,0) < 0 OR
                     IFNULL(NEW.owner_repayment,0) < 0 OR
                     IFNULL(NEW.owner_injection,0) < 0 OR
                     IFNULL(NEW.returns,0) < 0 OR
                     IFNULL(NEW.discounts,0) < 0
                THEN RAISE(ABORT, 'negative values not allowed in daily fields')
            END;
        END;
        """
    )

    conn.commit(); conn.close()

# ==== جداول جديدة: مشتريات الدقيق + غاز شهري ====
def init_inventory_tables():
    conn = _connect(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS flour_purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dte TEXT,
        bags INTEGER,
        bag_price INTEGER,
        note TEXT
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_flourp_dte ON flour_purchases(dte)")
    # منع السالب
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_flourp_nonneg_ins
    BEFORE INSERT ON flour_purchases
    BEGIN
        SELECT CASE
            WHEN IFNULL(NEW.bags,0) < 0 OR IFNULL(NEW.bag_price,0) < 0
            THEN RAISE(ABORT,'negative values not allowed in flour_purchases')
        END;
    END;
    """)
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_flourp_nonneg_upd
    BEFORE UPDATE ON flour_purchases
    BEGIN
        SELECT CASE
            WHEN IFNULL(NEW.bags,0) < 0 OR IFNULL(NEW.bag_price,0) < 0
            THEN RAISE(ABORT,'negative values not allowed in flour_purchases')
        END;
    END;
    """)
    conn.commit(); conn.close()

def init_gas_table():
    conn = _connect(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS gas_settings (
        year INTEGER,
        month INTEGER,
        monthly_gas INTEGER,
        PRIMARY KEY (year, month)
    )
    """)
    conn.commit(); conn.close()

# تهيئة لمرة واحدة لكل جلسة — + ترحيل تلقائي إن وُجد ملف /tmp قديم
if "db_init" not in st.session_state:
    # ترحيل من النسخة المؤقتة القديمة إن وجدت
    old_tmp = "/tmp/bakery_tracker.db"
    if os.path.exists(old_tmp) and not os.path.exists(DB_FILE):
        try:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            os.replace(old_tmp, DB_FILE)
        except Exception:
            pass
    init_db()
    init_inventory_tables()
    init_gas_table()
    st.session_state["db_init"] = True

# ====================== دوال بيانات أساسية ======================
def revenue_from_thousand(units: int, per_thousand: int) -> int:
    u = int(units or 0); p = int(per_thousand or 0)
    if p <= 0:
        return 0
    return int(round((u / p) * THOUSAND))

def set_monthly_rent(year: int, month: int, monthly_rent: int):
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rent_settings(year, month, monthly_rent)
        VALUES(?,?,?)
        ON CONFLICT(year,month) DO UPDATE SET monthly_rent=excluded.monthly_rent
        """,
        (int(year), int(month), int(monthly_rent))
    )
    conn.commit(); conn.close()

def get_monthly_rent(year: int, month: int) -> int:
    conn = _connect(); cur = conn.cursor()
    row = cur.execute("SELECT monthly_rent FROM rent_settings WHERE year=? AND month=?", (year, month)).fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0

@st.cache_data(show_spinner=False)
def rent_per_day_for(dt: pd.Timestamp) -> int:
    y, m = dt.year, dt.month
    rent_m = get_monthly_rent(y, m)
    dim = days_in_month(y, m)
    return int(round(rent_m / dim)) if dim else 0

def add_money_move(dte: date, source: str, amount: int, reason: str):
    if source not in ("cash", "bank"):
        return
    if int(amount or 0) == 0:
        return
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO money_moves (dte, source, amount, reason) VALUES (?,?,?,?)",
        (dte.isoformat() if isinstance(dte, date) else str(dte), source, int(amount), reason)
    )
    conn.commit(); conn.close()

@st.cache_data(show_spinner=False)
def money_balances() -> dict:
    conn = _connect()
    df = pd.read_sql_query("SELECT source, SUM(amount) AS bal FROM money_moves GROUP BY source", conn)
    conn.close()
    cash = int(df.loc[df["source"] == "cash", "bal"].sum()) if not df.empty else 0
    bank = int(df.loc[df["source"] == "bank", "bal"].sum()) if not df.empty else 0
    return {"cash": cash, "bank": bank}

def insert_daily(row: tuple):
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO daily (
            dte,
            units_samoli, per_thousand_samoli,
            units_madour, per_thousand_madour,
            flour_bags, flour_bag_price,
            flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp, ice, bags, daily_meal,
            owner_withdrawal, owner_repayment, owner_injection, funding,
            returns, discounts
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        row
    )
    conn.commit(); conn.close()
    fetch_daily_df.clear()  # تحديث الكاش

# ====================== دوال الدقيق (مشتريات + مخزون + متوسط تكلفة) ======================
def add_flour_purchase(dte: date, bags: int, bag_price: int, note: str = ""):
    if int(bags or 0) <= 0 or int(bag_price or 0) <= 0:
        return
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO flour_purchases (dte, bags, bag_price, note) VALUES (?,?,?,?)",
        (dte.isoformat(), int(bags), int(bag_price), note)
    )
    conn.commit(); conn.close()

@st.cache_data(show_spinner=False)
def flour_stock_on_hand(as_of: date | None = None) -> dict:
    conn = _connect()
    params = []
    q_buy = "SELECT SUM(bags) FROM flour_purchases"
    if as_of:
        q_buy += " WHERE date(dte) <= ?"
        params.append(as_of.isoformat())
    total_buy = conn.execute(q_buy, params).fetchone()[0] or 0

    params2 = []
    q_use = "SELECT SUM(flour_bags) FROM daily"
    if as_of:
        q_use += " WHERE date(dte) <= ?"
        params2.append(as_of.isoformat())
    total_use = conn.execute(q_use, params2).fetchone()[0] or 0
    conn.close()
    return {"purchased": int(total_buy), "used": int(total_use), "on_hand": int(total_buy) - int(total_use)}

@st.cache_data(show_spinner=False)
def avg_bag_cost_until(ts: pd.Timestamp) -> int:
    conn = _connect()
    rows = pd.read_sql_query(
        "SELECT bags, bag_price FROM flour_purchases WHERE date(dte) <= ?",
        conn, params=(ts.date().isoformat(),)
    )
    conn.close()
    if rows.empty or int(rows["bags"].sum()) == 0:
        return 0
    weighted = (rows["bags"] * rows["bag_price"]).sum()
    return int(round(weighted / rows["bags"].sum()))

# ====================== غاز شهري (توزيع يومي تلقائي) ======================
def set_monthly_gas(year: int, month: int, amount: int):
    conn = _connect(); cur = conn.cursor()
    cur.execute("""
    INSERT INTO gas_settings(year, month, monthly_gas)
    VALUES(?,?,?)
    ON CONFLICT(year,month) DO UPDATE SET monthly_gas=excluded.monthly_gas
    """, (int(year), int(month), int(amount)))
    conn.commit(); conn.close()

def get_monthly_gas(year: int, month: int) -> int:
    conn = _connect(); cur = conn.cursor()
    row = cur.execute("SELECT monthly_gas FROM gas_settings WHERE year=? AND month=?", (year, month)).fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0

@st.cache_data(show_spinner=False)
def gas_per_day_for(dt: pd.Timestamp) -> int:
    y
