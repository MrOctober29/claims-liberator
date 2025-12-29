import streamlit as st
import pdfplumber
import pandas as pd

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
    s = str(val).strip()
    # Must have a comma (Name, ST) and no numbers in the name part
    if "," not in s or len(s) < 4: return False
    if any(char.isdigit() for char in s): return False
    return True

# --- ENGINE: ROBUST PARSER (With De-Duplication) ---
@st.cache_data
def run_geo_parser(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                
                for row in table:
                    if not row or len(row) < 3: continue
                    
                    # 1. FIND THE COUNTY
                    county_cand = str(row[0]).strip()
                    if not is_valid_county(county_cand):
                        if len(row) > 1 and is_valid_county(row[1]):
                            county_cand = str(row[1]).strip()
                            data_start_idx = 2
                        else: continue
                    else:
                        data_start_idx = 1

                    # 2. EXTRACT NUMBERS
                    numerics = []
                    for cell in row[data_start_idx:]:
                        val = clean_numeric(cell)
                        if val > 0: numerics.append(val)
                    
                    if len(numerics) >= 2:
                        lives = max(numerics)
                        remaining = [n for n in numerics if n != lives]
                        dist = min(remaining) if remaining else 0.0
                        
                        # Fix for the "100.0" distance bug
                        if dist == 100.0 and len(remaining) > 1:
                            dist = sorted(remaining)[0]
                            
                        extracted_data.append({
                            "County": county_cand,
                            "Lives": int(lives),
                            "Avg Dist": dist,
                            "Access %": 100.0
                        })

    df = pd.DataFrame(extracted_data)
    
    if not df.empty:
        # --- THE FIX: DEDUPLICATION ---
        # We drop exact duplicates where County, Lives, and Distance are identical.
        # This handles pages that repeat the same data (like Page 5 and Page 8).
        df = df.drop_duplicates(subset=['County', 'Lives', 'Avg Dist'])
        
    return df

# --- MAIN UI ---
st.title("🛡️ Network Intelligence Suite")
st.markdown("##### Strategic Network Analysis")

uploaded_file = st.file_uploader("Upload GeoAccess PDF", type=["pdf"])

if uploaded_file:
    with st.spinner("Extracting & Cleaning Data..."):
        df = run_geo_parser(uploaded_file)

    if not df.empty:
        # Aggregation
        # We sum lives ONLY if the county appears once per list. 
        # Since we already deduped above, this is safe.
        final_df = df.groupby('County').agg({'Lives': 'max', 'Avg Dist': 'mean'}).reset_index()
        
        # Metrics
        total_lives = final_df['Lives'].sum()
        w_avg_dist = (final_df['Lives'] * final_df['Avg Dist']).sum() / total_lives if total_lives else 0
        
        # Risk Analysis
        final_df['Risk Level'] = final_df['Avg Dist'].apply(lambda x: 'Critical' if x > 15 else ('Warning' if x > 10 else 'Stable'))
        critical = final_df[final_df['Risk Level'] == 'Critical'].sort_values('Avg Dist', ascending=False)
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""<div class="metric-box"><div class="big-stat">{total_lives:,.0f}</div><div class="stat-label">Lives Analyzed</div></div>""", unsafe_allow_html=True)
        c2.markdown(f"""<div class="metric-box"><div class="big-stat">{w_avg_dist:.1f} mi</div><div class="stat-label">Avg Drive Distance</div></div>""", unsafe_allow_html=True)
        c3.markdown(f"""<div class="metric-box"><div class="big-stat" style="color:#ff4b4b">{len(critical)}</div><div class="stat-label">Critical Counties (>15mi)</div></div>""", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # --- CLEAN DATA GRID ---
        st.subheader("📍 County Access Ledger")
        st.caption("Sorted by longest drive time. Critical areas highlighted in red.")
        
        st.dataframe(
            final_df.sort_values("Avg Dist", ascending=False),
            column_order=("County", "Lives", "Avg Dist", "Risk Level"),
            column_config={
                "County": "County Name",
                "Lives": st.column_config.NumberColumn("Member Count", format="%d"),
                "Avg Dist": st.column_config.ProgressColumn(
                    "Avg Drive (Miles)",
                    help="Average miles to nearest provider",
                    format="%.1f mi",
                    min_value=0,
                    max_value=max(final_df['Avg Dist'].max(), 20),
                ),
                "Risk Level": st.column_config.TextColumn("Status"),
            },
            use_container_width=True,
            height=400,
            hide_index=True
        )

        # --- STRATEGIC ADVISOR PLAN ---
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
        st.caption("⚠️ **Disclaimer:** Data is extracted programmatically from uploaded carrier reports. Formatting inconsistencies in PDF source files may affect accuracy. Please verify critical figures with the carrier.")

    else:
        st.warning("⚠️ No valid county data found.")
        st.markdown("The parser couldn't find rows formatted like **'County, State'** (e.g., 'Adair, KY').")
