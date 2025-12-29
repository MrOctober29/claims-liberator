import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Apex: Benefit Intelligence Cloud", layout="wide", initial_sidebar_state="expanded")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #0f1116; }
    section[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
    .metric-box { background-color: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 24px; text-align: center; margin-bottom: 20px; }
    .big-stat { font-size: 32px; font-weight: 700; color: #ffffff; }
    .stat-label { font-size: 13px; color: #a0a0a0; text-transform: uppercase; letter-spacing: 1.2px; font-weight: 600; }
    .strategy-card { background-color: rgba(30, 41, 59, 0.5); border-left: 4px solid #00cc96; padding: 20px; border-radius: 4px; margin-bottom: 15px; }
    .alert-card { background-color: rgba(100, 20, 20, 0.3); border-left: 4px solid #ff4b4b; padding: 20px; border-radius: 4px; margin-bottom: 15px; }
    .locked-module { border: 1px dashed #444; border-radius: 10px; padding: 40px; text-align: center; color: #666; background-color: rgba(0,0,0,0.2); }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def clean_numeric(val):
    if not val: return 0.0
    s = str(val).split(' ')[0].replace(',', '').replace('%', '')
    try: return float(s)
    except: return 0.0

def is_valid_county_name(s):
    s = str(s).strip()
    if len(s) < 4: return False
    if "," not in s: return False
    blacklist = ["total", "member", "group", "metro", "micro", "rural", "urban", "grand", "access", "analysis", "without"]
    if any(x in s.lower() for x in blacklist): return False
    return True

def split_cell_values(cell_text):
    if not cell_text: return []
    return [x.strip() for x in str(cell_text).split('\n') if x.strip()]

# --- ENGINE: HYBRID PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "survey" in text.lower() or "questionnaire" in text.lower() or "cahps" in text.lower(): continue

            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                
                for row in table:
                    clean_row = [str(x).strip() if x else "" for x in row]
                    
                    # 1. FIND COUNTY COLUMN
                    county_idx = -1
                    county_values = []
                    for i, cell in enumerate(clean_row):
                        values = split_cell_values(cell)
                        if values and is_valid_county_name(values[0]):
                            county_idx = i
                            county_values = values
                            break
                    if county_idx == -1: continue

                    # 2. FIND DATA COLUMNS
                    num_rows = len(county_values)
                    lives_values = []
                    dist_values = []
                    
                    candidate_cols = []
                    for i, cell in enumerate(clean_row):
                        if i == county_idx: continue
                        values = split_cell_values(cell)
                        # Relaxed matching: Allow columns with MORE values (sometimes headers sneak in)
                        if len(values) >= num_rows:
                            # Verify numeric content
                            if any(clean_numeric(v) >= 0 for v in values[:num_rows]):
                                candidate_cols.append(values[:num_rows])

                    # 3. DECISION LOGIC (Lives vs Distance)
                    if candidate_cols:
                        # Lives is typically the column with the Largest Integer Max
                        # Distance typically has the Smallest Float Max (and usually contains decimals)
                        
                        # Sort cols by their Max Value
                        candidate_cols.sort(key=lambda col: max([clean_numeric(x) for x in col]), reverse=True)
                        
                        if len(candidate_cols) >= 1:
                            lives_values = candidate_cols[0] # Largest numbers = Lives
                        
                        if len(candidate_cols) >= 2:
                            # Look for the smallest max value that isn't lives
                            dist_values = candidate_cols[-1] # Smallest numbers = Distance

                    # 4. DATA EXTRACTION
                    if lives_values:
                        for j in range(num_rows):
                            c_name = county_values[j]
                            l_val = clean_numeric(lives_values[j])
                            d_val = clean_numeric(dist_values[j]) if dist_values else 0.0
                            
                            # Filter "Grand Total" lines that might look like counties
                            if l_val > 200000: continue
                            
                            extracted_data.append({
                                "County": c_name,
                                "Lives": int(l_val),
                                "Avg Dist": d_val
                            })

    df = pd.DataFrame(extracted_data)
    
    if not df.empty:
        # --- THE FIX ---
        
        # STEP 1: Strict Row Deduplication
        # This removes the exact duplicate pages in the Humana Report (Page 5 vs Page 8)
        df = df.drop_duplicates(subset=['County', 'Lives', 'Avg Dist'])
        
        # STEP 2: Aggregation by Sum
        # This correctly adds up the split zip codes in the Complex Report (Adair 122 + Adair 51)
        # Note: We take Weighted Average for distance
        
        # Helper for weighted average
        df['Weighted_Dist'] = df['Lives'] * df['Avg Dist']
        
        df = df.groupby('County').agg({
            'Lives': 'sum',
            'Weighted_Dist': 'sum'
        }).reset_index()
        
        df['Avg Dist'] = df['Weighted_Dist'] / df['Lives']
        
        # STEP 3: Grand Total Safety Net
        # If a single row contains > 90% of the total lives, it's a Summary Row. Kill it.
        total_sum = df['Lives'].sum()
        df = df[df['Lives'] < (total_sum * 0.9)]
        
    return df

# --- UI LOGIC ---
st.sidebar.markdown("## **Apex** Intelligence")
st.sidebar.caption("Benefit Advisory Cloud • v3.3")
st.sidebar.markdown("---")
menu = st.sidebar.radio("Platform Modules", ["Network Disruption", "Claims Intelligence", "Census Mapper", "SBC Decoder"], format_func=lambda x: f"🔒 {x}" if x != "Network Disruption" else f"🚀 {x}")
st.sidebar.markdown("---")
st.sidebar.info("**Client:** Global Corp Inc.\n\n**Plan Year:** 2026\n\n**Analyst:** J. Doe")

if menu == "Network Disruption":
    st.title("🚀 Network Disruption Analysis")
    st.markdown("##### Assess adequacy, identify leakage risks, and generate leverage.")
    uploaded_file = st.file_uploader("Upload Carrier GeoAccess Report (PDF)", type=["pdf"])

    if uploaded_file:
        with st.spinner("Initializing Apex Parsing Engine..."):
            df = run_geo_parser(uploaded_file)

        if not df.empty:
            total_lives = df['Lives'].sum()
            w_avg_dist = (df['Lives'] * df['Avg Dist']).sum() / total_lives if total_lives else 0
            df['Risk Level'] = df['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else ('Warning' if x > 10 else 'Stable'))
            critical = df[df['Risk Level'] == 'Critical'].sort_values('Avg Dist', ascending=False)
            
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,.0f}</div><div class="stat-label">Lives Mapped</div></div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
            c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Counties (>15mi)</div></div>""", unsafe_allow_html=True)
            
            st.markdown("### 📍 County Access Ledger")
            st.dataframe(df.sort_values("Avg Dist", ascending=False), column_order=("County", "Lives", "Avg Dist", "Risk Level"), column_config={"County": "County Name", "Lives": st.column_config.NumberColumn("Member Count", format="%d"), "Avg Dist": st.column_config.ProgressColumn("Avg Drive (Miles)", format="%.1f mi", min_value=0, max_value=max(df['Avg Dist'].max(), 20)), "Risk Level": st.column_config.TextColumn("Status")}, use_container_width=True, height=500, hide_index=True)

            st.markdown("### 🧠 Strategic Advisor Plan")
            if not critical.empty:
                top_county = critical.iloc[0]
                st.markdown(f"""<div class="alert-card"><div class="alert-title">🔥 Primary Target: {top_county['County']}</div>{top_county['Lives']} members are driving <b>{top_county['Avg Dist']:.1f} miles</b>.</div>""", unsafe_allow_html=True)
                col_a, col_b = st.columns(2)
                with col_a: st.markdown("""<div class="strategy-card"><b>1. Contract Strategy: Safe Harbor</b><br>Negotiate In-Network deductibles if no provider is within 15 miles.</div>""", unsafe_allow_html=True)
                with col_b: st.markdown(f"""<div class="strategy-card"><b>2. Tactical Fix: Travel Rider</b><br>Implement a travel reimbursement ($50/visit) for members in {top_county['County']}.</div>""", unsafe_allow_html=True)
            else: st.success("✅ Network is Stable.")
        else: st.warning("⚠️ No valid data found. Ensure PDF is a standard GeoAccess report.")

elif menu == "Claims Intelligence":
    st.title("🔒 Claims Intelligence")
    st.markdown("""<div class="locked-module"><h2>🚧 Module Coming Soon</h2><p>High Cost Claimant & J-Code Scrubbing.</p></div>""", unsafe_allow_html=True)
elif menu == "Census Mapper":
    st.title("🔒 Census Mapper")
    st.markdown("""<div class="locked-module"><h2>🚧 Module Coming Soon</h2><p>Geographic Risk Heatmaps.</p></div>""", unsafe_allow_html=True)
elif menu == "SBC Decoder":
    st.title("🔒 SBC Decoder")
    st.markdown("""<div class="locked-module"><h2>🚧 Module Coming Soon</h2><p>AI Plan Design Comparison.</p></div>""", unsafe_allow_html=True)
