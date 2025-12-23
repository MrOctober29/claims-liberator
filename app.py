import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Claims Liberator", layout="wide")

# --- HELPER FUNCTIONS ---
def clean_money_value(val_str):
    """
    Takes a single string like '$1,234.56' or '(500)' and makes it a float.
    Returns 0.0 if empty or invalid.
    """
    if not val_str: return 0.0
    # Remove common currency junk
    clean = str(val_str).replace('$', '').replace(',', '').replace(' ', '')
    # Handle accounting negatives: (500) -> -500
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
    
    # Target Cohorts
    cohort_keywords = [
        "HMO Actives", "HMO Retirees", "Horizon/Aetna PPO Actives", 
        "Horizon/Aetna PPO Retirees", "Employee Freestanding Actives", 
        "Employee Freestanding Retirees", "Employer Group Waiver Plan"
    ]
    
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        
        for page in pdf.pages:
            text = page.extract_text()
            
            # 1. Detect Month
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)
            
            # 2. Extract Tables
            # We go back to "lines" strategy (default) because it handles the grid better,
            # but we will manually fix the stacked text inside the loop.
            tables = page.extract_tables()
            
            for table in tables:
                for row in table:
                    # Basic cleanup: None -> ""
                    raw_row = [str(cell) if cell is not None else "" for cell in row]
                    if not raw_row: continue
                    
                    # --- THE HYBRID FIX: EXPLODE BY NEWLINE ---
                    # Check the first column (Cohort Name). Does it have a newline?
                    # Example: "Horizon PPO\nFreestanding Actives"
                    first_cell = raw_row[0]
                    num_lines = first_cell.count('\n') + 1
                    
                    # We will create 'num_lines' separate entries from this one row
                    for i in range(num_lines):
                        try:
                            # 1. Get the Cohort Name for this specific line
                            # We split the cell and take the i-th part
                            cohort_cell_parts = first_cell.split('\n')
                            if i >= len(cohort_cell_parts): continue
                            
                            row_label = cohort_cell_parts[i].strip()
                            
                            # check if valid cohort
                            matched_cohort = next((c for c in cohort_keywords if c in row_label), None)
                            
                            if matched_cohort and current_month:
                                # 2. Extract the numbers for THIS specific line
                                # We iterate through the columns we care about (Cost, Scripts)
                                # and split them by newline too, taking the matching i-th part.
                                
                                # Helper to grab i-th value from a column
                                def get_part(col_index, part_index):
                                    if col_index >= len(raw_row): return "0"
                                    val_parts = raw_row[col_index].split('\n')
                                    # If the column has fewer lines than the cohort column, 
                                    # it usually means it's a single value meant for the whole row 
                                    # OR empty spacing. For safety, we take index if exists, else 0.
                                    if part_index < len(val_parts):
                                        return val_parts[part_index]
                                    return "0"

                                # Target Columns (Aon Standard): 
                                # Last = Plan Cost
                                # 2nd to Last = Member Cost
                                # 3rd to Last = Gross Cost
                                # Scripts is tricky, usually column 1
                                
                                plan_cost_str = get_part(-1, i)
                                member_cost_str = get_part(-2, i)
                                gross_cost_str = get_part(-3, i)
                                scripts_str = get_part(1, i) 

                                entry = {
                                    "Month": current_month,
                                    "Cohort": matched_cohort,
                                    "Scripts": clean_money_value(scripts_str),
                                    "Gross Cost": clean_money_value(gross_cost_str),
                                    "Member Cost": clean_money_value(member_cost_str),
                                    "Plan Cost": clean_money_value(plan_cost_str)
                                }
                                extracted_data.append(entry)
                        
                        except Exception:
                            # If a specific split fails, skip just that sub-row
                            continue

    df = pd.DataFrame(extracted_data)
    
    # Aggregation: Since we might scrape "Retail" and "Mail" separately,
    # we must SUM them up to get the true monthly total.
    if not df.empty:
        df = df.groupby(["Month", "Cohort"], as_index=False).sum()

    return df

# --- UI ---
st.title("Claims Liberator v1.3")
st.caption("Logic: Split Stacked Rows + Aggregate Retail/Mail")

uploaded_file = st.file_uploader("Drag & Drop PDF", type="pdf")

if uploaded_file:
    with st.spinner('Extracting & Aggregating...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Success!")
        
        # Totals
        total_spend = df["Plan Cost"].sum()
        total_scripts = df["Scripts"].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Total Plan Spend (Check vs PDF)", f"${total_spend:,.2f}")
        c2.metric("Total Scripts", f"{int(total_scripts):,}")
        
        # Tabs
        tab1, tab2 = st.tabs(["Analysis", "Raw Data Check"])
        
        with tab1:
            # Sort Months
            month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
            df['Sort'] = df['Month'].map(month_map)
            df = df.sort_values('Sort')
            
            st.line_chart(df, x="Month", y="Plan Cost")
            st.bar_chart(df.groupby("Cohort")["Plan Cost"].sum())
            
        with tab2:
            st.write("This table shows the SUM of Retail + Mail for each cohort.")
            st.data_editor(df, num_rows="dynamic")
    else:
        st.error("No data found.")
