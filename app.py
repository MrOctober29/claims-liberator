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
    .strategy-card {
        background-color: rgba(0, 200, 150, 0.1);
        border-left: 5px solid #00cc96;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    .alert-card {
        background-color: rgba(255, 75, 75, 0.1);
        border-left: 5px solid #ff4b4b;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_numeric(val_str):
    """Aggressively cleans strings to floats (e.g. '1,234.5%' -> 1234.5)"""
    if not val_str: return 0.0
    # Remove citations or footnotes (e.g., '100.0 1' -> '100.0')
    clean = str(val_str).split(' ')[0] 
    clean = clean.replace('%', '').replace(',', '').strip()
    try: return float(clean)
    except ValueError: return 0.0

# --- ENGINE: CENSUS PARSER ---
@st.cache_data
def run_census_parser(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file)
        else: df = pd.read_excel(uploaded_file)
    except Exception as e: return pd.DataFrame(), str(e)
    
    df.columns = [c.strip().lower() for c in df.columns]
    zip_col = next((c for c in df.columns if 'zip' in c or 'postal' in c), None)
    
    if not zip_col: return pd.DataFrame(), "Missing Zip Column"
    
    processed = pd.DataFrame()
    processed['Zip'] = df[zip_col].astype(str).str[:5]
    processed['Count'] = 1
    return processed, None

# --- ENGINE: INTELLIGENT GEO PARSER (The "Brain") ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    report_type = "Summary" # Default
    
    # Context Tracking
    current_specialty = "General Access"
    known_specialties = ["Primary Care", "Pediatrics", "OB/GYN", "Behavioral Health", "Cardiology", "Orthopedics", "Pharmacy", "Hospital"]

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tables = page.extract_tables()
            
            # 1. DETECT CONTEXT (Read the Page Header)
            # This is crucial for reports where the specialty isn't in the table row
            for spec in known_specialties:
                if spec in text:
                    current_specialty = spec
                    break
            
            for table in tables:
                if not table: continue
                
                # 2. ANALYZE TABLE STRUCTURE
                # Flatten header row to a single string for keyword searching
                headers = [str(c).lower().replace('\n',' ') for c in table[0] if c]
                header_str = " ".join(headers)
                
                # --- STRATEGY A: COUNTY DETAIL TABLE (The Humana/Quest Format) ---
                # Looks for: "County" AND ("Member" OR "#") AND ("Access" OR "Dist")
                if "county" in header_str and ("member" in header_str or "#" in header_str):
                    report_type = "County Detail"
                    
                    # Dynamic Column Mapping
                    col_map = {'county': -1, 'lives': -1, 'dist': -1, 'access': -1}
                    
                    for idx, col_name in enumerate(headers):
                        if "county" in col_name: col_map['county'] = idx
                        elif "member" in col_name or "#" in col_name: col_map['lives'] = idx
                        elif "dist" in col_name: col_map['dist'] = idx
                        elif "access" in col_name and "without" not in col_name: col_map['access'] = idx
                    
                    # Parse Rows
                    if col_map['county'] != -1:
                        for row in table[1:]:
                            try:
                                # Clean data
                                county = str(row[col_map['county']]).replace('\n',' ').strip()
                                # Skip header rows repeated in body
                                if "County" in county or not county: continue
                                
                                lives = clean_numeric(row[col_map['lives']]) if col_map['lives'] != -1 else 0
                                dist = clean_numeric(row[col_map['dist']]) if col_map['dist'] != -1 else 0
                                access = clean_numeric(row[col_map['access']]) if col_map['access'] != -1 else 100.0
                                
                                if lives > 0:
                                    extracted_data.append({
                                        "Type": "County",
                                        "Name": county,
                                        "Specialty": current_specialty, # Uses the context we found earlier
                                        "Lives": lives,
                                        "Avg Dist": dist,
                                        "Access %": access
                                    })
                            except: continue

                # --- STRATEGY B: EXECUTIVE SUMMARY TABLE ---
                # Looks for "Specialty" column directly
                elif "specialty" in header_str and "access" in header_str:
                    spec_idx = next((i for i, h in enumerate(headers) if "specialty" in h), -1)
                    acc_idx = next((i for i, h in enumerate(headers) if "access" in h or "%" in h), -1)
                    
                    if spec_idx != -1 and acc_idx != -1:
                        for row in table[1:]:
                            try:
                                extracted_data.append({
                                    "Type": "Summary",
                                    "Name": "All Counties",
                                    "Specialty": row[spec_idx].replace('\n',' ').strip(),
                                    "Lives": 0,
                                    "Avg Dist": 0,
                                    "Access %": clean_numeric(row[acc_idx])
                                })
                            except: continue

    return pd.DataFrame(extracted_data), report_type

# --- MAIN UI ---
st.title("🛡️ Strategic Network Analyzer")
st.markdown("##### Detect gaps. Prescribe solutions. Close the deal.")

col1, col2 = st.columns(2)
census_file = col1.file_uploader("1. Upload Census (CSV/Excel)", type=["csv", "xlsx"])
geo_file = col2.file_uploader("2. Upload GeoAccess Report (PDF)", type=["pdf"])

# Run Parsers
if census_file: st.session_state['cdf'], _ = run_census_parser(census_file)
if geo_file: st.session_state['gdf'], st.session_state['rtype'] = run_geo_parser(geo_file)

if 'gdf' in st.session_state and not st.session_state['gdf'].empty:
    gdf = st.session_state['gdf']
    report_type = st.session_state.get('rtype', 'Unknown')
    
    st.markdown("---")
    st.success(f"✅ Data Extracted Successfully (Mode: {report_type})")
    
    # --- DASHBOARD LOGIC ---
    
    if report_type == "County Detail":
        # SOPHISTICATED VIEW (For the Humana/Quest Report)
        st.subheader("📍 Geographic Disruption Matrix")
        st.caption("Visualizing specific counties where member density is high but access is low.")
        
        # 1. KEY METRICS
        total_lives = gdf['Lives'].sum()
        # Weighted Average Distance calculation
        avg_dist = (gdf['Lives'] * gdf['Avg Dist']).sum() / total_lives if total_lives else 0
        
        # Identify "Problem Counties" (Access < 90% OR Distance > 15 miles)
        gdf['Risk Score'] = (100 - gdf['Access %']) + (gdf['Avg Dist'] * 2) # Custom risk algorithm
        problem_counties = gdf[gdf['Risk Score'] > 20].sort_values('Risk Score', ascending=False)
        
        m1, m2, m3 = st.columns(3)
        m1.markdown(f"""<div class="metric-box"><div class="big-stat">{int(total_lives):,}</div><div class="stat-label">Total Lives Analyzed</div></div>""", unsafe_allow_html=True)
        m2.markdown(f"""<div class="metric-box"><div class="big-stat">{avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
        m3.markdown(f"""<div class="metric-box"><div class="big-stat">{len(problem_counties)}</div><div class="stat-label">At-Risk Counties</div></div>""", unsafe_allow_html=True)

        # 2. THE SCATTER MATRIX (The "Aha!" Chart)
        # Filters for interactivity
        selected_spec = st.selectbox("Filter by Specialty", gdf['Specialty'].unique())
        chart_df = gdf[gdf['Specialty'] == selected_spec]
        
        fig = px.scatter(chart_df, x="Lives", y="Avg Dist", size="Lives", color="Access %",
                         hover_name="Name", text="Name",
                         color_continuous_scale="RdYlGn", # Red = Low Access (Bad)
                         title=f"{selected_spec}: Distance vs. Density",
                         labels={"Avg Dist": "Avg Drive Miles", "Lives": "Member Count"},
                         height=500)
        fig.update_traces(textposition='top center')
        st.plotly_chart(fig, use_container_width=True)
        
        # 3. BROKER STRATEGY GUIDE
        st.markdown("---")
        st.subheader("🧠 Broker Action Plan")
        
        col_list, col_strat = st.columns([1, 1])
        
        with col_list:
            st.markdown("**🚨 Critical Gaps Identified**")
            if not problem_counties.empty:
                display_cols = ['Name', 'Specialty', 'Lives', 'Avg Dist', 'Access %']
                st.dataframe(problem_counties[display_cols].head(10).style.format({"Avg Dist": "{:.1f} mi", "Access %": "{:.1f}%"}), use_container_width=True)
            else:
                st.success("No critical county gaps found.")
                
        with col_strat:
            st.markdown("**🛠️ Recommended Solutions**")
            if not problem_counties.empty:
                worst_county = problem_counties.iloc[0]
                st.markdown(f"""
                <div class="alert-card">
                <b>Priority Target: {worst_county['Name']}</b><br>
                {int(worst_county['Lives'])} members are driving {worst_county['Avg Dist']} miles for {worst_county['Specialty']}.
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div class="strategy-card">
                <b>1. Geo-Nomination Campaign</b><br>
                Request the carrier to recruit providers in zip codes near <b>{worst_county['Name']}</b>. Use this report as leverage.
                </div>
                <div class="strategy-card">
                <b>2. Telemedicine Overlay</b><br>
                Since {worst_county['Specialty']} access is low, propose a $0 copay Telehealth benefit to mitigate the {worst_county['Avg Dist']} mile drive.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""<div class="strategy-card"><b>✅ Defend the Renewal</b><br>Network is performing well. Use these charts to justify current premiums against lower-cost, narrower network competitors.</div>""", unsafe_allow_html=True)

    else:
        # SIMPLE SUMMARY VIEW
        st.subheader("📉 Network Access Summary")
        fig = px.bar(gdf, x="Specialty", y="Access %", color="Access %", range_y=[50, 105], color_continuous_scale="RdYlGn")
        fig.add_hline(y=90, line_dash="dot", annotation_text="Standard (90%)")
        st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Upload your GeoAccess PDF to begin analysis.")
