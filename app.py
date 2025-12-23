import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Claims Liberator", layout="wide")

# --- HELPER FUNCTIONS ---
def clean_money_value(val_str):
    """
    Parses money strings. 
    Crucial: splits by newline first to avoid the '0\n345' -> '0345' concatenation bug.
    """
    if not val_str: return 0.0
    # If a cell somehow still has newlines, take the last value (usually the total or plan cost)
    # or the first valid one. But our main logic should handle splitting before this.
    if '\n' in str(val_str):
        val_str = str(val_str).split('\n')[-1]
        
    clean = str(val_str).replace('$', '').replace(',', '').replace(' ', '')
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
    
    # Accurate keywords based on Screenshot 3
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
            
            # 1. Detect Month
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)
            
            # 2. Extract Tables (Text Strategy is VITAL for columns)
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 4,
            })
            
            # 3. Strategy: Find the "TOTAL" table. 
            # In the PDF structure (Screenshot 3), there are 3 tables: Mail, Retail, Total.
            # We want the LAST valid table that contains data.
            
            target_table = None
            
            # Look backwards from the last table
            for table in reversed(tables):
                # Check if this table looks like the summary table
                # It usually has "Total" in the header or high rows
                content_str = str(table).lower()
                if "hmo actives" in content_str: 
                    target_table = table
                    break
            
            if not target_table: continue

            # 4. Parse the Target Table
            for row in target_table:
                # Basic cleanup
                raw_row = [str(cell) if cell is not None else "" for cell in row]
                if not raw_row: continue
                
                # --- EXPLODE LOGIC (Fixes "Understated" / Missing Stacked Rows) ---
                # "Horizon PPO Actives" and "Retirees" are often in the same cell, separated by \n.
                # We split the first column (Label) to see how many lines we have.
                
                label_col = raw_row[0]
                lines_in_row = label_col.count('\n') + 1
                
                # We iterate through each "virtual line" inside this physical row
                for i in range(lines_in_row):
                    try:
                        # 1. Get the Label for this line
                        label_parts = label_col.split('\n')
                        if i >= len(label_parts): continue
                        current_label = label_parts[i].strip()
                        
                        # Fuzzy match check
                        matched_cohort = next((c for c in cohort_keywords if c in current_label or current_label in c), None)
                        
                        # Specific fix for "Horizon / Aetna PPO" splitting weirdly
                        if not matched_cohort and "Retirees" in current_label and "PPO" in label_col:
                            matched_cohort = "Horizon / Aetna PPO Retirees"
                        if not matched_cohort and "Actives" in current_label and "PPO" in label_col:
                            matched_cohort = "Horizon / Aetna PPO Actives"

                        if matched_cohort and current_month:
                            # 2. Extract Values for this specific line `i`
                            # We need to grab the i-th segment of the number cells too.
                            
                            def get_val(col_idx, line_idx):
                                if col_idx >= len(raw_row): return "0"
                                cell_val = raw_row[col_idx]
                                parts = cell_val.split('\n')
                                # If the number column has fewer lines than the label column,
                                # it often means the numbers are aligned to the bottom or top.
                                # We try to match index, otherwise grab the nearest.
                                if line_idx < len(parts):
                                    return parts[line_idx]
                                return "0"

                            # COLUMN MAPPING (Based on "TOTAL" table in Screenshot 3)
                            # The table has 3 sections: Brand, Generic, Total.
                            # We want the LAST section (Total).
                            # Structure: [Labels] ... [Brand Cols] ... [Generic Cols] ... [Total Scripts] [Total Gross] [Total Mem] [Total Plan]
                            
                            # We reliably grab from the END of the list:
                            # -1: Total Plan Cost
                            # -2: Total Member Cost
                            # -3: Total Gross Cost
                            # -4: Total Scripts
                            
                            plan_cost = clean_money_value(get_val(-1, i))
                            member_cost = clean_money_value(get_val(-2, i))
                            gross_cost = clean_money_value(get_val(-3, i))
                            scripts = clean_money_value(get_val(-4, i))
                            
                            # Sanity filter: If we grabbed a header row by accident (Cost is 0, Scripts is 0)
                            # we might want to skip, but legitimate 0s exist. 
                            # The keyword match is our primary filter.

                            entry = {
                                "Month": current_month,
                                "Cohort": matched_cohort,
                                "Scripts": scripts,
                                "Gross Cost": gross_cost,
                                "Member Cost": member_cost,
                                "Plan Cost": plan_cost
                            }
                            extracted_data.append(entry)
                    except Exception:
                        continue

    df = pd.DataFrame(extracted_data)
    return df

# --- UI ---
st.title("Claims Liberator v1.4")
st.caption("Targeting 'TOTAL' Table & Exploding Stacked Rows")

uploaded_file = st.file_uploader("Drag & Drop PDF", type="pdf")

if uploaded_file:
    with st.spinner('Analyzing Tables...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        # Sort Months
        month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
        df['Sort'] = df['Month'].map(month_map)
        df = df.sort_values('Sort')

        # Totals
        total_spend = df["Plan Cost"].sum()
        total_scripts = df["Scripts"].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Total Plan Spend", f"${total_spend:,.2f}")
        c2.metric("Total Scripts", f"{int(total_scripts):,}")
        
        # Tabs
        tab1, tab2 = st.tabs(["Analysis", "Validation Grid"])
        
        with tab1:
            st.subheader("Monthly Plan Cost")
            st.line_chart(df, x="Month", y="Plan Cost")
            
            st.subheader("Cost by Cohort")
            st.bar_chart(df.groupby("Cohort")["Plan Cost"].sum())
            
        with tab2:
            st.write("Data extracted from the 'TOTAL' summary table of each month.")
            st.data_editor(df, num_rows="dynamic")
    else:
        st.error("No data found.")
