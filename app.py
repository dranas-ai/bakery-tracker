# -*- coding: utf-8 -*-
"""
Streamlit Bakery Tracker — إصدار شامل (غير دائم)
- أعداد صحيحة فقط (بدون كسور/فواصل)
- نوعان خبز: صامولي/مدور — تسعير بالألف (كم رغيف لكل 1000)
- تكلفة الدقيق = عدد الجوالات * سعر الجوال
- مصروفات إضافية: ثلج/أكياس/فطور يومي/... إلخ
- إيجار يومي محسوب تلقائيًا من الإيجار الشهري عبر جدول rent_settings
- سلفة / رد سلفة / تمويل / تحويلات أخرى — لا تؤثر على الربح، وتُسجَّل في حركة النقد باختيار المصدر (خزنة/بنك)
- فصل الكاش عن البنك عبر جدول money_moves + عرض أرصدة الخزنة والبنك
- العملاء والتوريد اليومي (نقدي/آجل) + مدفوعات العملاء + أرصدة الذمم
- تقرير شهري + أسبوعي متعدد الأوراق للتنزيل (ملخص/يومي/العملاء/الذمم/حركة النقد)
- مؤشر إنتاجية جوال الدقيق

مهم: النسخة غير دائمة — قاعدة البيانات في /tmp
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

# ====================== ثوابت عامة ======================
DB_FILE = "/tmp/bakery_tracker.db"   # تخزين غير دائم
THOUSAND = 1000
FUND_LOOKBACK_DAYS = 14
GROWTH_WINDOW_DAYS = 14

# =============== أدوات مساعدة عامة ===============
def fmt_i(x):
    """تنسيق رقم صحيح كنص بدون فواصل/كسور."""
    try:
        return str(int(round(float(x or 0))))
    except Exception:
        return "0"

@st.cache_data(show_spinner=False)
def days_in_month(y: int, m: int) -> int:
    if m == 12:
        d1 = date(y, m, 1)
        d2 = date(y+1, 1, 1)
    else:
        d1 = date(y, m, 1)
        d2 = date(y, m+1, 1)
    return (d2 - d1).days

# ====================== اتصال/تهيئة قاعدة البيانات ======================
def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = _connect()
    cur = conn.cursor()

    # سجل اليوميات التشغيلية
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            -- إنتاج وتسعير بالألف
            units_samoli INTEGER,
            per_thousand_samoli INTEGER,
            units_madour INTEGER,
            per_thousand_madour INTEGER,
            -- الدقيق
            flour_bags INTEGER,
            flour_bag_price INTEGER,
            -- مصروفات تشغيلية
            flour_extra INTEGER,
            yeast INTEGER,
            salt INTEGER,
            oil INTEGER,
            gas INTEGER,
            electricity INTEGER,
            water INTEGER,
            salaries INTEGER,
            maintenance INTEGER,
            petty INTEGER,
            other_exp INTEGER,
            ice INTEGER,
            bags INTEGER,
            daily_meal INTEGER,
            -- سلفة/رد/تمويل/تحويلات
            owner_withdrawal INTEGER,   -- سلفة
            owner_repayment INTEGER,    -- رد سلفة
            owner_injection INTEGER,    -- تمويل
            funding INTEGER,            -- تحويلات أخرى (قد تكون موجبة/سالبة)
            -- حقول وصفية أخرى
            returns INTEGER,
            discounts INTEGER
        )
        """
    )

    # عملاء
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            active INTEGER DEFAULT 1
        )
        """
    )

    # توريدات العملاء
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            client_id INTEGER,
            bread_type TEXT,       -- 'samoli' أو 'madour'
            units INTEGER,
            per_thousand INTEGER,
            revenue INTEGER,       -- (units/per_thousand)*1000 مقربة للصحيح
            payment_method TEXT,   -- 'cash' أو 'credit'
            cash_source TEXT,      -- 'cash' أو 'bank' عند الدفع النقدي
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )

    # مدفوعات العملاء (لسداد الآجل)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS client_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            client_id INTEGER,
            amount INTEGER,
            source TEXT,           -- 'cash' أو 'bank'
            note TEXT,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )

    # إعداد الإيجار الشهري
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

    # حركة النقد (خزنة/بنك)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS money_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,
            source TEXT,    -- 'cash' أو 'bank'
            amount INTEGER, -- +داخل / -خارج
            reason TEXT     -- وصف مختصر
        )
        """
    )

    # ترقيات خفيفة لو أعمدة ناقصة في daily
    cur.execute("PRAGMA table_info(daily)")
    cols = {r[1] for r in cur.fetchall()}
    for col, sql in [
        ("flour_bag_price", "ALTER TABLE daily ADD COLUMN flour_bag_price INTEGER"),
        ("owner_withdrawal", "ALTER TABLE daily ADD COLUMN owner_withdrawal INTEGER"),
        ("owner_repayment", "ALTER TABLE daily ADD COLUMN owner_repayment INTEGER"),
        ("owner_injection", "ALTER TABLE daily ADD COLUMN owner_injection INTEGER"),
        ("funding", "ALTER TABLE daily ADD COLUMN funding INTEGER"),
        ("returns", "ALTER TABLE daily ADD COLUMN returns INTEGER"),
        ("discounts", "ALTER TABLE daily ADD COLUMN discounts INTEGER"),
    ]:
        if col not in cols:
            try:
                cur.execute(sql)
            except Exception:
                pass

    conn.commit()
    conn.close()

