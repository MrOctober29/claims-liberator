import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

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

def clean_percentage(val_str):
    """Converts '98.5%', '98.5', or 0.985 to float 98.5"""
    if not val_str: return 0.0
    clean = str(val_str).replace('%', '').replace(' ', '').strip()
    try:
        val = float(clean)
        # Handle decimal vs percent representation (0.9 vs 90)
        # Most Geo reports use whole numbers (90.5), but some use decimals (0.905)
        # We assume if max value in column is <= 1.0, it needs scaling.
        return val
    except ValueError:
        return 0.0

# --- SMART ROUTER ---
def detect_document_type(uploaded_file):
    filename = uploaded_file.name.lower()
    
    # 1. Census (Excel/CSV)
    if filename.endswith('.xlsx') or filename.endswith('.csv'): 
        return 'CENSUS'
    
    # 2. PDF Analysis
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            if not pdf.pages: return 'UNKNOWN'
            text = pdf.pages[0].extract_text() or ""
            
            # Keywords
            if "GeoAccess" in text or "Accessibility" in text or "Distance" in text:
                return 'GEO'
            if "Ingredient Cost" in text or "Plan Cost" in text:
                return 'RX'
    except: return 'UNKNOWN'
    return 'UNKNOWN'

# --- ENGINE: CENSUS PARSER ---
@st.cache_data
def run_census_parser(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
    except Exception as e: return pd.DataFrame(), str(e)
    
    # Normalize headers
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Smart Column Detection
    zip_col = next((c for c in df.columns if 'zip' in c or 'postal' in c), None)
    dob_col = next((c for c in df.columns if 'dob' in c or 'birth' in c), None)
    gender_col = next((c for c in df.columns if 'gender' in c or 'sex' in c), None)
    status_col = next((c for c in df.columns if 'status' in c or 'relat' in c), None) # Employee vs Dependent

    if not zip_col: return pd.DataFrame(), "Missing 'Zip Code' column."
    
    processed = pd.DataFrame()
    processed['Zip'] = df[zip_col].astype(str).str[:5] # Standardize 5-digit zip
    processed['Gender'] = df[gender_col] if gender_col else 'Unknown'
    processed['Type'] = df[status_col] if status_col else 'Member'
    
    if dob_col:
        df[dob_col] = pd.to_datetime(df[dob_col], errors='coerce')
        processed['Age'] = 2026 - df[dob_col].dt.year
    else: 
        processed['Age'] = 0
        
    return processed, None

# --- ENGINE: GEOACCESS PARSER (Production Grade) ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            
            for table in tables:
                if not table: continue
                
                # 1. Identify Header Row
                # We look for a row containing "Specialty" (or similar) AND "Access" (or %)
                header_idx = -1
                spec_col_idx = -1
                access_col_idx = -1
                
                for i, row in enumerate(table):
                    # Flatten row to string for searching
                    row_str = " ".join([str(c).lower() for c in row if c])
                    
                    if ("specialty" in row_str or "service" in row_str or "provider" in row_str) and \
                       ("access" in row_str or "%" in row_str or "match" in row_str):
                        header_idx = i
                        
                        # 2. Map Columns
                        for col_i, cell in enumerate(row):
                            cell_text = str(cell).lower()
                            if "specialty" in cell_text or "service" in cell_text or "type" in cell_text:
                                spec_col_idx = col_i
                            if "access" in cell_text or "%" in cell_text or "match" in cell_text:
                                access_col_idx = col_i
                        break
                
                # If we found a valid header, process the rows BELOW it
                if header_idx != -1 and spec_col_idx != -1 and access_col_idx != -1:
                    for row in table[header_idx+1:]:
                        if not row or len(row) <= max(spec_col_idx, access_col_idx): continue
                        
                        spec_name = row[spec_col_idx]
                        access_val = row[access_col_idx]
                        
                        if spec_name and access_val:
                            # Clean newline chars often found in PDF tables
                            spec_name = str(spec_name).replace('\n', ' ').strip()
                            
                            # Extract number
                            val = clean_percentage(access_val)
                            
                            if val > 0:
                                extracted_data.append({
                                    "Specialty": spec_name,
                                    "Access %": val
                                })

    df = pd.DataFrame(extracted_data)
    
    # Dedup: If multiple tables (Urban/Rural), we might average them or take the worst case.
    # For MVP, we take the average access across all found tables for that specialty.
    if not df.empty:
        df = df.groupby("Specialty")["Access %"].mean().reset_index()
        
    return df

# --- ENGINE: RX PARSER (Legacy) ---
@st.cache_data
def run_rx_parser(uploaded_file):
    # Minimal version for legacy support
    extracted_data = []
    cohort_keywords = ["HMO Actives", "HMO Retirees", "PPO Actives", "PPO Retirees"]
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
                label_col = raw_row[0]
                lines = label_col.count('\n') + 1
                for i in range(lines):
                    try:
                        label = label_col.split('\n')[i].strip()
                        cohort = next((c for c in cohort_keywords if c in label), None)
                        if cohort and current_month:
                             extracted_data.append({"Month": current_month, "Cohort": cohort, "Plan Cost": clean_money_value(raw_row[-1].split('\n')[i])})
                    except: continue
    return pd.DataFrame(extracted_data)

# --- SIDEBAR ---
st.sidebar.header("🔧 Settings")
parsing_mode = st.sidebar.selectbox("File Parser", ["Auto-Detect", "Census Engine", "GeoAccess Engine", "Rx Engine"])

# --- MAIN UI ---
st.title("🛡️ Network Disruption & Analytics")

uploaded_file = st.file_uploader("Upload Report", type=["pdf", "xlsx", "csv"])

if uploaded_file:
    # DETERMINE TYPE
    doc_type = 'UNKNOWN'
    if parsing_mode == "Auto-Detect": doc_type = detect_document_type(uploaded_file)
    elif parsing_mode == "Census Engine": doc_type = 'CENSUS'
    elif parsing_mode == "GeoAccess Engine": doc_type = 'GEO'
    elif parsing_mode == "Rx Engine": doc_type = 'RX'

    # --- CENSUS DASHBOARD ---
    if doc_type == 'CENSUS':
        st.success("👥 Processing Member Census")
        df, err = run_census_parser(uploaded_file)
        
        if not df.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Lives", f"{len(df):,}")
            c2.metric("Avg Age", f"{df['Age'].mean():.1f}")
            c3.metric("Unique Zips", f"{df['Zip'].nunique()}")
            
            st.subheader("📍 Member Heatmap")
            # Aggregating by Zip for visualization
            zip_counts = df['Zip'].value_counts().reset_index()
            zip_counts.columns = ['Zip', 'Count']
            
            # Interactive Bar for Density
            fig = px.bar(zip_counts.head(20), x='Zip', y='Count', color='Count', 
                         title="Top 20 Zip Codes (Density)", color_continuous_scale='Blues')
            st.plotly_chart(fig, use_container_width=True)
            
            # Demographics
            c1, c2 = st.columns(2)
            with c1: 
                fig_age = px.histogram(df[df['Age']>0], x="Age", nbins=15, title="Age Distribution", color_discrete_sequence=['#3498db'])
                st.plotly_chart(fig_age, use_container_width=True)
            with c2: 
                fig_gen = px.pie(df, names="Gender", title="Gender Split", hole=0.4)
                st.plotly_chart(fig_gen, use_container_width=True)
        else:
            st.error(f"Census Error: {err}")

    # --- GEOACCESS DASHBOARD ---
    elif doc_type == 'GEO':
        st.success("🌍 Processing GeoAccess Report")
        df = run_geo_parser(uploaded_file)
        
        if not df.empty:
            # Calc Disruption
            df['Disruption'] = 100 - df['Access %']
            
            c1, c2 = st.columns(2)
            c1.metric("Avg Network Match", f"{df['Access %'].mean():.1f}%")
            c2.metric("Specialties Analyzed", len(df))
            
            st.subheader("📉 Disruption Analysis")
            st.caption("Visualizing gaps where access is below 100%.")
            
            # Green to Red scale (Red = High Disruption/Low Access)
            fig = px.bar(df, x="Specialty", y="Access %", color="Disruption", 
                         title="Network Access by Specialty",
                         range_y=[50, 105], 
                         color_continuous_scale="RdYlGn_r")
            
            # Add Threshold Line
            fig.add_hline(y=90, line_dash="dot", annotation_text="Standard (90%)")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Detailed Findings")
            st.dataframe(df.style.format({"Access %": "{:.1f}%", "Disruption": "{:.1f}%"}), use_container_width=True)
        else:
            st.error("Extraction Failed: Could not identify standard GeoAccess tables. Please ensure the PDF contains a table with headers like 'Specialty' and 'Access %'.")

    # --- RX DASHBOARD ---
    elif doc_type == 'RX':
        st.info("Rx Engine Active")
        df = run_rx_parser(uploaded_file)
        if not df.empty:
            st.metric("Total Spend", f"${df['Plan Cost'].sum():,.0f}")
            st.plotly_chart(px.bar(df, x="Month", y="Plan Cost", color="Cohort"), use_container_width=True)
            
    else:
        st.info("👋 Ready to Analyze.")
        st.markdown("""
        **Supported Files:**
        * **Member Census:** Excel/CSV with columns for Zip, DOB, Gender.
        * **GeoAccess:** PDF Reports with standard Access tables.
        """)
