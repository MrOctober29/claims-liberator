import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re
import urllib.parse
import numpy as np

# --- CONFIGURATION ---
st.set_page_config(page_title="Network Disruption & Analytics", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    .metric-box {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
    }
    .big-stat { font-size: 28px; font-weight: 700; color: #ffffff; }
    .stat-label { font-size: 12px; color: #a0a0a0; text-transform: uppercase; letter-spacing: 1px; }
    [data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
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
    
    # 1. Census Detection (Excel/CSV)
    if filename.endswith('.xlsx') or filename.endswith('.csv'): 
        # We assume Excel/CSV uploads are Census files for now
        return 'CENSUS'
    
    # 2. PDF Detection (GeoAccess vs Rx)
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            if not pdf.pages: return 'UNKNOWN'
            text = pdf.pages[0].extract_text() or ""
            
            # GeoAccess Keywords
            if "GeoAccess" in text or "Accessibility Analysis" in text or "Distance to" in text:
                return 'GEO'
            
            # Rx Keywords
            if "Ingredient Cost" in text or "Plan Cost" in text:
                return 'RX'
    except: return 'UNKNOWN'
    return 'UNKNOWN'

# --- ENGINE 1: CENSUS PARSER ---
@st.cache_data
def run_census_parser(uploaded_file):
    """
    Parses a raw Census file (Excel/CSV).
    Auto-detects: Zip Code, Gender, DOB/Age.
    """
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        return pd.DataFrame(), str(e)

    # Standardize Columns (Fuzzy Match)
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Logic to find key columns
    zip_col = next((c for c in df.columns if 'zip' in c or 'postal' in c), None)
    gender_col = next((c for c in df.columns if 'gender' in c or 'sex' in c), None)
    age_col = next((c for c in df.columns if 'age' in c), None)
    dob_col = next((c for c in df.columns if 'dob' in c or 'birth' in c), None)

    if not zip_col:
        return pd.DataFrame(), "Could not find a 'Zip Code' column."

    # Process Data
    processed_df = pd.DataFrame()
    processed_df['Zip'] = df[zip_col].astype(str).str[:5] # Clean Zips
    
    if gender_col: processed_df['Gender'] = df[gender_col]
    else: processed_df['Gender'] = 'Unknown'
    
    if age_col: 
        processed_df['Age'] = pd.to_numeric(df[age_col], errors='coerce')
    elif dob_col:
        # Simple Age Calc (Current Year - Year of Birth)
        df[dob_col] = pd.to_datetime(df[dob_col], errors='coerce')
        processed_df['Age'] = 2026 - df[dob_col].dt.year
    else:
        processed_df['Age'] = 0

    return processed_df, None

# --- ENGINE 2: GEOACCESS PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    """
    Scrapes a GeoAccess PDF for summary tables.
    Looking for rows like: "Primary Care | 2 in 10 miles | 98.5%"
    """
    extracted_data = []
    # Common specialties in Geo reports
    specialties = ["Primary Care", "PCP", "Pediatrics", "OB/GYN", "Specialists", "Hospital", "Pharmacy", "Behavioral Health"]
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Clean Row
                    clean_row = [str(x).replace('\n', ' ').strip() for x in row if x]
                    row_text = " ".join(clean_row)
                    
                    # Logic: Look for specialty names and percentages in the same row
                    matched_specialty = next((s for s in specialties if s.lower() in row_text.lower()), None)
                    
                    # Regex to find percentages (e.g., 98.2%, 100%)
                    percent_match = re.search(r'(\d{1,3}\.?\d?)%', row_text)
                    
                    if matched_specialty and percent_match:
                        # Logic to find the "Standard" (e.g., "2 in 10")
                        # This is a heuristic guess based on common formats
                        standard = "Standard Match"
                        if "10 mile" in row_text: standard = "10 Miles"
                        elif "15 mile" in row_text: standard = "15 Miles"
                        elif "20 mile" in row_text: standard = "20 Miles"
                        
                        extracted_data.append({
                            "Specialty": matched_specialty,
                            "Access %": float(percent_match.group(1)),
                            "Standard": standard
                        })
    
    # Remove duplicates if any
    df = pd.DataFrame(extracted_data).drop_duplicates()
    return df

# --- ENGINE 3: RX PARSER (Legacy Support) ---
@st.cache_data
def run_rx_parser(uploaded_file):
    # (Kept identical to previous version for backwards compatibility)
    extracted_data = []
    cohort_keywords = ["HMO Actives", "HMO Retirees", "PPO Actives", "PPO Retirees", "Employer Group Waiver Plan"]
    with pdfplumber.open(uploaded_file) as pdf:
        current_month = None
        for page in pdf.pages:
            text = page.extract_text()
            month_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{4}', text)
            if month_match: current_month = month_match.group(0)
            tables = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 4})
            target_table = None
            for table in reversed(tables):
                if "hmo actives" in str(table).lower(): target_table = table; break
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
                        if matched_cohort and current_month:
                            extracted_data.append({
                                "Month": current_month, 
                                "Cohort": matched_cohort, 
                                "Plan Cost": clean_money_value(raw_row[-1].split('\n')[i] if i < len(raw_row[-1].split('\n')) else "0")
                            })
                    except: continue
    return pd.DataFrame(extracted_data)

# --- SIDEBAR ---
st.sidebar.header("🔧 Settings")
parsing_mode = st.sidebar.selectbox("File Parser", ["Auto-Detect", "Census Engine", "GeoAccess Engine", "Rx Engine"])

# --- MAIN UI ---
st.title("🛡️ Network Disruption & Analytics")
st.markdown("##### Transform raw Census & GeoAccess reports into actionable strategy.")

uploaded_file = st.file_uploader("Upload Report (Excel Census or PDF GeoAccess)", type=["pdf", "xlsx", "csv"])

if uploaded_file:
    # 1. DETERMINE TYPE
    doc_type = 'UNKNOWN'
    if parsing_mode == "Auto-Detect":
        doc_type = detect_document_type(uploaded_file)
    elif parsing_mode == "Census Engine": doc_type = 'CENSUS'
    elif parsing_mode == "GeoAccess Engine": doc_type = 'GEO'
    elif parsing_mode == "Rx Engine": doc_type = 'RX'

    # --- CENSUS DASHBOARD ---
    if doc_type == 'CENSUS':
        st.success("👥 Processing Member Census...")
        df, error = run_census_parser(uploaded_file)
        
        if not df.empty:
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"""<div class="metric-box"><div class="big-stat">{len(df):,}</div><div class="stat-label">Total Lives</div></div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="metric-box"><div class="big-stat">{df['Age'].mean():.1f}</div><div class="stat-label">Avg Age</div></div>""", unsafe_allow_html=True)
            c3.markdown(f"""<div class="metric-box"><div class="big-stat">{df['Zip'].nunique():,}</div><div class="stat-label">Unique Zips</div></div>""", unsafe_allow_html=True)
            
            st.subheader("📍 Member Concentration Map")
            st.caption("Heatmap based on Member Zip Codes.")
            
            # Simple aggregation for mapping
            zip_counts = df['Zip'].value_counts().reset_index()
            zip_counts.columns = ['Zip', 'Count']
            
            # We use a Scatter Mapbox (Requires Zip Lat/Lon database for real precision, 
            # but for this MVP we create a mock visualization structure)
            st.warning("ℹ️ Note: Precise Lat/Lon geocoding requires a Zip Code Database integration. Showing distribution by count.")
            
            fig = px.bar(zip_counts.head(15), x='Zip', y='Count', title="Top 15 Zip Codes by Enrollment", color='Count')
            st.plotly_chart(fig, use_container_width=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Demographics: Age Band")
                fig_age = px.histogram(df[df['Age']>0], x="Age", nbins=10, title="Age Distribution", color_discrete_sequence=['#3498db'])
                st.plotly_chart(fig_age, use_container_width=True)
            with col2:
                st.subheader("Demographics: Gender")
                fig_gen = px.pie(df, names='Gender', title="Gender Split", hole=0.4)
                st.plotly_chart(fig_gen, use_container_width=True)
                
        else:
            st.error(f"Census parsing failed: {error}")

    # --- GEOACCESS DASHBOARD ---
    elif doc_type == 'GEO':
        st.success("🌍 Processing GeoAccess Report...")
        df = run_geo_parser(uploaded_file)
        
        if not df.empty:
            # Calculate 'Disruption' (Inverse of Access)
            df['Disruption %'] = 100 - df['Access %']
            
            c1, c2 = st.columns(2)
            avg_access = df['Access %'].mean()
            c1.markdown(f"""<div class="metric-box"><div class="big-stat">{avg_access:.1f}%</div><div class="stat-label">Avg Network Match</div></div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="metric-box"><div class="big-stat">{len(df)}</div><div class="stat-label">Specialties Analyzed</div></div>""", unsafe_allow_html=True)
            
            st.subheader("📉 Network Gaps & Disruption")
            st.caption("Identifying specialties falling below 100% access.")
            
            # Highlight bars that are NOT 100%
            fig = px.bar(df, x="Specialty", y="Access %", color="Disruption %", 
                         title="Access Percentage by Specialty",
                         range_y=[50, 105],
                         color_continuous_scale="RdYlGn_r") # Red = High Disruption
            
            # Add a line for the target (e.g., 90%)
            fig.add_hline(y=90, line_dash="dot", annotation_text="Minimum Standard (90%)", annotation_position="bottom right")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Disruption Summary Table")
            st.dataframe(df.style.format({"Access %": "{:.1f}%", "Disruption %": "{:.1f}%"}), use_container_width=True)
        else:
            st.error("No GeoAccess tables found. Ensure the PDF contains standard tables like 'Primary Care | 98%'.")

    # --- RX DASHBOARD (Legacy) ---
    elif doc_type == 'RX':
        st.success("💊 Processing Rx Claims...")
        df = run_rx_parser(uploaded_file)
        if not df.empty:
            total_spend = df["Plan Cost"].sum()
            st.markdown(f"""<div class="metric-box"><div class="big-stat">${total_spend:,.0f}</div><div class="stat-label">Total Rx Spend</div></div>""", unsafe_allow_html=True)
            fig = px.bar(df, x="Month", y="Plan Cost", color="Cohort", title="Rx Trend Analysis")
            st.plotly_chart(fig, use_container_width=True)
    
    else:
        st.info("👋 Welcome to the Network Analytics Suite.")
        st.markdown("""
            **Upload a file to begin:**
            * **Member Census (Excel/CSV):** Analyzes demographics and location density.
            * **GeoAccess Report (PDF):** Visualizes network gaps and accessibility percentages.
        """)