# ====================== دوال مساعدة للبيانات ======================

def revenue_from_thousand(units: int, per_thousand: int) -> int:
    u = int(units or 0)
    p = int(per_thousand or 0)
    if p <= 0:
        return 0
    return int(round((u / p) * THOUSAND))

# الإيجار الشهري/اليومي
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

def rent_per_day_for(dt: pd.Timestamp) -> int:
    y, m = dt.year, dt.month
    rent_m = get_monthly_rent(y, m)
    dim = days_in_month(y, m)
    return int(round(rent_m / dim)) if dim else 0

# حركة النقد
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

def money_balances() -> dict:
    conn = _connect()
    df = pd.read_sql_query("SELECT source, SUM(amount) AS bal FROM money_moves GROUP BY source", conn)
    conn.close()
    cash = int(df.loc[df["source"] == "cash", "bal"].sum()) if not df.empty else 0
    bank = int(df.loc[df["source"] == "bank", "bal"].sum()) if not df.empty else 0
    return {"cash": cash, "bank": bank}

# CRUD: daily
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

def fetch_daily_df() -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"])
    conn.close()
    if df.empty:
        return df

    # إيرادات النوعين
    df["إيراد الصامولي"] = [revenue_from_thousand(u, p) for u, p in zip(df["units_samoli"], df["per_thousand_samoli"])]
    df["إيراد المدور"]   = [revenue_from_thousand(u, p) for u, p in zip(df["units_madour"], df["per_thousand_madour"])]
    df["إجمالي المبيعات"] = (df["إيراد الصامولي"].fillna(0) + df["إيراد المدور"].fillna(0)).astype(int)

    # تكلفة الدقيق
    df["تكلفة الدقيق"] = (df["flour_bags"].fillna(0).astype(int) * df["flour_bag_price"].fillna(0).astype(int)).astype(int)

    # إيجار يومي من الإعدادات
    df["إيجار يومي"] = df["dte"].apply(lambda ts: rent_per_day_for(pd.Timestamp(ts)))

    # إجمالي المصروفات اليومية (تشغيلية + إيجار يومي)
    expense_cols = [
        "تكلفة الدقيق","flour_extra","yeast","salt","oil","gas","electricity","water",
        "salaries","maintenance","petty","other_exp","ice","bags","daily_meal",
        "إيجار يومي"
    ]
    for c in expense_cols:
        if c not in df.columns:
            df[c] = 0
    df["الإجمالي اليومي للمصروفات"] = df[expense_cols].fillna(0).astype(int).sum(axis=1).astype(int)

    # صافي الربح
    df["الربح الصافي لليوم"] = (df["إجمالي المبيعات"].fillna(0) - df["الإجمالي اليومي للمصروفات"].fillna(0)).astype(int)

    # إنتاجية جوال الدقيق = إجمالي الأرغفة / الجوالات
    total_units = (df["units_samoli"].fillna(0).astype(int) + df["units_madour"].fillna(0).astype(int))
    df["إنتاجية الجوال (رغيف/جوال)"] = [int(u // b) if int(b or 0) > 0 else 0 for u, b in zip(total_units, df["flour_bags"].fillna(0))]

    return df

# عملاء
def add_client(name: str, active: bool = True):
    conn = _connect(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO clients(name,active) VALUES(?,?)", (name.strip(), 1 if active else 0))
    conn.commit(); conn.close()

def list_clients(active_only=False) -> pd.DataFrame:
    conn = _connect()
    q = "SELECT id,name,active FROM clients" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
    df = pd.read_sql_query(q, conn)
    conn.close(); return df

def set_client_active(client_id: int, active: bool):
    conn = _connect(); cur = conn.cursor()
    cur.execute("UPDATE clients SET active=? WHERE id=?", (1 if active else 0, int(client_id)))
    conn.commit(); conn.close()

# توريدات العملاء
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

    # لو نقدي: نسجل حركة نقد
    if payment_method == "cash":
        add_money_move(dte, cash_source, rev, f"تحصيل توريد عميل ({bread_type})")

# مدفوعات العملاء (لسداد الآجل)
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

# أرصدة الذمم
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
# ====================== التهيئة وواجهة المستخدم (Tabs) ======================
st.set_page_config(page_title="متابعة المخبز — شامل (غير دائم)", layout="wide")
st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; font-family: "Segoe UI", "Tahoma", "Arial", sans-serif; }
    [data-testid="stMetricLabel"] { direction: rtl; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 نظام متابعة المخبز — شامل (تجريبي غير دائم)")
init_db()

# التبويبات الرئيسية (ستُستخدم في الأجزاء التالية)
TAB_INPUT, TAB_DASH, TAB_MANAGE, TAB_CLIENTS, TAB_REPORT = st.tabs([
    "📝 الإدخال اليومي",
    "📈 لوحة المتابعة",
    "🧰 إدارة البيانات",
    "📦 العملاء والتوريد",
    "📑 التقارير",
])

# ====================== الجزء 2/6 — تبويب الإدخال اليومي ======================
with TAB_INPUT:
    st.subheader("بيانات اليوم")
    c0, c1, c2 = st.columns(3)
    dte = c0.date_input("التاريخ", value=date.today())
    flour_bags = c1.number_input("جوالات الدقيق المستهلكة", min_value=0, step=1, format="%d")
    flour_bag_price = c2.number_input("سعر جوال الدقيق", min_value=0, step=1, format="%d")

    st.markdown("### الإنتاج والتسعير بالألف")
    s1, s2, s3, s4 = st.columns(4)
    units_samoli = s1.number_input("إنتاج الصامولي (عدد)", min_value=0, step=10, format="%d")
    per_thousand_samoli = s2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
    units_madour = s3.number_input("إنتاج المدور (عدد)", min_value=0, step=10, format="%d")
    per_thousand_madour = s4.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")

    st.markdown("### المصروفات اليومية")
    e1, e2, e3, e4, e5 = st.columns(5)
    flour_extra = e1.number_input("مصاريف دقيق إضافية", min_value=0, step=1, format="%d")
    yeast = e2.number_input("خميرة", min_value=0, step=1, format="%d")
    salt = e3.number_input("ملح", min_value=0, step=1, format="%d")
    oil = e4.number_input("زيت/سمن", min_value=0, step=1, format="%d")
    gas = e5.number_input("غاز", min_value=0, step=1, format="%d")

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

    st.markdown("### سلفة / رد سلفة / تمويل / تحويلات أخرى (لا تؤثر على الربح)")
    w1, w2, w3, w4 = st.columns(4)
    owner_withdrawal = w1.number_input("سلفة", min_value=0, step=1, format="%d")
    owner_withdrawal_src = w1.selectbox("مصدر السلفة", ["خزنة", "بنك"], index=0, key="wdsrc")

    owner_repayment = w2.number_input("رد سلفة", min_value=0, step=1, format="%d")
    owner_repayment_src = w2.selectbox("مصدر رد السلفة", ["خزنة", "بنك"], index=0, key="rpsrc")

    owner_injection = w3.number_input("تمويل", min_value=0, step=1, format="%d")
    owner_injection_src = w3.selectbox("مصدر التمويل", ["خزنة", "بنك"], index=1, key="injsrc")

    # يسمح بالسالب/الموجب
    funding = w4.number_input("تحويلات أخرى (يسمح بسالب/موجب)", value=0, step=1, format="%d")
    funding_src = w4.selectbox("مصدر التحويل", ["خزنة", "بنك"], index=1, key="fdsrc")

    st.markdown("### حقول وصفية (اختياري)")
    r1, r2 = st.columns(2)
    returns = r1.number_input("مرتجع/هالك", min_value=0, step=1, format="%d")
    discounts = r2.number_input("خصومات/عروض", min_value=0, step=1, format="%d")

    if st.button("✅ حفظ السجل"):
        row = (
            dte.isoformat(),
            units_samoli, per_thousand_samoli,
            units_madour, per_thousand_madour,
            flour_bags, flour_bag_price,
            flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp, ice, bags, daily_meal,
            owner_withdrawal, owner_repayment, owner_injection, funding,
            returns, discounts,
        )
        insert_daily(row)

        # حركة نقد للمصروفات (اختياري - حسب اختيارك)
        total_daily_oper_exp = sum([
            flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp, ice, bags, daily_meal,
        ])
        if exp_pay_source in ("خزنة", "بنك") and total_daily_oper_exp > 0:
            add_money_move(dte, "cash" if exp_pay_source == "خزنة" else "bank", -int(total_daily_oper_exp), "مصروفات تشغيل لليوم")

        # حركة نقد للسلفة/الرد/التمويل/التحويلات الأخرى
        if owner_withdrawal > 0:
            add_money_move(dte, "cash" if owner_withdrawal_src == "خزنة" else "bank", -int(owner_withdrawal), "سلفة")
        if owner_repayment > 0:
            add_money_move(dte, "cash" if owner_repayment_src == "خزنة" else "bank", +int(owner_repayment), "رد سلفة")
        if owner_injection > 0:
            add_money_move(dte, "cash" if owner_injection_src == "خزنة" else "bank", +int(owner_injection), "تمويل")
        if int(funding) != 0:
            add_money_move(dte, "cash" if funding_src == "خزنة" else "bank", int(funding), "تحويلات أخرى")

        st.success("تم حفظ السجل وحركة النقد المرتبطة به")

    st.caption("⚠️ النسخة غير دائمة — أي إعادة تشغيل/نشر ستمسح البيانات.")
# ====================== الجزء 3/6 — تبويب لوحة المتابعة ======================
with TAB_DASH:
    st.subheader("لوحة المتابعة")
    df = fetch_daily_df()
    if df.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        total_revenue = int(df["إجمالي المبيعات"].sum())
        total_exp = int(df["الإجمالي اليومي للمصروفات"].sum())
        total_profit = int(total_revenue - total_exp)
        avg_daily_profit = int(df["الربح الصافي لليوم"].replace(0, pd.NA).dropna().mean() or 0)

        # سلفة/رد/تمويل/تحويلات
        salfa_sum = int(df.get("owner_withdrawal", pd.Series()).fillna(0).sum())
        radd_sum = int(df.get("owner_repayment", pd.Series()).fillna(0).sum())
        tamweel_sum = int(df.get("owner_injection", pd.Series()).fillna(0).sum())
        transfers_sum = int(df.get("funding", pd.Series()).fillna(0).sum())
        current_balance = tamweel_sum + radd_sum - salfa_sum  # الرصيد بينك وبين المخبز

        # رصيد الخزنة والبنك
        bals = money_balances()
        cash_bal = bals.get("cash", 0)
        bank_bal = bals.get("bank", 0)

        # إيجار
        total_rent = int(df.get("إيجار يومي", pd.Series()).fillna(0).sum())

        # إنتاجية الدقيق
        prod_avg = int(df["إنتاجية الجوال (رغيف/جوال)"].replace(0, pd.NA).dropna().mean() or 0)

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("إجمالي المبيعات", fmt_i(total_revenue))
        c2.metric("إجمالي المصروفات", fmt_i(total_exp))
        c3.metric("صافي الربح", fmt_i(total_profit))
        c4.metric("📌 رصيد السلفة", fmt_i(current_balance))
        c5.metric("💰 رصيد الخزنة", fmt_i(cash_bal))
        c6.metric("🏦 رصيد البنك", fmt_i(bank_bal))

        c7, c8, c9 = st.columns(3)
        c7.metric("🧱 إجمالي الإيجار", fmt_i(total_rent))
        c8.metric("🥖 إنتاجية الجوال (متوسط)", fmt_i(prod_avg))
        c9.metric("إيراد الصامولي", fmt_i(int(df["إيراد الصامولي"].sum())))

        # حالة المخبز بناءً على تمويل آخر 14 يوم
        recent_cutoff = pd.Timestamp(date.today() - timedelta(days=FUND_LOOKBACK_DAYS))
        recent_fund = int(df.loc[df["dte"] >= recent_cutoff, "owner_injection"].fillna(0).sum())
        st.metric("⚖️ حالة المخبز", "يغطي نفسه" if (total_profit >= 0 and recent_fund == 0) else "يعتمد على تمويل")

        st.markdown("### الربح الصافي اليومي")
        fig = px.line(df, x="dte", y="الربح الصافي لليوم", markers=True)
        fig.update_layout(xaxis_title="التاريخ", yaxis_title="الربح الصافي")
        fig.update_traces(hovertemplate="%{y:.0f}")
        fig.update_yaxes(tickformat="d")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### ملخص الإيرادات حسب النوع")
        sum_df = pd.DataFrame({
            "البند": ["إيراد الصامولي", "إيراد المدور"],
            "القيمة": [int(df["إيراد الصامولي"].sum()), int(df["إيراد المدور"].sum())]
        })
        bar = px.bar(sum_df, x="البند", y="القيمة")
        bar.update_traces(hovertemplate="%{y:.0f}")
        bar.update_yaxes(tickformat="d")
        st.plotly_chart(bar, use_container_width=True)

        st.markdown("### السجل التفصيلي")
        show = df.copy()
        show.rename(columns={
            "dte":"التاريخ",
            "units_samoli":"إنتاج الصامولي (عدد)",
            "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
            "units_madour":"إنتاج المدور (عدد)",
            "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
            "flour_bags":"جوالات الدقيق",
            "flour_bag_price":"سعر جوال الدقيق",
            "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","gas":"غاز",
            "electricity":"كهرباء","water":"مياه","salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
            "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي",
            "owner_withdrawal":"سلفة","owner_repayment":"رد سلفة","owner_injection":"تمويل","funding":"تحويلات أخرى",
            "returns":"مرتجع/هالك","discounts":"خصومات/عروض"
        }, inplace=True)
        for col in [
            "إيراد الصامولي","إيراد المدور","إجمالي المبيعات","تكلفة الدقيق","إيجار يومي",
            "دقيق إضافي","خميرة","ملح","زيت/سمن","غاز","كهرباء","مياه","رواتب","صيانة","نثريات","مصاريف أخرى","ثلج","أكياس","فطور يومي",
            "الإجمالي اليومي للمصروفات","الربح الصافي لليوم","سلفة","رد سلفة","تمويل","تحويلات أخرى","مرتجع/هالك","خصومات/عروض",
            "إنتاجية الجوال (رغيف/جوال)"
        ]:
            if col in show.columns:
                show[col] = show[col].fillna(0).astype(int)
        st.dataframe(show.drop(columns=["id"]) if "id" in show.columns else show, use_container_width=True)
# ====================== الجزء 4/6 — إدارة البيانات ======================
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
            st.success("تم الحذف.")

    st.markdown("---")
    st.markdown("#### إعداد الإيجار الشهري (يُوزَّع يوميًا)")
    y, m, mr = st.columns(3)
    yy = y.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d")
    mm = m.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d")
    monthly_rent = mr.number_input("الإيجار الشهري", min_value=0, step=1, format="%d")
    if st.button("💾 حفظ الإيجار"):
        set_monthly_rent(int(yy), int(mm), int(monthly_rent))
        st.success("تم حفظ الإيجار الشهري لهذا الشهر.")

    st.markdown("---")
    st.markdown("#### حركة نقد مباشرة (عام)")
    k1, k2, k3, k4 = st.columns(4)
    mv_date = k1.date_input("التاريخ", value=date.today())
    mv_source = k2.selectbox("المصدر", ["خزنة", "بنك"], index=0)
    mv_amount = k3.number_input("المبلغ (+داخل / -خارج)", value=0, step=1, format="%d")
    mv_reason = k4.text_input("السبب", value="حركة يدوية")
    if st.button("➕ إضافة حركة نقد"):
        add_money_move(mv_date, "cash" if mv_source == "خزنة" else "bank", int(mv_amount), mv_reason or "حركة")
        st.success("تمت إضافة الحركة.")

    # عرض الأرصدة
    bals = money_balances()
    c1, c2 = st.columns(2)
    c1.metric("💰 رصيد الخزنة", fmt_i(bals.get("cash", 0)))
    c2.metric("🏦 رصيد البنك", fmt_i(bals.get("bank", 0)))
# ====================== الجزء 5/6 — العملاء والتوريد + الذمم ======================
with TAB_CLIENTS:
    st.subheader("📦 إدارة العملاء والتوريد")

    # -------- 1) العملاء --------
    st.markdown("### 1) العملاء")
    new_name = st.text_input("اسم عميل جديد")
    if st.button("➕ إضافة عميل") and new_name.strip():
        add_client(new_name.strip(), True)
        st.success("تمت إضافة العميل.")

    cldf = list_clients()
    if not cldf.empty:
        st.dataframe(cldf.rename(columns={"id":"ID","name":"العميل","active":"نشط"}), use_container_width=True)
        # تبديل حالة عميل
        ids_map = {f"{r.id} — {r.name}": int(r.id) for r in cldf.itertuples(index=False)}
        sel_lbl = st.selectbox("تفعيل/إيقاف عميل", options=list(ids_map.keys()))
        if st.button("تبديل الحالة"):
            curr_active = int(cldf.loc[cldf["id"] == ids_map[sel_lbl], "active"].iloc[0])
            set_client_active(ids_map[sel_lbl], not bool(curr_active))
            st.success("تم التحديث.")

    st.markdown("---")

    # -------- 2) تسجيل توريد يومي --------
    st.markdown("### 2) تسجيل توريد يومي")
    act = list_clients(active_only=True)
    if act.empty:
        st.info("أضف عميلًا نشطًا أولاً.")
    else:
        ca, cb, cc = st.columns([2, 1, 1])
        idx = ca.selectbox("اختر العميل", options=act.index, format_func=lambda i: act.loc[i, "name"])
        d_delivery = cb.date_input("تاريخ التوريد", value=date.today())
        cash_source_for_cash = cc.selectbox("مصدر التحصيل النقدي", ["خزنة", "بنك"], index=0)

        st.caption("**توريد صامولي**")
        cs1, cs2, cs3 = st.columns(3)
        u_s = cs1.number_input("عدد الصامولي", min_value=0, step=10, format="%d")
        p_s = cs2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
        pay_s = cs3.selectbox("طريقة الدفع", ["cash", "credit"], index=0)
        if st.button("💾 حفظ توريد الصامولي"):
            add_client_delivery(d_delivery, int(act.loc[idx, "id"]), "samoli", u_s, p_s, pay_s, "cash" if cash_source_for_cash == "خزنة" else "bank")
            st.success("تم حفظ توريد الصامولي.")

        st.caption("**توريد مدور**")
        cm1, cm2, cm3 = st.columns(3)
        u_m = cm1.number_input("عدد المدور", min_value=0, step=10, format="%d")
        p_m = cm2.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0, step=10, format="%d")
        pay_m = cm3.selectbox("طريقة الدفع ", ["cash", "credit"], index=0)
        if st.button("💾 حفظ توريد المدور"):
            add_client_delivery(d_delivery, int(act.loc[idx, "id"]), "madour", u_m, p_m, pay_m, "cash" if cash_source_for_cash == "خزنة" else "bank")
            st.success("تم حفظ توريد المدور.")

    st.markdown("---")

    # -------- 3) سداد عملاء (للآجل) --------
    st.markdown("### 3) سداد عملاء (للآجل)")
    if act.empty:
        st.info("لا يوجد عملاء نشطون.")
    else:
        p1, p2, p3, p4 = st.columns(4)
        idx2 = p1.selectbox("اختر العميل", options=act.index, format_func=lambda i: act.loc[i, "name"], key="payc")
        p_date = p2.date_input("تاريخ السداد", value=date.today())
        p_amount = p3.number_input("مبلغ السداد", min_value=0, step=1, format="%d")
        p_src = p4.selectbox("المصدر", ["خزنة", "بنك"], index=0)
        note = st.text_input("ملاحظة (اختياري)", value="سداد عميل")
        if st.button("💾 حفظ سداد العميل"):
            add_client_payment(p_date, int(act.loc[idx2, "id"]), p_amount, "cash" if p_src == "خزنة" else "bank", note)
            st.success("تم حفظ السداد.")

    st.markdown("---")

    # -------- 4) أداء العملاء والذمم --------
    st.markdown("### 4) أداء العملاء والذمم")

    # جدول توريدات للعملاء من القاعدة
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

    # ملخص الإيراد لكل عميل
    if deliv_df.empty:
        st.info("لا توجد توريدات مسجلة.")
    else:
        grp = deliv_df.groupby("client_name", as_index=False).agg(
            إجمالي_الوحدات=("units","sum"),
            إجمالي_الإيراد=("revenue","sum"),
            نقدي=("payment_method", lambda s: int((s=="cash").sum())),
            آجل=("payment_method", lambda s: int((s=="credit").sum())),
        ).sort_values("إجمالي_الإيراد", ascending=False)
        st.markdown("#### ترتيب العملاء حسب الإيراد")
        st.dataframe(grp, use_container_width=True)

        # نمو الإيراد لآخر 14 يوم مقابل الـ 14 السابقة
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

        # اختيار عميل لعرض الاتجاه الزمني
        pick = st.selectbox("اختر عميل لعرض الاتجاه الزمني", options=sorted(set(deliv_df["client_name"])) )
        sub = deliv_df[deliv_df["client_name"] == pick]
        sub_day = sub.groupby("dte", as_index=False)["revenue"].sum()
        line = px.line(sub_day, x="dte", y="revenue", markers=True, title=f"إيراد التوريد — {pick}")
        line.update_layout(xaxis_title="التاريخ", yaxis_title="الإيراد")
        line.update_traces(hovertemplate="%{y:.0f}")
        line.update_yaxes(tickformat="d")
        st.plotly_chart(line, use_container_width=True)

    # الذمم (AR)
    ar = fetch_ar_df()
    st.markdown("#### أرصدة الذمم (العملاء الآجل)")
    st.dataframe(ar[["العميل","إيراد آجل","مدفوع","الرصيد"]] if not ar.empty else ar, use_container_width=True)
# ====================== الجزء 6/6 — التقارير (شهري + أسبوعي) ======================
with TAB_REPORT:
    st.subheader("📑 التقارير")

    # -------- تقرير شهري --------
    st.markdown("### 🗓 تقرير شهري")
    yr, mo = st.columns(2)
    R_y = yr.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d")
    R_m = mo.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d")

    if st.button("⬇️ تنزيل التقرير الشهري (Excel)"):
        df = fetch_daily_df()
        if df.empty:
            st.warning("لا توجد بيانات.")
        else:
            # تصفية الشهر المطلوب
            df_month = df[(df["dte"].dt.year == int(R_y)) & (df["dte"].dt.month == int(R_m))].copy()
            if df_month.empty:
                st.warning("لا توجد بيانات داخل هذا الشهر.")
            else:
                # ملخص شهري (أعداد صحيحة)
                summary = {
                    "إجمالي المبيعات":        [int(df_month["إجمالي المبيعات"].sum())],
                    "إجمالي المصروفات":      [int(df_month["الإجمالي اليومي للمصروفات"].sum())],
                    "صافي الربح":            [int(df_month["الربح الصافي لليوم"].sum())],
                    "إجمالي الإيجار":        [int(df_month.get("إيجار يومي", pd.Series()).sum())],
                    "متوسط إنتاجية الجوال":  [int(df_month["إنتاجية الجوال (رغيف/جوال)"].replace(0, pd.NA).dropna().mean() or 0)],
                }
                summary_df = pd.DataFrame(summary)

                # عملاء/توريد وسداد داخل الشهر
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

                # إعداد ملف اكسل متعدد الأوراق
                out_path = f"/tmp/تقرير_المخبز_{int(R_y)}_{int(R_m):02d}.xlsx"
                with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                    # ملخص
                    for c in summary_df.columns:
                        summary_df[c] = summary_df[c].fillna(0).astype(int)
                    summary_df.to_excel(writer, sheet_name="ملخص", index=False)

                    # اليومي
                    show = df_month.copy()
                    show.rename(columns={
                        "dte":"التاريخ",
                        "units_samoli":"إنتاج الصامولي (عدد)",
                        "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
                        "units_madour":"إنتاج المدور (عدد)",
                        "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
                        "flour_bags":"جوالات الدقيق",
                        "flour_bag_price":"سعر جوال الدقيق",
                        "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","gas":"غاز",
                        "electricity":"كهرباء","water":"مياه","salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                        "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي",
                        "owner_withdrawal":"سلفة","owner_repayment":"رد سلفة","owner_injection":"تمويل","funding":"تحويلات أخرى",
                        "returns":"مرتجع/هالك","discounts":"خصومات/عروض"
                    }, inplace=True)
                    for col in show.columns:
                        if col != "التاريخ":
                            show[col] = show[col].fillna(0).astype(int)
                    show.to_excel(writer, sheet_name="اليومي", index=False)

                    # توريد العملاء
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

                    # سداد العملاء
                    if not pays.empty:
                        pays_out = pays.copy()
                        pays_out.rename(columns={"dte":"التاريخ","client_name":"العميل","amount":"المبلغ","source":"المصدر","note":"ملاحظة"}, inplace=True)
                        pays_out["المبلغ"] = pays_out["المبلغ"].fillna(0).astype(int)
                        pays_out.to_excel(writer, sheet_name="سداد_العملاء", index=False)
                    else:
                        pd.DataFrame(columns=["لا توجد مدفوعات عملاء في هذا الشهر"]).to_excel(writer, sheet_name="سداد_العملاء", index=False)

                    # الذمم (AR) حتى تاريخه (ملف تعريفي)
                    ar_month = fetch_ar_df()
                    ar_month.to_excel(writer, sheet_name="الذمم", index=False)

                    # حركة النقد
                    if not money.empty:
                        money_out = money.copy()
                        money_out.rename(columns={"dte":"التاريخ","source":"المصدر","amount":"المبلغ","reason":"السبب"}, inplace=True)
                        money_out["المبلغ"] = money_out["المبلغ"].fillna(0).astype(int)
                        money_out.to_excel(writer, sheet_name="حركة_النقد", index=False)
                    else:
                        pd.DataFrame(columns=["لا توجد حركات نقدية في هذا الشهر"]).to_excel(writer, sheet_name="حركة_النقد", index=False)

                with open(out_path, "rb") as f:
                    st.download_button(
                        label="📥 تحميل التقرير الشهري",
                        data=f,
                        file_name=os.path.basename(out_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

    st.markdown("---")

    # -------- تقرير أسبوعي --------
    st.subheader("📆 تقرير أسبوعي")

    # اختار أي تاريخ داخل الأسبوع؛ هنحسب الإثنين إلى الأحد تلقائي
    w_col1, w_col2 = st.columns(2)
    picked_day = w_col1.date_input("اختر يوم داخل الأسبوع", value=date.today())
    show_chart = w_col2.checkbox("عرض مخطط الربح خلال الأسبوع", value=True)

    # حساب مدى الأسبوع (الإثنين بدايةً)
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
                # ملخص أسبوعي (أعداد صحيحة)
                weekly_summary = pd.DataFrame({
                    "إجمالي المبيعات":        [int(df_week["إجمالي المبيعات"].sum())],
                    "إجمالي المصروفات":      [int(df_week["الإجمالي اليومي للمصروفات"].sum())],
                    "صافي الربح":            [int(df_week["الربح الصافي لليوم"].sum())],
                    "إجمالي الإيجار":        [int(df_week.get("إيجار يومي", pd.Series()).sum())],
                    "متوسط إنتاجية الجوال":  [int(df_week["إنتاجية الجوال (رغيف/جوال)"].replace(0, pd.NA).dropna().mean() or 0)],
                })

                # توريدات ومدفوعات وحركة نقد داخل الأسبوع
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

                # إعداد ملف اكسل
                out_w_path = f"/tmp/تقرير_المخبز_اسبوع_{week_start.date()}_{week_end.date()}.xlsx"
                with pd.ExcelWriter(out_w_path, engine="openpyxl") as writer:
                    # ملخص
                    for c in weekly_summary.columns:
                        weekly_summary[c] = weekly_summary[c].fillna(0).astype(int)
                    weekly_summary.to_excel(writer, sheet_name="ملخص", index=False)

                    # اليومي داخل الأسبوع
                    show_w = df_week.copy()
                    show_w.rename(columns={
                        "dte":"التاريخ",
                        "units_samoli":"إنتاج الصامولي (عدد)",
                        "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
                        "units_madour":"إنتاج المدور (عدد)",
                        "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
                        "flour_bags":"جوالات الدقيق",
                        "flour_bag_price":"سعر جوال الدقيق",
                        "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","gas":"غاز",
                        "electricity":"كهرباء","water":"مياه","salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                        "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي",
                        "owner_withdrawal":"سلفة","owner_repayment":"رد سلفة","owner_injection":"تمويل","funding":"تحويلات أخرى",
                        "returns":"مرتجع/هالك","discounts":"خصومات/عروض"
                    }, inplace=True)
                    for col in show_w.columns:
                        if col != "التاريخ":
                            show_w[col] = show_w[col].fillna(0).astype(int)
                    show_w.to_excel(writer, sheet_name="اليومي", index=False)

                    # توريدات الأسبوع
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

                    # سداد العملاء (الآجل)
                    if not pays_w.empty:
                        pays_out = pays_w.copy()
                        pays_out.rename(columns={"dte":"التاريخ","client_name":"العميل","amount":"المبلغ","source":"المصدر","note":"ملاحظة"}, inplace=True)
                        pays_out["المبلغ"] = pays_out["المبلغ"].fillna(0).astype(int)
                        pays_out.to_excel(writer, sheet_name="سداد_العملاء", index=False)
                    else:
                        pd.DataFrame(columns=["لا توجد مدفوعات عملاء في هذا الأسبوع"]).to_excel(writer, sheet_name="سداد_العملاء", index=False)

                    # حركة النقد
                    if not money_w.empty:
                        money_out = money_w.copy()
                        money_out.rename(columns={"dte":"التاريخ","source":"المصدر","amount":"المبلغ","reason":"السبب"}, inplace=True)
                        money_out["المبلغ"] = money_out["المبلغ"].fillna(0).astype(int)
                        money_out.to_excel(writer, sheet_name="حركة_النقد", index=False)
                    else:
                        pd.DataFrame(columns=["لا توجد حركات نقدية في هذا الأسبوع"]).to_excel(writer, sheet_name="حركة_النقد", index=False)

                with open(out_w_path, "rb") as f:
                    st.download_button(
                        label="📥 تحميل التقرير الأسبوعي",
                        data=f,
                        file_name=os.path.basename(out_w_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

    # مخطط الربح للأسبوع (اختياري للعرض داخل الصفحة)
    if show_chart:
        dfw2 = fetch_daily_df()
        if not dfw2.empty:
            mask2 = (dfw2["dte"] >= week_start) & (dfw2["dte"] <= week_end)
            dfx = dfw2.loc[mask2, ["dte","الربح الصافي لليوم"]].copy()
            if not dfx.empty:
                fig_w = px.line(dfx, x="dte", y="الربح الصافي لليوم", markers=True, title="الربح الصافي خلال الأسبوع")
                fig_w.update_layout(xaxis_title="التاريخ", yaxis_title="الربح الصافي")
                fig_w.update_traces(hovertemplate="%{y:.0f}")
                fig_w.update_yaxes(tickformat="d")
                st.plotly_chart(fig_w, use_container_width=True)
