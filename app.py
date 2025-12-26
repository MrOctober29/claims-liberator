import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Claims Liberator", layout="wide")

# --- CUSTOM CSS FOR "CREATIVE" UI ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; color: #2c3e50; }
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #e9ecef; }
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

# --- BACKEND ENGINE (v1.4 Logic) ---
@st.cache_data
def parse_pdf(uploaded_file):
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
            
            # Text strategy is crucial for separation
            tables = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 4})
            
            # Find the "TOTAL" table (usually last)
            target_table = None
            for table in reversed(tables):
                if "hmo actives" in str(table).lower(): 
                    target_table = table
                    break
            
            if not target_table: continue

            for row in target_table:
                raw_row = [str(cell) if cell is not None else "" for cell in row]
                if not raw_row: continue
                
                # Explode Logic for Stacked Rows
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

# --- NEW CREATIVE UI ---
st.title("💊 Claims Liberator")
st.markdown("##### Turn dense PDF reports into interactive insights.")

uploaded_file = st.file_uploader("", type="pdf", label_visibility="collapsed")

if uploaded_file:
    with st.spinner('Parsing PDF...'):
        df = parse_pdf(uploaded_file)
    
    if not df.empty:
        # 1. DATA PREP
        month_map = {"April 2023": 4, "May 2023": 5, "June 2023": 6, "July 2023": 7, "August 2023": 8}
        df['Sort'] = df['Month'].map(month_map)
        df = df.sort_values('Sort')
        
        # 2. TOP LEVEL METRICS
        total_spend = df["Plan Cost"].sum()
        avg_monthly = total_spend / df["Month"].nunique()
        top_cohort_name = df.groupby("Cohort")["Plan Cost"].sum().idxmax()
        
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Spend (Period)", f"${total_spend:,.0f}", help="Sum of Plan Cost from all tables")
        col2.metric("Avg. Monthly Spend", f"${avg_monthly:,.0f}", help="Total Spend / Count of Months")
        col3.metric("Top Cost Driver", top_cohort_name)
        st.markdown("---")

        # 3. INTERACTIVE BAR CHARTS
        
        # CHART A: Monthly Spend (Stacked)
        st.subheader("📊 Spend Composition by Month")
        st.caption("Hover over the bars to see the exact split between cohorts.")
        
        fig_monthly = px.bar(
            df, 
            x="Month", 
            y="Plan Cost", 
            color="Cohort", 
            title="Monthly Trend",
            text_auto='.2s', # Shows compact numbers (e.g. 200k) on bars
            color_discrete_sequence=px.colors.qualitative.Prism # Nice professional colors
        )
        # Clean up the chart look
        fig_monthly.update_layout(xaxis_title="", yaxis_title="Plan Cost ($)", legend_title="")
        st.plotly_chart(fig_monthly, use_container_width=True)
        
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            # CHART B: Cohort Leaderboard (Horizontal)
            st.subheader("🏆 Cost by Cohort")
            cohort_df = df.groupby("Cohort")["Plan Cost"].sum().reset_index().sort_values("Plan Cost", ascending=True)
            
            fig_cohort = px.bar(
                cohort_df, 
                x="Plan Cost", 
                y="Cohort", 
                orientation='h', # Horizontal bars are easier to read for long names
                text_auto='.2s',
                color="Plan Cost",
                color_continuous_scale="Blues"
            )
            fig_cohort.update_layout(xaxis_title="Total Spend ($)", yaxis_title="", coloraxis_showscale=False)
            st.plotly_chart(fig_cohort, use_container_width=True)

        with col_right:
            # CHART C: Script Volume
            st.subheader("💊 Script Volume")
            script_df = df.groupby("Month")["Scripts"].sum().reset_index()
            
            fig_scripts = px.bar(
                script_df,
                x="Month",
                y="Scripts",
                text_auto=True,
                color_discrete_sequence=["#FF4B4B"] # Streamlit Red for contrast
            )
            fig_scripts.update_layout(xaxis_title="", yaxis_title="Total Scripts")
            st.plotly_chart(fig_scripts, use_container_width=True)

        # 4. DATA EXPLORER
        with st.expander("🔍 Drill Down into Raw Data"):
            st.info("Select specific cohorts to filter the data grid.")
            selected_cohorts = st.multiselect("Filter by Cohort", df["Cohort"].unique(), default=df["Cohort"].unique())
            filtered_df = df[df["Cohort"].isin(selected_cohorts)]
            st.dataframe(filtered_df, use_container_width=True)
            
    else:
        st.error("No data extracted. Please check the PDF format.")
elif not uploaded_file:
    # Empty state placeholder
    st.info("👆 Upload your 'Old Bridge' PDF to see the magic happen.")
