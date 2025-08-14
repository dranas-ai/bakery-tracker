# -*- coding: utf-8 -*-
import sqlite3
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
import os

DB_FILE = "/data/bakery_tracker.db"
FUND_LOOKBACK_DAYS = 14  # نافذة تمويل آخر X يوم

# ---------- إعداد الواجهة ----------
st.set_page_config(page_title="متابعة المخبز", layout="wide")

# RTL بسيط
st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; font-family: "Segoe UI", "Tahoma", "Arial", sans-serif; }
[data-testid="stMetricLabel"] { direction: rtl; }
</style>
""", unsafe_allow_html=True)

st.title("📊 نظام متابعة المخبز")

# ---------- إنشاء قاعدة البيانات ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dte TEXT,
        flour_bags REAL,
        units REAL,
        price REAL,
        returns REAL,
        discounts REAL,
        flour_extra REAL,
        yeast REAL,
        salt REAL,
        oil REAL,
        gas REAL,
        electricity REAL,
        water REAL,
        salaries REAL,
        maintenance REAL,
        petty REAL,
        other_exp REAL,
        funding REAL
    )
    """)
    conn.commit()
    conn.close()

def insert_row(row):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO daily
    (dte, flour_bags, units, price, returns, discounts, flour_extra, yeast, salt, oil, gas, electricity, water, salaries, maintenance, petty, other_exp, funding)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, row)
    conn.commit()
    conn.close()

def fetch_df():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"])
    conn.close()
    if df.empty:
        return df
    # حسابات مطابقة للإكسل
    df["إجمالي المبيعات"] = (df["units"].fillna(0) * df["price"].fillna(0))  # E
    expense_cols = ["flour_extra","yeast","salt","oil","gas","electricity","water","salaries","maintenance","petty","other_exp"]
    df["الإجمالي اليومي للمصروفات"] = df[expense_cols].fillna(0).sum(axis=1)  # T
    df["الربح الصافي لليوم"] = df["إجمالي المبيعات"] - df["الإجمالي اليومي للمصروفات"]  # U
    return df

def delete_row(row_id: int):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()

def export_to_excel(df: pd.DataFrame, path: str):
    # نرتب الأعمدة بالعربي على غرار الإكسل
    out = df.copy()
    out.rename(columns={
        "dte":"التاريخ",
        "flour_bags":"جوالات الدقيق المستهلكة",
        "units":"إنتاج الخبز (عدد)",
        "price":"سعر البيع للوحدة",
        "returns":"مرتجع/هالك",
        "discounts":"خصومات/عروض",
        "flour_extra":"مصاريف دقيق إضافية",
        "yeast":"خميرة",
        "salt":"ملح",
        "oil":"زيت/سمن",
        "gas":"غاز",
        "electricity":"كهرباء",
        "water":"مياه",
        "salaries":"رواتب",
        "maintenance":"صيانة",
        "petty":"نثريات",
        "other_exp":"مصاريف أخرى",
        "funding":"تمويل (تحويلات نقدية/بنكية)",
    }, inplace=True)
    cols_order = ["التاريخ","جوالات الدقيق المستهلكة","إنتاج الخبز (عدد)","سعر البيع للوحدة",
                  "إجمالي المبيعات","مرتجع/هالك","خصومات/عروض","مصاريف دقيق إضافية","خميرة","ملح",
                  "زيت/سمن","غاز","كهرباء","مياه","رواتب","صيانة","نثريات","مصاريف أخرى",
                  "تمويل (تحويلات نقدية/بنكية)","الإجمالي اليومي للمصروفات","الربح الصافي لليوم"]
    out = out[cols_order]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="المتابعة اليومية", index=False)
    return path

# ---------- بدء ----------
init_db()

# تبويب الإدخال/الملخص
tab_input, tab_dash, tab_manage = st.tabs(["📝 الإدخال اليومي", "📈 لوحة المتابعة", "🧰 إدارة البيانات"])

# ====================== 📝 الإدخال ======================
with tab_input:
    st.subheader("إدخال بيانات اليوم")
    col1, col2, col3, col4 = st.columns(4)
    dte = col1.date_input("التاريخ", value=date.today())
    flour_bags = col2.number_input("جوالات الدقيق المستهلكة", min_value=0.0, step=1.0)
    units = col3.number_input("إنتاج الخبز (عدد)", min_value=0.0, step=10.0)
    price = col4.number_input("سعر البيع للوحدة", min_value=0.0, step=0.1)

    st.markdown("### المصروفات اليومية")
    c1,c2,c3,c4,c5 = st.columns(5)
    returns = c1.number_input("مرتجع/هالك", min_value=0.0, step=1.0)
    discounts = c2.number_input("خصومات/عروض", min_value=0.0, step=1.0)
    flour_extra = c3.number_input("مصاريف دقيق إضافية", min_value=0.0, step=1.0)
    yeast = c4.number_input("خميرة", min_value=0.0, step=1.0)
    salt = c5.number_input("ملح", min_value=0.0, step=1.0)

    c6,c7,c8,c9,c10 = st.columns(5)
    oil = c6.number_input("زيت/سمن", min_value=0.0, step=1.0)
    gas = c7.number_input("غاز", min_value=0.0, step=1.0)
    electricity = c8.number_input("كهرباء", min_value=0.0, step=1.0)
    water = c9.number_input("مياه", min_value=0.0, step=1.0)
    salaries = c10.number_input("رواتب", min_value=0.0, step=1.0)

    c11,c12,c13 = st.columns(3)
    maintenance = c11.number_input("صيانة", min_value=0.0, step=1.0)
    petty = c12.number_input("نثريات", min_value=0.0, step=1.0)
    other_exp = c13.number_input("مصاريف أخرى", min_value=0.0, step=1.0)

    funding = st.number_input("تمويل (تحويلات نقدية/بنكية) — لا يُحسب كإيراد", min_value=0.0, step=1.0)

    if st.button("✅ حفظ السجل"):
        row = (
            dte.isoformat(),
            flour_bags, units, price,
            returns, discounts, flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp, funding
        )
        insert_row(row)
        st.success("تم الحفظ")

    st.markdown("---")
    st.caption("تنبيه: التمويل الذاتي **لا يدخل** في الأرباح؛ يظهر كزيادة في حقوق الملكية فقط.")

