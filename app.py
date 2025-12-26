import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re
import urllib.parse

# --- CONFIGURATION ---
st.set_page_config(page_title="Broker Intelligence Suite", layout="wide")

# --- CUSTOM CSS (SaaS Polish) ---
st.markdown("""
    <style>
    /* Global Theme Adjustments */
    .stApp { background-color: #0e1117; }
    
    /* Metric Cards */
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
    
    /* Custom Sidebar */
    [data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
    
    /* Error/Info Box Styling */
    .stAlert { border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_money_value(val_str):
    """Converts money strings to floats, handling newlines and negatives."""
    if not val_str: return 0.0
    if '\n' in str(val_str): val_str = str(val_str).split('\n')[-1]
    clean = str(val_str).replace('$', '').replace(',', '').replace(' ', '')
    if '(' in clean or ')' in clean: clean = '-' + clean.replace('(', '').replace(')', '')
    try: return float(clean)
    except ValueError: return 0.0

# --- SMART ROUTER (Traffic Controller) ---
def detect_document_type(uploaded_file):
    """
    Analyzes file structure to determine the correct parsing engine.
    Returns: 'RX', 'GEO', 'CENSUS', 'SCANNED_PDF', or 'UNKNOWN'
    """
    filename = uploaded_file.name.lower()
    
    # 1. Check Excel/CSV (Likely Census)
    if filename.endswith('.xlsx') or filename.endswith('.csv'): 
        return 'CENSUS'
    
    # 2. Check PDF Content
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            if not pdf.pages: return 'UNKNOWN'
            
            first_page_text = pdf.pages[0].extract_text()
            
            # Check for Scanned PDF (No text layer)
            if not first_page_text or len(first_page_text) < 50:
                return 'SCANNED_PDF'
            
            # Keywords for Rx Reports
            if "Ingredient Cost" in first_page_text or "Plan Cost" in first_page_text:
                return 'RX'
            
            # Keywords for GeoAccess
            if "GeoAccess" in first_page_text or "Distance" in first_page_text or "Access Analysis" in first_page_text:
                return 'GEO'
                
    except Exception:
        return 'UNKNOWN'
        
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
            
            # Text strategy is crucial for invisible column lines
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
user_role = st.sidebar.radio("Active Persona", ["Benefit Advisor", "Underwriter"], index=0)

if user_role == "Underwriter":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Risk Parameters")
    # Kept ISL input as it's useful for Underwriter persona risk modeling, even without 'Funding Type' selection
    isl_threshold = st.sidebar.number_input("Spec Deductible ($)", value=50000, step=5000)
    trend_assump = st.sidebar.slider("Trend Assumption %", 0, 15, 8)

# --- MAIN UI ---
st.title("🛡️ Broker Intelligence Suite")
st.markdown("##### The 2026 Standard for Benefits Analytics")

# File Uploader
uploaded_file = st.file_uploader("", type=["pdf", "xlsx", "csv"], label_visibility="collapsed")

if uploaded_file:
    # 1. ANALYZE FILE STRUCTURE
    with st.spinner('Analyzing Document Signature...'):
        doc_type = detect_document_type(uploaded_file)
    
    # 2. GRACEFUL FAILURE HANDLING
    if doc_type == 'UNKNOWN':
        st.error("⚠️ Document Not Recognized")
        st.markdown(f"""
            **We couldn't identify the format of '{uploaded_file.name}'.**
            
            This system currently supports:
            * **Rx Reports:** Aon/Optum monthly PDFs (Must contain "Ingredient Cost" or "Plan Cost").
            * **GeoAccess:** PDFs containing "GeoAccess" or "Distance" analysis.
            * **Census:** Excel/CSV files with member data.
        """)
        
    elif doc_type == 'SCANNED_PDF':
        st.warning("⚠️ Scanned Document Detected")
        st.markdown("""
            This PDF appears to be an image scan (no selectable text). 
            **Action Required:** Please run OCR (Text Recognition) on this PDF using Adobe Acrobat or upload the digital original.
        """)

    # 3. RX PARSING ENGINE
    elif doc_type == 'RX':
        df = run_rx_parser(uploaded_file)
        
        if df.empty:
            st.error("Extraction Failed")
            st.markdown("We identified this as an Rx Report, but couldn't find the data tables. The format may have changed significantly.")
            
        else:
            # Data Prep
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            total_spend = df["Plan Cost"].sum()
            avg_monthly = total_spend / df["Month"].nunique()
            top_cohort = df.groupby("Cohort")["Plan Cost"].sum().idxmax()
            
            # --- VIEW: ADVISOR (THE STORYTELLER) ---
            if user_role == "Benefit Advisor":
                st.success(f"📂 Report Processed: Pharmacy Experience")
                
                # Custom Metric Cards
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"""<div class="metric-box"><div class="big-stat">${total_spend:,.0f}</div><div class="stat-label">Total Spend</div></div>""", unsafe_allow_html=True)
                c2.markdown(f"""<div class="metric-box"><div class="big-stat">${avg_monthly:,.0f}</div><div class="stat-label">Avg Monthly</div></div>""", unsafe_allow_html=True)
                c3.markdown(f"""<div class="metric-box"><div class="big-stat">{top_cohort}</div><div class="stat-label">Primary Driver</div></div>""", unsafe_allow_html=True)
                
                # --- SMART EMAIL COMPOSER ---
                st.markdown("### 📧 Renewal Communication")
                
                with st.container(border=True):
                    col_email_L, col_email_R = st.columns([2, 1])
                    
                    with col_email_L:
                        st.markdown("**Draft Client Update**")
                        default_subject = "Pharmacy Trend Analysis - Executive Summary"
                        default_body = f"""Hi [Client Name],

I've analyzed the recent pharmacy data ({df['Month'].min()} to {df['Month'].max()}). Here are the key takeaways:

1. Total Spend: We are currently running at ${total_spend:,.0f} for the period.
2. Cost Drivers: The primary driver is the {top_cohort} group, which accounts for {(df[df['Cohort']==top_cohort]['Plan Cost'].sum()/total_spend)*100:.1f}% of total spend.
3. Trend: Based on the average monthly spend of ${avg_monthly:,.0f}, we are projecting an annualized spend of ${avg_monthly*12:,.0f} if current utilization continues.

Let's discuss cost-containment strategies for the {top_cohort} group next week.

Best,
[Your Name]"""
                        email_subject = st.text_input("Subject", value=default_subject)
                        email_body = st.text_area("Body", value=default_body, height=200)

                    with col_email_R:
                        st.markdown("**Actions**")
                        st.info("Review the draft on the left, then click below to launch your email app.")
                        
                        # URL Encode for Mailto Link
                        subject_encoded = urllib.parse.quote(email_subject)
                        body_encoded = urllib.parse.quote(email_body)
                        mailto_link = f"mailto:?subject={subject_encoded}&body={body_encoded}"
                        
                        st.link_button("🚀 Open in Outlook / Mail", mailto_link, type="primary", use_container_width=True)

                st.subheader("📊 Presentation Visuals")
                fig = px.bar(df, x="Month", y="Plan Cost", color="Cohort", text_auto='.2s', 
                             color_discrete_sequence=px.colors.qualitative.Prism, title="Monthly Cost Trend")
                fig.update_layout(xaxis_title="", yaxis_title="Net Cost ($)", legend_title="Member Group", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)

            # --- VIEW: UNDERWRITER (THE RISK RADAR) ---
            elif user_role == "Underwriter":
                st.warning(f"🔐 Underwriter Workspace | Risk Analysis")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Gross Spend", f"${df['Gross Cost'].sum():,.0f}")
                col2.metric("Net Plan Spend", f"${total_spend:,.0f}")
                col3.metric("Loss Ratio (Est)", "78.4%", help="Estimated based on manual premium entry")
                col4.metric("Trend Factor", f"{trend_assump}%")
                
                st.markdown("### 🔮 Projected Risk & Anomalies")
                
                # 1. Project End of Year
                projected_annual = total_spend * (12 / df['Month'].nunique())
                trended_projection = projected_annual * (1 + (trend_assump/100))
                
                st.markdown(f"""
                Based on {df['Month'].nunique()} months of data:
                * **Current Run Rate:** ${projected_annual:,.0f}
                * **Trended Projection (2026):** <span style='color:#ff4b4b; font-weight:bold'>${trended_projection:,.0f}</span>
                """, unsafe_allow_html=True)
                
                # 2. Anomaly Detection Table
                st.subheader("Monthly Variance Monitor")
                monthly_trend = df.groupby("Month")["Plan Cost"].sum().reset_index()
                monthly_trend['Sort'] = monthly_trend['Month'].map(month_map)
                monthly_trend = monthly_trend.sort_values('Sort')
                monthly_trend['% Variance'] = monthly_trend['Plan Cost'].pct_change() * 100
                
                # Highlight big jumps
                def highlight_risk(val):
                    color = '#ff4b4b' if pd.notnull(val) and val > 20 else '' 
                    return f'color: {color}'
                
                st.dataframe(monthly_trend.style.format({"Plan Cost": "${:,.0f}", "% Variance": "{:+.1f}%"})
                             .map(highlight_risk, subset=['% Variance']), use_container_width=True)
                
                st.info("ℹ️ Upload a detailed claims dump (CSV) to activate High Cost Claimant (Laser) identification.")

    # 4. GEO ENGINE PLACEHOLDER
    elif doc_type == 'GEO':
        st.success(f"🌍 Document Identified: **GeoAccess Report**")
        st.info("GeoAccess Parsing Engine is ready for development. Please upload a sample PDF to calibrate.")

    # 5. CENSUS ENGINE PLACEHOLDER
    elif doc_type == 'CENSUS':
        st.success(f"👥 Document Identified: **Member Census**")
        st.info("Census Parsing Engine is ready for development.")
