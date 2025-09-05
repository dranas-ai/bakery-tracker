# -*- coding: utf-8 -*-
import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px

# # ============== الإعدادات العامة # ==============
CURRENCY = "جنيه"
THOUSAND = 1000  # أساس التسعير
# مسار قاعدة البيانات — نحاول مسارات متعددة لضمان العمل على السحابة/المحلي
import os

def _resolve_db_path():
    candidates = []
    # 1) متغير بيئة اختياري
    env_dir = os.environ.get("DB_DIR")
    if env_dir:
        candidates.append(env_dir)
    # 2) مجلد محلي (قد يكون للقراءة فقط على بعض المنصات)
    candidates.append(os.path.join(os.getcwd(), "data"))
    # 3) مجلد /data لو متاح
    candidates.append("/data")
    # 4) مجلد مؤقت (دوام مؤقت فقط)
    candidates.append("/tmp/bakery_data")

    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            testfile = os.path.join(d, ".__wtest__")
            with open(testfile, "w") as f:
                f.write("ok")
            os.remove(testfile)
            return os.path.join(d, "bakery_tracker.db"), (d not in ["/tmp/bakery_data"])  # True = دائم غالبًا
        except Exception:
            continue
    # fallback أخير: ذاكرة فقط
    return ":memory:", False

DB_FILE, DB_PERSISTENT = _resolve_db_path()  # محاولة حفظ دائم
FUND_LOOKBACK_DAYS = 30  # نافذة تمويل آخر X يوم — عدلناها إلى 30 يوم
WORKING_DAYS_PER_MONTH = 26  # عدد أيام التشغيل في الشهر (لا نعمل الجمعة) 

# واجهة وتهيئة للموبايل + RTL
st.set_page_config(page_title="متابعة المخبز", layout="wide")

st.markdown(
    f"""
<style>
html, body, [class*="css"] {{ direction: rtl; font-family: "Segoe UI", "Tahoma", "Arial", sans-serif; }}
@media (max-width: 768px) {{
  section.main .block-container {{ padding-left: 0.6rem; padding-right: 0.6rem; }}
  .st-emotion-cache-ocqkz7, .st-emotion-cache-1r6slb0, .st-emotion-cache-1wmy9hl {{ width: 100% !important; display:block !important; }}
}}
[data-testid="stMetricLabel"] {{ direction: rtl; }}
.num {{ font-variant-numeric: tabular-nums; }}
</style>
""",
    unsafe_allow_html=True,
)

st.title("📊 نظام متابعة المخبز — نسخة مُحسّنة")

# # ============== قاعدة البيانات # ==============
SCHEMA_DAILY = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "dte": "TEXT",
    # الإنتاج حسب النوع
    "units_baton": "INTEGER",   # بسطونة (صامولي)
    "units_round": "INTEGER",   # مدور (بيرغر)
    # التسعير: كم وحدة لكل 1000 جنيه
    "u1000_baton": "INTEGER",
    "u1000_round": "INTEGER",
    # استهلاك الدقيق وسعر الجوال
    "flour_bags": "INTEGER",
    "flour_bag_price": "INTEGER",  # سعر الجوال (بدون كسور)
    # مصاريف يومية (بدون غاز/إيجار الآن)
    "returns": "INTEGER",
    "discounts": "INTEGER",
    "flour_extra": "INTEGER",
    "yeast": "INTEGER",
    "salt": "INTEGER",
    "oil": "INTEGER",
    "electricity": "INTEGER",
    "water": "INTEGER",
    "salaries": "INTEGER",
    "maintenance": "INTEGER",
    "petty": "INTEGER",
    "other_exp": "INTEGER",
    # إضافات جديدة
    "ice": "INTEGER",         # ثلج
    "breakfast": "INTEGER",   # فطور
    "daily_wage": "INTEGER",  # يومية
    # تمويل
    "funding": "INTEGER"
}

