import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Network Disruption & ROI", layout="wide")

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
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_percentage(val_str):
    if not val_str: return 0.0
    clean = str(val_str).replace('%', '').replace(' ', '').strip()
    try: return float(clean)
    except ValueError: return 0.0

# --- SMART ROUTER ---
def detect_document_type(uploaded_file):
    filename = uploaded_file.name.lower()
    if filename.endswith('.xlsx') or filename.endswith('.csv'): return 'CENSUS'
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            if not pdf.pages: return 'UNKNOWN'
            text = pdf.pages[0].extract_text() or ""
            if "GeoAccess" in text or "Accessibility" in text or "Distance" in text: return 'GEO'
    except: return 'UNKNOWN'
    return 'UNKNOWN'

# --- ENGINE: CENSUS PARSER ---
@st.cache_data
def run_census_parser(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
    except Exception as e: return pd.DataFrame(), str(e)
    
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Intelligent Column Mapping
    zip_col = next((c for c in df.columns if 'zip' in c), None)
    rel_col = next((c for c in df.columns if 'relation' in c or 'type' in c), None)
    
    if not zip_col: return pd.DataFrame(), "Missing Zip Column"
    
    processed = pd.DataFrame()
    processed['Zip'] = df[zip_col].astype(str).str[:5]
    processed['Relationship'] = df[rel_col] if rel_col else 'Member'
    processed['Count'] = 1
    
    return processed, None

# --- ENGINE: GEOACCESS PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    # We scan specifically for the Summary Tables in the PDF
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                # Look for headers
                spec_idx, acc_idx = -1, -1
                for i, row in enumerate(table):
                    row_str = " ".join([str(c).lower() for c in row if c])
                    if "specialty" in row_str and ("access" in row_str or "%" in row_str):
                        # Found Header
                        for col_i, cell in enumerate(row):
                            if "specialty" in str(cell).lower(): spec_idx = col_i
                            if "access" in str(cell).lower() or "%" in str(cell): acc_idx = col_i
                        
                        # Process Data Rows below header
                        if spec_idx != -1 and acc_idx != -1:
                            for data_row in table[i+1:]:
                                if len(data_row) > max(spec_idx, acc_idx):
                                    spec = data_row[spec_idx]
                                    acc = data_row[acc_idx]
                                    if spec and acc:
                                        val = clean_percentage(acc)
                                        if val > 0:
                                            extracted_data.append({"Specialty": str(spec).strip(), "Access %": val})
                        break
    
    df = pd.DataFrame(extracted_data)
    if not df.empty:
        # Average duplicate entries (e.g. Urban vs Rural lines)
        df = df.groupby("Specialty")["Access %"].mean().reset_index()
    return df

# --- MAIN UI ---
st.title("🛡️ Network Strategy & Disruption ROI")
st.markdown("##### Turn dense GeoAccess reports into financial strategy.")

col_upload_1, col_upload_2 = st.columns(2)
with col_upload_1:
    census_file = st.file_uploader("1. Upload Census (CSV/Excel)", type=["csv", "xlsx"])
with col_upload_2:
    geo_file = st.file_uploader("2. Upload GeoAccess (PDF)", type=["pdf"])

# STATE MANAGEMENT
if census_file: st.session_state['census_df'], _ = run_census_parser(census_file)
if geo_file: st.session_state['geo_df'] = run_geo_parser(geo_file)

# DASHBOARD
if 'census_df' in st.session_state and 'geo_df' in st.session_state:
    
    cdf = st.session_state['census_df']
    gdf = st.session_state['geo_df']
    
    if not cdf.empty and not gdf.empty:
        st.markdown("---")
        
        # 1. SUMMARY METRICS
        total_lives = len(cdf)
        avg_access = gdf['Access %'].mean()
        
        # Determine Network Strength
        net_status = "STRONG" if avg_access > 95 else "AT RISK"
        net_color = "#00cc96" if avg_access > 95 else "#ff4b4b"
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,}</div><div class="stat-label">Total Lives Analyzed</div></div>""", unsafe_allow_html=True)
        c2.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:{net_color}">{avg_access:.1f}%</div><div class="stat-label">Network Effectiveness</div></div>""", unsafe_allow_html=True)
        c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:{net_color}">{net_status}</div><div class="stat-label">Overall Status</div></div>""", unsafe_allow_html=True)
        
        # 2. ROI CALCULATOR (THE BROKER WEAPON)
        st.subheader("💰 Disruption ROI Calculator")
        st.info("Estimate the cost of 'Network Gaps' (Members seeking care Out-of-Network due to lack of access).")
        
        col_calc, col_res = st.columns([1, 2])
        
        with col_calc:
            st.markdown("**Assumptions**")
            avg_claim = st.number_input("Avg Cost per Visit ($)", value=250)
            leakage_rate = st.slider("Leakage Probability %", 10, 50, 25, help="% of members without access who will go Out-of-Network")
            oon_multiplier = st.number_input("OON Cost Multiplier", value=3.0, help="How much more expensive is OON care? (e.g. 3x)")
            
        with col_res:
            # ROI LOGIC:
            # 1. Find specialties below 95% access (The Gaps)
            # 2. Calculate Disrupted Members (Total Lives * (100 - Access%))
            # 3. Calculate Leakage Cost
            
            gdf['Disrupted Lives'] = (total_lives * (100 - gdf['Access %']) / 100).astype(int)
            gaps = gdf[gdf['Access %'] < 95].copy()
            
            if not gaps.empty:
                total_disrupted_lives = gaps['Disrupted Lives'].sum()
                # Leakage = Disrupted Lives * Probability * (OON Cost - In-Network Cost)
                estimated_waste = total_disrupted_lives * (leakage_rate/100) * (avg_claim * (oon_multiplier - 1))
                
                st.markdown(f"### Estimated Network Inefficiency: <span style='color:#ff4b4b'>${estimated_waste:,.0f} / year</span>", unsafe_allow_html=True)
                st.markdown(f"**{total_disrupted_lives}** member instances are currently disrupted in key specialties.")
                
                st.dataframe(gaps[['Specialty', 'Access %', 'Disrupted Lives']].style.format({"Access %": "{:.1f}%"}), use_container_width=True)
            else:
                st.success("No significant network gaps detected. ROI is optimized.")

        # 3. VISUALS
        c_left, c_right = st.columns(2)
        
        with c_left:
            st.subheader("📉 Gap Analysis")
            gdf['Gap'] = 100 - gdf['Access %']
            fig = px.bar(gdf, x="Specialty", y="Access %", color="Gap", 
                         title="Access by Specialty (Red = High Disruption)",
                         range_y=[70, 105], color_continuous_scale="RdYlGn_r")
            fig.add_hline(y=90, line_dash="dot", annotation_text="Standard (90%)")
            st.plotly_chart(fig, use_container_width=True)
            
        with c_right:
            st.subheader("📍 Census Heatmap")
            zip_counts = cdf['Zip'].value_counts().reset_index()
            zip_counts.columns = ['Zip', 'Count']
            fig2 = px.bar(zip_counts.head(10), x='Zip', y='Count', title="Top 10 Zip Codes", color='Count')
            st.plotly_chart(fig2, use_container_width=True)

    else:
        st.warning("Could not merge data. Check file formats.")
else:
    st.info("Upload both files to unlock the ROI Calculator.")
