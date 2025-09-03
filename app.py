# -*- coding: utf-8 -*-
"""
Streamlit Bakery Tracker (Non-persistent) — إصدار معدل لنوعين خبز وتسعير بالألف
- نوعان: صامولي و مدور
- لكل نوع: إدخال الإنتاج اليومي + "كم رغيف لكل 1000 جنيه"
- الإيراد: (الوحدات / وحدات لكل 1000) * 1000
- مصروفات مضافة: ثلج، أكياس، فطور يومي
"""

import os
import sqlite3
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

DB_FILE = "/tmp/bakery_tracker.db"   # غير دائم
FUND_LOOKBACK_DAYS = 14
THOUSAND = 1000.0  # أساس تسعير "بالألف"

# ==================== قاعدة البيانات ====================
def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # ننشئ جدول شامل الأعمدة الجديدة
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dte TEXT,

            -- إنتاج وتسعير "بالألف"
            units_samoli REAL,
            per_thousand_samoli REAL,   -- كم رغيف مقابل 1000 جنيه
            units_madour REAL,
            per_thousand_madour REAL,   -- كم رغيف مقابل 1000 جنيه

            -- مدخلات أخرى
            flour_bags REAL,
            returns REAL,
            discounts REAL,

            -- مصروفات المواد والتشغيل
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

            -- المصروفات المضافة
            ice REAL,        -- ثلج
            bags REAL,       -- أكياس
            daily_meal REAL, -- فطور يومي

            funding REAL
        )
        """
    )
    conn.commit()
    conn.close()


def insert_row(row: tuple) -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO daily (
            dte,
            units_samoli, per_thousand_samoli,
            units_madour, per_thousand_madour,
            flour_bags, returns, discounts,
            flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp,
            ice, bags, daily_meal,
            funding
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        row,
    )
    conn.commit()
    conn.close()


def fetch_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"]
    )
    conn.close()
    if df.empty:
        return df

    # إيراد كل نوع حسب "السعر بالألف"
    def revenue_from_thousand(units, per_thousand):
        units = pd.to_numeric(units, errors="coerce").fillna(0.0)
        per_thousand = pd.to_numeric(per_thousand, errors="coerce").fillna(0.0)
        # لو per_thousand = 0 نتجنب القسمة على صفر
        rev = units.where(per_thousand > 0, 0.0) / per_thousand.where(per_thousand > 0, 1.0) * THOUSAND
        return rev

    df["إيراد الصامولي"] = revenue_from_thousand(df["units_samoli"], df["per_thousand_samoli"])
    df["إيراد المدور"]   = revenue_from_thousand(df["units_madour"], df["per_thousand_madour"])
    df["إجمالي المبيعات"] = df["إيراد الصامولي"] + df["إيراد المدور"]

    expense_cols = [
        "flour_extra","yeast","salt","oil","gas","electricity","water",
        "salaries","maintenance","petty","other_exp",
        "ice","bags","daily_meal"
    ]
    df["الإجمالي اليومي للمصروفات"] = df[expense_cols].fillna(0).sum(axis=1)
    df["الربح الصافي لليوم"] = df["إجمالي المبيعات"] - df["الإجمالي اليومي للمصروفات"]
    return df


def delete_row(row_id: int) -> None:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()


def export_to_excel(df: pd.DataFrame, path: str) -> str:
    out = df.copy()
    out.rename(
        columns={
            "dte": "التاريخ",
            "units_samoli": "إنتاج الصامولي (عدد)",
            "per_thousand_samoli": "الصامولي: عدد الأرغفة لكل 1000",
            "units_madour": "إنتاج المدور (عدد)",
            "per_thousand_madour": "المدور: عدد الأرغفة لكل 1000",
            "flour_bags": "جوالات الدقيق المستهلكة",
            "returns": "مرتجع/هالك",
            "discounts": "خصومات/عروض",
            "flour_extra": "مصاريف دقيق إضافية",
            "yeast": "خميرة",
            "salt": "ملح",
            "oil": "زيت/سمن",
            "gas": "غاز",
            "electricity": "كهرباء",
            "water": "مياه",
            "salaries": "رواتب",
            "maintenance": "صيانة",
            "petty": "نثريات",
            "other_exp": "مصاريف أخرى",
            "ice": "ثلج",
            "bags": "أكياس",
            "daily_meal": "فطور يومي",
            "funding": "تمويل (تحويلات نقدية/بنكية)",
        },
        inplace=True,
    )
    cols_order = [
        "التاريخ",
        "إنتاج الصامولي (عدد)", "الصامولي: عدد الأرغفة لكل 1000", "إيراد الصامولي",
        "إنتاج المدور (عدد)",   "المدور: عدد الأرغفة لكل 1000",   "إيراد المدور",
        "إجمالي المبيعات",
        "جوالات الدقيق المستهلكة",
        "مرتجع/هالك","خصومات/عروض",
        "مصاريف دقيق إضافية","خميرة","ملح","زيت/سمن","غاز","كهرباء","مياه",
        "رواتب","صيانة","نثريات","مصاريف أخرى","ثلج","أكياس","فطور يومي",
        "الإجمالي اليومي للمصروفات","الربح الصافي لليوم",
        "تمويل (تحويلات نقدية/بنكية)",
    ]
    # نضيف أعمدة الإيراد المحسوبة للإخراج
    if "إيراد الصامولي" not in out.columns:
        out["إيراد الصامولي"] = df["إيراد الصامولي"]
    if "إيراد المدور" not in out.columns:
        out["إيراد المدور"] = df["إيراد المدور"]
    if "إجمالي المبيعات" not in out.columns:
        out["إجمالي المبيعات"] = df["إجمالي المبيعات"]
    if "الإجمالي اليومي للمصروفات" not in out.columns:
        out["الإجمالي اليومي للمصروفات"] = df["الإجمالي اليومي للمصروفات"]
    if "الربح الصافي لليوم" not in out.columns:
        out["الربح الصافي لليوم"] = df["الربح الصافي لليوم"]

    out = out.reindex(columns=cols_order)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="المتابعة اليومية", index=False)
    return path


# ==================== الواجهة ====================
def main() -> None:
    st.set_page_config(page_title="متابعة المخبز (غير دائم)", layout="wide")

    st.markdown(
        """
        <style>
        html, body, [class*="css"] { direction: rtl; font-family: "Segoe UI", "Tahoma", "Arial", sans-serif; }
        [data-testid="stMetricLabel"] { direction: rtl; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("📊 نظام متابعة المخبز — نوعين خبز وتسعير بالألف (تجريبي غير دائم)")
    init_db()

    tab_input, tab_dash, tab_manage = st.tabs([
        "📝 الإدخال اليومي",
        "📈 لوحة المتابعة",
        "🧰 إدارة البيانات",
    ])

    # ---------- الإدخال ----------
    with tab_input:
        st.subheader("بيانات اليوم")
        c0, c1, c2 = st.columns([1,1,1])
        dte = c0.date_input("التاريخ", value=date.today())
        flour_bags = c1.number_input("جوالات الدقيق المستهلكة", min_value=0.0, step=1.0)
        funding = c2.number_input("تمويل (تحويلات نقدية/بنكية) — لا يُحسب كإيراد", min_value=0.0, step=1.0)

        st.markdown("### الإنتاج والتسعير بالألف")
        st.caption("أدخل **عدد الأرغفة** لكل نوع، و**كم رغيف يقابل 1000 جنيه** لذلك النوع.")
        s1, s2, s3, s4 = st.columns(4)
        units_samoli = s1.number_input("إنتاج الصامولي (عدد)", min_value=0.0, step=10.0)
        per_thousand_samoli = s2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0.0, step=10.0)
        units_madour = s3.number_input("إنتاج المدور (عدد)", min_value=0.0, step=10.0)
        per_thousand_madour = s4.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0.0, step=10.0)

        st.markdown("### المرتجعات والخصومات")
        r1, r2 = st.columns(2)
        returns = r1.number_input("مرتجع/هالك", min_value=0.0, step=1.0)
        discounts = r2.number_input("خصومات/عروض", min_value=0.0, step=1.0)

        st.markdown("### المصروفات اليومية")
        e1, e2, e3, e4, e5 = st.columns(5)
        flour_extra = e1.number_input("مصاريف دقيق إضافية", min_value=0.0, step=1.0)
        yeast = e2.number_input("خميرة", min_value=0.0, step=1.0)
        salt = e3.number_input("ملح", min_value=0.0, step=1.0)
        oil = e4.number_input("زيت/سمن", min_value=0.0, step=1.0)
        gas = e5.number_input("غاز", min_value=0.0, step=1.0)

        e6, e7, e8, e9, e10 = st.columns(5)
        electricity = e6.number_input("كهرباء", min_value=0.0, step=1.0)
        water = e7.number_input("مياه", min_value=0.0, step=1.0)
        salaries = e8.number_input("رواتب", min_value=0.0, step=1.0)
        maintenance = e9.number_input("صيانة", min_value=0.0, step=1.0)
        petty = e10.number_input("نثريات", min_value=0.0, step=1.0)

        e11, e12, e13, e14 = st.columns(4)
        other_exp = e11.number_input("مصاريف أخرى", min_value=0.0, step=1.0)
        ice = e12.number_input("ثلج", min_value=0.0, step=1.0)
        bags = e13.number_input("أكياس", min_value=0.0, step=1.0)
        daily_meal = e14.number_input("فطور يومي", min_value=0.0, step=1.0)

        if st.button("✅ حفظ السجل"):
            row = (
                dte.isoformat(),
                units_samoli, per_thousand_samoli,
                units_madour, per_thousand_madour,
                flour_bags, returns, discounts,
                flour_extra, yeast, salt, oil, gas, electricity, water,
                salaries, maintenance, petty, other_exp,
                ice, bags, daily_meal,
                funding
            )
            insert_row(row)
            st.success("تم الحفظ")

        st.markdown("---")
        st.caption("تنبيه: البيانات غير دائمة—ستختفي عند إعادة تشغيل الخادم أو إعادة النشر.")

    # ---------- الداشبورد ----------
    with tab_dash:
        st.subheader("لوحة المتابعة")
        df = fetch_df()
        if df.empty:
            st.info("لا توجد بيانات بعد. أضف أول سجل من تبويب الإدخال.")
        else:
            total_revenue = df["إجمالي المبيعات"].sum()
            total_exp = df["الإجمالي اليومي للمصروفات"].sum()
            total_profit = total_revenue - total_exp
            avg_daily_profit = df["الربح الصافي لليوم"].replace(0, pd.NA).dropna().mean()
            total_funding = df["funding"].sum()

            # تمويل آخر 14 يوم
            recent_cutoff = pd.Timestamp(date.today() - timedelta(days=FUND_LOOKBACK_DAYS))
            recent_fund = df.loc[df["dte"] >= recent_cutoff, "funding"].sum()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("إجمالي المبيعات", f"{total_revenue:,.2f}")
            c2.metric("إجمالي المصروفات", f"{total_exp:,.2f}")
            c3.metric("صافي الربح", f"{total_profit:,.2f}")
            c4.metric("إجمالي التمويل الذاتي", f"{total_funding:,.2f}")

            c5, c6, c7 = st.columns(3)
            c5.metric("متوسط الربح اليومي", f"{(avg_daily_profit or 0):,.2f}")
            c6.metric("إيراد الصامولي", f"{df['إيراد الصامولي'].sum():,.2f}")
            c7.metric("إيراد المدور", f"{df['إيراد المدور'].sum():,.2f}")

            status = "المخبز يغطي نفسه" if (total_profit >= 0 and recent_fund == 0) else "المخبز يعتمد على التمويل الذاتي"
            st.metric("⚖️ حالة المخبز", status)

            st.markdown("### الربح الصافي اليومي")
            fig = px.line(df, x="dte", y="الربح الصافي لليوم", markers=True)
            fig.update_layout(xaxis_title="التاريخ", yaxis_title="الربح الصافي")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### ملخص الإيرادات حسب النوع")
            rev_sum = pd.DataFrame({
                "البند": ["إيراد الصامولي", "إيراد المدور"],
                "القيمة": [df["إيراد الصامولي"].sum(), df["إيراد المدور"].sum()]
            })
            bar = px.bar(rev_sum, x="البند", y="القيمة")
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
                "ice":"ثلج",
                "bags":"أكياس",
                "daily_meal":"فطور يومي",
                "funding":"تمويل",
            }, inplace=True)
            st.dataframe(
                show[[
                    "التاريخ",
                    "إنتاج الصامولي (عدد)","الصامولي: عدد الأرغفة لكل 1000","إيراد الصامولي",
                    "إنتاج المدور (عدد)","المدور: عدد الأرغفة لكل 1000","إيراد المدور",
                    "إجمالي المبيعات",
                    "جوالات الدقيق","مرتجع/هالك","خصومات",
                    "دقيق إضافي","خميرة","ملح","زيت/سمن","غاز","كهرباء","مياه",
                    "رواتب","صيانة","نثريات","مصاريف أخرى","ثلج","أكياس","فطور يومي",
                    "الإجمالي اليومي للمصروفات","الربح الصافي لليوم",
                    "تمويل"
                ]],
                use_container_width=True
            )

            st.markdown("#### تصدير إلى إكسل")
            if st.button("⬇️ تصدير المتابعة اليومية إلى Excel"):
                output_path = export_to_excel(df, "/tmp/متابعة_مخبز_الشروق.xlsx")
                with open(output_path, "rb") as f:
                    st.download_button(
                        label="تحميل الملف",
                        data=f,
                        file_name="متابعة_مخبز_الشروق.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

    # ---------- إدارة البيانات ----------
    with tab_manage:
        st.subheader("إدارة البيانات")
        df = fetch_df()
        if df.empty:
            st.info("لا توجد بيانات بعد.")
        else:
            st.markdown("احذف سجلًا محددًا")
            option = st.selectbox(
                "اختر السجل (بتاريخه ومعرّفه الداخلي)",
                options=df.apply(
                    lambda r: f"{r['id']} — {r['dte'].date().isoformat()} — ربح {r['الربح الصافي لليوم']:.2f}",
                    axis=1,
                ),
            )
            if st.button("🗑️ حذف السجل المحدد"):
                sel_id = int(option.split("—")[0].strip())
                delete_row(sel_id)
                st.success("تم الحذف. قد يستغرق التحديث بضع ثوانٍ.")

            st.markdown("---")
            st.caption("في هذا الإصدار التجريبي يتم حفظ البيانات مؤقتًا في قاعدة بيانات SQLite داخل /tmp.")

if __name__ == "__main__":
    main()