SCHEMA_MONTHLY = {
    # مفتاح الشهر بشكل YYYY-MM (مثلاً 2025-09)
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "month": "TEXT",         # أول يوم في الشهر للتوحيد (YYYY-MM-01)
    "gas": "INTEGER",        # غاز شهري
    "rent": "INTEGER"        # إيجار شهري
}


def _ensure_table(conn, name: str, schema: dict):
    cur = conn.cursor()
    cols_sql = ",".join([f"{k} {v}" for k, v in schema.items()])
    cur.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols_sql})")
    cur.execute(f"PRAGMA table_info({name})")
    existing = {row[1] for row in cur.fetchall()}
    for col, decl in schema.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE {name} ADD COLUMN {col} {decl.split()[0]}")
    conn.commit()


def init_db():
    global DB_FILE, DB_PERSISTENT
    try:
        conn = sqlite3.connect(DB_FILE)
        _ensure_table(conn, "daily", SCHEMA_DAILY)
        _ensure_table(conn, "monthly", SCHEMA_MONTHLY)
        conn.close()
    except Exception:
        # فشل فتح القاعدة في المسار الحالي → نستخدم in-memory ونكمّل التشغيل
        msg = (
            "تعذّر فتح قاعدة البيانات في المسارات الافتراضية. "
            "سيتم تشغيل التطبيق بدون حفظ دائم (ذاكرة مؤقتة). "
            "يمكنك تحديد مسار ثابت عبر متغير البيئة DB_DIR."
        )
        st.error(msg)
        DB_FILE = ":memory:"
        DB_PERSISTENT = False
        conn = sqlite3.connect(DB_FILE)
        _ensure_table(conn, "daily", SCHEMA_DAILY)
        _ensure_table(conn, "monthly", SCHEMA_MONTHLY)
        conn.close()


def insert_daily(row: dict):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cols = ",".join(row.keys())
    qmarks = ",".join(["?"] * len(row))
    cur.execute(f"INSERT INTO daily ({cols}) VALUES ({qmarks})", list(row.values()))
    conn.commit()
    conn.close()


