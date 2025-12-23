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

# --- BACKEND ENGINE (The Extraction Logic) ---
@st.cache_data
def parse_pdf(uploaded_file):
    extracted_data = []
    cohort_keywords = [
        "HMO Actives", "HMO Retirees", "Horizon/Aetna PPO Actives", 
        "Horizon/Aetna PPO Retirees", "Employee Freestanding Actives", 
        "Employer Group Waiver Plan"
    ]
    
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        for page in pdf.pages:
            text = page.extract_text()
            
            # Detect Month (e.g., "April 2023")
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match:
                current_month = month_match.group(0)

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    clean_row = [str(x).replace('\n', ' ').strip() if x else '' for x in row]
                    if not clean_row: continue
                    
                    row_label = clean_row[0]
                    matched_cohort = next((c for c in cohort_keywords if c in row_label), None)
                    
                    # Logic specifically for the Old Bridge PDF structure
                    if matched_cohort and current_month:
                        try:
                            # We grab the last few columns which consistently hold the Totals in this PDF format
                            # Note: In a production app, we would make column detection more dynamic
                            entry = {
                                "Month": current_month,
                                "Cohort": matched_cohort,
                                "Scripts": clean_row[-3],      # 3rd from last
                                "Gross Cost": clean_row[-2],   # 2nd from last
                                "Plan Cost": clean_row[-1]     # Last column
                            }
                            extracted_data.append(entry)
                        except IndexError:
                            continue
                            
    df = pd.DataFrame(extracted_data)
    
    # Cleaning: Remove $ and ,
    cols_to_clean = ["Scripts", "Gross Cost", "Plan Cost"]
    for col in cols_to_clean:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.replace('(', '-', regex=False).str.replace(')', '', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    return df

# --- UI: SIDEBAR ---
with st.sidebar:
    st.header("Claims Liberator v1.0")
    st.info("Upload a Monthly Experience Report PDF to begin.")
    st.markdown("---")
    st.caption("Proof of Concept for: Old Bridge Twp")

# --- UI: MAIN AREA ---
st.title("💊 Claims Analysis Dashboard")

# 1. THE DROP ZONE
uploaded_file = st.file_uploader("Drag & Drop your PDF Report here", type="pdf")

if uploaded_file:
    # 2. PROCESSING
    with st.spinner('Parsing PDF structure... extracting tables...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Extraction Complete!")
        
        # 3. THE SANITY CHECK (Validation Mode)
        with st.expander("🔍 Sanity Check (Validate Data)", expanded=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("### Source Validation")
                st.write("Review the extracted numbers against your PDF.")
                st.warning("⚠️ If you see a discrepancy, you can edit the values in the grid directly.")
            with col2:
                # Interactive Data Editor - User can fix numbers here!
                edited_df = st.data_editor(df, num_rows="dynamic")
        
        # 4. THE PAYOFF (Visualization)
        st.divider()
        st.subheader("📈 Monthly Cost Analysis")
        
        # Metrics Row
        total_spend = edited_df["Plan Cost"].sum()
        total_scripts = edited_df["Scripts"].sum()
        top_cohort = edited_df.groupby("Cohort")["Plan Cost"].sum().idxmax()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Plan Spend", f"${total_spend:,.2f}")
        m2.metric("Total Scripts", f"{int(total_scripts):,}")
        m3.metric("Highest Cost Cohort", top_cohort)
        
        # Charts
        tab1, tab2 = st.tabs(["Spend Trend", "Cohort Breakdown"])
        
        with tab1:
            # Aggregate by Month
            trend_data = edited_df.groupby("Month")["Plan Cost"].sum().reset_index()
            # Sort months chronologically (simple logic for POC)
            months_order = ["April 2023", "May 2023", "June 2023", "July 2023", "August 2023"]
            trend_data["Month"] = pd.Categorical(trend_data["Month"], categories=months_order, ordered=True)
            trend_data = trend_data.sort_values("Month")
            
            st.line_chart(trend_data, x="Month", y="Plan Cost")
            
        with tab2:
            # Aggregate by Cohort
            cohort_data = edited_df.groupby("Cohort")["Plan Cost"].sum()
            st.bar_chart(cohort_data)

    else:
        st.error("Could not find recognizable data tables. Please check the PDF format.")
