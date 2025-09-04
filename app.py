# -*- coding: utf-8 -*-
"""
Streamlit Bakery Tracker — شامل (غير دائم) — متجاوب للموبايل
- RTL محسّن للمس + تكديس أعمدة ثابت على الشاشات الصغيرة
- مراقبة مخزون الدقيق (مشتريات + متوسط تكلفة مرجّح + مخزون على اليد)
- الغاز يُضبط شهريًا ويُوزَّع يوميًا تلقائيًا (يمكن تجاوز التوزيع بإدخال يومي)
- نفس الميزات السابقة (لوحة، عملاء، تقارير، نسخ احتياطي)
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

# ====================== إعداد عام ======================
DB_FILE = "/tmp/bakery_tracker.db"   # تخزين غير دائم
THOUSAND = 1000
GROWTH_WINDOW_DAYS = 14

st.set_page_config(page_title="متابعة المخبز — شامل (غير دائم)", page_icon="📊", layout="wide")

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

st.title("📊 نظام متابعة المخبز — شامل (تجريبي غير دائم)")

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

# ====================== قاعدة البيانات ======================
def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
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

    conn.commit()
    conn.close()

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

# تهيئة لمرة واحدة لكل جلسة
if "db_init" not in st.session_state:
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
    y, m = dt.year, dt.month
    monthly = get_monthly_gas(y, m)
    dim = days_in_month(y, m)
    return int(round(monthly / dim)) if dim else 0

# ====================== تحميل البيانات المركّبة ======================
@st.cache_data(show_spinner=False)
def fetch_daily_df() -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"])
    conn.close()
    if df.empty:
        return df

    # الإيرادات
    df["إيراد الصامولي"] = [revenue_from_thousand(u, p) for u, p in zip(df["units_samoli"], df["per_thousand_samoli"])]
    df["إيراد المدور"]   = [revenue_from_thousand(u, p) for u, p in zip(df["units_madour"], df["per_thousand_madour"])]
    df["إجمالي المبيعات"] = (df["إيراد الصامولي"].fillna(0) + df["إيراد المدور"].fillna(0)).astype(int)

    # تكلفة الدقيق = عدد الجوالات المستهلكة × متوسط تكلفة الجوال المرجّح حتى تاريخ اليوم
    avg_costs = []
    bags_series = df["flour_bags"].fillna(0).astype(int)
    for ts, bags in zip(df["dte"], bags_series):
        if bags and bags > 0:
            avg_costs.append(bags * avg_bag_cost_until(pd.Timestamp(ts)))
        else:
            avg_costs.append(0)
    # fallback: لو 0 ولم تُسجّل مشتريات بعد، استخدم سعر اليوم المدخل إن وُجد
    fallback = (bags_series * df["flour_bag_price"].fillna(0).astype(int))
    df["تكلفة الدقيق"] = (pd.Series(avg_costs, index=df.index).where(lambda s: s > 0, fallback)).astype(int)

    # إيجار يومي
    df["إيجار يومي"] = df["dte"].apply(lambda ts: rent_per_day_for(pd.Timestamp(ts)))

    # غاز يومي موزّع (يحترم إدخال يومي إن وُجد)
    if "gas" not in df.columns:
        df["gas"] = 0
    df["gas"] = df.apply(
        lambda r: int(r["gas"]) if int(r["gas"] or 0) > 0 else gas_per_day_for(pd.Timestamp(r["dte"])),
        axis=1
    ).astype(int)

    expense_cols = [
        "تكلفة الدقيق","flour_extra","yeast","salt","oil","gas","electricity","water",
        "salaries","maintenance","petty","other_exp","ice","bags","daily_meal","إيجار يومي"
    ]
    for c in expense_cols:
        if c not in df.columns:
            df[c] = 0

    df["الإجمالي اليومي للمصروفات"] = df[expense_cols].fillna(0).astype(int).sum(axis=1).astype(int)
    df["الربح الصافي لليوم"] = (df["إجمالي المبيعات"].fillna(0) - df["الإجمالي اليومي للمصروفات"].fillna(0)).astype(int)

    total_units = (df["units_samoli"].fillna(0).astype(int) + df["units_madour"].fillna(0).astype(int))
    df["إنتاجية الجوال (رغيف/جوال)"] = [int(u // b) if int(b or 0) > 0 else 0 for u, b in zip(total_units, df["flour_bags"].fillna(0))]

    return df

# ====================== عملاء ======================
def add_client(name: str, active: bool = True):
    conn = _connect(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO clients(name,active) VALUES(?,?)", (name.strip(), 1 if active else 0))
    conn.commit(); conn.close()

@st.cache_data(show_spinner=False)
def list_clients(active_only=False) -> pd.DataFrame:
    conn = _connect()
    q = "SELECT id,name,active FROM clients" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
    df = pd.read_sql_query(q, conn)
    conn.close(); return df

def set_client_active(client_id: int, active: bool):
    conn = _connect(); cur = conn.cursor()
    cur.execute("UPDATE clients SET active=? WHERE id=?", (1 if active else 0, int(client_id)))
    conn.commit(); conn.close()
    list_clients.clear()

def add_client_delivery(dte: date, client_id: int, bread_type: str, units: int, per_thousand: int, payment_method: str, cash_source: str):
    rev = revenue_from_thousand(units, per_thousand)
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO client_deliveries (dte, client_id, bread_type, units, per_thousand, revenue, payment_method, cash_source)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (dte.isoformat(), int(client_id), bread_type, int(units or 0), int(per_thousand or 0), int(rev), payment_method, cash_source)
    )
    conn.commit(); conn.close()

    if payment_method == "cash":
        add_money_move(dte, "cash" if cash_source in ("cash","خزنة") else "bank", rev, f"تحصيل توريد عميل ({bread_type})")

def add_client_payment(dte: date, client_id: int, amount: int, source: str, note: str = "سداد عميل"):
    if int(amount or 0) <= 0:
        return
    conn = _connect(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO client_payments (dte, client_id, amount, source, note) VALUES (?,?,?,?,?)",
        (dte.isoformat(), int(client_id), int(amount), source, note)
    )
    conn.commit(); conn.close()
    add_money_move(dte, source, amount, note)

def fetch_ar_df() -> pd.DataFrame:
    conn = _connect()
    dels = pd.read_sql_query("SELECT dte, client_id, revenue, payment_method FROM client_deliveries", conn, parse_dates=["dte"])
    pays = pd.read_sql_query("SELECT dte, client_id, amount FROM client_payments", conn, parse_dates=["dte"])
    clients = pd.read_sql_query("SELECT id,name FROM clients", conn)
    conn.close()

    if dels.empty and pays.empty:
        return pd.DataFrame(columns=["العميل","إيراد آجل","مدفوع","الرصيد"])

    credit_rev = dels.loc[dels["payment_method"] == "credit"].groupby("client_id")["revenue"].sum() if not dels.empty else pd.Series(dtype=int)
    paid = pays.groupby("client_id")["amount"].sum() if not pays.empty else pd.Series(dtype=int)
    base = pd.DataFrame({"client_id": clients["id"], "العميل": clients["name"]})
    base["إيراد آجل"] = base["client_id"].map(credit_rev).fillna(0).astype(int)
    base["مدفوع"] = base["client_id"].map(paid).fillna(0).astype(int)
    base["الرصيد"] = (base["إيراد آجل"] - base["مدفوع"]).astype(int)
    return base.sort_values("الرصيد", ascending=False)

# ====================== التبويبات ======================
TAB_UNIFIED, TAB_DASH, TAB_MANAGE, TAB_CLIENTS, TAB_REPORT = st.tabs([
    "🧾 الإدخال الموحّد",
    "📈 لوحة المتابعة",
    "🧰 إدارة البيانات",
    "📦 العملاء والتوريد",
    "📑 التقارير",
])

# ====================== الإدخال الموحّد ======================
with TAB_UNIFIED:
    st.subheader("مركز الإدخال اليومي — موحّد")

    with st.expander("A) اليوميات: إنتاج/تسعير + مصروفات + تمويلات", expanded=True):
        with st.form("form_daily", clear_on_submit=False):
            c0, c1, c2 = st.columns(3)
            dte = c0.date_input("التاريخ", value=date.today(), key="in_date")
            flour_bags = c1.number_input("جوالات الدقيق المستهلكة", min_value=0, step=1, format="%d")
            flour_bag_price = c2.number_input("سعر جوال الدقيق (اختياري كـ fallback)", min_value=0, step=1, format="%d")

            st.markdown("**الإنتاج والتسعير بالألف**")
            s1, s2, s3, s4 = st.columns(4)
            units_samoli = s1.number_input("إنتاج الصامولي (عدد)", min_value=0, step=10, format="%d")
            per_thousand_samoli = s2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
            units_madour = s3.number_input("إنتاج المدور (عدد)", min_value=0, step=10, format="%d")
            per_thousand_madour = s4.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")

            st.markdown("**المصروفات التشغيلية**")
            e1, e2, e3, e4, e5 = st.columns(5)
            flour_extra = e1.number_input("مصاريف دقيق إضافية", min_value=0, step=1, format="%d")
            yeast = e2.number_input("خميرة", min_value=0, step=1, format="%d")
            salt = e3.number_input("ملح", min_value=0, step=1, format="%d")
            oil = e4.number_input("زيت/سمن", min_value=0, step=1, format="%d")
            gas_manual = e5.number_input("غاز (اتركه 0 لاستخدام التوزيع الشهري تلقائيًا)", min_value=0, step=1, format="%d")

            e6, e7, e8, e9, e10 = st.columns(5)
            electricity = e6.number_input("كهرباء", min_value=0, step=1, format="%d")
            water = e7.number_input("مياه", min_value=0, step=1, format="%d")
            salaries = e8.number_input("رواتب", min_value=0, step=1, format="%d")
            maintenance = e9.number_input("صيانة", min_value=0, step=1, format="%d")
            petty = e10.number_input("نثريات", min_value=0, step=1, format="%d")

            e11, e12, e13 = st.columns(3)
            other_exp = e11.number_input("مصاريف أخرى", min_value=0, step=1, format="%d")
            ice = e12.number_input("ثلج", min_value=0, step=1, format="%d")
            bags = e13.number_input("أكياس", min_value=0, step=1, format="%d")

            e14, e15 = st.columns(2)
            daily_meal = e14.number_input("فطور يومي", min_value=0, step=1, format="%d")
            exp_pay_source = e15.selectbox("مصدر صرف المصروفات لليوم (اختياري)", ["لا تسجل", "خزنة", "بنك"], index=0)

            st.markdown("**سلفة / رد سلفة / تمويل / تحويلات أخرى (لا تؤثر على الربح)**")
            w1, w2, w3, w4 = st.columns(4)
            owner_withdrawal = w1.number_input("سلفة", min_value=0, step=1, format="%d")
            owner_withdrawal_src = w1.selectbox("مصدر السلفة", ["خزنة", "بنك"], index=0, key="wdsrc")

            owner_repayment = w2.number_input("رد سلفة", min_value=0, step=1, format="%d")
            owner_repayment_src = w2.selectbox("مصدر رد السلفة", ["خزنة", "بنك"], index=0, key="rpsrc")

            owner_injection = w3.number_input("تمويل", min_value=0, step=1, format="%d")
            owner_injection_src = w3.selectbox("مصدر التمويل", ["خزنة", "بنك"], index=1, key="injsrc")

            funding = w4.number_input("تحويلات أخرى (يسمح بسالب/موجب)", value=0, step=1, format="%d")
            funding_src = w4.selectbox("مصدر التحويل", ["خزنة", "بنك"], index=1, key="fdsrc")

            st.markdown("**حقول وصفية (اختياري)**")
            r1, r2 = st.columns(2)
            returns = r1.number_input("مرتجع/هالك", min_value=0, step=1, format="%d")
            discounts = r2.number_input("خصومات/عروض", min_value=0, step=1, format="%d")

            subA = st.form_submit_button("✅ حفظ اليوميات")
            if subA:
                row = (
                    dte.isoformat(),
                    int(units_samoli or 0), int(per_thousand_samoli or 0),
                    int(units_madour or 0), int(per_thousand_madour or 0),
                    int(flour_bags or 0), int(flour_bag_price or 0),
                    int(flour_extra or 0), int(yeast or 0), int(salt or 0), int(oil or 0), int(gas_manual or 0),
                    int(electricity or 0), int(water or 0), int(salaries or 0), int(maintenance or 0),
                    int(petty or 0), int(other_exp or 0), int(ice or 0), int(bags or 0), int(daily_meal or 0),
                    int(owner_withdrawal or 0), int(owner_repayment or 0), int(owner_injection or 0), int(funding or 0),
                    int(returns or 0), int(discounts or 0),
                )
                insert_daily(row)

                total_daily_oper_exp = sum([
                    int(flour_extra or 0), int(yeast or 0), int(salt or 0), int(oil or 0), int(gas_manual or 0),
                    int(electricity or 0), int(water or 0), int(salaries or 0), int(maintenance or 0),
                    int(petty or 0), int(other_exp or 0), int(ice or 0), int(bags or 0), int(daily_meal or 0),
                ])
                if exp_pay_source in ("خزنة", "بنك") and total_daily_oper_exp > 0:
                    add_money_move(dte, "cash" if exp_pay_source == "خزنة" else "bank",
                                   -total_daily_oper_exp, "مصروفات تشغيل لليوم")

                if int(owner_withdrawal or 0) > 0:
                    add_money_move(dte, "cash" if owner_withdrawal_src == "خزنة" else "bank",
                                   -int(owner_withdrawal), "سلفة")
                if int(owner_repayment or 0) > 0:
                    add_money_move(dte, "cash" if owner_repayment_src == "خزنة" else "bank",
                                   +int(owner_repayment), "رد سلفة")
                if int(owner_injection or 0) > 0:
                    add_money_move(dte, "cash" if owner_injection_src == "خزنة" else "bank",
                                   +int(owner_injection), "تمويل")
                if int(funding or 0) != 0:
                    add_money_move(dte, "cash" if funding_src == "خزنة" else "bank",
                                   int(funding), "تحويلات أخرى")

                fetch_daily_df.clear()
                st.success("تم حفظ اليوميات وحركة النقد المرتبطة.")

    with st.expander("B) توريد العملاء (صامولي/مدور) نقدي/آجل", expanded=False):
        act = list_clients(active_only=True)
        if act.empty:
            st.info("أضف عميلًا نشطًا أولاً من قسم إدارة العملاء.")
        else:
            with st.form("form_client_delivery"):
                ca, cb, cc = st.columns([2, 1, 1])
                idx = ca.selectbox("اختر العميل", options=act.index, format_func=lambda i: act.loc[i, "name"])
                d_delivery = cb.date_input("تاريخ التوريد", value=date.today())
                cash_source_for_cash = cc.selectbox("مصدر التحصيل النقدي", ["خزنة", "بنك"], index=0)

                st.caption("**توريد صامولي**")
                cs1, cs2, cs3 = st.columns(3)
                u_s = cs1.number_input("عدد الصامولي", min_value=0, step=10, format="%d")
                p_s = cs2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
                pay_s = cs3.selectbox("طريقة الدفع", ["cash", "credit"], index=0)

                st.caption("**توريد مدور**")
                cm1, cm2, cm3 = st.columns(3)
                u_m = cm1.number_input("عدد المدور", min_value=0, step=10, format="%d")
                p_m = cm2.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
                pay_m = cm3.selectbox("طريقة الدفع ", ["cash", "credit"], index=0)

                subB = st.form_submit_button("💾 حفظ توريد العميل")
                if subB:
                    cid = int(act.loc[idx, "id"])
                    if u_s > 0:
                        add_client_delivery(d_delivery, cid, "samoli", u_s, p_s, pay_s,
                                            "cash" if cash_source_for_cash == "خزنة" else "bank")
                    if u_m > 0:
                        add_client_delivery(d_delivery, cid, "madour", u_m, p_m, pay_m,
                                            "cash" if cash_source_for_cash == "خزنة" else "bank")
                    st.success("تم حفظ توريد العميل.")

    with st.expander("C) سداد عملاء (للآجل)", expanded=False):
        act2 = list_clients(active_only=True)
        if act2.empty:
            st.info("لا يوجد عملاء نشطون.")
        else:
            with st.form("form_client_payment"):
                p1, p2, p3, p4 = st.columns(4)
                idx2 = p1.selectbox("اختر العميل", options=act2.index, format_func=lambda i: act2.loc[i, "name"])
                p_date = p2.date_input("تاريخ السداد", value=date.today())
                p_amount = p3.number_input("مبلغ السداد", min_value=0, step=1, format="%d")
                p_src = p4.selectbox("المصدر", ["خزنة", "بنك"], index=0)
                note = st.text_input("ملاحظة (اختياري)", value="سداد عميل")
                subC = st.form_submit_button("💾 حفظ السداد")
                if subC and p_amount > 0:
                    add_client_payment(p_date, int(act2.loc[idx2, "id"]), p_amount,
                                       "cash" if p_src == "خزنة" else "bank", note)
                    st.success("تم حفظ سداد العميل.")

    with st.expander("D) حركة نقد عامة (خزنة/بنك)", expanded=False):
        with st.form("form_money_move"):
            k1, k2, k3, k4 = st.columns(4)
            mv_date = k1.date_input("التاريخ", value=date.today())
            mv_source = k2.selectbox("المصدر", ["خزنة", "بنك"], index=0)
            mv_amount = k3.number_input("المبلغ (+داخل / -خارج)", value=0, step=1, format="%d")
            mv_reason = k4.text_input("السبب", value="حركة يدوية")
            subD = st.form_submit_button("➕ إضافة حركة نقد")
            if subD and int(mv_amount or 0) != 0:
                add_money_move(mv_date, "cash" if mv_source == "خزنة" else "bank", int(mv_amount), mv_reason or "حركة")
                st.success("تمت إضافة الحركة.")

    with st.expander("E) إعداد الإيجار الشهري (يُوزَّع يوميًا تلقائيًا)", expanded=False):
        with st.form("form_rent"):
            y, m, mr = st.columns(3)
            yy = y.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d")
            mm = m.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d")
            monthly_rent = mr.number_input("الإيجار الشهري", min_value=0, step=1, format="%d")
            subE = st.form_submit_button("💾 حفظ الإيجار")
            if subE:
                set_monthly_rent(int(yy), int(mm), int(monthly_rent))
                rent_per_day_for.clear()
                st.success("تم حفظ الإيجار الشهري.")

    with st.expander("F) إعداد الغاز الشهري (يُوزَّع يوميًا تلقائيًا)", expanded=False):
        gy, gm, ga = st.columns(3)
        gas_y = gy.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d")
        gas_m = gm.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d")
        gas_amt = ga.number_input("قيمة الغاز للشهر", min_value=0, step=1, format="%d")
        if st.button("💾 حفظ الغاز الشهري"):
            set_monthly_gas(int(gas_y), int(gas_m), int(gas_amt))
            gas_per_day_for.clear()
            st.success("تم حفظ قيمة الغاز لهذا الشهر.")

# ====================== لوحة المتابعة ======================
with TAB_DASH:
    st.subheader("📈 لوحة المتابعة")
    df_dash = fetch_daily_df()
    if df_dash.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("إجمالي المبيعات", fmt_i(df_dash["إجمالي المبيعات"].sum()))
        c2.metric("إجمالي المصروفات", fmt_i(df_dash["الإجمالي اليومي للمصروفات"].sum()))
        c3.metric("صافي الربح", fmt_i(df_dash["الربح الصافي لليوم"].sum()))

        fig = px.line(df_dash, x="dte", y="الربح الصافي لليوم", markers=True, title="اتجاه الربح الصافي")
        fig.update_layout(autosize=True, xaxis_title="التاريخ", yaxis_title="الربح", margin=dict(l=10,r=10,t=60,b=10))
        fig.update_traces(hovertemplate="%{y:.0f}")
        fig.update_yaxes(tickformat="d")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})

# ====================== إدارة البيانات ======================
with TAB_MANAGE:
    st.subheader("إدارة البيانات")
    df = fetch_daily_df()
    if df.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        st.markdown("#### حذف سجل يومي")
        opt = st.selectbox(
            "اختر السجل",
            options=df.apply(lambda r: f"{r['id']} — {r['dte'].date().isoformat()} — ربح {fmt_i(r['الربح الصافي لليوم'])}", axis=1)
        )
        if st.button("🗑️ حذف السجل المحدد"):
            sel_id = int(opt.split("—")[0].strip())
            conn = _connect(); cur = conn.cursor()
            cur.execute("DELETE FROM daily WHERE id=?", (sel_id,))
            conn.commit(); conn.close()
            fetch_daily_df.clear()
            st.success("تم الحذف.")

        st.markdown("---")
        st.markdown("#### إعداد الإيجار الشهري (يُوزَّع يوميًا)")
        y, m, mr = st.columns(3)
        yy = y.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d", key="manage_rent_y")
        mm = m.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d", key="manage_rent_m")
        monthly_rent = mr.number_input("الإيجار الشهري", min_value=0, step=1, format="%d", key="manage_rent_amt")
        if st.button("💾 حفظ الإيجار", key="manage_rent_btn"):
            set_monthly_rent(int(yy), int(mm), int(monthly_rent))
            rent_per_day_for.clear()
            st.success("تم حفظ الإيجار الشهري لهذا الشهر.")

        st.markdown("---")
        st.markdown("#### حركة نقد مباشرة (عام)")
        k1, k2, k3, k4 = st.columns(4)
        mv_date = k1.date_input("التاريخ", value=date.today(), key="manage_mv_date")
        mv_source = k2.selectbox("المصدر", ["خزنة", "بنك"], index=0, key="manage_mv_source")
        mv_amount = k3.number_input("المبلغ (+داخل / -خارج)", value=0, step=1, format="%d")
        mv_reason = k4.text_input("السبب", value="حركة يدوية", key="manage_mv_reason")
        if st.button("➕ إضافة حركة نقد", key="manage_mv_btn"):
            add_money_move(mv_date, "cash" if mv_source == "خزنة" else "bank", int(mv_amount), mv_reason or "حركة")
            st.success("تمت إضافة الحركة.")

        bals = money_balances()
        c1, c2 = st.columns(2)
        c1.metric("💰 رصيد الخزنة", fmt_i(bals.get("cash", 0)))
        c2.metric("🏦 رصيد البنك", fmt_i(bals.get("bank", 0)))

        st.markdown("---")
        st.markdown("#### 📦 مخزون الدقيق — مشتريات وإجمالي على اليد")
        c1, c2, c3, c4 = st.columns(4)
        p_date = c1.date_input("تاريخ الشراء", value=date.today(), key="flour_buy_date")
        p_bags = c2.number_input("عدد الجوالات", min_value=0, step=1, format="%d", key="flour_buy_bags")
        p_price = c3.number_input("سعر الجوال", min_value=0, step=1, format="%d", key="flour_buy_price")
        p_note = c4.text_input("ملاحظة", value="", key="flour_buy_note")
        if st.button("➕ إضافة شراء دقيق", key="flour_buy_btn"):
            add_flour_purchase(p_date, p_bags, p_price, p_note)
            flour_stock_on_hand.clear(); avg_bag_cost_until.clear(); fetch_daily_df.clear()
            st.success("تم تسجيل شراء الدقيق.")

        stock = flour_stock_on_hand()
        s1, s2, s3 = st.columns(3)
        s1.metric("إجمالي مشتريات الجوالات", stock["purchased"])
        s2.metric("إجمالي الجوالات المستهلكة", stock["used"])
        s3.metric("المخزون على اليد الآن", stock["on_hand"])

        conn = _connect()
        fp = pd.read_sql_query(
            "SELECT dte AS التاريخ, bags AS الجوالات, bag_price AS سعر_الجوال, note AS ملاحظة FROM flour_purchases ORDER BY dte DESC, id DESC",
            conn
        )
        conn.close()
        if not fp.empty:
            st.dataframe(fp, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🧯 إعداد الغاز الشهري (يُوزَّع يوميًا تلقائيًا)")
        gy, gm, ga = st.columns(3)
        gas_y = gy.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d", key="gas_y_manage")
        gas_m = gm.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d", key="gas_m_manage")
        gas_amt = ga.number_input("قيمة الغاز للشهر", min_value=0, step=1, format="%d", key="gas_amt_manage")
        if st.button("💾 حفظ الغاز الشهري", key="gas_save_manage"):
            set_monthly_gas(int(gas_y), int(gas_m), int(gas_amt))
            gas_per_day_for.clear(); fetch_daily_df.clear()
            st.success("تم حفظ قيمة الغاز لهذا الشهر.")

# ====================== العملاء والتوريد + الذمم ======================
with TAB_CLIENTS:
    st.subheader("📦 إدارة العملاء والتوريد")

    st.markdown("### 1) العملاء")
    new_name = st.text_input("اسم عميل جديد")
    if st.button("➕ إضافة عميل") and new_name.strip():
        add_client(new_name.strip(), True)
        list_clients.clear()
        st.success("تمت إضافة العميل.")

    cldf = list_clients()
    if not cldf.empty:
        st.dataframe(cldf.rename(columns={"id":"ID","name":"العميل","active":"نشط"}), use_container_width=True)
        ids_map = {f"{r.id} — {r.name}": int(r.id) for r in cldf.itertuples(index=False)}
        sel_lbl = st.selectbox("تفعيل/إيقاف عميل", options=list(ids_map.keys()))
        if st.button("تبديل الحالة"):
            curr_active = int(cldf.loc[cldf["id"] == ids_map[sel_lbl], "active"].iloc[0])
            set_client_active(ids_map[sel_lbl], not bool(curr_active))
            st.success("تم التحديث.")

    st.markdown("---")

    st.markdown("### 2) تسجيل توريد يومي")
    act = list_clients(active_only=True)
    if act.empty:
        st.info("أضف عميلًا نشطًا أولاً.")
    else:
        ca, cb, cc = st.columns([2, 1, 1])
        idx = ca.selectbox("اختر العميل", options=act.index, format_func=lambda i: act.loc[i, "name"])
        d_delivery = cb.date_input("تاريخ التوريد", value=date.today(), key="delivery_date")
        cash_source_for_cash = cc.selectbox("مصدر التحصيل النقدي", ["خزنة", "بنك"], index=0)

        st.caption("**توريد صامولي**")
        cs1, cs2, cs3 = st.columns(3)
        u_s = cs1.number_input("عدد الصامولي", min_value=0, step=10, format="%d", key="client_units_samoli")
        p_s = cs2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d", key="client_pt_samoli")
        pay_s = cs3.selectbox("طريقة الدفع", ["cash", "credit"], index=0, key="client_pay_method_s")
        if st.button("💾 حفظ توريد الصامولي"):
            add_client_delivery(d_delivery, int(act.loc[idx, "id"]), "samoli", u_s, p_s, pay_s,
                                "cash" if cash_source_for_cash == "خزنة" else "bank")
            st.success("تم حفظ توريد الصامولي.")

        st.caption("**توريد مدور**")
        cm1, cm2, cm3 = st.columns(3)
        u_m = cm1.number_input("عدد المدور", min_value=0, step=10, format="%d")
        p_m = cm2.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
        pay_m = cm3.selectbox("طريقة الدفع ", ["cash", "credit"], index=0)
        if st.button("💾 حفظ توريد المدور"):
            add_client_delivery(d_delivery, int(act.loc[idx, "id"]), "madour", u_m, p_m, pay_m,
                                "cash" if cash_source_for_cash == "خزنة" else "bank")
            st.success("تم حفظ توريد المدور.")

    st.markdown("---")

    st.markdown("### 3) سداد عملاء (للآجل)")
    if act.empty:
        st.info("لا يوجد عملاء نشطون.")
    else:
        p1, p2, p3, p4 = st.columns(4)
        idx2 = p1.selectbox("اختر العميل", options=act.index, format_func=lambda i: act.loc[i, "name"], key="payc")
        p_date = p2.date_input("تاريخ السداد", value=date.today(), key="client_pay_date")
        p_amount = p3.number_input("مبلغ السداد", min_value=0, step=1, format="%d")
        p_src = p4.selectbox("المصدر", ["خزنة", "بنك"], index=0, key="client_pay_source")
        note = st.text_input("ملاحظة (اختياري)", value="سداد عميل")
        if st.button("💾 حفظ سداد العميل"):
            add_client_payment(p_date, int(act.loc[idx2, "id"]), p_amount, "cash" if p_src == "خزنة" else "bank", note)
            st.success("تم حفظ السداد.")

    st.markdown("---")

    st.markdown("### 4) أداء العملاء والذمم")
    conn = _connect()
    deliv_df = pd.read_sql_query(
        """
        SELECT cd.*, c.name AS client_name
        FROM client_deliveries cd
        LEFT JOIN clients c ON c.id = cd.client_id
        ORDER BY cd.dte ASC, cd.id ASC
        """,
        conn, parse_dates=["dte"]
    )
    conn.close()

    if deliv_df.empty:
        st.info("لا توجد توريدات مسجلة.")
    else:
        grp = deliv_df.groupby("client_name", as_index=False).agg(
            إجمالي_الوحدات=("units","sum"),
            إجمالي_الإيراد=("revenue","sum"),
            نقدي=("payment_method", lambda s: int((s=="cash").count())),
            آجل=("payment_method", lambda s: int((s=="credit").count())),
        ).sort_values("إجمالي_الإيراد", ascending=False)
        st.markdown("#### ترتيب العملاء حسب الإيراد")
        st.dataframe(grp, use_container_width=True)

        cutoff1 = pd.Timestamp(date.today() - timedelta(days=GROWTH_WINDOW_DAYS))
        cutoff0 = pd.Timestamp(date.today() - timedelta(days=2*GROWTH_WINDOW_DAYS))
        recent = deliv_df[deliv_df["dte"] >= cutoff1].groupby("client_name")["revenue"].sum()
        prev   = deliv_df[(deliv_df["dte"] < cutoff1) & (deliv_df["dte"] >= cutoff0)].groupby("client_name")["revenue"].sum()
        growth = (recent - prev).fillna(0)
        growth_pct = ((recent - prev) / prev.replace(0, pd.NA) * 100).fillna(0)

        grow_df = pd.DataFrame({"العميل": sorted(set(deliv_df["client_name"]))})
        grow_df["إيراد آخر 14 يوم"] = grow_df["العميل"].map(recent).fillna(0).astype(int)
        grow_df["إيراد الـ14 قبلها"] = grow_df["العميل"].map(prev).fillna(0).astype(int)
        grow_df["الفرق"] = grow_df["العميل"].map(growth).fillna(0).astype(int)
        grow_df["النسبة %"] = grow_df["العميل"].map(growth_pct).fillna(0).round(0).astype(int)

        st.markdown("#### نمو الإيراد (آخر 14 يوم)")
        st.dataframe(grow_df.sort_values("الفرق", ascending=False), use_container_width=True)

        pick = st.selectbox("اختر عميل لعرض الاتجاه الزمني", options=sorted(set(deliv_df["client_name"])) )
        sub = deliv_df[deliv_df["client_name"] == pick]
        sub_day = sub.groupby("dte", as_index=False)["revenue"].sum()
        line = px.line(sub_day, x="dte", y="revenue", markers=True, title=f"إيراد التوريد — {pick}")
        line.update_layout(autosize=True, xaxis_title="التاريخ", yaxis_title="الإيراد", margin=dict(l=10,r=10,t=60,b=10))
        line.update_traces(hovertemplate="%{y:.0f}")
        line.update_yaxes(tickformat="d")
        st.plotly_chart(line, use_container_width=True, config={"displayModeBar": False, "responsive": True})

    ar = fetch_ar_df()
    st.markdown("#### أرصدة الذمم (العملاء الآجل)")
    st.dataframe(ar[["العميل","إيراد آجل","مدفوع","الرصيد"]] if not ar.empty else ar, use_container_width=True)

# ====================== نسخة احتياطية / استرجاع ======================
st.markdown("---")
st.markdown("#### 🧯 نسخة احتياطية / استرجاع قاعدة البيانات")

if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 0:
    with open(DB_FILE, "rb") as f:
        st.download_button("📥 تنزيل نسخة القاعدة الحالية", f, file_name="bakery_tracker_backup.sqlite",
                           mime="application/x-sqlite3")
else:
    st.info("لا توجد قاعدة بيانات بعد للتنزيل.")

up = st.file_uploader("📤 ارفع ملف SQLite للاسترجاع (سَيَستبدل القاعدة الحالية)", type=["sqlite","db"])
if up is not None:
    try:
        if os.path.exists(DB_FILE):
            os.replace(DB_FILE, DB_FILE + ".bak")
        with open(DB_FILE, "wb") as dst:
            dst.write(up.read())
        fetch_daily_df.clear()
        list_clients.clear()
        flour_stock_on_hand.clear()
        avg_bag_cost_until.clear()
        st.success("تم الاسترجاع بنجاح. أعد تحميل الصفحة لقراءة البيانات.")
    except Exception as e:
        st.error(f"تعذّر الاسترجاع: {e}")

# ====================== التقارير ======================
with TAB_REPORT:
    st.subheader("📑 التقارير")

    st.markdown("### 🗓 تقرير شهري")
    yr, mo = st.columns(2)
    R_y = yr.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d", key="report_year")
    R_m = mo.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d", key="report_month")
    if st.button("⬇️ تنزيل التقرير الشهري (Excel)"):
        df = fetch_daily_df()
        if df.empty:
            st.warning("لا توجد بيانات.")
        else:
            df_month = df[(df["dte"].dt.year == int(R_y)) & (df["dte"].dt.month == int(R_m))].copy()
            if df_month.empty:
                st.warning("لا توجد بيانات داخل هذا الشهر.")
            else:
                summary = {
                    "إجمالي المبيعات":        [int(df_month["إجمالي المبيعات"].sum())],
                    "إجمالي المصروفات":      [int(df_month["الإجمالي اليومي للمصروفات"].sum())],
                    "صافي الربح":            [int(df_month["الربح الصافي لليوم"].sum())],
                    "إجمالي الإيجار":        [int(df_month.get("إيجار يومي", pd.Series()).sum())],
                    "متوسط إنتاجية الجوال":  [int(df_month["إنتاجية الجوال (رغيف/جوال)"].replace(0, pd.NA).dropna().mean() or 0)],
                }
                summary_df = pd.DataFrame(summary)

                conn = _connect()
                delivs = pd.read_sql_query(
                    """
                    SELECT cd.*, c.name AS client_name
                    FROM client_deliveries cd
                    LEFT JOIN clients c ON c.id = cd.client_id
                    WHERE strftime('%Y', cd.dte) = ? AND strftime('%m', cd.dte) = ?
                    ORDER BY cd.dte
                    """,
                    conn, params=(str(int(R_y)), f"{int(R_m):02d}"), parse_dates=["dte"]
                )
                pays = pd.read_sql_query(
                    """
                    SELECT cp.*, c.name AS client_name
                    FROM client_payments cp
                    LEFT JOIN clients c ON c.id = cp.client_id
                    WHERE strftime('%Y', cp.dte) = ? AND strftime('%m', cp.dte) = ?
                    ORDER BY cp.dte
                    """,
                    conn, params=(str(int(R_y)), f"{int(R_m):02d}"), parse_dates=["dte"]
                )
                money = pd.read_sql_query(
                    """
                    SELECT * FROM money_moves
                    WHERE strftime('%Y', dte) = ? AND strftime('%m', dte) = ?
                    ORDER BY dte
                    """,
                    conn, params=(str(int(R_y)), f"{int(R_m):02d}"), parse_dates=["dte"]
                )
                conn.close()

                out_path = f"/tmp/تقرير_المخبز_{int(R_y)}_{int(R_m):02d}.xlsx"
                try:
                    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                        for c in summary_df.columns:
                            summary_df[c] = summary_df[c].fillna(0).astype(int)
                        summary_df.to_excel(writer, sheet_name="ملخص", index=False)

                        show = df_month.copy()
                        show.rename(columns={
                            "dte":"التاريخ",
                            "units_samoli":"إنتاج الصامولي (عدد)",
                            "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
                            "units_madour":"إنتاج المدور (عدد)",
                            "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
                            "flour_bags":"جوالات الدقيق",
                            "flour_bag_price":"سعر جوال الدقيق (fallback)",
                            "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","gas":"غاز (يومي/موزّع)",
                            "electricity":"كهرباء","water":"مياه","salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                            "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي",
                            "owner_withdrawal":"سلفة","owner_repayment":"رد سلفة","owner_injection":"تمويل","funding":"تحويلات أخرى",
                            "returns":"مرتجع/هالك","discounts":"خصومات/عروض"
                        }, inplace=True)
                        for col in show.columns:
                            if col != "التاريخ":
                                show[col] = show[col].fillna(0).astype(int)
                        show.to_excel(writer, sheet_name="اليومي", index=False)

                        if not delivs.empty:
                            delivs_out = delivs.copy()
                            delivs_out.rename(columns={
                                "dte":"التاريخ","client_name":"العميل","bread_type":"النوع","units":"الكمية",
                                "per_thousand":"عدد للرغيف/1000","revenue":"الإيراد","payment_method":"طريقة الدفع","cash_source":"مصدر النقد"
                            }, inplace=True)
                            for c in ["الكمية","عدد للرغيف/1000","الإيراد"]:
                                if c in delivs_out.columns:
                                    delivs_out[c] = delivs_out[c].fillna(0).astype(int)
                            delivs_out.to_excel(writer, sheet_name="العملاء", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد توريدات في هذا الشهر"]).to_excel(writer, sheet_name="العملاء", index=False)

                        if not pays.empty:
                            pays_out = pays.copy()
                            pays_out.rename(columns={"dte":"التاريخ","client_name":"العميل","amount":"المبلغ","source":"المصدر","note":"ملاحظة"}, inplace=True)
                            pays_out["المبلغ"] = pays_out["المبلغ"].fillna(0).astype(int)
                            pays_out.to_excel(writer, sheet_name="سداد_العملاء", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد مدفوعات عملاء في هذا الشهر"]).to_excel(writer, sheet_name="سداد_العملاء", index=False)

                        # أرصدة الذمم الحالية
                        ar_month = fetch_ar_df()
                        ar_month.to_excel(writer, sheet_name="الذمم", index=False)

                        if not money.empty:
                            money_out = money.copy()
                            money_out.rename(columns={"dte":"التاريخ","source":"المصدر","amount":"المبلغ","reason":"السبب"}, inplace=True)
                            money_out["المبلغ"] = pd.to_numeric(money_out["المبلغ"], errors="coerce").fillna(0).astype(int)
                            money_out.to_excel(writer, sheet_name="حركة_النقد", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد حركات نقدية في هذا الشهر"]).to_excel(writer, sheet_name="حركة_النقد", index=False)
                except Exception as e:
                    st.error(f"فشل إنشاء ملف Excel: {e}")
                else:
                    with open(out_path, "rb") as f:
                        st.download_button(
                            label="📥 تحميل التقرير الشهري",
                            data=f,
                            file_name=os.path.basename(out_path),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

    st.markdown("---")

    st.subheader("📆 تقرير أسبوعي")
    w_col1, w_col2 = st.columns(2)
    picked_day = w_col1.date_input("اختر يوم داخل الأسبوع", value=date.today(), key="weekly_pick_day")
    show_chart = w_col2.checkbox("عرض مخطط الربح خلال الأسبوع", value=True, key="weekly_show_chart")

    picked_ts = pd.Timestamp(picked_day)
    week_start = picked_ts - pd.Timedelta(days=(picked_ts.weekday()))   # Monday
    week_end   = week_start + pd.Timedelta(days=6)                      # Sunday

    st.caption(f"المدى: من {week_start.date()} إلى {week_end.date()}")

    if st.button("⬇️ تنزيل التقرير الأسبوعي (Excel)"):
        dfw = fetch_daily_df()
        if dfw.empty:
            st.warning("لا توجد بيانات.")
        else:
            mask = (dfw["dte"] >= week_start) & (dfw["dte"] <= week_end)
            df_week = dfw.loc[mask].copy()
            if df_week.empty:
                st.warning("لا توجد بيانات داخل هذا الأسبوع.")
            else:
                weekly_summary = pd.DataFrame({
                    "إجمالي المبيعات":        [int(df_week["إجمالي المبيعات"].sum())],
                    "إجمالي المصروفات":      [int(df_week["الإجمالي اليومي للمصروفات"].sum())],
                    "صافي الربح":            [int(df_week["الربح الصافي لليوم"].sum())],
                    "إجمالي الإيجار":        [int(df_week.get("إيجار يومي", pd.Series()).sum())],
                    "متوسط إنتاجية الجوال":  [int(df_week["إنتاجية الجوال (رغيف/جوال)"].replace(0, pd.NA).dropna().mean() or 0)],
                })

                conn = _connect()
                delivs_w = pd.read_sql_query(
                    """
                    SELECT cd.*, c.name AS client_name
                    FROM client_deliveries cd
                    LEFT JOIN clients c ON c.id = cd.client_id
                    WHERE date(cd.dte) BETWEEN ? AND ?
                    ORDER BY cd.dte
                    """,
                    conn, params=(week_start.date().isoformat(), week_end.date().isoformat()),
                    parse_dates=["dte"]
                )
                pays_w = pd.read_sql_query(
                    """
                    SELECT cp.*, c.name AS client_name
                    FROM client_payments cp
                    LEFT JOIN clients c ON c.id = cp.client_id
                    WHERE date(cp.dte) BETWEEN ? AND ?
                    ORDER BY cp.dte
                    """,
                    conn, params=(week_start.date().isoformat(), week_end.date().isoformat()),
                    parse_dates=["dte"]
                )
                money_w = pd.read_sql_query(
                    """
                    SELECT * FROM money_moves
                    WHERE date(dte) BETWEEN ? AND ?
                    ORDER BY dte
                    """,
                    conn, params=(week_start.date().isoformat(), week_end.date().isoformat()),
                    parse_dates=["dte"]
                )
                conn.close()

                out_w_path = f"/tmp/تقرير_المخبز_اسبوع_{week_start.date()}_{week_end.date()}.xlsx"
                try:
                    with pd.ExcelWriter(out_w_path, engine="openpyxl") as writer:
                        for c in weekly_summary.columns:
                            weekly_summary[c] = weekly_summary[c].fillna(0).astype(int)
                        weekly_summary.to_excel(writer, sheet_name="ملخص", index=False)

                        show_w = df_week.copy()
                        show_w.rename(columns={
                            "dte":"التاريخ",
                            "units_samoli":"إنتاج الصامولي (عدد)",
                            "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
                            "units_madour":"إنتاج المدور (عدد)",
                            "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
                            "flour_bags":"جوالات الدقيق",
                            "flour_bag_price":"سعر جوال الدقيق (fallback)",
                            "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","gas":"غاز (يومي/موزّع)",
                            "electricity":"كهرباء","water":"مياه","salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                            "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي",
                            "owner_withdrawal":"سلفة","owner_repayment":"رد سلفة","owner_injection":"تمويل","funding":"تحويلات أخرى",
                            "returns":"مرتجع/هالك","discounts":"خصومات/عروض"
                        }, inplace=True)
                        for col in show_w.columns:
                            if col != "التاريخ":
                                show_w[col] = show_w[col].fillna(0).astype(int)
                        show_w.to_excel(writer, sheet_name="اليومي", index=False)

                        if not delivs_w.empty:
                            del_out = delivs_w.copy()
                            del_out.rename(columns={
                                "dte":"التاريخ","client_name":"العميل","bread_type":"النوع","units":"الكمية",
                                "per_thousand":"عدد للرغيف/1000","revenue":"الإيراد","payment_method":"طريقة الدفع","cash_source":"مصدر النقد"
                            }, inplace=True)
                            for c in ["الكمية","عدد للرغيف/1000","الإيراد"]:
                                if c in del_out.columns:
                                    del_out[c] = del_out[c].fillna(0).astype(int)
                            del_out.to_excel(writer, sheet_name="العملاء", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد توريدات في هذا الأسبوع"]).to_excel(writer, sheet_name="العملاء", index=False)

                        if not pays_w.empty:
                            pays_out = pays_w.copy()
                            pays_out.rename(columns={"dte":"التاريخ","client_name":"العميل","amount":"المبلغ","source":"المصدر","note":"ملاحظة"}, inplace=True)
                            pays_out["المبلغ"] = pays_out["المبلغ"].fillna(0).astype(int)
                            pays_out.to_excel(writer, sheet_name="سداد_العملاء", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد مدفوعات عملاء في هذا الأسبوع"]).to_excel(writer, sheet_name="سداد_العملاء", index=False)

                        if not money_w.empty:
                            money_out = money_w.copy()
                            money_out.rename(columns={"dte":"التاريخ","source":"المصدر","amount":"المبلغ","reason":"السبب"}, inplace=True)
                            money_out["المبلغ"] = pd.to_numeric(money_out["المبلغ"], errors="coerce").fillna(0).astype(int)
                            money_out.to_excel(writer, sheet_name="حركة_النقد", index=False)
                        else:
                            pd.DataFrame(columns=["لا توجد حركات نقدية في هذا الأسبوع"]).to_excel(writer, sheet_name="حركة_النقد", index=False)
                except Exception as e:
                    st.error(f"فشل إنشاء ملف Excel: {e}")
                else:
                    with open(out_w_path, "rb") as f:
                        st.download_button(
                            label="📥 تحميل التقرير الأسبوعي",
                            data=f,
                            file_name=os.path.basename(out_w_path),
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

    if show_chart:
        dfw2 = fetch_daily_df()
        if not dfw2.empty:
            mask2 = (dfw2["dte"] >= week_start) & (dfw2["dte"] <= week_end)
            dfx = dfw2.loc[mask2, ["dte","الربح الصافي لليوم"]].copy()
            if not dfx.empty:
                fig_w = px.line(dfx, x="dte", y="الربح الصافي لليوم", markers=True, title="الربح الصافي خلال الأسبوع")
                fig_w.update_layout(autosize=True, xaxis_title="التاريخ", yaxis_title="الربح الصافي", margin=dict(l=10,r=10,t=60,b=10))
                fig_w.update_traces(hovertemplate="%{y:.0f}")
                fig_w.update_yaxes(tickformat="d")
                st.plotly_chart(fig_w, use_container_width=True, config={"displayModeBar": False, "responsive": True})
