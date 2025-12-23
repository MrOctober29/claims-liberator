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
    """Converts '$1,234.56' to float 1234.56"""
    if not value: return 0.0
    # Convert to string, remove $, commas, and newlines
    clean = str(value).replace('$', '').replace(',', '').replace(' ', '').replace('\n', '')
    
    # Handle negative numbers in parentheses e.g., (500) -> -500
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
    
    # The cohorts we want to find
    cohort_keywords = [
        "HMO Actives", "HMO Retirees", "Horizon/Aetna PPO Actives", 
        "Horizon/Aetna PPO Retirees", "Employee Freestanding Actives", 
        "Employer Group Waiver Plan", "Employee Freestanding Retirees"
    ]
    
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        
        for page in pdf.pages:
            text = page.extract_text()
            
            # 1. Detect Month
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)
            
            # 2. Extract Tables with "Text Strategy"
            # This setting tells pdfplumber to look for whitespace to find columns
            # instead of relying on solid lines.
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            })
            
            for table in tables:
                for row in table:
                    # Clean None values
                    raw_row = [str(cell) if cell is not None else "" for cell in row]
                    
                    # Skip empty rows
                    if not raw_row or len(raw_row) < 2: continue
                    
                    # Check first cell for Cohort Name
                    row_label = raw_row[0].replace('\n', ' ') # Flatten stacked text in label
                    
                    # Match Cohort
                    matched_cohort = next((c for c in cohort_keywords if c in row_label), None)
                    
                    if matched_cohort and current_month:
                        try:
                            # --- DYNAMIC COLUMN MAPPING ---
                            # Because whitespace strategies can shift columns, we look for data 
                            # from the END of the row backwards, which is usually safer.
                            
                            # Standard Aon Report usually has ~16-17 columns.
                            # The last column is Total Plan Cost.
                            # The 2nd to last is Total Member Cost.
                            # The 3rd to last is Total Gross Cost.
                            
                            plan_cost = clean_money(raw_row[-1])
                            member_cost = clean_money(raw_row[-2])
                            gross_cost = clean_money(raw_row[-3])
                            
                            # Scripts is trickier. It's usually the first number after the label.
                            # Let's try to find the first valid number in the row after index 0
                            scripts = 0
                            for cell in raw_row[1:5]: # Check columns 1-4
                                val = clean_money(cell)
                                if val > 0:
                                    scripts = val
                                    break
                            
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

    df = pd.DataFrame(extracted_data)
    
    # Final cleanup to ensure numbers are numbers
    if not df.empty:
        df['Plan Cost'] = pd.to_numeric(df['Plan Cost']).fillna(0)
        df['Scripts'] = pd.to_numeric(df['Scripts']).fillna(0)

    return df

# --- UI: MAIN AREA ---
st.title("💊 Claims Analysis Dashboard")
st.caption("Using Whitespace-Detection Strategy")

uploaded_file = st.file_uploader("Drag & Drop your PDF Report here", type="pdf")

if uploaded_file:
    with st.spinner('Parsing PDF...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Extraction Complete!")
        
        # --- METRICS ---
        total_spend = df["Plan Cost"].sum()
        total_scripts = df["Scripts"].sum()
        
        # Top Cost Driver
        cohort_spend = df.groupby("Cohort")["Plan Cost"].sum()
        top_cohort = cohort_spend.idxmax() if not cohort_spend.empty else "N/A"
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Plan Spend", f"${total_spend:,.2f}")
        m2.metric("Total Scripts", f"{int(total_scripts):,}")
        m3.metric("Top Cost Driver", top_cohort)
        
        # --- CHARTS ---
        tab1, tab2, tab3 = st.tabs(["Spend Trend", "Cohort Breakdown", "Raw Data"])
        
        with tab1:
            st.subheader("Monthly Plan Cost")
            # Sort chronologically
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            trend_df = df.groupby("Month")["Plan Cost"].sum().reset_index()
            trend_df['Sort'] = trend_df['Month'].map(month_map)
            trend_df = trend_df.sort_values('Sort')
            st.line_chart(trend_df, x="Month", y="Plan Cost")
            
        with tab2:
            st.bar_chart(cohort_spend)
            
        with tab3:
            st.warning("Verify the extracted numbers below:")
            st.data_editor(df, num_rows="dynamic")

    else:
        st.error("Could not detect data. The PDF layout might be too unusual.")
