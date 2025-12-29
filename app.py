import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Network Intelligence Suite", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #0f1116; }
    .big-stat { font-size: 32px; font-weight: 700; color: #ffffff; }
    .stat-label { font-size: 14px; color: #a0a0a0; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER: CLEANING ---
def clean_numeric(val):
    if not val: return 0.0
    s = str(val).split(' ')[0].replace(',', '').replace('%', '')
    try: return float(s)
    except: return 0.0

def is_valid_county(val):
    """
    STRICT FILTER: Only accepts format 'Name, ST' (e.g., 'Adair, KY').
    Reject 'Large Metro', 'Total', 'Micro', etc.
    """
    s = str(val).strip()
    # Must have a comma and be longer than 3 chars (e.g. "X, Y" is min)
    if "," not in s or len(s) < 4: return False
    # Reject lines with numbers in the name (e.g. "Total 2024")
    if any(char.isdigit() for char in s): return False
    return True

# --- ENGINE: ROBUST PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            
            for table in tables:
                if not table or len(table) < 2: continue
                
                # We iterate through ROWS, not headers, to find the pattern
                for row in table:
                    # Filter out short rows or empty rows
                    if not row or len(row) < 3: continue
                    
                    # 1. FIND THE COUNTY NAME
                    # Usually in Col 0, but sometimes Col 1 if Col 0 is "Large Metro"
                    county_cand = str(row[0]).strip()
                    
                    # If Col 0 isn't a county (e.g. "Large Metro"), check Col 1
                    if not is_valid_county(county_cand):
                        if len(row) > 1 and is_valid_county(row[1]):
                            county_cand = str(row[1]).strip()
                            # If we shifted to Col 1, the data usually shifts too
                            data_start_idx = 2
                        else:
                            continue # Skip this row, it's garbage
                    else:
                        data_start_idx = 1

                    # 2. EXTRACT NUMBERS (The "Smart Scan")
                    # We grab all numbers in the rest of the row
                    numerics = []
                    for cell in row[data_start_idx:]:
                        val = clean_numeric(cell)
                        if val > 0: numerics.append(val)
                    
                    # 3. ASSIGN DATA (Heuristic Logic)
                    # We need at least 2 numbers: [Lives, Distance] or [Lives, Access, Distance]
                    if len(numerics) >= 2:
                        # Assumption for Quest/Optum Reports:
                        # Largest Integer = Member Count
                        # Float between 0-50 = Distance
                        # Float > 80 (usually 100) = Access %
                        
                        lives = max(numerics) # Lives is usually the biggest number
                        
                        # Remove lives from list to find distance
                        remaining = [n for n in numerics if n != lives]
                        
                        dist = 0.0
                        access = 100.0
                        
                        if remaining:
                            # Distance is usually the smallest non-zero number
                            dist = min(remaining)
                            
                        # Edge Case: If Distance is somehow parsed as 100.0 (like in your screenshot), 
                        # we correct it. Real average distances > 60 miles are rare.
                        if dist == 100.0 and len(remaining) > 1:
                            dist = sorted(remaining)[0] # Take the smaller one
                            
                        extracted_data.append({
                            "County": county_cand,
                            "Lives": int(lives),
                            "Avg Dist": dist,
                            "Access %": 100.0 # Defaulting to 100 unless we see a gap
                        })

    return pd.DataFrame(extracted_data)

# --- MAIN UI ---
st.title("🛡️ Network Intelligence Suite")
st.markdown("##### Strategic Network Analysis")

uploaded_file = st.file_uploader("Upload GeoAccess PDF", type=["pdf"])

if uploaded_file:
    with st.spinner("Extracting & Cleaning Data..."):
        df = run_geo_parser(uploaded_file)

    if not df.empty:
        # Aggregation (Handle dupes)
        df = df.groupby('County').agg({'Lives': 'sum', 'Avg Dist': 'mean'}).reset_index()
        
        # Risk Analysis
        df['Risk Level'] = df['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else ('Warning' if x > 10 else 'Stable'))
        critical = df[df['Risk Level'] == 'Critical'].sort_values('Avg Dist', ascending=False)
        
        # --- METRICS ---
        total_lives = df['Lives'].sum()
        w_avg_dist = (df['Lives'] * df['Avg Dist']).sum() / total_lives if total_lives else 0
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,.0f}</div><div class="stat-label">Lives Analyzed</div></div>""", unsafe_allow_html=True)
        c2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
        c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Counties (>15mi)</div></div>""", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # --- THE CLEAN DATA GRID (Replacing the confusing charts) ---
        st.subheader("📍 County Access Ledger")
        st.caption("Sorted by longest drive time. Critical areas highlighted in red.")
        
        # We use Streamlit's Native Column Config for a beautiful table
        st.dataframe(
            df.sort_values("Avg Dist", ascending=False),
            column_order=("County", "Lives", "Avg Dist", "Risk Level"),
            column_config={
                "County": "County Name",
                "Lives": st.column_config.NumberColumn("Member Count", format="%d"),
                "Avg Dist": st.column_config.ProgressColumn(
                    "Avg Drive (Miles)",
                    help="Average miles to nearest provider",
                    format="%.1f mi",
                    min_value=0,
                    max_value=max(df['Avg Dist'].max(), 20), # Cap visual at 20+
                ),
                "Risk Level": st.column_config.TextColumn("Status"),
            },
            use_container_width=True,
            height=400,
            hide_index=True
        )

        # --- ACTION PLAN (Native UI Components - No more HTML glitches) ---
        st.markdown("---")
        st.subheader("🧠 Strategic Advisor Plan")

        if not critical.empty:
            top_county = critical.iloc[0]
            
            # 1. The Alert Box
            st.error(f"🔥 **Primary Risk Target: {top_county['County']}**")
            st.markdown(f"""
            **The Issue:** {top_county['Lives']} members are driving an average of **{top_county['Avg Dist']:.1f} miles** to find care.
            This exceeds the standard benchmark (15 miles) and exposes the plan to leakage.
            """)
            
            c_strat1, c_strat2 = st.columns(2)
            
            with c_strat1:
                with st.container(border=True):
                    st.markdown("#### 1. Contract Strategy")
                    st.markdown("**Safe Harbor Clause**")
                    st.caption("Negotiate In-Network deductibles for any claim in this county if a provider isn't available within 15 miles.")
            
            with c_strat2:
                with st.container(border=True):
                    st.markdown("#### 2. Tactical Fix")
                    st.markdown("**Travel Rider**")
                    st.caption(f"Implement a travel reimbursement ($50/visit) specifically for members in {top_county['County']} to avoid ER usage.")
        
        else:
            st.success("✅ **Network is Stable.** No critical access gaps detected.")
            st.info("Leverage this report to defend the current carrier against narrow-network competitors.")

        # --- DISCLAIMER ---
        st.markdown("---")
        st.caption("⚠️ **Disclaimer:** Data is extracted programmatically from uploaded carrier reports. Formatting inconsistencies in PDF source files may affect accuracy. Please verify critical figures with the carrier.")

    else:
        st.warning("⚠️ No valid county data found.")
        st.markdown("The parser couldn't find rows formatted like **'County, State'** (e.g., 'Adair, KY'). Please ensure your PDF contains the County Detail pages.")
