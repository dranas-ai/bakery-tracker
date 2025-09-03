# -*- coding: utf-8 -*-
"""
Streamlit Bakery Tracker (Non-persistent)
- نوعين خبز + تسعير بالألف
- تكلفة الدقيق (سعر الجوال * عدد الجوالات)
- مصروفات: ثلج/أكياس/فطور يومي ..الخ
- تتبُّع العملاء والتوريد اليومي + لوحة أداء ونمو آخر 14 يوم
"""

import os
import sqlite3
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

DB_FILE = "/tmp/bakery_tracker.db"
FUND_LOOKBACK_DAYS = 14
GROWTH_WINDOW_DAYS = 14
THOUSAND = 1000.0

# ==================== DB ====================
def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = _connect()
    cur = conn.cursor()
    # جدول اليوميات (تشغيل المخبز)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dte TEXT,
        units_samoli REAL,
        per_thousand_samoli REAL,
        units_madour REAL,
        per_thousand_madour REAL,
        flour_bags REAL,
        flour_bag_price REAL,
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
        ice REAL,
        bags REAL,
        daily_meal REAL,
        funding REAL
    )""")
    # أعمدة ترقية إن لزم
    cur.execute("PRAGMA table_info(daily)")
    cols = {r[1] for r in cur.fetchall()}
    if "flour_bag_price" not in cols:
        cur.execute("ALTER TABLE daily ADD COLUMN flour_bag_price REAL")

    # جدول العملاء
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        active INTEGER DEFAULT 1
    )""")
    # جدول توريدات العملاء
    cur.execute("""
    CREATE TABLE IF NOT EXISTS client_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dte TEXT,
        client_id INTEGER,
        bread_type TEXT,          -- 'samoli' أو 'madour'
        units REAL,
        per_thousand REAL,        -- كم رغيف لكل 1000 لهذا التوريد
        revenue REAL,             -- محسوب وقت الإدخال: (units/per_thousand)*1000
        FOREIGN KEY(client_id) REFERENCES clients(id)
    )""")
    conn.commit()
    conn.close()

# ========== Helpers ==========
def revenue_from_thousand(units, per_thousand):
    u = pd.to_numeric(units, errors="coerce").fillna(0.0)
    p = pd.to_numeric(per_thousand, errors="coerce").fillna(0.0)
    return u.where(p > 0, 0.0) / p.where(p > 0, 1.0) * THOUSAND

# ========== CRUD: daily ==========
def insert_daily(row):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily (
            dte, units_samoli, per_thousand_samoli, units_madour, per_thousand_madour,
            flour_bags, flour_bag_price, returns, discounts,
            flour_extra, yeast, salt, oil, gas, electricity, water,
            salaries, maintenance, petty, other_exp, ice, bags, daily_meal, funding
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, row)
    conn.commit()
    conn.close()

def fetch_daily_df():
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY dte ASC, id ASC", conn, parse_dates=["dte"])
    conn.close()
    if df.empty:
        return df
    df["إيراد الصامولي"] = revenue_from_thousand(df["units_samoli"], df["per_thousand_samoli"])
    df["إيراد المدور"]   = revenue_from_thousand(df["units_madour"], df["per_thousand_madour"])
    df["إجمالي المبيعات"] = df["إيراد الصامولي"] + df["إيراد المدور"]
    df["تكلفة الدقيق"] = df["flour_bags"].fillna(0) * df["flour_bag_price"].fillna(0)
    expense_cols = ["تكلفة الدقيق","flour_extra","yeast","salt","oil","gas","electricity","water",
                    "salaries","maintenance","petty","other_exp","ice","bags","daily_meal"]
    df["الإجمالي اليومي للمصروفات"] = df[expense_cols].fillna(0).sum(axis=1)
    df["الربح الصافي لليوم"] = df["إجمالي المبيعات"] - df["الإجمالي اليومي للمصروفات"]
    return df

