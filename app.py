# -*- coding: utf-8 -*-
"""
Bakery Tracker — Lite (بسيط جدًا)
- إدخال يومي مختصر (صامولي/مدور + دقيق + مصروفات أساسية)
- تسعير بالألف (كم رغيف لكل 1000)
- إيجار يومي محسوب تلقائيًا من الإيجار الشهري
- عرض ملخص سريع + جدول الأيام
- تنزيل تقرير شهري بسيط (ملخص + اليوميات)

⚠️ غير دائم: القاعدة في /tmp
"""

import os
import sqlite3
from datetime import date

import pandas as pd
import streamlit as st

DB_FILE = "/tmp/bakery_lite.db"
THOUSAND = 1000

# ----------------- قاعدة البيانات -----------------
def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    return sqlite3.connect(DB_FILE)

@st.cache_data(show_spinner=False)
def days_in_month(y: int, m: int) -> int:
    if m == 12:
        d1 = pd.Timestamp(y, m, 1)
        d2 = pd.Timestamp(y+1, 1, 1)
    else:
        d1 = pd.Timestamp(y, m, 1)
        d2 = pd.Timestamp(y, m+1, 1)
    return (d2 - d1).days


def init_db():
    conn = _connect(); cur = conn.cursor()
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
            flour_bag_price INTEGER,
            gas INTEGER,
            electricity INTEGER,
            salaries INTEGER,
            other_exp INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rent_settings (
            year INTEGER,
            month INTEGER,
            monthly_rent INTEGER,
            PRIMARY KEY(year, month)
        )
        """
    )
    conn.commit(); conn.close()

# ----------------- وظائف مساعدة -----------------

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
        ON CONFLICT(year, month) DO UPDATE SET monthly_rent=excluded.monthly_rent
        """,
        (int(year), int(month), int(monthly_rent))
    )
    conn.commit(); conn.close()


def get_daily_df() -> pd.DataFrame:
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte", conn, parse_dates=["dte"]) if os.path.exists(DB_FILE) else pd.DataFrame()
    conn.close()
    if df.empty:
        return df

    # مبيعات
    df["إيراد الصامولي"] = [revenue_from_thousand(u, p) for u, p in zip(df["units_samoli"], df["per_thousand_samoli"])]
    df["إيراد المدور"] = [revenue_from_thousand(u, p) for u, p in zip(df["units_madour"], df["per_thousand_madour"])]
    df["إجمالي المبيعات"] = (df["إيراد الصامولي"].fillna(0) + df["إيراد المدور"].fillna(0)).astype(int)

    # إيجار يومي حسب إعداد الشهر
    def rent_per_day(ts: pd.Timestamp) -> int:
        y, m = int(ts.year), int(ts.month)
        conn = _connect(); cur = conn.cursor()
        row = cur.execute("SELECT monthly_rent FROM rent_settings WHERE year=? AND month=?", (y, m)).fetchone()
        conn.close()
        monthly = int(row[0]) if row else 0
        dim = days_in_month(y, m)
        return int(round(monthly / dim)) if dim else 0

    df["إيجار يومي"] = df["dte"].apply(rent_per_day)

    # مصروفات
    expense_cols = ["gas", "electricity", "salaries", "other_exp", "إيجار يومي"]
    for c in expense_cols:
        if c not in df.columns:
            df[c] = 0
    df["إجمالي المصروفات"] = df[expense_cols].fillna(0).astype(int).sum(axis=1)

    # ربح
    df["الربح الصافي لليوم"] = (df["إجمالي المبيعات"] - df["إجمالي المصروفات"]).astype(int)

    return df


