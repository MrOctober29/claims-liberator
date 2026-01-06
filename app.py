import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import sqlite3
import re
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Apex Rx: Advisor Book of Business",
    layout="wide",
    page_icon="💊",
    initial_sidebar_state="expanded"
)

# --- DATABASE MANAGEMENT ---
DB_NAME = "rx_claims_v2.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS fact_rx_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT,
            report_month DATE,
            cohort_group TEXT,
            delivery_channel TEXT,
            drug_type TEXT,
            scripts INTEGER,
            ingredient_cost REAL,
            dispensing_fee REAL,
            gross_cost REAL,
            member_pay REAL,
            plan_pay REAL,
            upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(df):
    conn = sqlite3.connect(DB_NAME)
    df.to_sql('fact_rx_claims', conn, if_exists='append', index=False)
    conn.close()

def load_clients():
    conn = sqlite3.connect(DB_NAME)
    # Check if table exists first
    try:
        query = """
            SELECT 
                client_name, 
                COUNT(*) as record_count, 
                MIN(report_month) as first_month,
                MAX(report_month) as last_month,
                SUM(plan_pay) as total_spend
            FROM fact_rx_claims 
            GROUP BY client_name
            ORDER BY total_spend DESC
        """
        df = pd.read_sql(query, conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def load_client_data(client_name):
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT * FROM fact_rx_claims WHERE client_name = ?"
    df = pd.read_sql(query, conn, params=(client_name,))
    conn.close()
    return df

def reset_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS fact_rx_claims")
    conn.commit()
    conn.close()
    init_db()

# --- HELPER FUNCTIONS ---
def clean_money(val):
    if not val: return 0.0
    s = str(val).replace('$', '').replace(',', '').replace(' ', '')
    if '(' in s and ')' in s: s = s.replace('(', '-').replace(')', '')
    try: return float(s)
    except: return 0.0

def clean_int(val):
    if not val: return 0
    s = str(val).replace(',', '').replace(' ', '').split('.')[0]
    try: return int(s)
    except: return 0

# --- ROBUST PARSER ---
def parse_rx_report(uploaded_file):
    records = []
    client_name = "Unknown Client"
    current_month_str = None
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tables = page.extract_tables()

            # 1. Metadata Extraction
            if "Client Name:" in text:
                try:
                    match = re.search(r"Client Name:\s*(.*)", text)
                    if match: client_name = match.group(1).strip()
                except: pass

            # 2. Month Detection
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text)
            if month_match:
                try:
                    dt = datetime.strptime(month_match.group(0), "%B %Y")
                    current_month_str = dt.strftime("%Y-%m-%d")
                except:
                    current_month_str = month_match.group(0)

            # 3. Table Parsing
            for table in tables:
                if not table: continue
                
                # Context Detection within Table Header
                # We assume the table has a structure like:
                # Row 0: ... MAIL ... (Header)
                # Row 1: ... Brand ... Generic ... (Subheader)
                # Row 2: Scripts | Ing Cost | ... (Columns)
                
                # Flatten first 3 rows to find keywords
                header_dump = " ".join([str(x).upper() for row in table[:4] for x in row if x])
                
                current_channel = "Unknown"
                if "MAIL" in header_dump: current_channel = "Mail Order"
                elif "RETAIL" in header_dump: current_channel = "Retail"
                else: continue # Skip tables that aren't Rx data (e.g. disclaimer tables)

                # Locate Column Indexes Dynamically
                # We search for the row containing "Scripts" to anchor our indexes
                brand_idx = -1
                generic_idx = -1
                
                # Iterate rows to find the "Data Start" row
                for r_idx, row in enumerate(table):
                    row_str = " ".join([str(x) for x in row if x])
                    
                    # If we find the column headers row
                    if "Scripts" in row_str and "Ingredient" in row_str:
                        # Find where "Scripts" appears. 
                        # Usually appearing twice: once for Brand, once for Generic.
                        script_indices = [i for i, x in enumerate(row) if x and "Scripts" in str(x)]
                        
                        if len(script_indices) >= 2:
                            brand_idx = script_indices[0]
                            generic_idx = script_indices[1]
                        elif len(script_indices) == 1:
                            # Maybe only one block? Assume Brand if ambiguous
                            brand_idx = script_indices[0]
                        
                        # Now iterate the DATA rows following this header
                        for data_row in table[r_idx+1:]:
                            clean_row = [str(x).strip() if x else "" for x in data_row]
                            
                            # Valid Row Check
                            if not clean_row or len(clean_row) < 5: continue
                            row_label = clean_row[0]
                            
                            # Skip Garbage Rows
                            if not row_label or any(x in row_label for x in ["Scripts", "Ingredient", "Total", "Cost", "Client"]):
                                continue

                            # EXTRACT BRAND
                            if brand_idx != -1 and len(clean_row) > brand_idx + 5:
                                try:
                                    b_scripts = clean_int(clean_row[brand_idx])
                                    b_gross = clean_money(clean_row[brand_idx+3]) # Gross is usually +3 from Scripts
                                    b_plan = clean_money(clean_row[brand_idx+5])  # Plan is usually +5
                                    
                                    if b_scripts > 0 or b_gross > 0:
                                        records.append({
                                            "client_name": client_name,
                                            "report_month": current_month_str,
                                            "cohort_group": row_label,
                                            "delivery_channel": current_channel,
                                            "drug_type": "Brand",
                                            "scripts": b_scripts,
                                            "ingredient_cost": clean_money(clean_row[brand_idx+1]),
                                            "dispensing_fee": clean_money(clean_row[brand_idx+2]),
                                            "gross_cost": b_gross,
                                            "member_pay": clean_money(clean_row[brand_idx+4]),
                                            "plan_pay": b_plan
                                        })
                                except: pass

                            # EXTRACT GENERIC
                            if generic_idx != -1 and len(clean_row) > generic_idx + 5:
                                try:
                                    g_scripts = clean_int(clean_row[generic_idx])
                                    g_gross = clean_money(clean_row[generic_idx+3])
                                    g_plan = clean_money(clean_row[generic_idx+5])
                                    
                                    if g_scripts > 0 or g_gross > 0:
                                        records.append({
                                            "client_name": client_name,
                                            "report_month": current_month_str,
                                            "cohort_group": row_label,
                                            "delivery_channel": current_channel,
                                            "drug_type": "Generic",
                                            "scripts": g_scripts,
                                            "ingredient_cost": clean_money(clean_row[generic_idx+1]),
                                            "dispensing_fee": clean_money(clean_row[generic_idx+2]),
                                            "gross_cost": g_gross,
                                            "member_pay": clean_money(clean_row[generic_idx+4]),
                                            "plan_pay": g_plan
                                        })
                                except: pass
                        break # Stop looking for headers in this table once found

    return pd.DataFrame(records)

