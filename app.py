import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Broker Intelligence Suite", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; }
    .stMetric { 
        background-color: rgba(255, 255, 255, 0.05); 
        padding: 15px; 
        border-radius: 10px; 
        border: 1px solid rgba(255, 255, 255, 0.1); 
    }
    /* Sidebar styling to differentiate it */
    [data-testid="stSidebar"] {
        background-color: rgba(255, 255, 255, 0.02);
    }
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
            first_page_text = pdf.pages[0].extract_text() or ""
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
        "Horizon / Aetna PPO Actives", "Horizon/Aetna PPO Actives",
        "Horizon / Aetna PPO Retirees", "Horizon/Aetna PPO Retirees",
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
                    target_table = table
                    break
            
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

# --- SIDEBAR: CONTEXT SETTINGS ---
st.sidebar.title("⚙️ Analysis Context")
user_role = st.sidebar.radio("User Persona", ["Benefit Advisor", "Underwriter"], index=0)
funding_type = st.sidebar.selectbox("Funding Type", ["Fully Insured", "Level Funded", "Traditional Stop Loss"])

if user_role == "Underwriter":
    isl_threshold = st.sidebar.number_input("ISL Threshold ($)", value=50000, step=10000)
    st.sidebar.info(f"Targeting claimants > 50% of ${isl_threshold:,}")

# --- MAIN UI ---
st.title("🛡️ Broker Intelligence Suite")

uploaded_file = st.file_uploader("Upload Report (Rx, Geo, Census)", type=["pdf", "xlsx", "csv"], label_visibility="visible")

if uploaded_file:
    # 1. DETECT
    doc_type = detect_document_type(uploaded_file)
    
    # 2. PARSE RX
    if doc_type == 'RX':
        df = run_rx_parser(uploaded_file)
        if not df.empty:
            # Common Data Prep
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            total_spend = df["Plan Cost"].sum()
            
            # ---------------------------
            # VIEW 1: BENEFIT ADVISOR
            # ---------------------------
            if user_role == "Benefit Advisor":
                st.success(f"📂 Report Loaded: Pharmacy Experience ({funding_type} Context)")
                
                # Big Metrics
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Spend", f"${total_spend:,.0f}")
                c2.metric("Avg Monthly", f"${total_spend / df['Month'].nunique():,.0f}")
                c3.metric("Top Cost Driver", df.groupby("Cohort")["Plan Cost"].sum().idxmax())
                
                # Visuals
                st.subheader("📊 Executive Summary")
                fig_monthly = px.bar(df, x="Month", y="Plan Cost", color="Cohort", 
                                     text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Prism)
                st.plotly_chart(fig_monthly, use_container_width=True)
                
                st.subheader("🏆 Cohort Analysis")
                cohort_df = df.groupby("Cohort")["Plan Cost"].sum().reset_index().sort_values("Plan Cost")
                fig_c = px.bar(cohort_df, x="Plan Cost", y="Cohort", orientation='h', text_auto='.2s')
                st.plotly_chart(fig_c, use_container_width=True)

            # ---------------------------
            # VIEW 2: UNDERWRITER
            # ---------------------------
            elif user_role == "Underwriter":
                st.warning(f"🔐 Underwriter Mode Active | Funding: {funding_type}")
                
                # Technical Metrics
                col1, col2, col3, col4 = st.columns(4)
                total_scripts = df["Scripts"].sum()
                cost_per_script = total_spend / total_scripts if total_scripts > 0 else 0
                
                col1.metric("Gross Spend", f"${df['Gross Cost'].sum():,.0f}", help="Before Member Share")
                col2.metric("Plan Spend", f"${total_spend:,.0f}", help="Net Employer Cost")
                col3.metric("Member Share %", f"{(df['Member Cost'].sum() / df['Gross Cost'].sum()) * 100:.1f}%")
                col4.metric("Cost Per Script", f"${cost_per_script:,.2f}")
                
                st.markdown("### 📉 Risk Analysis & Trend Anomalies")
                
                # Month-over-Month Variance Calculation
                monthly_trend = df.groupby("Month")["Plan Cost"].sum().reset_index()
                monthly_trend['Sort'] = monthly_trend['Month'].map(month_map)
                monthly_trend = monthly_trend.sort_values('Sort')
                monthly_trend['% Change'] = monthly_trend['Plan Cost'].pct_change() * 100
                
                st.dataframe(monthly_trend.style.format({"Plan Cost": "${:,.2f}", "% Change": "{:+.2f}%"}), use_container_width=True)
                
                # ISL / HCC Placeholder
                st.markdown("### ⚠️ High Cost Claimant (HCC) / ISL Analysis")
                if "Claimant ID" in df.columns:
                    # Logic for ISL breach would go here
                    pass
                else:
                    st.info(f"""
                    **Aggregate Report Detected:** This file contains cohort-level data only. 
                    Individual Stop Loss (ISL) breaches at the ${isl_threshold:,} level cannot be calculated.
                    
                    *Upload a Detailed Claims Report (CSV/Excel) to enable HCC detection.*
                    """)
                    
                st.markdown("### 🔍 Raw Data Inspection")
                st.dataframe(df, use_container_width=True)

    # 3. OTHER DOC TYPES
    elif doc_type == 'GEO':
        st.info("GeoAccess Engine Loaded. (Upload sample to activate)")
    elif doc_type == 'CENSUS':
        st.info("Census Engine Loaded. (Upload sample to activate)")
    else:
        st.error("Unknown File Type.")
