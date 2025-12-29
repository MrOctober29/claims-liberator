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
    .metric-box {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
    }
    .big-stat { font-size: 32px; font-weight: 700; color: #ffffff; }
    .stat-label { font-size: 14px; color: #a0a0a0; }
    
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
    
    .disclaimer { font-size: 11px; color: #666; margin-top: 50px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# --- HELPER: CLEANING ---
def clean_numeric(val):
    if not val: return 0.0
    # Removes footnotes like '100.0 1' -> '100.0'
    s = str(val).split(' ')[0].replace(',', '').replace('%', '')
    try: return float(s)
    except: return 0.0

# --- ENGINE: GREEDY PARSER ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            
            for table in tables:
                if not table or len(table) < 2: continue
                
                for row in table:
                    # Filter out purely empty rows
                    if not row or len(row) < 3: continue
                    
                    # 1. GRAB NUMBERS FIRST (The Source of Truth)
                    # We look for ANY cell that looks like a number
                    numerics = []
                    for cell in row:
                        val = clean_numeric(cell)
                        if val > 0: numerics.append(val)
                    
                    # We need at least 2 numbers (Lives + Distance) to consider this valid data
                    if len(numerics) >= 2:
                        
                        # 2. IDENTIFY COUNTY NAME
                        # If the row has valid numbers, we assume the first text cell is the name
                        county_cand = str(row[0]).strip()
                        
                        # Fix: If Col 0 is "Large Metro" or empty, grab Col 1
                        if not county_cand or "Metro" in county_cand or "Micro" in county_cand:
                            if len(row) > 1: county_cand = str(row[1]).strip()
                            
                        # Final Garbage Check: If name is "Total", skip it (we sum it ourselves)
                        if "Total" in county_cand or "Average" in county_cand: continue

                        # 3. ASSIGN VALUES
                        # Assumption: Largest Int = Lives. Smallest Float = Distance.
                        lives = max(numerics)
                        
                        # Get distance (remove the lives count from the pool)
                        remaining = [n for n in numerics if n != lives]
                        dist = min(remaining) if remaining else 0.0
                        
                        # Sanity Check: If "Distance" is 100.0, it's likely the Access % column
                        if dist == 100.0 and len(remaining) > 1:
                            dist = sorted(remaining)[0]
                            
                        extracted_data.append({
                            "County": county_cand,
                            "Lives": int(lives),
                            "Avg Dist": dist,
                            "Raw Data": str(row) # For debugging if needed
                        })

    df = pd.DataFrame(extracted_data)
    
    if not df.empty:
        # Deduplicate based on exact match of Name + Lives + Dist
        df = df.drop_duplicates(subset=['County', 'Lives', 'Avg Dist'])
        
    return df

# --- MAIN UI ---
st.title("🛡️ Network Intelligence Suite")
st.markdown("##### Strategic Network Analysis")

uploaded_file = st.file_uploader("Upload GeoAccess PDF", type=["pdf"])

if uploaded_file:
    with st.spinner("Extracting Data..."):
        df = run_geo_parser(uploaded_file)

    if not df.empty:
        # Aggregation
        final_df = df.groupby('County').agg({'Lives': 'max', 'Avg Dist': 'mean'}).reset_index()
        
        # Risk Analysis
        final_df['Risk Level'] = final_df['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else ('Warning' if x > 10 else 'Stable'))
        critical = final_df[final_df['Risk Level'] == 'Critical'].sort_values('Avg Dist', ascending=False)
        
        # Metrics
        total_lives = final_df['Lives'].sum()
        w_avg_dist = (final_df['Lives'] * final_df['Avg Dist']).sum() / total_lives if total_lives else 0
        
        # --- TOP LEVEL METRICS ---
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,.0f}</div><div class="stat-label">Lives Analyzed</div></div>""", unsafe_allow_html=True)
        c2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
        c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Counties (>15mi)</div></div>""", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # --- DATA GRID ---
        st.subheader("📍 County Access Ledger")
        st.dataframe(
            final_df.sort_values("Avg Dist", ascending=False),
            column_order=("County", "Lives", "Avg Dist", "Risk Level"),
            column_config={
                "County": "County Name",
                "Lives": st.column_config.NumberColumn("Member Count", format="%d"),
                "Avg Dist": st.column_config.ProgressColumn("Avg Drive (Miles)", format="%.1f mi", min_value=0, max_value=max(final_df['Avg Dist'].max(), 20)),
                "Risk Level": st.column_config.TextColumn("Status"),
            },
            use_container_width=True,
            height=400,
            hide_index=True
        )

        # --- STRATEGY ---
        st.markdown("---")
        st.subheader("🧠 Strategic Advisor Plan")

        if not critical.empty:
            top_county = critical.iloc[0]
            st.error(f"🔥 **Primary Risk Target: {top_county['County']}**")
            st.markdown(f"**The Issue:** {top_county['Lives']} members are driving **{top_county['Avg Dist']:.1f} miles**.")
            
            c_strat1, c_strat2 = st.columns(2)
            with c_strat1:
                with st.container(border=True):
                    st.markdown("#### 1. Contract Strategy")
                    st.markdown("**Safe Harbor Clause**")
                    st.caption("Negotiate In-Network deductibles for claims in this county if no provider is within 15 miles.")
            with c_strat2:
                with st.container(border=True):
                    st.markdown("#### 2. Tactical Fix")
                    st.markdown("**Travel Rider**")
                    st.caption(f"Implement a travel reimbursement ($50/visit) for members in {top_county['County']}.")
        
        else:
            st.success("✅ **Network is Stable.** No critical access gaps detected.")

        st.markdown("---")
        st.caption("⚠️ **Disclaimer:** Data is extracted programmatically. Please verify totals with the carrier report.")

    else:
        st.error("⚠️ No Data Found")
        st.markdown("We couldn't extract any valid data rows. Please check if the PDF is a scanned image.")
