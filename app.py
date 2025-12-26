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
    /* Transparent cards for Dark/Light mode compatibility */
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
    # If a cell somehow still has newlines, take the last value
    if '\n' in str(val_str): val_str = str(val_str).split('\n')[-1]
    
    clean = str(val_str).replace('$', '').replace(',', '').replace(' ', '')
    if '(' in clean or ')' in clean: clean = '-' + clean.replace('(', '').replace(')', '')
    try: return float(clean)
    except ValueError: return 0.0

# --- SMART ROUTER (Traffic Controller) ---
def detect_document_type(uploaded_file):
    """
    Peeks at the file content to guess the report type.
    Returns: 'RX', 'GEO', 'CENSUS', or 'UNKNOWN'
    """
    filename = uploaded_file.name.lower()
    if filename.endswith('.xlsx') or filename.endswith('.csv'): return 'CENSUS'
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
            # Keywords to identify Rx Reports
            if "Ingredient Cost" in first_page_text or "Plan Cost" in first_page_text:
                return 'RX'
            # Keywords for GeoAccess
            if "GeoAccess" in first_page_text or "Distance" in first_page_text:
                return 'GEO'
    except:
        return 'UNKNOWN'
        
    return 'UNKNOWN'

# --- ENGINE: RX PARSER ---
@st.cache_data
def run_rx_parser(uploaded_file):
    extracted_data = []
    
    # Target Cohorts based on your PDF
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
            
            # Detect Month
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match: current_month = month_match.group(0)
            
            # Extract Tables with "Text" strategy (Crucial for invisible columns)
            tables = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 4})
            
            # Find the "TOTAL" table (usually last on page)
            target_table = None
            for table in reversed(tables):
                if "hmo actives" in str(table).lower(): 
                    target_table = table
                    break
            
            if not target_table: continue

            for row in target_table:
                raw_row = [str(cell) if cell is not None else "" for cell in row]
                if not raw_row: continue
                
                # --- EXPLODE LOGIC for Stacked Rows ---
                label_col = raw_row[0]
                lines_in_row = label_col.count('\n') + 1
                
                for i in range(lines_in_row):
                    try:
                        label_parts = label_col.split('\n')
                        if i >= len(label_parts): continue
                        current_label = label_parts[i].strip()
                        
                        # Fuzzy match check
                        matched_cohort = next((c for c in cohort_keywords if c in current_label or current_label in c), None)
                        if not matched_cohort and "Retirees" in current_label and "PPO" in label_col: matched_cohort = "Horizon / Aetna PPO Retirees"
                        if not matched_cohort and "Actives" in current_label and "PPO" in label_col: matched_cohort = "Horizon / Aetna PPO Actives"

                        if matched_cohort and current_month:
                            # Extract value for this specific virtual line `i`
                            def get_val(col_idx, line_idx):
                                if col_idx >= len(raw_row): return "0"
                                parts = raw_row[col_idx].split('\n')
                                if line_idx < len(parts): return parts[line_idx]
                                return "0"
                            
                            # Grab from end of row (Standard Aon format)
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
# This creates the toggle for Advisor vs Underwriter
st.sidebar.title("⚙️ Analysis Context")
user_role = st.sidebar.radio("User Persona", ["Benefit Advisor", "Underwriter"], index=0)
funding_type = st.sidebar.selectbox("Funding Type", ["Fully Insured", "Level Funded", "Traditional Stop Loss"])

if user_role == "Underwriter":
    isl_threshold = st.sidebar.number_input("ISL Threshold ($)", value=50000, step=10000)
    st.sidebar.info(f"Targeting claimants > 50% of ${isl_threshold:,}")

# --- MAIN UI ---
st.title("🛡️ Broker Intelligence Suite")
st.markdown("##### Upload any report (Rx, Geo, Census) - We'll figure it out.")

uploaded_file = st.file_uploader("", type=["pdf", "xlsx", "csv"], label_visibility="collapsed")

if uploaded_file:
    # 1. DETECT TYPE
    with st.spinner('Analyzing Document Structure...'):
        doc_type = detect_document_type(uploaded_file)
    
    # 2. ROUTE TO RX ENGINE
    if doc_type == 'RX':
        df = run_rx_parser(uploaded_file)
        
        if not df.empty:
            # Common Data Prep
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            total_spend = df["Plan Cost"].sum()
            
            # ---------------------------
            # VIEW 1: BENEFIT ADVISOR (Story Mode)
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
                st.caption("Monthly spend trend broken down by cohort.")
                fig_monthly = px.bar(df, x="Month", y="Plan Cost", color="Cohort", 
                                     text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Prism)
                fig_monthly.update_layout(xaxis_title="", yaxis_title="Plan Cost ($)", legend_title="")
                st.plotly_chart(fig_monthly, use_container_width=True)
                
                col_left, col_right = st.columns(2)
                with col_left:
                    st.subheader("🏆 Cohort Costs")
                    cohort_df = df.groupby("Cohort")["Plan Cost"].sum().reset_index().sort_values("Plan Cost")
                    fig_c = px.bar(cohort_df, x="Plan Cost", y="Cohort", orientation='h', text_auto='.2s', color="Plan Cost", color_continuous_scale="Blues")
                    fig_c.update_layout(coloraxis_showscale=False, yaxis_title="")
                    st.plotly_chart(fig_c, use_container_width=True)
                with col_right:
                    st.subheader("Data Grid")
                    st.dataframe(df, use_container_width=True, height=400)

            # ---------------------------
            # VIEW 2: UNDERWRITER (Risk Mode)
            # ---------------------------
            elif user_role == "Underwriter":
                st.warning(f"🔐 Underwriter Mode Active | Funding: {funding_type}")
                
                # Technical Metrics
                col1, col2, col3, col4 = st.columns(4)
                total_scripts = df["Scripts"].sum()
                cost_per_script = total_spend / total_scripts if total_scripts > 0 else 0
                gross_spend = df['Gross Cost'].sum()
                
                col1.metric("Gross Spend", f"${gross_spend:,.0f}", help="Before Member Share")
                col2.metric("Plan Spend", f"${total_spend:,.0f}", help="Net Employer Cost")
                col3.metric("Member Share %", f"{(df['Member Cost'].sum() / gross_spend) * 100:.1f}%")
                col4.metric("Cost Per Script", f"${cost_per_script:,.2f}")
                
                st.markdown("### 📉 Risk Analysis & Trend Anomalies")
                
                # Month-over-Month Variance Calculation
                monthly_trend = df.groupby("Month")["Plan Cost"].sum().reset_index()
                monthly_trend['Sort'] = monthly_trend['Month'].map(month_map)
                monthly_trend = monthly_trend.sort_values('Sort')
                monthly_trend['% Change'] = monthly_trend['Plan Cost'].pct_change() * 100
                
                st.dataframe(monthly_trend.style.format({"Plan Cost": "${:,.2f}", "% Change": "{:+.2f}%"}), use_container_width=True)
                
                # ISL / HCC Placeholder
                st.markdown("### ⚠️ High Cost Claimant (HCC) Analysis")
                if "Claimant ID" in df.columns:
                    # Future logic for line-level reports
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
        st.success(f"🌍 Document Identified: **GeoAccess Report**")
        st.info("GeoAccess Engine Loaded. (Upload sample to activate)")
        
    elif doc_type == 'CENSUS':
        st.success(f"👥 Document Identified: **Member Census**")
        st.info("Census Engine Loaded. (Upload sample to activate)")
        
    else:
        st.error("Unknown File Type. Please upload a standard Rx Report, GeoAccess PDF, or Census Excel.")