def delete_daily(row_id:int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()

# ========== Clients & Deliveries ==========
def add_client(name:str, active:bool=True):
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO clients(name,active) VALUES(?,?)", (name, 1 if active else 0))
        conn.commit()
    finally:
        conn.close()

def list_clients(active_only=False):
    conn = _connect()
    q = "SELECT id,name,active FROM clients" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
    df = pd.read_sql_query(q, conn)
    conn.close()
    return df

def set_client_active(client_id:int, active:bool):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE clients SET active=? WHERE id=?", (1 if active else 0, client_id))
    conn.commit()
    conn.close()

def add_client_delivery(dte, client_id:int, bread_type:str, units:float, per_thousand:float):
    rev = (units / per_thousand * THOUSAND) if per_thousand and per_thousand>0 else 0.0
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO client_deliveries (dte, client_id, bread_type, units, per_thousand, revenue)
        VALUES (?,?,?,?,?,?)
    """, (dte, client_id, bread_type, units, per_thousand, rev))
    conn.commit()
    conn.close()

def fetch_deliveries_df():
    conn = _connect()
    df = pd.read_sql_query("""
        SELECT cd.*, c.name AS client_name
        FROM client_deliveries cd
        LEFT JOIN clients c ON c.id = cd.client_id
        ORDER BY cd.dte ASC, cd.id ASC
    """, conn, parse_dates=["dte"])
    conn.close()
    return df

# ========== Export ==========
def export_to_excel(df: pd.DataFrame, path: str) -> str:
    out = df.copy()
    out.rename(columns={
        "dte":"التاريخ",
        "units_samoli":"إنتاج الصامولي (عدد)",
        "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
        "units_madour":"إنتاج المدور (عدد)",
        "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
        "flour_bags":"جوالات الدقيق المستهلكة",
        "flour_bag_price":"سعر جوال الدقيق",
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
        "ice":"ثلج",
        "bags":"أكياس",
        "daily_meal":"فطور يومي",
        "funding":"تمويل (تحويلات نقدية/بنكية)",
    }, inplace=True)
    for col in ["إيراد الصامولي","إيراد المدور","إجمالي المبيعات","تكلفة الدقيق","الإجمالي اليومي للمصروفات","الربح الصافي لليوم"]:
        if col not in out.columns:
            out[col] = df[col]
    cols_order = [
        "التاريخ",
        "إنتاج الصامولي (عدد)","الصامولي: عدد الأرغفة لكل 1000","إيراد الصامولي",
        "إنتاج المدور (عدد)","المدور: عدد الأرغفة لكل 1000","إيراد المدور",
        "إجمالي المبيعات",
        "جوالات الدقيق المستهلكة","سعر جوال الدقيق","تكلفة الدقيق",
        "مرتجع/هالك","خصومات/عروض",
        "مصاريف دقيق إضافية","خميرة","ملح","زيت/سمن","غاز","كهرباء","مياه",
        "رواتب","صيانة","نثريات","مصاريف أخرى","ثلج","أكياس","فطور يومي",
        "الإجمالي اليومي للمصروفات","الربح الصافي لليوم",
        "تمويل (تحويلات نقدية/بنكية)",
    ]
    out = out.reindex(columns=cols_order)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="المتابعة اليومية", index=False)
    return path

# ==================== UI ====================
def main():
    st.set_page_config(page_title="متابعة المخبز (غير دائم)", layout="wide")
    st.markdown("""
    <style>
    html, body, [class*="css"] { direction: rtl; font-family: "Segoe UI","Tahoma","Arial",sans-serif; }
    [data-testid="stMetricLabel"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)
    st.title("📊 نظام متابعة المخبز — تشغيل + عملاء (تجريبي غير دائم)")
    init_db()

    tab_input, tab_dash, tab_manage, tab_clients = st.tabs([
        "📝 الإدخال اليومي",
        "📈 لوحة المتابعة",
        "🧰 إدارة البيانات",
        "📦 العملاء والتوريد",
    ])

    # -------- الإدخال اليومي --------
    with tab_input:
        st.subheader("بيانات اليوم")
        c0, c1, c2 = st.columns([1,1,1])
        dte = c0.date_input("التاريخ", value=date.today())
        flour_bags = c1.number_input("جوالات الدقيق المستهلكة", min_value=0.0, step=1.0)
        flour_bag_price = c2.number_input("سعر جوال الدقيق", min_value=0.0, step=10.0)

        st.markdown("### الإنتاج والتسعير بالألف")
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

        e11, e12, e13, e14, e15 = st.columns(5)
        other_exp = e11.number_input("مصاريف أخرى", min_value=0.0, step=1.0)
        ice = e12.number_input("ثلج", min_value=0.0, step=1.0)
        bags = e13.number_input("أكياس", min_value=0.0, step=1.0)
        daily_meal = e14.number_input("فطور يومي", min_value=0.0, step=1.0)
        funding = e15.number_input("تمويل (تحويلات نقدية/بنكية) — لا يُحسب كإيراد", min_value=0.0, step=1.0)

        if st.button("✅ حفظ السجل"):
            row = (
                dte.isoformat(),
                units_samoli, per_thousand_samoli,
                units_madour, per_thousand_madour,
                flour_bags, flour_bag_price,
                returns, discounts,
                flour_extra, yeast, salt, oil, gas, electricity, water,
                salaries, maintenance, petty, other_exp, ice, bags, daily_meal, funding
            )
            insert_daily(row)
            st.success("تم الحفظ")

        st.caption("⚠️ هذه النسخة غير دائمة—أي إعادة تشغيل ستمسح البيانات.")

    # -------- الداشبورد --------
    with tab_dash:
        st.subheader("لوحة المتابعة")
        df = fetch_daily_df()
        if df.empty:
            st.info("لا توجد بيانات بعد.")
        else:
            total_revenue = df["إجمالي المبيعات"].sum()
            total_exp = df["الإجمالي اليومي للمصروفات"].sum()
            total_profit = total_revenue - total_exp
            avg_daily_profit = df["الربح الصافي لليوم"].replace(0, pd.NA).dropna().mean()
            total_funding = df["funding"].sum()

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

            st.metric("⚖️ حالة المخبز",
                      "المخبز يغطي نفسه" if (total_profit >= 0 and recent_fund == 0) else "المخبز يعتمد على التمويل الذاتي")

            st.markdown("### الربح الصافي اليومي")
            fig = px.line(df, x="dte", y="الربح الصافي لليوم", markers=True)
            fig.update_layout(xaxis_title="التاريخ", yaxis_title="الربح الصافي")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### السجل التفصيلي")
            show = df.copy().rename(columns={
                "dte":"التاريخ",
                "units_samoli":"إنتاج الصامولي (عدد)",
                "per_thousand_samoli":"الصامولي: عدد الأرغفة لكل 1000",
                "units_madour":"إنتاج المدور (عدد)",
                "per_thousand_madour":"المدور: عدد الأرغفة لكل 1000",
                "flour_bags":"جوالات الدقيق",
                "flour_bag_price":"سعر جوال الدقيق",
                "returns":"مرتجع/هالك","discounts":"خصومات",
                "flour_extra":"دقيق إضافي","yeast":"خميرة","salt":"ملح","oil":"زيت/سمن",
                "gas":"غاز","electricity":"كهرباء","water":"مياه","salaries":"رواتب",
                "maintenance":"صيانة","petty":"نثريات","other_exp":"مصاريف أخرى",
                "ice":"ثلج","bags":"أكياس","daily_meal":"فطور يومي","funding":"تمويل",
                "تكلفة الدقيق":"تكلفة الدقيق"
            })
            st.dataframe(show[[
                "التاريخ",
                "إنتاج الصامولي (عدد)","الصامولي: عدد الأرغفة لكل 1000","إيراد الصامولي",
                "إنتاج المدور (عدد)","المدور: عدد الأرغفة لكل 1000","إيراد المدور",
                "إجمالي المبيعات",
                "جوالات الدقيق","سعر جوال الدقيق","تكلفة الدقيق",
                "مرتجع/هالك","خصومات",
                "دقيق إضافي","خميرة","ملح","زيت/سمن","غاز","كهرباء","مياه",
                "رواتب","صيانة","نثريات","مصاريف أخرى","ثلج","أكياس","فطور يومي",
                "الإجمالي اليومي للمصروفات","الربح الصافي لليوم","تمويل"
            ]], use_container_width=True)

    # -------- إدارة البيانات --------
    with tab_manage:
        st.subheader("حذف سجل يومي")
        df = fetch_daily_df()
        if df.empty:
            st.info("لا توجد بيانات.")
        else:
            opt = st.selectbox(
                "اختر السجل",
                options=df.apply(lambda r: f"{r['id']} — {r['dte'].date().isoformat()} — ربح {r['الربح الصافي لليوم']:.2f}", axis=1)
            )
            if st.button("🗑️ حذف السجل المحدد"):
                sel_id = int(opt.split("—")[0].strip())
                delete_daily(sel_id)
                st.success("تم الحذف.")

    # -------- العملاء والتوريد --------
    with tab_clients:
        st.subheader("📦 إدارة العملاء والتوريد اليومي")

        st.markdown("### 1) إضافة/إدارة عملاء")
        c1, c2 = st.columns([2,1])
        with c1:
            new_name = st.text_input("اسم العميل الجديد")
            if st.button("➕ إضافة عميل"):
                if new_name.strip():
                    add_client(new_name.strip(), True)
                    st.success("تمت الإضافة.")
        clients_df = list_clients()
        if not clients_df.empty:
            st.dataframe(clients_df.rename(columns={"id":"ID","name":"العميل","active":"نشط"}))
            # تبديل حالة
            client_choices = {f"{row['id']} — {row['name']}": int(row['id']) for _,row in clients_df.iterrows()}
            sel = st.selectbox("تفعيل/إيقاف عميل", options=list(client_choices.keys()))
            if st.button("تبديل الحالة"):
                cid = client_choices[sel]
                current = int(clients_df.loc[clients_df["id"]==cid, "active"].iloc[0])
                set_client_active(cid, not bool(current))
                st.success("تم التحديث.")

        st.markdown("---")
        st.markdown("### 2) تسجيل توريد اليوم")
        active_clients = list_clients(active_only=True)
        if active_clients.empty:
            st.info("أضف عميل أولاً.")
        else:
            colA, colB, colC = st.columns([2,1,1])
            idx = colA.selectbox("اختر العميل", options=active_clients.index, format_func=lambda i: active_clients.loc[i,"name"])
            d_delivery = colB.date_input("تاريخ التوريد", value=date.today())
            # صامولي
            st.caption("**توريد صامولي**")
            cs1, cs2 = st.columns(2)
            u_s = cs1.number_input("عدد الصامولي", min_value=0.0, step=10.0, key="u_s")
            p_s = cs2.number_input("الصامولي: عدد الأرغفة لكل 1000", min_value=0.0, step=10.0, key="p_s")
            if st.button("💾 حفظ توريد الصامولي"):
                add_client_delivery(d_delivery.isoformat(), int(active_clients.loc[idx,"id"]), "samoli", u_s, p_s)
                st.success("تم حفظ توريد الصامولي.")
            # مدور
            st.caption("**توريد مدور**")
            cm1, cm2 = st.columns(2)
            u_m = cm1.number_input("عدد المدور", min_value=0.0, step=10.0, key="u_m")
            p_m = cm2.number_input("المدور: عدد الأرغفة لكل 1000", min_value=0.0, step=10.0, key="p_m")
            if st.button("💾 حفظ توريد المدور"):
                add_client_delivery(d_delivery.isoformat(), int(active_clients.loc[idx,"id"]), "madour", u_m, p_m)
                st.success("تم حفظ توريد المدور.")

        st.markdown("---")
        st.markdown("### 3) أداء العملاء واتجاه النمو")
        deliv_df = fetch_deliveries_df()
        if deliv_df.empty:
            st.info("لا توجد توريدات مسجلة بعد.")
        else:
            # ملخص بالإجماليات
            grp = deliv_df.groupby("client_name", as_index=False).agg(
                إجمالي_الوحدات=("units","sum"),
                إجمالي_الإيراد=("revenue","sum")
            ).sort_values("إجمالي_الإيراد", ascending=False)
            st.markdown("#### ترتيب العملاء حسب الإيراد")
            st.dataframe(grp, use_container_width=True)

            # نمو آخر 14 يوم مقابل الـ14 قبلها
            cutoff1 = pd.Timestamp(date.today() - timedelta(days=GROWTH_WINDOW_DAYS))
            cutoff0 = pd.Timestamp(date.today() - timedelta(days=2*GROWTH_WINDOW_DAYS))
            recent = deliv_df[deliv_df["dte"] >= cutoff1].groupby("client_name")["revenue"].sum()
            prev   = deliv_df[(deliv_df["dte"] < cutoff1) & (deliv_df["dte"] >= cutoff0)].groupby("client_name")["revenue"].sum()
            growth = (recent - prev).fillna(0)
            growth_pct = ((recent - prev) / prev.replace(0, pd.NA) * 100).fillna(0)

            grow_df = pd.DataFrame({
                "العميل": sorted(set(deliv_df["client_name"])),
            })
            grow_df["إيراد آخر 14 يوم"] = grow_df["العميل"].map(recent).fillna(0.0)
            grow_df["إيراد الـ14 قبلها"] = grow_df["العميل"].map(prev).fillna(0.0)
            grow_df["الفرق"] = grow_df["العميل"].map(growth).fillna(0.0)
            grow_df["النسبة %"] = grow_df["العميل"].map(growth_pct).fillna(0.0).round(1)
            st.markdown("#### نمو الإيراد (آخر 14 يوم)")
            st.dataframe(grow_df.sort_values("الفرق", ascending=False), use_container_width=True)

            # مخطط عميل محدد
            pick = st.selectbox("اختر عميل لعرض الاتجاه الزمني", options=sorted(set(deliv_df["client_name"])))
            sub = deliv_df[deliv_df["client_name"]==pick]
            sub_day = sub.groupby("dte", as_index=False)["revenue"].sum()
            line = px.line(sub_day, x="dte", y="revenue", markers=True, title=f"إيراد التوريد — {pick}")
            line.update_layout(xaxis_title="التاريخ", yaxis_title="الإيراد")
            st.plotly_chart(line, use_container_width=True)

if __name__ == "__main__":
    main()
