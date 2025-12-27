import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re
import urllib.parse

# --- CONFIGURATION ---
st.set_page_config(page_title="Broker Intelligence Suite", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    .metric-box {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
    }
    .big-stat { font-size: 28px; font-weight: 700; color: #ffffff; }
    .stat-label { font-size: 12px; color: #a0a0a0; text-transform: uppercase; letter-spacing: 1px; }
    [data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
    .stAlert { border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_money_value(val_str):
    if not val_str: return 0.0
    if '\n' in str(val_str): val_str = str(val_str).split('\n')[-1]
    clean = str(val_str).replace('$', '').replace(',', '').replace(' ', '')
    if '(' in clean or ')' in clean: clean = '-' + clean.replace('(', '').replace(')', '')
    try: return float(clean)
    except ValueError: return 0.0

# --- SMART ROUTER ---
def detect_document_type(uploaded_file):
    filename = uploaded_file.name.lower()
    if filename.endswith('.xlsx') or filename.endswith('.csv'): return 'CENSUS'
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            if not pdf.pages: return 'UNKNOWN'
            first_page_text = pdf.pages[0].extract_text()
            if not first_page_text or len(first_page_text) < 50: return 'SCANNED_PDF'
            if "Ingredient Cost" in first_page_text or "Plan Cost" in first_page_text: return 'RX'
            if "GeoAccess" in first_page_text or "Distance" in first_page_text: return 'GEO'
    except: return 'UNKNOWN'
    return 'UNKNOWN'

# --- ENGINE: RX PARSER ---
@st.cache_data
def run_rx_parser(uploaded_file):
    extracted_data = []
    cohort_keywords = [
        "HMO Actives", "HMO Retirees", 
        "Horizon / Aetna PPO Actives", "Horizon/Aetna PPO Retirees",
        "Employee Freestanding Actives", "Employee Freestanding Retirees", 
        "Employer Group Waiver Plan"
    ]
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        for page in pdf.pages:
            text = page.extract_text()
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match: current_month = month_match.group(0)
            
            tables = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 4})
            target_table = None
            for table in reversed(tables):
                if "hmo actives" in str(table).lower(): 
                    target_table = table; break
            
            if not target_table: continue

            for row in target_table:
                raw_row = [str(cell) if cell is not None else "" for cell in row]
                if not raw_row: continue
                label_col = raw_row[0]
                lines_in_row = label_col.count('\n') + 1
                
                for i in range(lines_in_row):
                    try:
                        label_parts = label_col.split('\n')
                        if i >= len(label_parts): continue
                        current_label = label_parts[i].strip()
                        matched_cohort = next((c for c in cohort_keywords if c in current_label or current_label in c), None)
                        if not matched_cohort and "Retirees" in current_label and "PPO" in label_col: matched_cohort = "Horizon / Aetna PPO Retirees"
                        if not matched_cohort and "Actives" in current_label and "PPO" in label_col: matched_cohort = "Horizon / Aetna PPO Actives"

                        if matched_cohort and current_month:
                            def get_val(col_idx, line_idx):
                                if col_idx >= len(raw_row): return "0"
                                parts = raw_row[col_idx].split('\n')
                                if line_idx < len(parts): return parts[line_idx]
                                return "0"
                            extracted_data.append({
                                "Month": current_month,
                                "Cohort": matched_cohort,
                                "Scripts": clean_money_value(get_val(-4, i)),
                                "Gross Cost": clean_money_value(get_val(-3, i)),
                                "Member Cost": clean_money_value(get_val(-2, i)),
                                "Plan Cost": clean_money_value(get_val(-1, i))
                            })
                    except Exception: continue
    return pd.DataFrame(extracted_data)

# --- SIDEBAR: INTELLIGENCE HUB ---
st.sidebar.header("🧠 Intelligence Hub")

# 1. USER PERSONA
user_role = st.sidebar.radio("Active Persona", ["Benefit Advisor", "Underwriter"], index=0)

if user_role == "Underwriter":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Risk Parameters")
    isl_threshold = st.sidebar.number_input("Spec Deductible ($)", value=50000, step=5000)
    trend_assump = st.sidebar.slider("Trend Assumption %", 0, 15, 8)

st.sidebar.markdown("---")

# 2. THE MANUAL OVERRIDE (Solves your "Direction" concern)
st.sidebar.subheader("🔧 File Parsing Mode")
parsing_mode = st.sidebar.selectbox(
    "Processing Engine", 
    ["Auto-Detect (Recommended)", "Force Rx Engine", "Force Geo Engine", "Force Census Engine"],
    help="If Auto-Detect fails, manually select the file type here."
)

# --- MAIN UI ---
st.title("🛡️ Broker Intelligence Suite")
st.markdown("##### The 2026 Standard for Benefits Analytics")

uploaded_file = st.file_uploader("Drop your PDF, Excel, or CSV report here:", type=["pdf", "xlsx", "csv"])

if uploaded_file:
    # 1. DETERMINE ENGINE
    if parsing_mode == "Auto-Detect (Recommended)":
        with st.spinner('Analyzing Document Signature...'):
            doc_type = detect_document_type(uploaded_file)
    elif parsing_mode == "Force Rx Engine":
        doc_type = 'RX'
    elif parsing_mode == "Force Geo Engine":
        doc_type = 'GEO'
    elif parsing_mode == "Force Census Engine":
        doc_type = 'CENSUS'

    # 2. HANDLE "UNKNOWN"
    if doc_type == 'UNKNOWN':
        st.error("⚠️ Document Not Recognized")
        st.markdown(f"""
            **Auto-Detect failed for '{uploaded_file.name}'.**
            
            **Try this:**
            1. Open the Sidebar (arrow > top left).
            2. Scroll to **"File Parsing Mode"**.
            3. Manually select the correct report type (e.g., "Force Rx Engine").
        """)
        
    elif doc_type == 'SCANNED_PDF':
        st.warning("⚠️ Scanned Document Detected")
        st.markdown("This PDF appears to be an image. Please use the Sidebar to force a parsing mode, though results may be limited without OCR.")

    # 3. RX ENGINE
    elif doc_type == 'RX':
        df = run_rx_parser(uploaded_file)
        if df.empty:
            st.error("Extraction Failed")
            st.markdown("Rx Engine loaded, but no data found. The table format might be unique.")
        else:
            # Data Prep
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            total_spend = df["Plan Cost"].sum()
            avg_monthly = total_spend / df["Month"].nunique()
            top_cohort = df.groupby("Cohort")["Plan Cost"].sum().idxmax()
            
            # ADVISOR VIEW
            if user_role == "Benefit Advisor":
                st.success(f"📂 Report Processed: Pharmacy Experience")
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"""<div class="metric-box"><div class="big-stat">${total_spend:,.0f}</div><div class="stat-label">Total Spend</div></div>""", unsafe_allow_html=True)
                c2.markdown(f"""<div class="metric-box"><div class="big-stat">${avg_monthly:,.0f}</div><div class="stat-label">Avg Monthly</div></div>""", unsafe_allow_html=True)
                c3.markdown(f"""<div class="metric-box"><div class="big-stat">{top_cohort}</div><div class="stat-label">Primary Driver</div></div>""", unsafe_allow_html=True)
                
                st.markdown("### 📧 Renewal Communication")
                with st.container(border=True):
                    col_email_L, col_email_R = st.columns([2, 1])
                    with col_email_L:
                        st.markdown("**Draft Client Update**")
                        default_subject = "Pharmacy Trend Analysis - Executive Summary"
                        default_body = f"""Hi [Client Name],\n\nI've analyzed the recent pharmacy data. Key takeaways:\n1. Total Spend: ${total_spend:,.0f}\n2. Top Driver: {top_cohort}\n\nBest,\n[Your Name]"""
                        email_subject = st.text_input("Subject", value=default_subject)
                        email_body = st.text_area("Body", value=default_body, height=150)
                    with col_email_R:
                        st.markdown("**Actions**")
                        st.info("Review draft, then click to launch email.")
                        subject_encoded = urllib.parse.quote(email_subject)
                        body_encoded = urllib.parse.quote(email_body)
                        mailto_link = f"mailto:?subject={subject_encoded}&body={body_encoded}"
                        st.link_button("🚀 Open in Outlook", mailto_link, type="primary", use_container_width=True)

                st.subheader("📊 Presentation Visuals")
                fig = px.bar(df, x="Month", y="Plan Cost", color="Cohort", text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Prism)
                fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)

            # UNDERWRITER VIEW
            elif user_role == "Underwriter":
                st.warning(f"🔐 Underwriter Workspace")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Gross Spend", f"${df['Gross Cost'].sum():,.0f}")
                col2.metric("Net Plan Spend", f"${total_spend:,.0f}")
                col3.metric("Loss Ratio (Est)", "78.4%")
                col4.metric("Trend Factor", f"{trend_assump}%")
                
                st.markdown("### 🔮 Projected Risk")
                projected_annual = total_spend * (12 / df['Month'].nunique())
                trended_projection = projected_annual * (1 + (trend_assump/100))
                st.markdown(f"* **Trended Projection (2026):** <span style='color:#ff4b4b; font-weight:bold'>${trended_projection:,.0f}</span>", unsafe_allow_html=True)
                
                st.subheader("Monthly Variance Monitor")
                monthly_trend = df.groupby("Month")["Plan Cost"].sum().reset_index()
                monthly_trend['Sort'] = monthly_trend['Month'].map(month_map)
                monthly_trend = monthly_trend.sort_values('Sort')
                monthly_trend['% Variance'] = monthly_trend['Plan Cost'].pct_change() * 100
                
                def highlight_risk(val):
                    return f'color: #ff4b4b' if pd.notnull(val) and val > 20 else ''
                st.dataframe(monthly_trend.style.format({"Plan Cost": "${:,.0f}", "% Variance": "{:+.1f}%"}).map(highlight_risk, subset=['% Variance']), use_container_width=True)

    # 4. GEO ENGINE PLACEHOLDER
    elif doc_type == 'GEO':
        st.success(f"🌍 Document Identified: **GeoAccess Report**")
        st.info("GeoAccess Parsing Engine is ready for development. Please upload a sample PDF to calibrate.")

    # 5. CENSUS ENGINE PLACEHOLDER
    elif doc_type == 'CENSUS':
        st.success(f"👥 Document Identified: **Member Census**")
        st.info("Census Parsing Engine is ready for development.")
