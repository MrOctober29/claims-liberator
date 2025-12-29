import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Apex: Benefit Intelligence Cloud", layout="wide", initial_sidebar_state="expanded")

# --- CUSTOM CSS (THE "PLATFORM" LOOK) ---
st.markdown("""
    <style>
    /* Global Dark Theme Polish */
    .stApp { background-color: #0f1116; }
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    
    /* Card Styling */
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
    
    /* Feature Tags */
    .beta-tag {
        background-color: #00cc96; color: black; padding: 2px 8px; 
        border-radius: 4px; font-size: 10px; font-weight: bold; vertical-align: middle;
    }
    .locked-tag {
        background-color: #ff4b4b; color: white; padding: 2px 8px; 
        border-radius: 4px; font-size: 10px; font-weight: bold; vertical-align: middle;
    }
    
    /* Strategy Cards */
    .strategy-card {
        background-color: rgba(30, 41, 59, 0.5);
        border-left: 4px solid #00cc96;
        padding: 20px; border-radius: 4px; margin-bottom: 15px;
    }
    .alert-card {
        background-color: rgba(100, 20, 20, 0.3);
        border-left: 4px solid #ff4b4b;
        padding: 20px; border-radius: 4px; margin-bottom: 15px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER: CLEANING ---
def clean_numeric(val):
    if not val: return 0.0
    s = str(val).split(' ')[0].replace(',', '').replace('%', '')
    try: return float(s)
    except: return 0.0

def is_valid_county_row(name):
    """STRICT FILTER: Kills summary rows like 'Metro', 'Micro', 'Total'."""
    s = str(name).strip()
    if len(s) < 4: return False
    
    s_lower = s.lower()
    blacklist = ["total", "member", "group", "question", "metro", "micro", "rural", "urban", "all members", "grand", "access"]
    if any(x in s_lower for x in blacklist): return False
    
    # Must look like a location (Text)
    if s.replace(' ', '').isdigit(): return False
    
    return True

# --- ENGINE: GEO PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Skip Survey Pages (Garbage Avoidance)
            if "survey" in text.lower() or "questionnaire" in text.lower() or "cahps" in text.lower(): continue

            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                
                for row in table:
                    if not row or len(row) < 3: continue
                    
                    # 1. FIND COUNTY NAME
                    county_cand = str(row[0]).strip()
                    data_start_idx = 1
                    
                    if not is_valid_county_row(county_cand):
                        if len(row) > 1 and is_valid_county_row(row[1]):
                            county_cand = str(row[1]).strip()
                            data_start_idx = 2
                        else: continue

                    # 2. EXTRACT NUMBERS
                    numerics = []
                    for cell in row[data_start_idx:]:
                        val = clean_numeric(cell)
                        if val > 0: numerics.append(val)
                    
                    if len(numerics) >= 2:
                        lives = max(numerics)
                        
                        # HARD FILTER: Remove the "Grand Total" row (144,875) if it got scraped
                        if lives > 144000 and lives < 146000: continue 
                        if lives > 400000: continue # Sanity cap

                        remaining = [n for n in numerics if n != lives]
                        dist = min(remaining) if remaining else 0.0
                        
                        if dist == 100.0 and len(remaining) > 1: dist = sorted(remaining)[0]
                            
                        extracted_data.append({
                            "County": county_cand.replace('\n', ' '),
                            "Lives": int(lives),
                            "Avg Dist": dist
                        })

    df = pd.DataFrame(extracted_data)
    if not df.empty:
        # Deduplicate: Group by County and take MAX lives (Handles Page 5 vs Page 8 repeats)
        df = df.groupby('County').agg({'Lives': 'max', 'Avg Dist': 'max'}).reset_index()
    return df

# --- SIDEBAR: PLATFORM NAVIGATION ---
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/1152/1152912.png", width=50) # Generic Shield Icon
st.sidebar.markdown("## **Apex Intelligence**")
st.sidebar.caption("The Advisor's Edge")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Modules",
    ["Network Disruption", "Claims Analyzer", "Census Mapper", "SBC Decoder"],
    format_func=lambda x: f"🔒 {x}" if x != "Network Disruption" else f"🚀 {x}"
)

st.sidebar.markdown("---")
st.sidebar.info("**Client:** Global Corp Inc.\n\n**Plan Year:** 2026\n\n**Advisor:** J. Doe")

# --- MODULE 1: NETWORK DISRUPTION (ACTIVE) ---
if menu == "Network Disruption":
    st.title("🚀 Network Disruption Analysis")
    st.markdown("##### Assess network adequacy, identify gaps, and generate negotiation leverage.")
    
    uploaded_file = st.file_uploader("Upload Carrier GeoAccess Report (PDF)", type=["pdf"])

    if uploaded_file:
        with st.spinner("Parsing Carrier Data Structure..."):
            df = run_geo_parser(uploaded_file)

        if not df.empty:
            # Metrics
            total_lives = df['Lives'].sum()
            w_avg_dist = (df['Lives'] * df['Avg Dist']).sum() / total_lives if total_lives else 0
            
            df['Risk Level'] = df['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else ('Warning' if x > 10 else 'Stable'))
            critical = df[df['Risk Level'] == 'Critical'].sort_values('Avg Dist', ascending=False)
            
            # --- DASHBOARD ---
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,.0f}</div><div class="stat-label">Lives Analyzed</div></div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
            c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Counties (>15mi)</div></div>""", unsafe_allow_html=True)
            
            st.markdown("### 📍 County Access Ledger")
            st.dataframe(
                df.sort_values("Avg Dist", ascending=False),
                column_order=("County", "Lives", "Avg Dist", "Risk Level"),
                column_config={
                    "County": "County Name",
                    "Lives": st.column_config.NumberColumn("Member Count", format="%d"),
                    "Avg Dist": st.column_config.ProgressColumn("Avg Drive (Miles)", format="%.1f mi", min_value=0, max_value=max(df['Avg Dist'].max(), 20)),
                    "Risk Level": st.column_config.TextColumn("Status"),
                },
                use_container_width=True, height=500, hide_index=True
            )

            st.markdown("### 🧠 Strategic Advisor Plan")
            if not critical.empty:
                top_county = critical.iloc[0]
                st.markdown(f"""
                <div class="alert-card">
                    <div class="alert-title">🔥 Primary Target: {top_county['County']}</div>
                    {top_county['Lives']} members are driving <b>{top_county['Avg Dist']:.1f} miles</b>.
                </div>
                """, unsafe_allow_html=True)
                
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("""<div class="strategy-card"><b>1. Contract Strategy: Safe Harbor</b><br>Negotiate In-Network deductibles for claims in this county if no provider is within 15 miles.</div>""", unsafe_allow_html=True)
                with col_b:
                    st.markdown(f"""<div class="strategy-card"><b>2. Tactical Fix: Travel Rider</b><br>Implement a travel reimbursement ($50/visit) for members in {top_county['County']}.</div>""", unsafe_allow_html=True)
            else:
                st.success("✅ Network is Stable. No critical gaps.")

        else:
            st.warning("⚠️ No valid data found. Ensure PDF is a standard GeoAccess report.")