# --- APP UI ---
init_db()

st.sidebar.title("💊 Apex Rx Advisor")
st.sidebar.caption("Book of Business v3.0")

menu = st.sidebar.radio("Navigation", ["📂 Book of Business", "📤 Upload New Files", "⚙️ Admin"])

# --- UPLOAD ---
if menu == "📤 Upload New Files":
    st.title("📤 Ingest New Client Data")
    st.markdown("Upload **Monthly Rx PDF Reports**. The system will scan headers dynamically to find data.")
    
    uploaded_files = st.file_uploader("Drop Aon/Optum PDFs here", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        if st.button("Process & Save to Database"):
            progress_bar = st.progress(0)
            total_records = 0
            
            for i, file in enumerate(uploaded_files):
                try:
                    df_part = parse_rx_report(file)
                    if not df_part.empty:
                        save_to_db(df_part)
                        total_records += len(df_part)
                    else:
                        st.warning(f"File {file.name} yielded no data. Check format.")
                except Exception as e:
                    st.error(f"Error processing {file.name}: {e}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            if total_records > 0:
                st.success(f"✅ Successfully saved {total_records} records to the Vault.")
            else:
                st.error("❌ No valid records found. The parser could not find the 'Scripts' columns.")

# --- BOOK OF BUSINESS ---
elif menu == "📂 Book of Business":
    st.title("📂 Advisor Book of Business")
    
    clients_df = load_clients()
    
    if clients_df.empty:
        st.info("📭 Your vault is empty. Go to 'Upload New Files' to start.")
    else:
        st.markdown("### Active Clients")
        for index, row in clients_df.iterrows():
            with st.container():
                # Client Card
                st.markdown(f"""
                <div style="background-color: #1e2129; padding: 20px; border-radius: 10px; border: 1px solid #30363d; margin-bottom: 15px;">
                    <h3>🏢 {row['client_name']}</h3>
                    <div style="display: flex; gap: 20px; color: #a0a0a0;">
                        <span>💰 Spend: <b>${row['total_spend']:,.0f}</b></span>
                        <span>📄 Records: <b>{row['record_count']}</b></span>
                        <span>📅 Range: <b>{row['first_month']}</b> to <b>{row['last_month']}</b></span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"Analyze {row['client_name']}", key=f"btn_{index}"):
                    st.session_state['selected_client'] = row['client_name']
                    st.rerun()

    # --- ANALYSIS DASHBOARD ---
    if 'selected_client' in st.session_state:
        client = st.session_state['selected_client']
        st.markdown("---")
        st.header(f"📊 Analysis: {client}")
        
        df = load_client_data(client)
        
        # Filters
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            months = sorted(df['report_month'].dropna().unique())
            sel_months = st.multiselect("Filter Months", months, default=months)
        
        if sel_months:
            dff = df[df['report_month'].isin(sel_months)]
            
            # Metrics
            tot_spend = dff['plan_pay'].sum()
            tot_scripts = dff['scripts'].sum()
            
            # GUR
            gen_scripts = dff[dff['drug_type']=='Generic']['scripts'].sum()
            gur = (gen_scripts / tot_scripts * 100) if tot_scripts else 0
            
            # Mail Order
            mail_scripts = dff[dff['delivery_channel']=='Mail Order']['scripts'].sum()
            mail_pen = (mail_scripts / tot_scripts * 100) if tot_scripts else 0
            
            # Plan Efficiency (Member Share)
            mem_share_pct = (dff['member_pay'].sum() / dff['gross_cost'].sum() * 100) if dff['gross_cost'].sum() else 0
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Plan Spend", f"${tot_spend:,.0f}")
            k2.metric("Generic Use (GUR)", f"{gur:.1f}%", delta="Target: >85%", delta_color="off")
            k3.metric("Mail Order %", f"{mail_pen:.1f}%", delta="Target: >15%", delta_color="off")
            k4.metric("Member Cost Share", f"{mem_share_pct:.1f}%")
            
            # Visuals
            tab1, tab2, tab3 = st.tabs(["💰 Cost Drivers", "📉 Monthly Trend", "🔬 Raw Data"])
            
            with tab1:
                c1, c2 = st.columns(2)
                with c1:
                    # Cohort Spend
                    fig_coh = px.bar(dff.groupby('cohort_group')['plan_pay'].sum().reset_index(), 
                                     x='plan_pay', y='cohort_group', orientation='h', title="Spend by Cohort")
                    st.plotly_chart(fig_coh, use_container_width=True)
                with c2:
                    # Brand vs Generic
                    fig_pie = px.pie(dff.groupby('drug_type')['plan_pay'].sum().reset_index(), 
                                     values='plan_pay', names='drug_type', title="Spend by Drug Type",
                                     color_discrete_sequence=['#ef553b', '#00cc96'])
                    st.plotly_chart(fig_pie, use_container_width=True)

            with tab2:
                trend = dff.groupby('report_month')['plan_pay'].sum().reset_index()
                fig_line = px.line(trend, x='report_month', y='plan_pay', markers=True, title="Spend Trend")
                st.plotly_chart(fig_line, use_container_width=True)

            with tab3:
                st.dataframe(dff, use_container_width=True)

# --- ADMIN ---
elif menu == "⚙️ Admin":
    st.title("⚙️ Admin")
    if st.button("⚠️ Wipe Database"):
        reset_db()
        st.success("Vault Cleared.")
