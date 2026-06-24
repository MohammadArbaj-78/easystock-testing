import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import feedparser
from substitute_data import SUBSTITUTE_DATA
from bill_storage import save_bill, load_all_bills, delete_bill, get_monthly_summary

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="Apna Medical Store Tool",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# CUSTOM THEME — Medical/Trust colors
# Deep teal (trust, healthcare) + warm off-white + clean accents
# ============================================
st.markdown("""
<style>
    /* Overall app background */
    .stApp {
        background-color: #F7F5F0;
    }

    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #0F4C46;
    }
    section[data-testid="stSidebar"] * {
        color: #F7F5F0 !important;
    }
    section[data-testid="stSidebar"] .stRadio label {
        font-size: 16px;
        padding: 6px 0px;
    }

    /* Main headers */
    h1 {
        color: #0F4C46;
        font-weight: 700;
        border-bottom: 3px solid #C97B3D;
        padding-bottom: 12px;
    }
    h2, h3 {
        color: #0F4C46;
        font-weight: 600;
    }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E0DCD0;
        border-left: 5px solid #C97B3D;
        border-radius: 8px;
        padding: 14px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }

    /* Buttons */
    .stButton button {
        background-color: #0F4C46;
        color: #FFFFFF;
        border-radius: 6px;
        border: none;
        font-weight: 600;
        padding: 8px 20px;
    }
    .stButton button:hover {
        background-color: #C97B3D;
        color: #FFFFFF;
    }
    .stDownloadButton button {
        background-color: #FFFFFF;
        color: #0F4C46;
        border: 1.5px solid #0F4C46;
        border-radius: 6px;
        font-weight: 600;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        color: #6B6356;
    }
    .stTabs [aria-selected="true"] {
        color: #0F4C46 !important;
        border-bottom: 3px solid #C97B3D !important;
    }

    /* Dataframes / tables */
    div[data-testid="stDataFrame"] {
        border: 1px solid #E0DCD0;
        border-radius: 8px;
    }

    /* Divider color */
    hr {
        border-color: #E0DCD0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# SESSION STATE INITIALIZATION
# ============================================
if "medicine_data" not in st.session_state:
    st.session_state.medicine_data = pd.DataFrame(
        columns=["Dawai Ka Naam", "Quantity (Stock)", "Expiry Date", "Price (₹)"]
    )
if "last_uploaded_file" not in st.session_state:
    st.session_state.last_uploaded_file = None

# ============================================
# SIDEBAR NAVIGATION
# ============================================
with st.sidebar:
    st.markdown("# 💊 Apna Store")
    st.caption("Manawar Medical Stores ke liye")
    st.markdown("---")

    page = st.radio(
        "Tool Chunein",
        [
            "📊 Stock Daalein",
            "⏰ Expiry & Low Stock Alert",
            "🧾 GST Calculator",
            "📂 Bill History",
            "🔄 Generic Substitute Finder",
            "📰 News & Updates"
        ],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption("Har feature alag tab mein hai — jo chahiye wahi kholiye")

# ============================================
# PAGE 1: STOCK DATA ENTRY
# ============================================
if page == "📊 Stock Daalein":
    st.title("📊 Apna Stock Data Daalein")
    st.write("Yahan apni dawaiyon ki list banayein — Excel upload karke ya manually type karke. Yeh data **Expiry Alert** aur **Low Stock Alert** dono ke liye use hoga.")
    st.divider()

    tab1, tab2 = st.tabs(["📁 Excel File Upload Karein", "✍️ Manually Type Karein"])

    # ---------- TAB 1: EXCEL UPLOAD ----------
    with tab1:
        st.write("Apni Excel file upload karein. File mein yeh columns hone chahiye:")
        st.code("Dawai Ka Naam | Quantity (Stock) | Expiry Date | Price (₹)")

        uploaded_file = st.file_uploader(
            "Excel file chunein (.xlsx ya .csv)",
            type=["xlsx", "csv"]
        )

        if uploaded_file is not None:
            file_signature = f"{uploaded_file.name}_{uploaded_file.size}"

            if st.session_state.last_uploaded_file != file_signature:
                try:
                    if uploaded_file.name.endswith(".csv"):
                        df_upload = pd.read_csv(uploaded_file)
                    else:
                        df_upload = pd.read_excel(uploaded_file)

                    df_upload.columns = [str(c).strip() for c in df_upload.columns]

                    st.session_state.medicine_data = pd.concat(
                        [st.session_state.medicine_data, df_upload],
                        ignore_index=True
                    )
                    st.session_state.last_uploaded_file = file_signature
                    st.success(f"✅ {len(df_upload)} dawaiyon ka data successfully add ho gaya!")
                except Exception as e:
                    st.error(f"⚠️ File padhne mein problem hui: {e}")
                    st.info("Check karein ki columns ke naam sahi hain: 'Dawai Ka Naam', 'Quantity (Stock)', 'Expiry Date', 'Price (₹)'")
            else:
                st.info(f"ℹ️ '{uploaded_file.name}' already add ho chuki hai. Nayi file ke liye, pehle 'Sab Data Clear Karein' dabayein.")

        sample_df = pd.DataFrame({
            "Dawai Ka Naam": ["Paracetamol 500mg", "Amoxicillin 250mg"],
            "Quantity (Stock)": [50, 10],
            "Expiry Date": ["2026-08-15", "2026-07-01"],
            "Price (₹)": [25, 80]
        })
        buffer = io.BytesIO()
        sample_df.to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            label="📋 Sample Excel Template Download Karein",
            data=buffer.getvalue(),
            file_name="sample_medicine_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # ---------- TAB 2: MANUAL ENTRY ----------
    with tab2:
        st.write("Ek-ek dawai manually daalein:")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            med_name = st.text_input("Dawai Ka Naam", key="manual_name")
        with col2:
            med_qty = st.number_input("Quantity (Stock)", min_value=0, step=1, key="manual_qty")
        with col3:
            med_expiry = st.date_input("Expiry Date", key="manual_expiry")
        with col4:
            med_price = st.number_input("Price (₹)", min_value=0.0, step=1.0, key="manual_price")

        if st.button("➕ Dawai List Mein Add Karein"):
            if med_name.strip() == "":
                st.warning("⚠️ Dawai ka naam daalein")
            else:
                new_row = pd.DataFrame([{
                    "Dawai Ka Naam": med_name,
                    "Quantity (Stock)": med_qty,
                    "Expiry Date": med_expiry.strftime("%Y-%m-%d"),
                    "Price (₹)": med_price
                }])
                st.session_state.medicine_data = pd.concat(
                    [st.session_state.medicine_data, new_row],
                    ignore_index=True
                )
                st.success(f"✅ '{med_name}' add ho gayi!")

    st.divider()

    if not st.session_state.medicine_data.empty:
        st.subheader("📋 Aapka Pura Stock Data")
        st.dataframe(st.session_state.medicine_data, use_container_width=True)

        col_clear, col_count = st.columns([1, 3])
        with col_clear:
            if st.button("🗑️ Sab Data Clear Karein"):
                st.session_state.medicine_data = pd.DataFrame(
                    columns=["Dawai Ka Naam", "Quantity (Stock)", "Expiry Date", "Price (₹)"]
                )
                st.session_state.last_uploaded_file = None
                st.rerun()
        with col_count:
            st.metric("Total Dawaiyan", len(st.session_state.medicine_data))
    else:
        st.info("👆 Excel upload karein ya manually data daalein — phir yahan table dikhega.")

# ============================================
# PAGE 2: EXPIRY & LOW STOCK ALERT
# ============================================
elif page == "⏰ Expiry & Low Stock Alert":
    st.title("⏰ Expiry & Low Stock Alert")

    if st.session_state.medicine_data.empty:
        st.warning("⚠️ Pehle '📊 Stock Daalein' page mein jaake apna data daalein.")
    else:
        settings_col1, settings_col2 = st.columns(2)
        with settings_col1:
            expiry_days = st.slider(
                "Kitne dinon ke andar expiry ho rahi dawaiyan dikhayein?",
                min_value=15, max_value=120, value=60, step=15
            )
        with settings_col2:
            low_stock_limit = st.slider(
                "Kitni quantity se kam ho to 'Low Stock' maana jaaye?",
                min_value=1, max_value=50, value=5, step=1
            )

        work_df = st.session_state.medicine_data.copy()
        work_df["Expiry Date"] = pd.to_datetime(work_df["Expiry Date"], errors="coerce")
        work_df["Quantity (Stock)"] = pd.to_numeric(work_df["Quantity (Stock)"], errors="coerce")
        work_df["Price (₹)"] = pd.to_numeric(work_df["Price (₹)"], errors="coerce")

        today = pd.Timestamp(datetime.now().date())
        cutoff_date = today + timedelta(days=expiry_days)

        expiring_soon = work_df[
            (work_df["Expiry Date"] >= today) & (work_df["Expiry Date"] <= cutoff_date)
        ].copy()
        already_expired = work_df[work_df["Expiry Date"] < today].copy()

        expiring_soon["Days Left"] = (expiring_soon["Expiry Date"] - today).dt.days
        expiring_soon["Total Value (₹)"] = expiring_soon["Quantity (Stock)"] * expiring_soon["Price (₹)"]

        st.divider()

        tab_exp, tab_stock = st.tabs(["⏰ Expiry Alert", "📉 Low Stock Alert"])

        with tab_exp:
            if not already_expired.empty:
                st.error(f"🔴 **{len(already_expired)} dawaiyan PEHLE HI EXPIRE ho gayi hain!** Inhe turant hatayein.")
                st.dataframe(
                    already_expired[["Dawai Ka Naam", "Quantity (Stock)", "Expiry Date", "Price (₹)"]],
                    use_container_width=True
                )

            if not expiring_soon.empty:
                total_loss = expiring_soon["Total Value (₹)"].sum()
                m1, m2 = st.columns(2)
                m1.metric("Expire Hone Wali Dawaiyan", len(expiring_soon))
                m2.metric("Total Value", f"₹{total_loss:,.0f}")

                display_df = expiring_soon[["Dawai Ka Naam", "Quantity (Stock)", "Expiry Date", "Days Left", "Total Value (₹)"]].sort_values("Days Left")
                st.dataframe(display_df, use_container_width=True)

                st.markdown("##### 📱 WhatsApp Pe Bhejne Wala Message")
                msg_lines = [f"⏰ *Expiry Alert* — Agle {expiry_days} dinon mein expire ho rahi dawaiyan:\n"]
                for _, row in display_df.iterrows():
                    msg_lines.append(f"• {row['Dawai Ka Naam']} — Qty: {row['Quantity (Stock)']}, {row['Days Left']} din baaki")
                msg_lines.append(f"\n💰 Total value: ₹{total_loss:,.0f}")
                msg_lines.append("Inhe distributor ko turant return karen!")
                whatsapp_msg = "\n".join(msg_lines)

                st.text_area("Yeh message copy karke WhatsApp pe paste karein:", whatsapp_msg, height=180)
            else:
                if already_expired.empty:
                    st.success(f"✅ Koi dawai agle {expiry_days} dinon mein expire nahi ho rahi. Sab theek hai!")

        with tab_stock:
            low_stock_df = work_df[work_df["Quantity (Stock)"] <= low_stock_limit].copy()
            low_stock_df = low_stock_df.sort_values("Quantity (Stock)")

            if not low_stock_df.empty:
                st.metric("Low Stock Dawaiyan", len(low_stock_df))
                st.dataframe(
                    low_stock_df[["Dawai Ka Naam", "Quantity (Stock)", "Price (₹)"]],
                    use_container_width=True
                )

                st.markdown("##### 📱 WhatsApp Pe Bhejne Wala Message")
                msg_lines2 = ["📉 *Low Stock Alert* — Yeh dawaiyan jaldi order karein:\n"]
                for _, row in low_stock_df.iterrows():
                    msg_lines2.append(f"• {row['Dawai Ka Naam']} — Sirf {row['Quantity (Stock)']} bachi hai")
                whatsapp_msg2 = "\n".join(msg_lines2)

                st.text_area("Yeh message copy karke WhatsApp pe paste karein:", whatsapp_msg2, height=150, key="stock_msg")
            else:
                st.success(f"✅ Koi dawai ka stock kam nahi hai (sab {low_stock_limit} se zyada hain)")

# ============================================
# PAGE 3: GST CALCULATOR (CA-Style Breakdown)
# ============================================
elif page == "🧾 GST Calculator":
    st.title("🧾 GST Calculator")
    st.write("CGST + SGST alag-alag dekhein — bilkul jaisa proper invoice mein hota hai.")
    st.divider()

    calc_tab1, calc_tab2 = st.tabs(["⚡ Quick Calculator (1 Dawai)", "📄 Pura Bill (Save Hoga)"])

    # ---------- TAB 1: QUICK SINGLE-ITEM CALCULATOR ----------
    with calc_tab1:
        st.caption("Sirf ek dawai ka GST jaldi check karna ho, toh yahan use karein.")

        col_input1, col_input2, col_input3 = st.columns(3)
        with col_input1:
            base_amount = st.number_input("Dawai Ka Amount (₹) — GST se pehle", min_value=0.0, step=1.0, value=100.0)
        with col_input2:
            gst_rate = st.selectbox("GST Rate Chunein", [5, 12, 18, 28], index=0)
        with col_input3:
            quantity_gst = st.number_input("Quantity", min_value=1, step=1, value=1)

        total_base = base_amount * quantity_gst
        cgst_rate = gst_rate / 2
        sgst_rate = gst_rate / 2
        cgst_amount = total_base * (cgst_rate / 100)
        sgst_amount = total_base * (sgst_rate / 100)
        total_gst = cgst_amount + sgst_amount
        grand_total = total_base + total_gst

        st.divider()

        breakdown_df = pd.DataFrame({
            "Detail": [
                "Base Amount (Qty x Price)",
                f"CGST @ {cgst_rate}%",
                f"SGST @ {sgst_rate}%",
                "Total GST",
                "Grand Total"
            ],
            "Amount (₹)": [
                f"₹{total_base:,.2f}",
                f"₹{cgst_amount:,.2f}",
                f"₹{sgst_amount:,.2f}",
                f"₹{total_gst:,.2f}",
                f"₹{grand_total:,.2f}"
            ]
        })
        st.dataframe(breakdown_df, use_container_width=True, hide_index=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("Base Amount", f"₹{total_base:,.2f}")
        m2.metric("Total GST", f"₹{total_gst:,.2f}")
        m3.metric("Grand Total", f"₹{grand_total:,.2f}")

        st.caption("Note: Yeh intra-state billing (CGST + SGST) ke liye hai. Inter-state mein IGST lagta hai, jo abhi shamil nahi hai.")

    # ---------- TAB 2: FULL BILL — MULTIPLE MEDICINES, SAVES TO HISTORY ----------
    with calc_tab2:
        st.caption("Poora bill upload karein — sabhi dawaiyon ka GST ek saath calculate hoga, aur yeh bill permanently save bhi ho jaayega.")

        st.write("Excel file mein yeh columns hone chahiye:")
        st.code("Dawai Ka Naam | Quantity | Price (₹) | GST Rate (%)")

        bill_file = st.file_uploader(
            "Bill ki Excel/CSV file upload karein",
            type=["xlsx", "csv"],
            key="bill_upload"
        )

        sample_bill_df = pd.DataFrame({
            "Dawai Ka Naam": ["Paracetamol 500mg", "Amoxicillin 250mg"],
            "Quantity": [50, 10],
            "Price (₹)": [25, 80],
            "GST Rate (%)": [12, 12]
        })
        buffer_bill = io.BytesIO()
        sample_bill_df.to_excel(buffer_bill, index=False, engine="openpyxl")
        st.download_button(
            label="📋 Sample Bill Template Download Karein",
            data=buffer_bill.getvalue(),
            file_name="sample_bill_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        if bill_file is not None:
            try:
                if bill_file.name.endswith(".csv"):
                    bill_df = pd.read_csv(bill_file)
                else:
                    bill_df = pd.read_excel(bill_file)

                bill_df.columns = [str(c).strip() for c in bill_df.columns]

                required_cols = {"Dawai Ka Naam", "Quantity", "Price (₹)", "GST Rate (%)"}
                if not required_cols.issubset(set(bill_df.columns)):
                    st.error(f"⚠️ File mein yeh columns missing hain: {required_cols - set(bill_df.columns)}")
                else:
                    bill_df["Quantity"] = pd.to_numeric(bill_df["Quantity"], errors="coerce")
                    bill_df["Price (₹)"] = pd.to_numeric(bill_df["Price (₹)"], errors="coerce")
                    bill_df["GST Rate (%)"] = pd.to_numeric(bill_df["GST Rate (%)"], errors="coerce")

                    bill_df["Base Amount (₹)"] = bill_df["Quantity"] * bill_df["Price (₹)"]
                    bill_df["CGST (₹)"] = bill_df["Base Amount (₹)"] * (bill_df["GST Rate (%)"] / 2 / 100)
                    bill_df["SGST (₹)"] = bill_df["Base Amount (₹)"] * (bill_df["GST Rate (%)"] / 2 / 100)
                    bill_df["Total GST (₹)"] = bill_df["CGST (₹)"] + bill_df["SGST (₹)"]
                    bill_df["Item Total (₹)"] = bill_df["Base Amount (₹)"] + bill_df["Total GST (₹)"]

                    st.divider()
                    st.subheader("📋 Bill Ki Pori Breakdown")
                    st.dataframe(
                        bill_df[["Dawai Ka Naam", "Quantity", "Price (₹)", "GST Rate (%)",
                                 "Base Amount (₹)", "CGST (₹)", "SGST (₹)", "Total GST (₹)", "Item Total (₹)"]],
                        use_container_width=True
                    )

                    total_base_amt = bill_df["Base Amount (₹)"].sum()
                    total_cgst_amt = bill_df["CGST (₹)"].sum()
                    total_sgst_amt = bill_df["SGST (₹)"].sum()
                    total_gst_amt = bill_df["Total GST (₹)"].sum()
                    grand_total_amt = bill_df["Item Total (₹)"].sum()

                    st.divider()
                    st.subheader("💰 Is Bill Ka Total")

                    bm1, bm2, bm3, bm4 = st.columns(4)
                    bm1.metric("Base Amount", f"₹{total_base_amt:,.0f}")
                    bm2.metric("Total CGST", f"₹{total_cgst_amt:,.0f}")
                    bm3.metric("Total SGST", f"₹{total_sgst_amt:,.0f}")
                    bm4.metric("Grand Total", f"₹{grand_total_amt:,.0f}")

                    st.divider()
                    bill_name_input = st.text_input(
                        "Bill Ka Naam/Number Daalein (yaad rakhne ke liye)",
                        value=f"Bill - {datetime.now().strftime('%d %b %Y')}"
                    )

                    if st.button("💾 Yeh Bill Permanently Save Karein"):
                        saved = save_bill(
                            bill_name=bill_name_input,
                            items_df=bill_df[["Dawai Ka Naam", "Quantity", "Price (₹)", "GST Rate (%)"]],
                            total_amount=total_base_amt,
                            total_cgst=total_cgst_amt,
                            total_sgst=total_sgst_amt,
                            total_gst=total_gst_amt
                        )
                        st.success(f"✅ '{bill_name_input}' save ho gaya! Iसे '📂 Bill History' mein dekh sakte hain.")

            except Exception as e:
                st.error(f"⚠️ File padhne mein problem hui: {e}")

# ============================================
# PAGE: BILL HISTORY
# ============================================
elif page == "📂 Bill History":
    st.title("📂 Bill History")
    st.write("Saare purane bills yahan permanently save hain — kabhi bhi wapas dekh sakte hain.")
    st.divider()

    all_bills = load_all_bills()

    if not all_bills:
        st.info("📭 Abhi tak koi bill save nahi hua. '🧾 GST Calculator' → '📄 Pura Bill' tab se bill upload aur save karein.")
    else:
        hist_tab1, hist_tab2 = st.tabs(["📋 Saare Bills", "📅 Monthly Summary"])

        with hist_tab1:
            st.subheader(f"Total Saved Bills: {len(all_bills)}")

            for bill in reversed(all_bills):
                with st.expander(f"🧾 {bill['bill_name']} — ₹{bill['grand_total']:,.0f} ({bill['date_saved']})"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Base Amount", f"₹{bill['total_amount']:,.0f}")
                    c2.metric("CGST", f"₹{bill['total_cgst']:,.0f}")
                    c3.metric("SGST", f"₹{bill['total_sgst']:,.0f}")
                    c4.metric("Grand Total", f"₹{bill['grand_total']:,.0f}")

                    st.markdown("**Dawaiyon Ki List:**")
                    items_display = pd.DataFrame(bill["items"])
                    st.dataframe(items_display, use_container_width=True, hide_index=True)

                    if st.button("🗑️ Yeh Bill Delete Karein", key=f"del_{bill['bill_id']}"):
                        delete_bill(bill["bill_id"])
                        st.rerun()

        with hist_tab2:
            monthly = get_monthly_summary()

            if not monthly:
                st.info("Abhi koi data nahi hai.")
            else:
                for month_key in sorted(monthly.keys(), reverse=True):
                    data = monthly[month_key]
                    month_display = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")

                    st.markdown(f"#### 📅 {month_display}")
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Total Bills", data["total_bills"])
                    mc2.metric("Total CGST", f"₹{data['total_cgst']:,.0f}")
                    mc3.metric("Total SGST", f"₹{data['total_sgst']:,.0f}")
                    mc4.metric("Total GST", f"₹{data['total_gst']:,.0f}")
                    st.caption("Yeh summary seedha CA ko bhej sakte hain GST return file karne ke liye.")
                    st.divider()

# ============================================
# PAGE 4: GENERIC SUBSTITUTE FINDER
# ============================================
elif page == "🔄 Generic Substitute Finder":
    st.title("🔄 Generic Substitute Finder")
    st.write("Branded dawai ka naam search karein — uski saalt/composition aur sasti generic alternatives dekhein. Customer ka paisa bachao, apna margin badhao.")
    st.divider()

    substitute_df = pd.DataFrame(SUBSTITUTE_DATA)

    search_query = st.text_input("🔍 Branded Dawai Ka Naam Search Karein", placeholder="Jaise: Crocin, Augmentin, Pan 40...")

    if search_query.strip():
        matches = substitute_df[
            substitute_df["brand"].str.contains(search_query.strip(), case=False, na=False)
        ]

        if matches.empty:
            st.warning(f"⚠️ '{search_query}' ke liye koi match nahi mila. Database abhi 50 dawaiyon tak hai — dheere-dheere badhega.")
        else:
            for _, row in matches.iterrows():
                with st.container(border=True):
                    col_a, col_b = st.columns([1, 2])
                    with col_a:
                        st.markdown(f"**Brand:** {row['brand']}")
                        st.caption(f"Category: {row['category']}")
                    with col_b:
                        st.markdown(f"**Saalt/Composition:** {row['salt']}")
                        st.markdown("**Generic Alternatives:**")
                        for alt in row["generic_alternatives"]:
                            st.markdown(f"- {alt}")
    else:
        st.info("👆 Upar search box mein koi bhi branded dawai ka naam likhein.")

        st.markdown("##### 📚 Poori Database Dekhein")
        display_table = substitute_df.copy()
        display_table["generic_alternatives"] = display_table["generic_alternatives"].apply(lambda x: ", ".join(x))
        display_table = display_table.rename(columns={
            "brand": "Brand",
            "salt": "Saalt/Composition",
            "generic_alternatives": "Generic Alternatives",
            "category": "Category"
        })
        st.dataframe(display_table, use_container_width=True, hide_index=True)

    st.divider()
    st.caption(f"📊 Abhi database mein {len(SUBSTITUTE_DATA)} branded dawaiyan hain. Field mein jo bhi naya naam pucha jaaye, woh add karte jayenge.")

# ============================================
# PAGE: NEWS & UPDATES (Automatic RSS Feed)
# ============================================
elif page == "📰 News & Updates":
    st.title("📰 News & Updates")
    st.write("Pharma, GST aur health-related taza updates — automatically internet se aate hain.")
    st.divider()

    # RSS feeds — pharma/health/business news ke liye
    RSS_FEEDS = {
        "PIB India — Health Ministry": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "Economic Times — Pharma": "https://economictimes.indiatimes.com/industry/healthcare/biotech/pharmaceuticals/rssfeeds/13358350.cms",
        "Business Standard — Pharma": "https://www.business-standard.com/rss/industry/pharma-10711.rss"
    }

    selected_feed = st.selectbox("News Source Chunein", list(RSS_FEEDS.keys()))

    if st.button("🔄 Taza News Laayein"):
        with st.spinner("News laayi jaa rahi hai..."):
            try:
                feed_url = RSS_FEEDS[selected_feed]
                parsed_feed = feedparser.parse(feed_url)

                if not parsed_feed.entries:
                    st.warning("⚠️ Abhi iस source se koi news nahi mil rahi. Koi doosra source try karein.")
                else:
                    st.success(f"✅ {len(parsed_feed.entries[:10])} news milein")
                    st.divider()

                    for entry in parsed_feed.entries[:10]:
                        with st.container(border=True):
                            st.markdown(f"**{entry.get('title', 'No Title')}**")
                            if entry.get("published"):
                                st.caption(f"📅 {entry.get('published')}")
                            if entry.get("summary"):
                                summary_text = entry.get("summary")
                                if len(summary_text) > 250:
                                    summary_text = summary_text[:250] + "..."
                                st.write(summary_text)
                            if entry.get("link"):
                                st.markdown(f"[Pura Padhein →]({entry.get('link')})")
            except Exception as e:
                st.error(f"⚠️ News laane mein problem hui: {e}")
                st.info("Internet connection check karein, ya kuch der baad try karein.")
    else:
        st.info("👆 Upar se source chunein aur 'Taza News Laayein' button dabayein.")

    st.divider()
    st.caption("Note: Yeh news internet se live aati hai — agar internet slow hai ya source down hai, to thoda time lag sakta hai ya news na aaye.")

# ============================================
# FOOTER
# ============================================
st.sidebar.markdown("---")
st.sidebar.caption("Made with ❤️ for Manawar Medical Stores")