# --- MODULE 2: CLAIMS (LOCKED) ---
elif menu == "Claims Analyzer":
    st.title("🔒 Claims Intelligence")
    st.markdown("### 🚧 Module In Development")
    st.info("The Claims Parsing Engine is currently in Beta testing with select enterprise partners.")
    st.markdown("""
    **Capabilities Coming Soon:**
    * **High Cost Claimant (HCC) Identification:** Instantly flag diagnoses > $50k.
    * **J-Code Scrubbing:** Detect pharmacy rebates hidden in medical claims.
    * **Network Leakage:** Map OON spend by facility.
    """)
    st.image("https://placehold.co/800x300/1e2129/FFF?text=Claims+Dashboard+Preview", use_container_width=True)

# --- MODULE 3: CENSUS (LOCKED) ---
elif menu == "Census Mapper":
    st.title("🔒 Census Demographics")
    st.markdown("### 🚧 Module In Development")
    st.markdown("Advanced heatmap visualization and risk-scoring based on member zip codes.")

# --- MODULE 4: SBC (LOCKED) ---
elif menu == "SBC Decoder":
    st.title("🔒 SBC Decoder")
    st.markdown("### 🚧 Module In Development")
    st.markdown("AI-powered comparison of Summary of Benefits & Coverage documents.")
