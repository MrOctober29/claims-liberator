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
    .highlight-red { color: #ff4b4b; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_numeric(val_str):
    """Aggressively cleans strings to floats (e.g. '1,234.5%' -> 1234.5)"""
    if not val_str: return 0.0
    clean = str(val_str).replace('%', '').replace(',', '').replace(' ', '').strip()
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
    zip_col = next((c for c in df.columns if 'zip' in c), None)
    
    if not zip_col: return pd.DataFrame(), "Missing Zip Column"
    
    processed = pd.DataFrame()
    processed['Zip'] = df[zip_col].astype(str).str[:5]
    processed['Count'] = 1
    return processed, None

# --- ENGINE: ADVANCED GEOACCESS PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    report_type = "Unknown"
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            text = page.extract_text() or ""
            
            # Identify Specialty context from page header (e.g. "Primary Care")
            specialty_context = "Unknown Specialty"
            if "Primary Care" in text: specialty_context = "Primary Care"
            elif "Pediatrics" in text: specialty_context = "Pediatrics"
            elif "Behavioral" in text: specialty_context = "Behavioral Health"
            
            for table in tables:
                if not table: continue
                
                # --- STRATEGY 1: COUNTY DETAIL TABLE (Complex) ---
                # Looks for: County | Member # | Avg Dist OR With Access %
                # Found in the Kentucky Sample
                headers = [str(c).lower().replace('\n',' ') for c in table[0] if c]
                header_str = " ".join(headers)
                
                if "county" in header_str and ("member" in header_str or "#" in header_str):
                    report_type = "County Detail"
                    
                    # map columns dynamically
                    col_map = {'county': -1, 'lives': -1, 'dist': -1, 'access': -1}
                    
                    for idx, col_name in enumerate(headers):
                        if "county" in col_name: col_map['county'] = idx
                        elif "member" in col_name or "#" in col_name: col_map['lives'] = idx
                        elif "dist" in col_name: col_map['dist'] = idx
                        elif "access" in col_name and "without" not in col_name: col_map['access'] = idx
                    
                    # Parse rows
                    if col_map['county'] != -1:
                        for row in table[1:]:
                            try:
                                # Clean row data
                                county = row[col_map['county']].replace('\n',' ')
                                lives = clean_numeric(row[col_map['lives']]) if col_map['lives'] != -1 else 0
                                dist = clean_numeric(row[col_map['dist']]) if col_map['dist'] != -1 else 0
                                access = clean_numeric(row[col_map['access']]) if col_map['access'] != -1 else 100.0 # Default to 100 if not found
                                
                                if lives > 0: # Filter out empty rows
                                    extracted_data.append({
                                        "Type": "County",
                                        "Name": county,
                                        "Specialty": specialty_context,
                                        "Lives": lives,
                                        "Avg Dist": dist,
                                        "Access %": access
                                    })
                            except: continue

                # --- STRATEGY 2: SUMMARY TABLE (Simple) ---
                # Looks for: Specialty | Access %
                elif "specialty" in header_str and "access" in header_str:
                    report_type = "Summary"
                    # (Logic from v3.0 - kept for backwards compatibility)
                    spec_idx = next((i for i, h in enumerate(headers) if "specialty" in h), -1)
                    acc_idx = next((i for i, h in enumerate(headers) if "access" in h or "%" in h), -1)
                    
                    if spec_idx != -1 and acc_idx != -1:
                        for row in table[1:]:
                            try:
                                extracted_data.append({
                                    "Type": "Summary",
                                    "Name": "All Counties",
                                    "Specialty": row[spec_idx].replace('\n',' '),
                                    "Lives": 0,
                                    "Avg Dist": 0,
                                    "Access %": clean_numeric(row[acc_idx])
                                })
                            except: continue

    return pd.DataFrame(extracted_data), report_type

# --- MAIN UI ---
st.title("🛡️ Network Disruption & ROI")
st.markdown("##### Enterprise-Grade Analysis for GeoAccess & Census Data")

col1, col2 = st.columns(2)
census_file = col1.file_uploader("1. Upload Census (CSV/Excel)", type=["csv", "xlsx"])
geo_file = col2.file_uploader("2. Upload GeoAccess Report (PDF)", type=["pdf"])

# Run Parsers
if census_file: st.session_state['cdf'], _ = run_census_parser(census_file)
if geo_file: st.session_state['gdf'], st.session_state['rtype'] = run_geo_parser(geo_file)

if 'cdf' in st.session_state and 'gdf' in st.session_state:
    cdf = st.session_state['cdf']
    gdf = st.session_state['gdf']
    report_type = st.session_state.get('rtype', 'Unknown')
    
    if not gdf.empty:
        st.markdown("---")
        st.success(f"✅ Data Extracted Successfully (Mode: {report_type})")
        
        # --- VIEW 1: IF COUNTY DETAIL (The Sophisticated View) ---
        if report_type == "County Detail":
            # This handles the Kentucky-style report
            st.subheader("📍 Geographic Weakness Detector")
            st.caption("Analyzing member distance and access at the COUNTY level.")
            
            # 1. METRICS
            total_lives = gdf['Lives'].sum()
            avg_dist = (gdf['Lives'] * gdf['Avg Dist']).sum() / total_lives if total_lives else 0
            # Weighted Access Calculation
            w_access = (gdf['Lives'] * gdf['Access %']).sum() / total_lives if total_lives else 0
            
            m1, m2, m3 = st.columns(3)
            m1.markdown(f"""<div class="metric-box"><div class="big-stat">{int(total_lives):,}</div><div class="stat-label">Lives Mapped</div></div>""", unsafe_allow_html=True)
            m2.markdown(f"""<div class="metric-box"><div class="big-stat">{avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
            m3.markdown(f"""<div class="metric-box"><div class="big-stat">{w_access:.1f}%</div><div class="stat-label">Weighted Access</div></div>""", unsafe_allow_html=True)
            
            # 2. THE PROBLEM ZONES (Scatter Plot)
            # Y-Axis = Distance (Bad), X-Axis = # of Lives (Impact), Color = Access %
            st.markdown("### 🚦 The Disruption Matrix")
            st.info("Top Right Quadrant = **High Risk** (Many people driving long distances).")
            
            fig = px.scatter(gdf, x="Lives", y="Avg Dist", size="Lives", color="Access %",
                             hover_name="Name", text="Name",
                             color_continuous_scale="RdYlGn", # Red = Low Access
                             title="County Analysis: Distance vs. Density",
                             height=500)
            fig.update_traces(textposition='top center')
            st.plotly_chart(fig, use_container_width=True)
            
            # 3. WORST OFFENDERS LIST
            st.subheader("🚨 Top 5 'Problem Counties'")
            # Rank by (Distance * Lives) to find largest aggregate burden
            gdf['Burden Score'] = gdf['Avg Dist'] * gdf['Lives']
            bad_counties = gdf.sort_values("Burden Score", ascending=False).head(5)
            
            st.dataframe(
                bad_counties[['Name', 'Specialty', 'Lives', 'Avg Dist', 'Access %']]
                .style.format({"Avg Dist": "{:.1f} mi", "Access %": "{:.1f}%"}), 
                use_container_width=True
            )

        # --- VIEW 2: IF SUMMARY ONLY (The Standard View) ---
        else:
            st.subheader("📉 Network Gaps Summary")
            avg_access = gdf['Access %'].mean()
            st.metric("Overall Network Score", f"{avg_access:.1f}%")
            
            fig = px.bar(gdf, x="Specialty", y="Access %", color="Access %", 
                         range_y=[50, 105], color_continuous_scale="RdYlGn")
            fig.add_hline(y=90, line_dash="dot", annotation_text="Standard (90%)")
            st.plotly_chart(fig, use_container_width=True)

        # --- ROI CALCULATOR (Universal) ---
        st.markdown("---")
        st.subheader("💰 Disruption ROI Calculator")
        
        # Calculate disrupted lives based on the loaded data
        if report_type == "County Detail":
            disrupted_lives = gdf[gdf['Access %'] < 95]['Lives'].sum()
        else:
            # Estimate based on census total if we only have percentages
            total_census = len(cdf) if not cdf.empty else 1000
            disrupted_lives = int(total_census * (1 - (gdf['Access %'].mean()/100)))

        c1, c2 = st.columns([1,2])
        with c1:
            st.markdown("**Assumptions**")
            cost_oon = st.number_input("Avg OON Claim ($)", 300)
            freq = st.slider("Visits per Disrupted Member/Yr", 1, 10, 3)
        with c2:
            waste = disrupted_lives * cost_oon * freq
            st.markdown(f"#### Estimated Leakage: <span class='highlight-red'>${waste:,.0f}</span>", unsafe_allow_html=True)
            st.write(f"Based on **{int(disrupted_lives)}** members in low-access areas/specialties.")

    else:
        st.info("Upload files to see the analysis.")