def upsert_monthly(month_key: str, gas: int, rent: int):
    """month_key بصيغة YYYY-MM-01."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id FROM monthly WHERE month=?", (month_key,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE monthly SET gas=?, rent=? WHERE month=?", (int(gas), int(rent), month_key))
    else:
        cur.execute("INSERT INTO monthly (month, gas, rent) VALUES (?,?,?)", (month_key, int(gas), int(rent)))
    conn.commit()
    conn.close()


def fetch_daily_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"])
    # نقرأ الشهري لاحتساب التوزيع اليومي (غاز/إيجار)
    dfm = pd.read_sql_query("SELECT * FROM monthly ORDER BY month ASC, id ASC", conn)
    conn.close()
    if df.empty:
        return df

    # السعر للوحدة (عدد الوحدات لكل 1000 -> سعر للوحدة) بدون كسور
    price_baton = (THOUSAND // df["u1000_baton"].replace(0, pd.NA)).fillna(0).astype(int)
    price_round = (THOUSAND // df["u1000_round"].replace(0, pd.NA)).fillna(0).astype(int)

    # المبيعات لكل نوع
    sales_baton = (df["units_baton"].fillna(0).astype(int) * price_baton).astype(int)
    sales_round = (df["units_round"].fillna(0).astype(int) * price_round).astype(int)

    df["سعر الوحدة — بسطونة"] = price_baton
    df["سعر الوحدة — مدور"] = price_round
    df["مبيعات البسطونة"] = sales_baton
    df["مبيعات المدور"] = sales_round

    # إجمالي المبيعات
    df["إجمالي المبيعات"] = (sales_baton + sales_round).astype(int)

    # تكلفة الدقيق اليومية
    flour_cost = (
        df["flour_bags"].fillna(0).astype(int) * df["flour_bag_price"].fillna(0).astype(int)
    ).astype(int) + df["flour_extra"].fillna(0).astype(int)

    # مصاريف يومية (بدون غاز/إيجار)
    expense_cols = [
        "yeast","salt","oil","electricity","water","salaries",
        "maintenance","petty","other_exp","ice","breakfast","daily_wage"
    ]
    daily_core = (flour_cost + df[expense_cols].fillna(0).astype(int).sum(axis=1)).astype(int)
    df["الإجمالي اليومي للمصروفات (بدون الغاز والإيجار)"] = daily_core

    # ===== توزيع الغاز والإيجار على الأيام =====
    df["month"] = df["dte"].dt.to_period("M").dt.to_timestamp()
    if dfm is not None and not dfm.empty:
        m = dfm.copy()
        m["month"] = pd.to_datetime(m["month"])  # YYYY-MM-01
        # تقسيم ثابت على 26 يوم كما طلبت + توزيع البواقي على آخر يوم مُسجّل في الشهر
        m["per_day_gas"] = (m["gas"].fillna(0).astype(int) // WORKING_DAYS_PER_MONTH).astype(int)
        m["per_day_rent"] = (m["rent"].fillna(0).astype(int) // WORKING_DAYS_PER_MONTH).astype(int)
        m["rem_gas"] = (m["gas"].fillna(0).astype(int) % WORKING_DAYS_PER_MONTH).astype(int)
        m["rem_rent"] = (m["rent"].fillna(0).astype(int) % WORKING_DAYS_PER_MONTH).astype(int)
        df = df.merge(
            m[["month","per_day_gas","per_day_rent","rem_gas","rem_rent"]],
            on="month", how="left"
        ).fillna({"per_day_gas":0, "per_day_rent":0, "rem_gas":0, "rem_rent":0})
        # إضافة البواقي لآخر تاريخ مُسجّل في كل شهر
        last_dte = df.groupby("month")["dte"].transform("max")
        is_last = df["dte"].eq(last_dte)
        df.loc[is_last, "per_day_gas"] = df.loc[is_last, "per_day_gas"] + df.loc[is_last, "rem_gas"]
        df.loc[is_last, "per_day_rent"] = df.loc[is_last, "per_day_rent"] + df.loc[is_last, "rem_rent"]
        df.drop(columns=["rem_gas","rem_rent"], inplace=True)
    else:
        df["per_day_gas"] = 0
        df["per_day_rent"] = 0

    df["تكلفة يومية مُوزعة (غاز + إيجار)"] = (df["per_day_gas"].astype(int) + df["per_day_rent"].astype(int))
    df["الإجمالي اليومي للمصروفات (شامل الموزع)"] = (daily_core + df["تكلفة يومية مُوزعة (غاز + إيجار)"]).astype(int)

    # الربح الصافي اليومي (شامل توزيع الغاز/الإيجار)
    df["الربح الصافي لليوم"] = (df["إجمالي المبيعات"] - df["الإجمالي اليومي للمصروفات (شامل الموزع)"]).astype(int)

    return df

    # السعر للوحدة (عدد الوحدات لكل 1000 -> سعر للوحدة) بدون كسور
    price_baton = (THOUSAND // df["u1000_baton"].replace(0, pd.NA)).fillna(0).astype(int)
    price_round = (THOUSAND // df["u1000_round"].replace(0, pd.NA)).fillna(0).astype(int)

    # المبيعات لكل نوع
    sales_baton = (df["units_baton"].fillna(0).astype(int) * price_baton).astype(int)
    sales_round = (df["units_round"].fillna(0).astype(int) * price_round).astype(int)

    df["سعر الوحدة — بسطونة"] = price_baton
    df["سعر الوحدة — مدور"] = price_round
    df["مبيعات البسطونة"] = sales_baton
    df["مبيعات المدور"] = sales_round

    # إجمالي المبيعات (يمكن لاحقًا خصم المرتجع/الخصومات لو حبيت)
    df["إجمالي المبيعات"] = (sales_baton + sales_round).astype(int)

    # تكلفة الدقيق اليومية = عدد الجوالات × سعر الجوال + أي مصروف دقيق إضافي
    flour_cost = (
        df["flour_bags"].fillna(0).astype(int) * df["flour_bag_price"].fillna(0).astype(int)
    ).astype(int) + df["flour_extra"].fillna(0).astype(int)

    # مصاريف يومية (بدون غاز/إيجار)
    expense_cols = [
        "yeast","salt","oil","electricity","water","salaries",
        "maintenance","petty","other_exp","ice","breakfast","daily_wage"
    ]
    df["الإجمالي اليومي للمصروفات (بدون الغاز والإيجار)"] = (
        flour_cost + df[expense_cols].fillna(0).astype(int).sum(axis=1)
    ).astype(int)

    # الربح الصافي اليومي (بدون الغاز/الإيجار الشهري)
    df["الربح الصافي لليوم (بدون الغاز/الإيجار)"] = (
        df["إجمالي المبيعات"] - df["الإجمالي اليومي للمصروفات (بدون الغاز والإيجار)"]
    ).astype(int)

    return df


def fetch_monthly_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    dfm = pd.read_sql_query("SELECT * FROM monthly ORDER BY month ASC, id ASC", conn)
    conn.close()
    return dfm


def delete_row(row_id: int):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()


def export_to_excel(daily_df: pd.DataFrame, monthly_df: pd.DataFrame, path: str):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # ورقة اليومية
        out = daily_df.copy()
        out.rename(
            columns={
                "dte":"التاريخ",
                "units_baton":"إنتاج البسطونة (عدد)",
                "units_round":"إنتاج المدور (عدد)",
                "u1000_baton":f"وحدات/ألف — بسطونة",
                "u1000_round":f"وحدات/ألف — مدور",
                "flour_bags":"جوالات الدقيق المستهلكة",
                "flour_bag_price":"سعر جوال الدقيق",
                "returns":"مرتجع/هالك",
                "discounts":"خصومات/عروض",
                "flour_extra":"مصاريف دقيق إضافية",
                "yeast":"خميرة","salt":"ملح","oil":"زيت/سمن","electricity":"كهرباء","water":"مياه",
                "salaries":"رواتب","maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                "ice":"ثلج","breakfast":"فطور","daily_wage":"يومية",
                "funding":"تمويل (تحويلات)",
                "الإجمالي اليومي للمصروفات (بدون الغاز والإيجار)":"الإجمالي اليومي للمصروفات",
                "الربح الصافي لليوم (بدون الغاز/الإيجار)":"الربح الصافي لليوم",
            }, inplace=True,
        )
        cols_order = [
            "التاريخ",
            "إنتاج البسطونة (عدد)", "إنتاج المدور (عدد)",
            f"وحدات/ألف — بسطونة", f"وحدات/ألف — مدور",
            "سعر الوحدة — بسطونة", "سعر الوحدة — مدور",
            "مبيعات البسطونة", "مبيعات المدور", "إجمالي المبيعات",
            "جوالات الدقيق المستهلكة", "سعر جوال الدقيق", "مصاريف دقيق إضافية",
            "خميرة","ملح","زيت/سمن","كهرباء","مياه","رواتب","صيانة",
            "نثريات","مصاريف أخرى","ثلج","فطور","يومية",
            "مرتجع/هالك","خصومات/عروض",
            "الإجمالي اليومي للمصروفات","الربح الصافي لليوم",
            "تمويل (تحويلات)",
        ]
        keep = [c for c in cols_order if c in out.columns]
        out[keep].to_excel(writer, sheet_name="يومي", index=False)

        # ورقة شهرية
        if monthly_df is not None and not monthly_df.empty:
            m = monthly_df.copy()
            m.rename(columns={"month":"الشهر","gas":"غاز شهري","rent":"إيجار شهري"}, inplace=True)
            m.to_excel(writer, sheet_name="شهري", index=False)

    return path


# # ============== بدء التطبيق # ==============
init_db()

# تبويب الإدخال/الملخص/الشهري/الإدارة
(tab_input, tab_dash, tab_monthly, tab_manage) = st.tabs(["📝 الإدخال اليومي", "📈 لوحة المتابعة", "🗓️ التكاليف الشهرية", "🧰 إدارة البيانات"]) 

# # ======= 📝 الإدخال # =======
with tab_input:
    st.subheader("إدخال بيانات اليوم")
    col1, col2, col3 = st.columns(3)
    dte = col1.date_input("التاريخ", value=date.today())

    # الإنتاج حسب النوع + التسعير
    with st.expander("الإنتاج والتسعير (بدون كسور)", expanded=True):
        c1, c2 = st.columns(2)
        units_baton = c1.number_input("إنتاج البسطونة (عدد)", min_value=0, step=1, format="%d")
        u1000_baton = c2.number_input(f"كم وحدة بسطونة لكل {THOUSAND} {CURRENCY}?", min_value=1, step=1, value=200, format="%d")

        c3, c4 = st.columns(2)
        units_round = c3.number_input("إنتاج المدور (عدد)", min_value=0, step=1, format="%d")
        u1000_round = c4.number_input(f"كم وحدة مدور لكل {THOUSAND} {CURRENCY}?", min_value=1, step=1, value=160, format="%d")

        price_baton_preview = THOUSAND // max(1, u1000_baton)
        price_round_preview = THOUSAND // max(1, u1000_round)
        st.caption(f"سعر الوحدة المتوقع — بسطونة: **{price_baton_preview:,}** {CURRENCY} | مدور: **{price_round_preview:,}** {CURRENCY}")

    with st.expander("الدقيق والمصاريف اليومية", expanded=True):
        r1, r2, r3 = st.columns(3)
        flour_bags = r1.number_input("جوالات الدقيق المستهلكة", min_value=0, step=1, format="%d")
        flour_bag_price = r2.number_input("سعر جوال الدقيق", min_value=0, step=1, value=0, format="%d")
        flour_extra = r3.number_input("مصاريف دقيق إضافية", min_value=0, step=1, format="%d")

        s1, s2, s3 = st.columns(3)
        yeast = s1.number_input("خميرة", min_value=0, step=1, format="%d")
        salt = s2.number_input("ملح", min_value=0, step=1, format="%d")
        oil = s3.number_input("زيت/سمن", min_value=0, step=1, format="%d")

        e1, e2, e3, e4, e5 = st.columns(5)
        electricity = e1.number_input("كهرباء", min_value=0, step=1, format="%d")
        water = e2.number_input("مياه", min_value=0, step=1, format="%d")
        salaries = e3.number_input("رواتب", min_value=0, step=1, format="%d")
        maintenance = e4.number_input("صيانة", min_value=0, step=1, format="%d")
        petty = e5.number_input("نثريات", min_value=0, step=1, format="%d")

        o1, o2, o3 = st.columns(3)
        other_exp = o1.number_input("مصاريف أخرى", min_value=0, step=1, format="%d")
        daily_wage = o2.number_input("يومية", min_value=0, step=1, format="%d")
        ice = o3.number_input("ثلج", min_value=0, step=1, format="%d")

        f1 = st.columns(1)[0]
        breakfast = f1.number_input("فطور", min_value=0, step=1, format="%d")

    funding = st.number_input("تمويل (تحويلات نقدية/بنكية) — لا يُحسب كإيراد", min_value=0, step=1, format="%d")

    if st.button("✅ حفظ السجل"):
        row = dict(
            dte=dte.isoformat(),
            units_baton=int(units_baton), units_round=int(units_round),
            u1000_baton=int(u1000_baton), u1000_round=int(u1000_round),
            flour_bags=int(flour_bags), flour_bag_price=int(flour_bag_price), flour_extra=int(flour_extra),
            yeast=int(yeast), salt=int(salt), oil=int(oil), electricity=int(electricity), water=int(water),
            salaries=int(salaries), maintenance=int(maintenance), petty=int(petty), other_exp=int(other_exp),
            ice=int(ice), breakfast=int(breakfast), daily_wage=int(daily_wage),
            returns=0, discounts=0,  # موجودة لو احتجتها لاحقًا
            funding=int(funding),
        )
        insert_daily(row)
        st.success("تم الحفظ ✔️ — البيانات محفوظة دائمًا داخل SQLite في /data")

    st.markdown("---")
    st.caption("تم نقل **الغاز** و**الإيجار** إلى إدخال شهري من تبويب \"التكاليف الشهرية\". التسعير يعتمد على الوحدات لكل ألف جنيه، ولا توجد كسور نهائيًا.")

# # ======= 📈 الداشبورد # =======
with tab_dash:
    st.subheader("لوحة المتابعة")
    df = fetch_daily_df()
    dfm = fetch_monthly_df()

    if df.empty:
        st.info("لا توجد بيانات بعد. أضف أول سجل من تبويب الإدخال.")
    else:
        # ملخصات إجمالية (شاملة التوزيع اليومي للغاز/الإيجار)
        total_revenue = int(df["إجمالي المبيعات"].sum())
        total_exp_daily = int(df["الإجمالي اليومي للمصروفات (شامل الموزع)"].sum())
        total_profit_daily = int(total_revenue - total_exp_daily)
        avg_daily_profit = int(df["الربح الصافي لليوم"].replace(0, pd.NA).dropna().mean() or 0)
        total_funding = int(df["funding"].fillna(0).sum())

        # تمويل آخر 30 يوم
        recent_cutoff = pd.Timestamp(date.today() - timedelta(days=FUND_LOOKBACK_DAYS))
        recent_fund = int(df.loc[df["dte"] >= recent_cutoff, "funding"].fillna(0).sum())

        # # ====== بطاقات اليوم + MTD للرسم # ======
        latest_day = df["dte"].max().normalize()
        month_start = latest_day.replace(day=1).normalize()
        df_mtd = df[(df["dte"] >= month_start) & (df["dte"] <= latest_day)].copy()

        df_today = df[df["dte"].dt.normalize() == latest_day].copy()
        today_revenue = int(df_today["إجمالي المبيعات"].sum()) if not df_today.empty else 0
        today_exp = int(df_today["الإجمالي اليومي للمصروفات (شامل الموزع)"].sum()) if not df_today.empty else 0
        today_profit = int(today_revenue - today_exp)

        c7,c8,c9 = st.columns(3)
        c7.metric("مبيعات اليوم", f"{today_revenue:,}", help=f"آخر يوم مسجّل: {latest_day.date().isoformat()}")
        c8.metric("مصروفات اليوم", f"{today_exp:,}", help=f"آخر يوم مسجّل: {latest_day.date().isoformat()}")
        c9.metric("صافي ربح اليوم", f"{today_profit:,}", help=f"آخر يوم مسجّل: {latest_day.date().isoformat()}")

        # # ====== الرسم: يومي / تراكمي (MTD) # ======
        st.markdown("### الربح الصافي — يومي / تراكمي (MTD)")
        mode = st.radio("اختر النمط", ["يومي","تراكمي (MTD)"], horizontal=True, index=0)
        if mode == "يومي":
            fig = px.line(df.sort_values("dte"), x="dte", y="الربح الصافي لليوم", markers=True)
            y_title = f"الربح الصافي ({CURRENCY})"
        else:
            if df_mtd.empty:
                st.info("لا توجد بيانات في هذا الشهر لعرض التراكمي. سيتم عرض الرسم اليومي.")
                fig = px.line(df.sort_values("dte"), x="dte", y="الربح الصافي لليوم", markers=True)
                y_title = f"الربح الصافي ({CURRENCY})"
            else:
                df_plot = df_mtd.sort_values("dte").copy()
                df_plot["الربح التراكمي (MTD)"] = df_plot["الربح الصافي لليوم"].cumsum()
                fig = px.line(df_plot, x="dte", y="الربح التراكمي (MTD)", markers=True)
                y_title = f"الربح التراكمي (MTD) ({CURRENCY})"
        fig.update_layout(xaxis_title="التاريخ", yaxis_title=y_title)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### ملخص الإيرادات مقابل المصروفات")
        sum_df = pd.DataFrame({"البند": ["إجمالي المبيعات", "إجمالي المصروفات"], "القيمة": [total_revenue, total_exp_daily]})
        bar = px.bar(sum_df, x="البند", y="القيمة")
        st.plotly_chart(bar, use_container_width=True)

        # تصدير
        st.markdown("#### تصدير إلى Excel")
        if st.button("⬇️ تصدير (يومي + شهري) إلى Excel"):
            path = export_to_excel(df, dfm, "متابعة_المخبز_تقارير_شهرية.xlsx")
            st.success("تم إنشاء ملف Excel وحُفظ بجانب التطبيق.")

# # ======= 🗓️ التكاليف الشهرية # =======
with tab_monthly:
    st.subheader("إدخال التكاليف الشهرية: الغاز + الإيجار")
    # اختيار الشهر: نستخدم أول يوم في الشهر كمفتاح ثابت
    chosen = st.date_input("اختر شهر التكاليف", value=date(date.today().year, date.today().month, 1))
    month_key = date(chosen.year, chosen.month, 1).strftime("%Y-%m-01")

    c1, c2 = st.columns(2)
    gas_m = c1.number_input("الغاز الشهري", min_value=0, step=1, format="%d")
    rent_m = c2.number_input("الإيجار الشهري", min_value=0, step=1, format="%d")

    if st.button("💾 حفظ التكاليف الشهرية"):
        upsert_monthly(month_key, gas_m, rent_m)
        st.success(f"تم الحفظ للشهر {month_key} ✅")

    # عرض آخر 12 شهر مدخلة
    dfm = fetch_monthly_df()
    if dfm is not None and not dfm.empty:
        st.markdown("### آخر القيود الشهرية")
        showm = dfm.copy()
        showm.rename(columns={"month":"الشهر","gas":"غاز شهري","rent":"إيجار شهري"}, inplace=True)
        st.dataframe(showm.sort_values("الشهر", ascending=False).head(12), use_container_width=True)

# # ======= 🧰 إدارة البيانات # =======
with tab_manage:
    st.subheader("إدارة البيانات")
    df = fetch_daily_df()
    if df.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        # حذف سجل من اليومية
        st.markdown("احذف سجلًا محددًا من اليومية")
        to_delete = st.selectbox(
            "اختر السجل (بالـ ID والتاريخ والربح)",
            options=df.apply(lambda r: f"{r['id']} — {r['dte'].date().isoformat()} — ربح {int(r['الربح الصافي لليوم']):,}", axis=1)
        )
        if st.button("🗑️ حذف السجل المحدد"):
            sel_id = int(to_delete.split("—")[0].strip())
            delete_row(sel_id)
            st.success("تم الحذف. حدّث الصفحة لو ما اتحدّث الجدول تلقائيًا.")

        st.markdown("---")
        persist_note = "دائم" if DB_PERSISTENT else "مؤقّت (اعيّن DB_DIR لمسار كتابة دائم)"
        st.caption(f"قاعدة البيانات: {DB_FILE} — حفظ {persist_note}.")

        # --- مزامنة مع Google Sheets (قراءة/كتابة) ---
        st.markdown("### مزامنة مع Google Sheets")

        def _normalize_private_key(pk: str) -> str:
            """يحّول private_key لسطر PEM صحيح لو كان بدون \\n."""
            if "\\n" in pk:      # مكتوب فيه \n كنص
                return pk.replace("\\n", "\n")
            if "\n" in pk:       # فيه أسطر جديدة حقيقية
                return pk
            head = "-----BEGIN PRIVATE KEY-----"
            tail = "-----END PRIVATE KEY-----"
            body = pk.replace(head, "").replace(tail, "").strip().replace(" ", "")
            return f"{head}\n{body}\n{tail}\n"

        def _get_sheet_id_from_secrets():
            # جرّب المستوى الأعلى
            if "GOOGLE_SHEETS_DOC_ID" in st.secrets:
                return st.secrets["GOOGLE_SHEETS_DOC_ID"]
            # جرّب داخل [google] باسم sheet_id
            if "google" in st.secrets and "sheet_id" in st.secrets["google"]:
                return st.secrets["google"]["sheet_id"]
            # جرّب داخل [google] باسم GOOGLE_SHEETS_DOC_ID
            if "google" in st.secrets and "GOOGLE_SHEETS_DOC_ID" in st.secrets["google"]:
                return st.secrets["google"]["GOOGLE_SHEETS_DOC_ID"]
            return None

        # فاحص سريع للأسرار (اختياري للفحص)
        with st.expander("🔎 فحص الإعدادات (Secrets)"):
            has_google = "google" in st.secrets
            sheet_id_detected = _get_sheet_id_from_secrets() is not None
            st.write("قسم [google] موجود:", "✅" if has_google else "❌")
            st.write("Sheet ID متوفر (في الأعلى أو داخل [google]):", "✅" if sheet_id_detected else "❌")
            if has_google:
                must_keys = ["type","project_id","private_key_id","private_key","client_email"]
                missing = [k for k in must_keys if k not in st.secrets["google"]]
                st.write("حقول أساسية ناقصة في [google]:", "❌ " + ", ".join(missing) if missing else "✅ لا شيء ناقص")

        if st.button("🔄 Sync to Google Sheets"):
            try:
                from google.oauth2.service_account import Credentials
                import gspread
                from gspread_dataframe import set_with_dataframe

                # 1) قراءة أسرار الخدمة
                if "google" not in st.secrets:
                    raise RuntimeError("قسم [google] غير موجود في Secrets.")
                gsec = dict(st.secrets["google"])
                if "private_key" not in gsec:
                    raise RuntimeError("حقل private_key غير موجود داخل [google].")
                gsec["private_key"] = _normalize_private_key(gsec["private_key"])

                sheet_id = _get_sheet_id_from_secrets()
                if not sheet_id:
                    raise RuntimeError(
                        "لم يتم العثور على Sheet ID. أضِفه إمّا كـ GOOGLE_SHEETS_DOC_ID في أعلى Secrets "
                        "أو كـ sheet_id داخل قسم [google]."
                    )

                # 2) إنشاء الاعتماد والاتصال
                SCOPES = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive.file",
                ]
                creds = Credentials.from_service_account_info(gsec, scopes=SCOPES)
                client = gspread.authorize(creds)
                sh = client.open_by_key(sheet_id)

                # 3) تحضير ورقة Daily
                try:
                    ws_daily = sh.worksheet("Daily")
                except gspread.exceptions.WorksheetNotFound:
                    ws_daily = sh.add_worksheet(title="Daily", rows=2000, cols=50)

                daily = fetch_daily_df()
                d = daily.copy()
                if not d.empty and "dte" in d.columns:
                    d["dte"] = d["dte"].dt.date.astype(str)
                ws_daily.clear()
                set_with_dataframe(ws_daily, d)

                # 4) تحضير ورقة Monthly (إن وُجدت بيانات)
                monthly = fetch_monthly_df()
                if monthly is not None and not monthly.empty:
                    try:
                        ws_monthly = sh.worksheet("Monthly")
                    except gspread.exceptions.WorksheetNotFound:
                        ws_monthly = sh.add_worksheet(title="Monthly", rows=200, cols=30)
                    m = monthly.copy()
                    if "month" in m.columns:
                        m["month"] = pd.to_datetime(m["month"]).dt.date.astype(str)
                    ws_monthly.clear()
                    set_with_dataframe(ws_monthly, m)

                st.success("تمت المزامنة بنجاح إلى أوراق Daily و Monthly ✅")

            except Exception as e:
                st.error(f"فشلت المزامنة: {e}")
                st.caption(
                    "تأكد من: قسم [google] مضبوط و private_key في سطر واحد، "
                    "وأن Sheet ID مضاف إمّا كـ GOOGLE_SHEETS_DOC_ID (خارج [google]) أو كـ sheet_id داخل [google]، "
                    "وأن الشيت متشارك مع client_email بصلاحية Editor."
                )
