import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Claims Liberator", layout="wide")
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        border-left: 5px solid #ff4b4b;
        padding: 10px;
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_money(value):
    """Converts '$1,234.56', '1,234' or '(500)' to a float."""
    if not value: return 0.0
    clean = str(value).replace('$', '').replace(',', '').replace(' ', '').replace('\n', '')
    if '(' in clean or ')' in clean:
        clean = '-' + clean.replace('(', '').replace(')', '')
    try:
        return float(clean)
    except ValueError:
        return 0.0

# --- BACKEND ENGINE ---
@st.cache_data
def parse_pdf(uploaded_file):
    extracted_data = []
    
    # Keywords to identify valid data rows
    cohort_keywords = [
        "HMO Actives", "HMO Retirees", "Horizon/Aetna PPO Actives", 
        "Horizon/Aetna PPO Retirees", "Employee Freestanding Actives", 
        "Employer Group Waiver Plan", "Employee Freestanding Retirees",
        "Total", "HMO Total", "Horizon/Aetna PPO Total", "Employee Freestanding Total"
    ]
    
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        
        for page in pdf.pages:
            text = page.extract_text()
            
            # 1. Detect Month
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)
            
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Clean None values
                    raw_row = [str(cell) if cell is not None else "" for cell in row]
                    if not raw_row: continue
                    
                    # --- EXPLODE STACKED ROWS ---
                    # Split rows where multiple cohorts are stacked in one cell
                    first_col_lines = raw_row[0].split('\n')
                    num_sub_rows = len(first_col_lines)
                    
                    sub_rows = [[] for _ in range(num_sub_rows)]
                    
                    for cell_text in raw_row:
                        parts = cell_text.split('\n')
                        # Pad cells to match the row height
                        while len(parts) < num_sub_rows:
                            parts.append("")
                        for i in range(num_sub_rows):
                            sub_rows[i].append(parts[i])
                            
                    # --- PROCESS SUB-ROWS ---
                    for clean_row in sub_rows:
                        clean_row = [c.strip() for c in clean_row]
                        row_label = clean_row[0]
                        
                        matched_cohort = next((c for c in cohort_keywords if c in row_label), None)
                        
                        if matched_cohort and current_month:
                            try:
                                # TARGETING FIX:
                                # Scripts is usually Index 1 (2nd column)
                                # Plan Cost is usually Index -1 (Last column)
                                
                                scripts = clean_money(clean_row[1]) if len(clean_row) > 1 else 0.0
                                gross_cost = clean_money(clean_row[-3]) if len(clean_row) >= 3 else 0.0
                                member_cost = clean_money(clean_row[-2]) if len(clean_row) >= 2 else 0.0
                                plan_cost = clean_money(clean_row[-1]) if len(clean_row) >= 1 else 0.0

                                entry = {
                                    "Month": current_month,
                                    "Cohort": matched_cohort,
                                    "Scripts": scripts,
                                    "Gross Cost": gross_cost,
                                    "Member Cost": member_cost,
                                    "Plan Cost": plan_cost
                                }
                                extracted_data.append(entry)
                            except (ValueError, IndexError):
                                continue

    # Create DataFrame
    df = pd.DataFrame(extracted_data)
    
    # --- CRITICAL FIX: FORCE NUMBER TYPES ---
    # This prevents the "String Concatenation" bug
    if not df.empty:
        df['Plan Cost'] = pd.to_numeric(df['Plan Cost'], errors='coerce').fillna(0)
        df['Scripts'] = pd.to_numeric(df['Scripts'], errors='coerce').fillna(0)
        df['Member Cost'] = pd.to_numeric(df['Member Cost'], errors='coerce').fillna(0)
        df['Gross Cost'] = pd.to_numeric(df['Gross Cost'], errors='coerce').fillna(0)

    return df

# --- UI: MAIN AREA ---
st.title("💊 Claims Analysis Dashboard")

uploaded_file = st.file_uploader("Drag & Drop your PDF Report here", type="pdf")

if uploaded_file:
    with st.spinner('Processing stacked data rows...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Extraction Complete!")
        
        # Filter out "Total" rows for charts to avoid double counting
        chart_df = df[~df['Cohort'].str.contains("Total")]
        
        # Metrics
        total_spend = chart_df["Plan Cost"].sum()
        total_scripts = chart_df["Scripts"].sum()
        
        # Top Cost Driver
        cohort_spend = chart_df.groupby("Cohort")["Plan Cost"].sum()
        top_cohort = cohort_spend.idxmax() if not cohort_spend.empty else "N/A"
        
        # Display Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Plan Spend", f"${total_spend:,.2f}")
        m2.metric("Total Scripts", f"{int(total_scripts):,}")
        m3.metric("Top Cost Driver", top_cohort)
        
        # Charts
        tab1, tab2, tab3 = st.tabs(["Spend Trend", "Cohort Breakdown", "Raw Data"])
        
        with tab1:
            st.subheader("Monthly Plan Cost")
            trend_df = chart_df.groupby("Month")["Plan Cost"].sum().reset_index()
            # Simple sorter for months
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            trend_df['SortKey'] = trend_df['Month'].map(month_map)
            trend_df = trend_df.sort_values('SortKey')
            
            st.line_chart(trend_df, x="Month", y="Plan Cost")
            
        with tab2:
            st.subheader("Cost by Cohort")
            st.bar_chart(cohort_spend)
            
        with tab3:
            st.markdown("### Validation Grid")
            st.warning("You can edit values below if needed.")
            edited_df = st.data_editor(df, num_rows="dynamic")

    else:
        st.error("No data found. The PDF format might have changed.")
