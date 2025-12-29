import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Strategic Network Analyzer", layout="wide")

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
    if not val_str: return 0.0
    clean = str(val_str).split(' ')[0] 
    clean = clean.replace('%', '').replace(',', '').strip()
    try: return float(clean)
    except ValueError: return 0.0

# --- ENGINE: INTELLIGENT GEO PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    report_type = "Unknown"
    
    known_specialties = ["Primary Care", "Pediatrics", "OB/GYN", "Behavioral Health", "Cardiology", "Orthopedics", "Pharmacy", "Hospital"]
    current_specialty = "General Access"

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tables = page.extract_tables()
            
            # 1. Update Context (Specialty)
            for spec in known_specialties:
                if spec in text: current_specialty = spec; break
            
            for table in tables:
                if not table or len(table) < 2: continue
                
                # 2. HEADER ANALYSIS (Look across first 3 rows for messy headers)
                header_rows = table[:3]
                header_text = " ".join([str(cell).lower() for row in header_rows for cell in row if cell])
                
                # --- STRATEGY A: COUNTY DETAIL (Complex/Stacked) ---
                if "county" in header_text and ("member" in header_text or "#" in header_text):
                    report_type = "County Detail"
                    
                    # Find column indices dynamically
                    # We assume the LAST row of the header block contains the specific sub-columns
                    # BUT "County" might be in the first row. This is tricky. 
                    # We will scan the *first valid data row* to guess columns by content type.
                    
                    # Heuristic: Find the first row that starts with a County Name (Text) and has Numbers
                    for row in table:
                        # Skip likely header rows (checking if first cell is "County" or empty)
                        first_cell = str(row[0]).lower()
                        if "county" in first_cell or "class" in first_cell: continue
                        
                        # Data Row Validation
                        # Needs: Name (Col 0), Lives (Number), Dist (Number), Access (Number)
                        try:
                            county_name = str(row[0]).strip()
                            # Standard Quest/Optum Layout:
                            # [0] County, [1] ?, [2] Member #, [3] Avg Dist, [4] Access % (sometimes)
                            
                            # Let's try to map by index for the Kentucky Format specifically
                            # Based on your PDF Page 5: 
                            # Col 0: County Name
                            # Col 2: Member # (Index 2)
                            # Col 3: Avg Dist (Index 3)
                            # Col 4, 5, 6: % Access 15/30/45 miles
                            
                            if len(row) > 4:
                                lives = clean_numeric(row[2]) # Column 2
                                dist = clean_numeric(row[3])  # Column 3
                                access = clean_numeric(row[4]) # Column 4 (First access column)
                                
                                # Sanity check: Lives should be > 0
                                if lives > 0 and county_name:
                                    extracted_data.append({
                                        "Type": "County",
                                        "Name": county_name.replace('\n', ' '),
                                        "Specialty": current_specialty,
                                        "Lives": lives,
                                        "Avg Dist": dist,
                                        "Access %": access
                                    })
                        except: continue

                # --- STRATEGY B: SUMMARY LIST (Simple) ---
                elif "specialty" in header_text and "access" in header_text:
                    report_type = "Summary"
                    # Simple parsing logic for summary tables
                    # (Simplified for brevity, assumes standard 2-column layout)
                    pass 

    return pd.DataFrame(extracted_data), report_type

# --- MAIN UI ---
st.title("🛡️ Strategic Network Analyzer")
st.markdown("##### Detect gaps. Prescribe solutions. Close the deal.")

uploaded_file = st.file_uploader("Upload GeoAccess Report (PDF)", type=["pdf"])

if uploaded_file:
    with st.spinner("Analyzing PDF Structure..."):
        gdf, report_type = run_geo_parser(uploaded_file)
    
    if not gdf.empty:
        st.success(f"✅ Analysis Complete (Mode: {report_type})")
        
        # --- DASHBOARD ---
        total_lives = gdf['Lives'].sum()
        avg_dist = (gdf['Lives'] * gdf['Avg Dist']).sum() / total_lives if total_lives else 0
        
        # Risk Logic
        gdf['Risk'] = gdf.apply(lambda x: 'Critical' if x['Access %'] < 90 or x['Avg Dist'] > 15 else 'Good', axis=1)
        critical_counties = gdf[gdf['Risk'] == 'Critical'].sort_values('Avg Dist', ascending=False)

        # 1. METRICS
        m1, m2, m3 = st.columns(3)
        m1.markdown(f"""<div class="metric-box"><div class="big-stat">{int(total_lives):,}</div><div class="stat-label">Lives Mapped</div></div>""", unsafe_allow_html=True)
        m2.markdown(f"""<div class="metric-box"><div class="big-stat">{avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
        m3.markdown(f"""<div class="metric-box"><div class="big-stat">{len(critical_counties)}</div><div class="stat-label">Critical Counties</div></div>""", unsafe_allow_html=True)

        # 2. SCATTER PLOT
        st.subheader("📍 Geographic Disruption Matrix")
        st.caption("Counties in Red have high drive times or low access.")
        
        fig = px.scatter(gdf, x="Lives", y="Avg Dist", size="Lives", color="Risk",
                         hover_name="Name", text="Name",
                         color_discrete_map={'Good': '#00cc96', 'Critical': '#ff4b4b'},
                         title="Distance vs. Density", height=500)
        fig.update_traces(textposition='top center')
        st.plotly_chart(fig, use_container_width=True)

        # 3. ACTION PLAN
        st.subheader("🧠 Broker Action Plan")
        if not critical_counties.empty:
            top_issue = critical_counties.iloc[0]
            st.markdown(f"""
            <div class="alert-card">
            <b>🚨 Top Priority: {top_issue['Name']}</b><br>
            {int(top_issue['Lives'])} members are driving <b>{top_issue['Avg Dist']} miles</b> on average.
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("**Recommended Strategy:**")
            st.markdown(f"1. **Disruption Report:** Request a provider match specifically for {top_issue['Name']}.")
            st.markdown(f"2. **Travel Benefit:** If {top_issue['Avg Dist']} miles exceeds the plan limit, propose a travel reimbursement rider.")
        else:
            st.markdown('<div class="strategy-card"><b>✅ Network Stable</b><br>No critical gaps detected.</div>', unsafe_allow_html=True)
            
        with st.expander("View Raw Data"):
            st.dataframe(gdf)

    else:
        st.error("⚠️ No Data Found")
        st.markdown("""
        **Why?** The PDF tables might be formatted unexpectedly. 
        **Try this:** Ensure your PDF has "County Detail" pages (lists of counties with member counts and distances).
        """)
