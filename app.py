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
DB_NAME = "rx_claims.db"

def init_db():
    """Initializes the SQLite database with the Universal Schema."""
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
    """Saves a dataframe to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    # Append data, do not overwrite
    df.to_sql('fact_rx_claims', conn, if_exists='append', index=False)
    conn.close()

def load_clients():
    """Fetches a list of unique clients and their summary stats."""
    conn = sqlite3.connect(DB_NAME)
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
    conn.close()
    return df

def load_client_data(client_name):
    """Fetches all rows for a specific client."""
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT * FROM fact_rx_claims WHERE client_name = ?"
    df = pd.read_sql(query, conn, params=(client_name,))
    conn.close()
    return df

def reset_db():
    """Drops the table (for debugging/clearing data)."""
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

# --- UNIVERSAL PARSER ---
def parse_rx_report(uploaded_file):
    records = []
    client_name = "Unknown Client"
    
    # Context Tracking
    current_month_str = None
    current_channel = "Retail" # Default, switches when keyword found

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            tables = page.extract_tables()

            # 1. Metadata Extraction
            if "Client Name:" in text:
                try:
                    match = re.search(r"Client Name:\s*(.*)", text)
                    if match: client_name = match.group(1).strip()
                except: pass

            # 2. Month Detection
            # Regex for "January 2023", "April 2024"
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text)
            if month_match:
                # Convert to YYYY-MM-01 format for sorting
                m_str = month_match.group(0)
                try:
                    dt = datetime.strptime(m_str, "%B %Y")
                    current_month_str = dt.strftime("%Y-%m-%d")
                except:
                    current_month_str = m_str

            # 3. Channel Context (Mail vs Retail)
            # Aon reports often label the table or section. We look for keywords.
            if "MAIL" in text.upper() and "RETAIL" not in text.upper():
                current_channel = "Mail Order"
            elif "RETAIL" in text.upper():
                current_channel = "Retail"
            
            # If the table header itself contains "MAIL", that overrides page context
            
            for table in tables:
                if not table: continue
                
                # Check Header Row for Context
                header_row = [str(x).upper() for x in table[0] if x]
                header_str = " ".join(header_row)
                
                if "MAIL" in header_str: current_channel = "Mail Order"
                if "RETAIL" in header_str: current_channel = "Retail"

                # Parse Rows
                for row in table:
                    clean_row = [str(x).strip() if x else "" for x in row]
                    if len(clean_row) < 5: continue
                    
                    row_label = clean_row[0]
                    # Filter Headers/Totals
                    if not row_label or any(x in row_label for x in ["Scripts", "Ingredient", "Client", "Total", "Brand", "Generic"]):
                        continue

                    # Try Aon/Optum Column Layout
                    # Brand: 1=Scripts, 2=Ing, 3=Disp, 4=Gross, 5=Mem, 6=Plan
                    # Generic: 7=Scripts, 8=Ing, 9=Disp, 10=Gross, 11=Mem, 12=Plan
                    
                    try:
                        # BRAND
                        b_scripts = clean_int(row[1])
                        b_gross = clean_money(row[4])
                        b_plan = clean_money(row[6])
                        
                        if b_scripts > 0 or b_gross > 0:
                            records.append({
                                "client_name": client_name,
                                "report_month": current_month_str,
                                "cohort_group": row_label,
                                "delivery_channel": current_channel,
                                "drug_type": "Brand",
                                "scripts": b_scripts,
                                "ingredient_cost": clean_money(row[2]),
                                "dispensing_fee": clean_money(row[3]),
                                "gross_cost": b_gross,
                                "member_pay": clean_money(row[5]),
                                "plan_pay": b_plan
                            })

                        # GENERIC (Offset 7 usually)
                        # Sometimes there is an empty column. Let's check index 7 first.
                        g_idx_start = 7
                        if len(row) > 12:
                            g_scripts = clean_int(row[g_idx_start])
                            g_gross = clean_money(row[g_idx_start+3])
                            g_plan = clean_money(row[g_idx_start+5])
                            
                            if g_scripts > 0 or g_gross > 0:
                                records.append({
                                    "client_name": client_name,
                                    "report_month": current_month_str,
                                    "cohort_group": row_label,
                                    "delivery_channel": current_channel,
                                    "drug_type": "Generic",
                                    "scripts": g_scripts,
                                    "ingredient_cost": clean_money(row[g_idx_start+1]),
                                    "dispensing_fee": clean_money(row[g_idx_start+2]),
                                    "gross_cost": g_gross,
                                    "member_pay": clean_money(row[g_idx_start+4]),
                                    "plan_pay": g_plan
                                })
                    except: continue

    return pd.DataFrame(records)

# --- CSS STYLING ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    .card {
        background-color: #1e2129;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .metric-val { font-size: 24px; font-weight: bold; color: white; }
    .metric-lbl { font-size: 12px; color: #a0a0a0; text-transform: uppercase; }
    </style>
""", unsafe_allow_html=True)

# --- APP NAVIGATION ---
init_db() # Ensure DB exists

st.sidebar.title("💊 Apex Rx Advisor")
st.sidebar.caption("Book of Business v2.0")

menu = st.sidebar.radio("Navigation", ["📂 Book of Business", "📤 Upload New Files", "⚙️ Admin"])

