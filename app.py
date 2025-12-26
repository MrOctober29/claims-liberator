import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Broker Intelligence Suite", layout="wide")

# --- CUSTOM CSS (Fixed for Dark Mode) ---
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

# --- THE SMART ROUTER (Traffic Controller) ---
def detect_document_type(uploaded_file):
    """
    Peeks at the file content to guess the report type.
    Returns: 'RX', 'GEO', 'CENSUS', or 'UNKNOWN'
    """
    filename = uploaded_file.name.lower()
    
    # 1. Check Extension for Census (usually Excel/CSV)
    if filename.endswith('.xlsx') or filename.endswith('.csv'):
        return 'CENSUS'
    
    # 2. Check PDF Content
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ""
            # Keywords to identify Rx Reports
            if "Ingredient Cost" in first_page_text or "Plan Cost" in first_page_text:
                return 'RX'
            # Keywords for GeoAccess (Adjust based on your actual Geo reports)
            if "GeoAccess" in first_page_text or "Distance" in first_page_text or "Access Analysis" in first_page_text:
                return 'GEO'
    except:
        return 'UNKNOWN'
        
    return 'UNKNOWN'

# --- ENGINE 1: RX PARSER (The logic we perfected) ---
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

# --- ENGINE 2: GEOACCESS PARSER (Placeholder) ---
def run_geo_parser(uploaded_file):
    # FUTURE WORK: This will parse the GeoAccess PDF structure
    st.info("GeoAccess Logic Initialized. Parser coming in next sprint.")
    # Returning dummy data so you can see the UI switch
    return pd.DataFrame({
        "Zip Code": ["07747", "08857", "07001"],
        "City": ["Old Bridge", "Matawan", "Avenel"],
        "Access %": [98, 95, 82],
        "Gap": [False, False, True]
    })

# --- UI: MAIN AREA ---
st.title("🛡️ Broker Intelligence Suite")
st.markdown("##### Upload any report (Rx, GeoAccess, Census) - We'll figure it out.")

uploaded_file = st.file_uploader("", type=["pdf", "xlsx", "csv"], label_visibility="collapsed")

if uploaded_file:
    with st.spinner('Analyzing Document Structure...'):
        # 1. DETECT TYPE
        doc_type = detect_document_type(uploaded_file)
    
    # 2. ROUTE TO CORRECT ENGINE
    if doc_type == 'RX':
        st.success(f"📂 Document Identified: **Pharmacy Experience Report**")
        df = run_rx_parser(uploaded_file)
        
        if not df.empty:
            # --- RX DASHBOARD ---
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            
            total_spend = df["Plan Cost"].sum()
            avg_monthly = total_spend / df["Month"].nunique()
            top_cohort_name = df.groupby("Cohort")["Plan Cost"].sum().idxmax()
            
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Spend", f"${total_spend:,.0f}")
            c2.metric("Avg Monthly", f"${avg_monthly:,.0f}")
            c3.metric("Top Cost Driver", top_cohort_name)
            
            st.subheader("📊 Spend Composition")
            fig_monthly = px.bar(df, x="Month", y="Plan Cost", color="Cohort", 
                                 text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Prism)
            fig_monthly.update_layout(xaxis_title="", yaxis_title="Plan Cost ($)", legend_title="")
            st.plotly_chart(fig_monthly, use_container_width=True)

            col_left, col_right = st.columns(2)
            with col_left:
                st.subheader("🏆 Cohort Costs")
                cohort_df = df.groupby("Cohort")["Plan Cost"].sum().reset_index().sort_values("Plan Cost")
                fig_c = px.bar(cohort_df, x="Plan Cost", y="Cohort", orientation='h', text_auto='.2s')
                st.plotly_chart(fig_c, use_container_width=True)
            with col_right:
                st.subheader("Data Grid")
                st.dataframe(df, use_container_width=True, height=300)
    
    elif doc_type == 'GEO':
        st.success(f"🌍 Document Identified: **GeoAccess Report**")
        st.warning("🚧 The GeoAccess Parsing Engine is under construction. (Upload a sample to build it!)")
        
    elif doc_type == 'CENSUS':
        st.success(f"👥 Document Identified: **Member Census**")
        st.warning("🚧 The Census Parsing Engine is under construction.")
        
    else:
        st.error("Unknown Document Type. Please upload a standard Rx Report, GeoAccess PDF, or Census Excel.")
