import streamlit as st
import pdfplumber
import pandas as pd
import plotly.express as px
import re

st.set_page_config(page_title="Strategic Network Analyzer", layout="wide")

# --- CSS FOR "STRATEGY CARDS" ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; }
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

# --- PARSERS ---
def clean_numeric(val_str):
    if not val_str: return 0.0
    clean = str(val_str).replace('%', '').replace(',', '').strip()
    try: return float(clean)
    except: return 0.0

@st.cache_data
def run_geo_parser(uploaded_file):
    extracted = []
    network_name = "Unknown Network"
    
    with pdfplumber.open(uploaded_file) as pdf:
        # 1. Detect Network Name from Header
        first_page = pdf.pages[0].extract_text()
        if "Network Analyzed:" in first_page:
            try:
                network_name = first_page.split("Network Analyzed:")[1].split('\n')[0].strip()
            except: pass
            
        # 2. Extract County Tables
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                # Flatten header to find "County" and "Access"
                header = [str(x).lower() for x in table[0]]
                if "county" in str(header) and ("%" in str(header) or "access" in str(header)):
                    # Map Columns
                    col_map = {'name': -1, 'lives': -1, 'access': -1, 'dist': -1}
                    for i, col in enumerate(header):
                        if "county" in col: col_map['name'] = i
                        if "member" in col or "#" in col: col_map['lives'] = i
                        if "access" in col and "without" not in col: col_map['access'] = i
                        if "dist" in col: col_map['dist'] = i
                    
                    # Parse Rows
                    for row in table[1:]:
                        try:
                            extracted.append({
                                "County": row[col_map['name']],
                                "Lives": clean_numeric(row[col_map['lives']]),
                                "Access %": clean_numeric(row[col_map['access']]),
                                "Avg Dist": clean_numeric(row[col_map['dist']])
                            })
                        except: continue

    return pd.DataFrame(extracted), network_name

# --- MAIN UI ---
st.title("🛡️ Strategic Network Analyzer")
st.markdown("##### Detect gaps. Prescribe solutions. Close the deal.")

geo_file = st.file_uploader("Upload GeoAccess Report (PDF)", type=["pdf"])

if geo_file:
    df, net_name = run_geo_parser(geo_file)
    
    if not df.empty:
        st.success(f"📂 Analyzed Network: **{net_name}**")
        
        # 1. THE "PROBLEM FINDER"
        df['Risk'] = df['Access %'].apply(lambda x: 'Critical' if x < 85 else ('Warning' if x < 95 else 'Good'))
        critical = df[df['Risk'] == 'Critical']
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Counties", len(df))
        c2.metric("Avg Access", f"{df['Access %'].mean():.1f}%")
        c3.metric("Critical Gaps", len(critical), delta_color="inverse")
        
        # 2. VISUALIZE THE PAIN
        st.subheader("📍 Gap Identification Matrix")
        fig = px.scatter(df, x="Lives", y="Avg Dist", size="Lives", color="Risk",
                         hover_name="County", text="County",
                         color_discrete_map={'Good': '#00cc96', 'Warning': '#ffa500', 'Critical': '#ff4b4b'},
                         title="Distance vs. Member Density (Top Right = High Impact Gaps)")
        st.plotly_chart(fig, use_container_width=True)
        
        # 3. THE BROKER GUIDE (Prescriptive Logic)
        st.markdown("---")
        st.subheader("🧠 Broker Strategy Guide")
        
        if not critical.empty:
            st.markdown(f"""
            <div class="alert-card">
            <b>🚨 Critical Network Failures Detected</b><br>
            The following counties have access below 85%. This is your leverage point.
            </div>
            """, unsafe_allow_html=True)
            
            st.dataframe(critical)
            
            # DYNAMIC RECOMMENDATIONS
            st.markdown("### 🛠️ Recommended Fixes")
            
            # Fix 1: Disruption Report
            st.markdown(f"""
            <div class="strategy-card">
            <b>1. Request a Provider Disruption Report</b><br>
            Since <b>{critical.iloc[0]['County']}</b> has {critical.iloc[0]['Access %']}% access, ask {net_name} to run a disruption report specifically for the {int(critical['Lives'].sum())} lives in these counties.
            </div>
            """, unsafe_allow_html=True)
            
            # Fix 2: Travel Benefit
            if critical['Avg Dist'].max() > 20:
                st.markdown(f"""
                <div class="strategy-card">
                <b>2. Propose a "Travel & Lodging" Benefit</b><br>
                Members in <b>{critical.iloc[0]['County']}</b> are driving over {critical['Avg Dist'].max()} miles. 
                Suggest adding a travel reimbursement rider ($50/visit) for specialists > 50 miles away.
                </div>
                """, unsafe_allow_html=True)
                
            # Fix 3: Direct Contracting
            st.markdown(f"""
            <div class="strategy-card">
            <b>3. Explore Direct Contracting</b><br>
            If {net_name} cannot solve the gap in {critical.iloc[0]['County']}, consider a direct contract with the local hospital system or a "Wrap Network" like MultiPlan for this specific zip cluster.
            </div>
            """, unsafe_allow_html=True)
            
        else:
            st.markdown("""
            <div class="strategy-card">
            <b>✅ Network is Stable</b><br>
            No critical gaps found. Use this data to validate the renewal increase or defend against competitor poaching.
            </div>
            """, unsafe_allow_html=True)
            
    else:
        st.error("Could not parse county data. Ensure PDF matches the standard format.")