# ====================== 📈 الداشبورد ======================
with tab_dash:
    st.subheader("لوحة المتابعة")
    df = fetch_df()
    if df.empty:
        st.info("لا توجد بيانات بعد. أضف أول سجل من تبويب الإدخال.")
    else:
        # ملخصات
        total_revenue = df["إجمالي المبيعات"].sum()
        total_exp = df["الإجمالي اليومي للمصروفات"].sum()
        total_profit = total_revenue - total_exp
        avg_daily_profit = df["الربح الصافي لليوم"].replace(0, pd.NA).dropna().mean() if not df.empty else 0
        total_funding = df["funding"].sum()

        # تمويل آخر 14 يوم (حسب التاريخ)
        recent_cutoff = pd.Timestamp(date.today() - timedelta(days=FUND_LOOKBACK_DAYS))
        recent_fund = df.loc[df["dte"] >= recent_cutoff, "funding"].sum()

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("إجمالي المبيعات", f"{total_revenue:,.2f}")
        c2.metric("إجمالي المصروفات", f"{total_exp:,.2f}")
        c3.metric("صافي الربح", f"{total_profit:,.2f}")
        c4.metric("إجمالي التمويل الذاتي", f"{total_funding:,.2f}")

        c5,c6 = st.columns(2)
        c5.metric("متوسط الربح اليومي", f"{(avg_daily_profit or 0):,.2f}")
        # حالة المخبز
        status = "المخبز يغطي نفسه" if (total_profit >= 0 and recent_fund == 0) else "المخبز يعتمد على التمويل الذاتي"
        c6.metric("⚖️ حالة المخبز", status)

        st.markdown("### الربح الصافي اليومي")
        fig = px.line(df, x="dte", y="الربح الصافي لليوم", markers=True)
        fig.update_layout(xaxis_title="التاريخ", yaxis_title="الربح الصافي")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### ملخص الإيرادات مقابل المصروفات")
        sum_df = pd.DataFrame({
            "البند": ["إجمالي المبيعات", "إجمالي المصروفات"],
            "القيمة": [total_revenue, total_exp]
        })
        bar = px.bar(sum_df, x="البند", y="القيمة")
        st.plotly_chart(bar, use_container_width=True)

        st.markdown("### السجل التفصيلي")
        # عرض البيانات بشكل مقروء
        show = df.copy()
        show.rename(columns={
            "dte":"التاريخ",
            "flour_bags":"جوالات الدقيق",
            "units":"إنتاج (عدد)",
            "price":"سعر الوحدة",
            "returns":"مرتجع/هالك",
            "discounts":"خصومات",
            "flour_extra":"دقيق إضافي",
            "yeast":"خميرة",
            "salt":"ملح",
            "oil":"زيت/سمن",
            "gas":"غاز",
            "electricity":"كهرباء",
            "water":"مياه",
            "salaries":"رواتب",
            "maintenance":"صيانة",
            "petty":"نثريات",
            "other_exp":"مصاريف أخرى",
            "funding":"تمويل",
        }, inplace=True)
        st.dataframe(show.drop(columns=["id"]), use_container_width=True)

        # تصدير
        st.markdown("#### تصدير إلى إكسل")
        if st.button("⬇️ تصدير المتابعة اليومية إلى Excel"):
            path = export_to_excel(df, "متابعة_مخبز_الشروق_من_التطبيق.xlsx")
            st.success("تم إنشاء ملف Excel (حاليًا محفوظ محليًا بجانب التطبيق).")

# ====================== 🧰 إدارة البيانات ======================
with tab_manage:
    st.subheader("إدارة البيانات")
    df = fetch_df()
    if df.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        # حذف سجل
        st.markdown("احذف سجلًا محددًا")
        to_delete = st.selectbox(
            "اختر السجل (بتاريخه ومعرّفه الداخلي)",
            options=df.apply(lambda r: f"{r['id']} — {r['dte'].date().isoformat()} — ربح {r['الربح الصافي لليوم']:.2f}", axis=1)
        )
        if st.button("🗑️ حذف السجل المحدد"):
            sel_id = int(to_delete.split("—")[0].strip())
            delete_row(sel_id)
            st.success("تم الحذف. حدّث الصفحة (R) لو ما اتحدث الجدول تلقائيًا.")

        st.markdown("---")
        st.caption("تُحفظ البيانات في ملف SQLite دائم باسم bakery_tracker.db داخل مجلد /data (لا تُحذف عند إعادة التشغيل).")


