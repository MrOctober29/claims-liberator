import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px

# --- CONFIGURATION ---
st.set_page_config(page_title="Network Intelligence Suite", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
    
    /* Metrics */
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
    
    /* Strategy Cards */
    .strategy-card {
        background-color: rgba(30, 41, 59, 0.5);
        border-left: 4px solid #00cc96;
        padding: 20px;
        border-radius: 4px;
        margin-bottom: 15px;
    }
    .strategy-title { font-weight: bold; color: #00cc96; font-size: 16px; margin-bottom: 5px; }
    .strategy-body { font-size: 14px; color: #e0e0e0; }
    
    /* Critical Alert */
    .alert-card {
        background-color: rgba(100, 20, 20, 0.3);
        border-left: 4px solid #ff4b4b;
        padding: 20px;
        border-radius: 4px;
        margin-bottom: 15px;
    }
    .alert-title { font-weight: bold; color: #ff4b4b; font-size: 16px; margin-bottom: 5px; }
    
    /* Disclaimer */
    .disclaimer { font-size: 11px; color: #666; margin-top: 50px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_numeric(val_str):
    if not val_str: return 0.0
    clean = str(val_str).split(' ')[0] 
    clean = clean.replace('%', '').replace(',', '').strip()
    try: return float(clean)
    except ValueError: return 0.0

# --- ENGINE: GEO PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    current_specialty = "General Access"
    known_specialties = ["Primary Care", "Pediatrics", "OB/GYN", "Behavioral", "Cardiology", "Orthopedics", "Pharmacy"]

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tables = page.extract_tables()
            
            # Detect Context
            for spec in known_specialties:
                if spec in text: 
                    current_specialty = spec; break
            
            for table in tables:
                if not table or len(table) < 2: continue
                
                # Analyze Header (First 4 rows)
                header_text = " ".join([str(cell).lower() for row in table[:4] for cell in row if cell])
                
                if "county" in header_text and ("member" in header_text or "#" in header_text):
                    for row in table:
                        if not row or "county" in str(row[0]).lower(): continue
                        try:
                            county = str(row[0]).strip()
                            if not county and row[1]: county = str(row[1]).strip()
                            if not county or "Total" in county: continue

                            nums = []
                            for cell in row[1:]:
                                val = clean_numeric(cell)
                                if val > 0: nums.append(val)
                            
                            if len(nums) >= 2:
                                extracted_data.append({
                                    "County": county,
                                    "Specialty": current_specialty,
                                    "Lives": nums[0],
                                    "Avg Dist": nums[1],
                                    "Access %": 100.0 # Default
                                })
                        except: continue
    return pd.DataFrame(extracted_data)

# --- STRATEGY GENERATOR ---
def generate_strategy(issue_county, dist, lives, specialty):
    strategies = []
    
    # Strategy 1: The Contract Shield
    strategies.append(f"""
    <div class="strategy-card">
        <div class="strategy-title">1. Contract Protection: "Safe Harbor" Clause</div>
        <div class="strategy-body">
            <b>The Play:</b> {lives} members in {issue_county} are legally exposed. 
            Negotiate a "Safe Harbor" clause ensuring In-Network benefit levels (deductibles/copays) 
            for any claim incurred within this zip cluster if a network provider is not available within 15 miles.
        </div>
    </div>
    """)
    
    # Strategy 2: The Tactical Fix
    if dist > 20:
        strategies.append(f"""
        <div class="strategy-card">
            <div class="strategy-title">2. Benefit Override: Travel & Lodging Rider</div>
            <div class="strategy-body">
                <b>The Play:</b> Driving {dist} miles is a barrier to care. 
                Propose a specialized travel rider allowing up to $100/visit reimbursement for 
                {specialty} services in this specific county. This is cheaper than one ER visit due to delayed care.
            </div>
        </div>
        """)
    else:
        strategies.append(f"""
        <div class="strategy-card">
            <div class="strategy-title">2. Recruitment: Geo-Nomination Campaign</div>
            <div class="strategy-body">
                <b>The Play:</b> Submit a formal "Network Deficiency Notice" to the carrier. 
                Require them to attempt recruitment of 3 specific providers in {issue_county} 
                within 60 days or offer a Single Case Agreement (SCA).
            </div>
        </div>
        """)
        
    # Strategy 3: The Financial Defense
    strategies.append(f"""
    <div class="strategy-card">
        <div class="strategy-title">3. Financial Defense: RBP Overlay</div>
        <div class="strategy-body">
            <b>The Play:</b> If the carrier cannot solve {issue_county}, carve out this specific region 
            and apply a Reference Based Pricing (RBP) vendor for {specialty} claims only.
        </div>
    </div>
    """)
    
    return "".join(strategies)

# --- MAIN UI ---
st.title("🛡️ Network Intelligence Suite")
st.markdown("##### Empowering Benefit Advisors with Actionable Insights")

uploaded_file = st.file_uploader("Upload GeoAccess Report (PDF)", type=["pdf"])

if uploaded_file:
    with st.spinner("Extracting insights..."):
        gdf = run_geo_parser(uploaded_file)
    
    if not gdf.empty:
        # Aggregation
        gdf = gdf.groupby(['County', 'Specialty']).agg({'Lives': 'sum', 'Avg Dist': 'mean'}).reset_index()
        
        # Risk Logic (Threshold: 15 miles)
        gdf['Risk'] = gdf['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else 'Good')
        critical = gdf[gdf['Risk'] == 'Critical'].sort_values('Avg Dist', ascending=False)
        
        # 1. KPI ROW
        total_lives = gdf['Lives'].sum()
        w_avg_dist = (gdf['Lives'] * gdf['Avg Dist']).sum() / total_lives if total_lives else 0
        
        m1, m2, m3 = st.columns(3)
        m1.markdown(f"""<div class="metric-box"><div class="big-stat">{int(total_lives):,}</div><div class="stat-label">Lives Analyzed</div></div>""", unsafe_allow_html=True)
        m2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Time</div></div>""", unsafe_allow_html=True)
        m3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Zones</div></div>""", unsafe_allow_html=True)

        st.markdown("---")

        # 2. VISUALS (SIMPLIFIED)
        c_chart, c_list = st.columns([2, 1])
        
        with c_chart:
            st.subheader("📊 Top 10 Longest Drive Times")
            st.caption("Counties where members face the highest barriers to care.")
            
            # Simple Bar Chart - Easy to read
            top_10 = gdf.sort_values("Avg Dist", ascending=False).head(10)
            fig = px.bar(top_10, x="Avg Dist", y="County", orientation='h', 
                         color="Risk", color_discrete_map={'Good': '#2e86de', 'Critical': '#ff4b4b'},
                         text_auto='.1f', title="")
            fig.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title="Average Miles to Provider", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
            
        with c_list:
            st.subheader("🚨 Risk Ledger")
            if not critical.empty:
                st.dataframe(
                    critical[['County', 'Lives', 'Avg Dist']]
                    .style.format({"Avg Dist": "{:.1f} mi", "Lives": "{:,.0f}"}), 
                    use_container_width=True, height=400
                )
            else:
                st.success("No counties exceed the 15-mile risk threshold.")

        # 3. ADVISOR STRATEGY
        st.markdown("---")
        st.subheader("🧠 Strategic Action Plan")
        
        if not critical.empty:
            top_issue = critical.iloc[0]
            
            st.markdown(f"""
            <div class="alert-card">
                <div class="alert-title">🔥 Primary Target: {top_issue['County']}</div>
                Analysis shows <b>{int(top_issue['Lives'])} members</b> are currently forced to drive 
                <b>{top_issue['Avg Dist']:.1f} miles</b> for {top_issue['Specialty']} services. 
                This exceeds the standard of care.
            </div>
            """, unsafe_allow_html=True)
            
            # Generate the detailed strategy text
            strategy_html = generate_strategy(
                top_issue['County'], 
                top_issue['Avg Dist'], 
                int(top_issue['Lives']), 
                top_issue['Specialty']
            )
            st.markdown(strategy_html, unsafe_allow_html=True)
            
        else:
            st.markdown("""
            <div class="strategy-card">
                <div class="strategy-title">✅ Market Check Complete</div>
                <div class="strategy-body">
                    The network meets all standard access requirements. 
                    <b>Action:</b> Leverage this strong access report to defend against competitor 
                    proposals that may offer lower premiums but narrower networks.
                </div>
            </div>
            """, unsafe_allow_html=True)

        # 4. DISCLAIMER
        st.markdown("""
        <div class="disclaimer">
        <b>DISCLAIMER:</b> This analysis is generated based on data parsed from third-party PDF reports uploaded by the user. 
        Formatting inconsistencies in original carrier reports may affect extraction accuracy. 
        Advisors should verify all critical figures with the carrier before executing contracts.
        </div>
        """, unsafe_allow_html=True)

    else:
        st.error("⚠️ Unable to Extract Data")
        st.markdown("The uploaded PDF structure does not match standard GeoAccess formats. Please verify the file contains County Detail tables.")