# ----------------- الواجهة -----------------
st.set_page_config(page_title="متابعة المخبز — Lite", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; font-family: "Segoe UI", Tahoma, Arial, sans-serif; }
[data-testid="stMetricLabel"] { direction: rtl; }
</style>
""", unsafe_allow_html=True)

st.title("🥖 نظام متابعة المخبز — نسخة خفيفة (Lite)")
init_db()

TAB_INPUT, TAB_REPORT = st.tabs(["🧾 إدخال يومي", "📑 تقرير شهري بسيط"]) 

with TAB_INPUT:
    with st.form("daily_form"):
        c0, c1, c2 = st.columns(3)
        dte = c0.date_input("التاريخ", value=date.today())
        flour_bags = c1.number_input("جوالات الدقيق (اختياري)", min_value=0, step=1, format="%d")
        flour_bag_price = c2.number_input("سعر الجوال (اختياري)", min_value=0, step=1, format="%d")

        st.markdown("**الإنتاج والتسعير بالألف**")
        s1, s2, s3, s4 = st.columns(4)
        units_samoli = s1.number_input("صامولي — عدد", min_value=0, step=10, format="%d")
        pt_samoli = s2.number_input("صامولي — عدد/1000", min_value=0, step=10, format="%d")
        units_madour = s3.number_input("مدور — عدد", min_value=0, step=10, format="%d")
        pt_madour = s4.number_input("مدور — عدد/1000", min_value=0, step=10, format="%d")

        st.markdown("**مصروفات أساسية (اختياري)**")
        e1, e2, e3, e4 = st.columns(4)
        gas = e1.number_input("غاز", min_value=0, step=1, format="%d")
        electricity = e2.number_input("كهرباء", min_value=0, step=1, format="%d")
        salaries = e3.number_input("رواتب", min_value=0, step=1, format="%d")
        other_exp = e4.number_input("مصاريف أخرى", min_value=0, step=1, format="%d")

        st.markdown("**إيجار شهري (يُوزع يوميًا تلقائيًا)**")
        r1, r2, r3 = st.columns(3)
        ry = r1.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d")
        rm = r2.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d")
        monthly_rent = r3.number_input("الإيجار الشهري", min_value=0, step=1, format="%d")

        saved = st.form_submit_button("✅ حفظ")
        if saved:
            # احفظ الإيجار إن تم إدخال قيمة
            if int(monthly_rent or 0) > 0:
                set_monthly_rent(int(ry), int(rm), int(monthly_rent))

            conn = _connect(); cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO daily (dte, units_samoli, per_thousand_samoli, units_madour, per_thousand_madour,
                                   flour_bags, flour_bag_price, gas, electricity, salaries, other_exp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    dte.isoformat(),
                    int(units_samoli or 0), int(pt_samoli or 0),
                    int(units_madour or 0), int(pt_madour or 0),
                    int(flour_bags or 0), int(flour_bag_price or 0),
                    int(gas or 0), int(electricity or 0), int(salaries or 0), int(other_exp or 0)
                )
            )
            conn.commit(); conn.close()
            st.success("تم الحفظ ✅")

    st.markdown("---")
    df = get_daily_df()
    if df.empty:
        st.info("لا توجد بيانات بعد.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("إجمالي المبيعات", f"{int(df['إجمالي المبيعات'].sum()):,}".replace(",",""))
        c2.metric("إجمالي المصروفات", f"{int(df['إجمالي المصروفات'].sum()):,}".replace(",",""))
        c3.metric("صافي الربح", f"{int(df['الربح الصافي لليوم'].sum()):,}".replace(",",""))

        show = df[[
            "dte","units_samoli","per_thousand_samoli","units_madour","per_thousand_madour",
            "إيراد الصامولي","إيراد المدور","إجمالي المبيعات","gas","electricity","salaries","other_exp","إيجار يومي","إجمالي المصروفات","الربح الصافي لليوم"
        ]].copy()
        show.rename(columns={
            "dte":"التاريخ",
            "units_samoli":"صامولي (عدد)",
            "per_thousand_samoli":"صامولي/1000",
            "units_madour":"مدور (عدد)",
            "per_thousand_madour":"مدور/1000",
        }, inplace=True)
        for col in show.columns:
            if col != "التاريخ":
                show[col] = show[col].fillna(0).astype(int)
        st.dataframe(show, use_container_width=True)

with TAB_REPORT:
    y, m = st.columns(2)
    ry = y.number_input("السنة", min_value=2020, max_value=2100, value=date.today().year, step=1, format="%d", key="ry2")
    rm = m.number_input("الشهر", min_value=1, max_value=12, value=date.today().month, step=1, format="%d", key="rm2")

    if st.button("⬇️ تنزيل التقرير الشهري (Excel) — مبسّط"):
        df = get_daily_df()
        if df.empty:
            st.warning("لا توجد بيانات.")
        else:
            df_month = df[(df["dte"].dt.year == int(ry)) & (df["dte"].dt.month == int(rm))].copy()
            if df_month.empty:
                st.warning("لا توجد بيانات داخل هذا الشهر.")
            else:
                summary = pd.DataFrame({
                    "إجمالي المبيعات": [int(df_month["إجمالي المبيعات"].sum())],
                    "إجمالي المصروفات": [int(df_month["إجمالي المصروفات"].sum())],
                    "صافي الربح": [int(df_month["الربح الصافي لليوم"].sum())]
                })
                out_path = f"/tmp/تقرير_المخبز_Lite_{int(ry)}_{int(rm):02d}.xlsx"
                with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                    summary.to_excel(writer, sheet_name="ملخص", index=False)
                    df_out = df_month.copy()
                    df_out.rename(columns={
                        "dte":"التاريخ",
                        "units_samoli":"صامولي (عدد)",
                        "per_thousand_samoli":"صامولي/1000",
                        "units_madour":"مدور (عدد)",
                        "per_thousand_madour":"مدور/1000",
                    }, inplace=True)
                    for col in df_out.columns:
                        if col != "التاريخ":
                            df_out[col] = df_out[col].fillna(0).astype(int)
                    df_out.to_excel(writer, sheet_name="اليومي", index=False)

                with open(out_path, "rb") as f:
                    st.download_button(
                        label="📥 تحميل التقرير",
                        data=f,
                        file_name=os.path.basename(out_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
