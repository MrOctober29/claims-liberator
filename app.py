import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Claims Liberator", layout="wide")

# Custom CSS to make the metrics pop
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
    """Converts '$1,234.56' or '1,234' to a float."""
    if not value: return 0.0
    # Remove $, commas, and parentheses for negatives
    clean = str(value).replace('$', '').replace(',', '').replace(' ', '')
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
    
    # These keywords help us identify which rows matter
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
            
            # 1. Detect Month (e.g., "April 2023")
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)
            
            # 2. Extract Tables
            tables = page.extract_tables()
            
            for table in tables:
                for row in table:
                    # Clean None values to empty strings
                    raw_row = [str(cell) if cell is not None else "" for cell in row]
                    
                    if not raw_row: continue
                    
                    # --- THE FIX: EXPLODE STACKED ROWS ---
                    # Sometimes one row contains multiple lines separated by \n
                    # We split the first column to see how many "sub-rows" exist.
                    first_col_lines = raw_row[0].split('\n')
                    num_sub_rows = len(first_col_lines)
                    
                    # Create empty sub-rows
                    sub_rows = [[] for _ in range(num_sub_rows)]
                    
                    # Distribute the data from each cell into the sub-rows
                    for cell_text in raw_row:
                        # Split this cell by newline
                        parts = cell_text.split('\n')
                        
                        # Pad with empty strings if this cell has fewer lines than the first column
                        # (Common in empty number columns)
                        while len(parts) < num_sub_rows:
                            parts.append("")
                        
                        # Assign parts to their respective sub-row
                        for i in range(num_sub_rows):
                            sub_rows[i].append(parts[i])
                            
                    # --- PROCESS EACH EXPLODED ROW ---
                    for clean_row in sub_rows:
                        # Clean up whitespace
                        clean_row = [c.strip() for c in clean_row]
                        row_label = clean_row[0]
                        
                        # Check if this is a row we want
                        matched_cohort = next((c for c in cohort_keywords if c in row_label), None)
                        
                        if matched_cohort and current_month:
                            try:
                                # We target the LAST 3 columns for the "Total" section stats.
                                # Structure: ... | Total Scripts | Gross Cost | Member Cost | Plan Cost |
                                # Note: Sometimes columns merge. We look for the last valid numbers.
                                
                                # Safety: ensure we have enough columns
                                if len(clean_row) < 4: continue

                                plan_cost = clean_money(clean_row[-1])
                                member_cost = clean_money(clean_row[-2])
                                gross_cost = clean_money(clean_row[-3])
                                
                                # Scripts is often the 4th from last, or 3rd from last if Member/Gross merged.
                                # For this specific report, let's grab the column preceding the costs
                                scripts = clean_money(clean_row[-4]) if len(clean_row) > 4 else 0

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
    return df

# --- UI: SIDEBAR ---
with st.sidebar:
    st.header("Claims Liberator v1.1")
    st.info("Upload a Monthly Experience Report PDF to begin.")
    st.markdown("---")
    st.caption("Proof of Concept for: Old Bridge Twp")

# --- UI: MAIN AREA ---
st.title("💊 Claims Analysis Dashboard")

uploaded_file = st.file_uploader("Drag & Drop your PDF Report here", type="pdf")

if uploaded_file:
    with st.spinner('Processing stacked data rows...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Extraction Complete!")
        
        # Filter out "Total" rows for the charts (to avoid double counting)
        chart_df = df[~df['Cohort'].str.contains("Total")]
        
        # --- METRICS ---
        total_spend = chart_df["Plan Cost"].sum()
        total_scripts = chart_df["Scripts"].sum()
        
        # Find top cost driver
        cohort_spend = chart_df.groupby("Cohort")["Plan Cost"].sum()
        top_cohort = cohort_spend.idxmax() if not cohort_spend.empty else "N/A"
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Plan Spend", f"${total_spend:,.2f}")
        m2.metric("Total Scripts", f"{int(total_scripts):,}")
        m3.metric("Top Cost Driver", top_cohort)
        
        # --- TABS ---
        tab1, tab2, tab3 = st.tabs(["Spend Trend", "Cohort Breakdown", "Raw Data"])
        
        with tab1:
            st.subheader("Monthly Plan Cost")
            # Sort by month logic
            month_order = ["April 2023", "May 2023", "June 2023", "July 2023", "August 2023"]
            trend_df = chart_df.groupby("Month")["Plan Cost"].sum().reindex(month_order).reset_index()
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