# --- 1. UPLOAD MODULE ---
if menu == "📤 Upload New Files":
    st.title("📤 Ingest New Client Data")
    st.markdown("Upload **Monthly Rx PDF Reports**. The system will normalize them and add them to your Book of Business.")
    
    uploaded_files = st.file_uploader("Drop Aon/Optum PDFs here", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        if st.button("Process & Save to Database"):
            progress_bar = st.progress(0)
            total_records = 0
            
            for i, file in enumerate(uploaded_files):
                df_part = parse_rx_report(file)
                if not df_part.empty:
                    save_to_db(df_part)
                    total_records += len(df_part)
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.success(f"✅ Successfully saved {total_records} records to the Vault.")
            st.info("Go to 'Book of Business' to analyze.")

# --- 2. BOOK OF BUSINESS (HOME) ---
elif menu == "📂 Book of Business":
    st.title("📂 Advisor Book of Business")
    
    clients_df = load_clients()
    
    if clients_df.empty:
        st.info("📭 Your vault is empty. Go to 'Upload New Files' to start.")
    else:
        # Display Client Cards
        st.markdown("### Active Clients")
        
        for index, row in clients_df.iterrows():
            with st.container():
                st.markdown(f"""
                <div class="card">
                    <h3>🏢 {row['client_name']}</h3>
                    <div style="display: flex; gap: 20px;">
                        <div>
                            <div class="metric-val">${row['total_spend']:,.0f}</div>
                            <div class="metric-lbl">Total Spend</div>
                        </div>
                        <div>
                            <div class="metric-val">{row['record_count']}</div>
                            <div class="metric-lbl">Records Analyzed</div>
                        </div>
                        <div>
                            <div class="metric-val">{row['last_month']}</div>
                            <div class="metric-lbl">Latest Data</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # The "Analyze" Button needs a unique key
                if st.button(f"Analyze {row['client_name']}", key=f"btn_{index}"):
                    st.session_state['selected_client'] = row['client_name']
                    st.rerun()

    # --- CLIENT DASHBOARD (Rendered if selected) ---
    if 'selected_client' in st.session_state:
        client = st.session_state['selected_client']
        st.markdown("---")
        st.header(f"📊 Analysis: {client}")
        
        # Load Data
        df = load_client_data(client)
        
        # --- DASHBOARD LOGIC ---
        # 1. Filters
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            months = sorted(df['report_month'].unique())
            sel_months = st.multiselect("Filter Months", months, default=months)
        
        if sel_months:
            dff = df[df['report_month'].isin(sel_months)]
            
            # 2. KPIs
            tot_spend = dff['plan_pay'].sum()
            tot_scripts = dff['scripts'].sum()
            
            # Generic Utilization
            gen_scripts = dff[dff['drug_type']=='Generic']['scripts'].sum()
            gur = (gen_scripts / tot_scripts * 100) if tot_scripts else 0
            
            # Mail Order %
            mail_scripts = dff[dff['delivery_channel']=='Mail Order']['scripts'].sum()
            mail_pen = (mail_scripts / tot_scripts * 100) if tot_scripts else 0
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Spend", f"${tot_spend:,.0f}")
            k2.metric("Script Volume", f"{tot_scripts:,}")
            k3.metric("Generic Utilization", f"{gur:.1f}%", help="Target: >85%")
            k4.metric("Mail Order %", f"{mail_pen:.1f}%", help="Target: >15%")
            
            # 3. Visuals
            tab1, tab2, tab3 = st.tabs(["💰 Cost Drivers", "📉 Trends", "🔬 Data Grid"])
            
            with tab1:
                # Spend by Cohort
                cohort_spend = dff.groupby('cohort_group')['plan_pay'].sum().reset_index()
                fig_cohort = px.bar(cohort_spend, x='plan_pay', y='cohort_group', orientation='h', title="Spend by Cohort", template="plotly_dark")
                st.plotly_chart(fig_cohort, use_container_width=True)
                
                # Brand vs Generic Spend
                bg_spend = dff.groupby('drug_type')['plan_pay'].sum().reset_index()
                fig_pie = px.pie(bg_spend, values='plan_pay', names='drug_type', title="Cost Share: Brand vs Generic", template="plotly_dark")
                st.plotly_chart(fig_pie, use_container_width=True)

            with tab2:
                # Monthly Trend
                trend = dff.groupby('report_month')['plan_pay'].sum().reset_index()
                fig_line = px.line(trend, x='report_month', y='plan_pay', markers=True, title="Monthly Spend Trend", template="plotly_dark")
                st.plotly_chart(fig_line, use_container_width=True)

            with tab3:
                st.dataframe(dff, use_container_width=True)
                
            # 4. Auto-Narrative
            st.info(f"💡 **Advisor Insight:** You are analyzing **{len(sel_months)} months** of data. "
                    f"The plan is running at a **{gur:.1f}% GUR**. " 
                    f"{'⚠️ This is below the 85% target - consider a generic step-therapy program.' if gur < 85 else '✅ Generic usage is strong.'} "
                    f"Mail order penetration is **{mail_pen:.1f}%**.")

# --- 3. ADMIN ---
elif menu == "⚙️ Admin":
    st.title("⚙️ Database Admin")
    st.warning("Danger Zone")
    if st.button("⚠️ Wipe Database (Clear All Clients)"):
        reset_db()
        st.success("Database cleared.")
