import os
import sys
import asyncio
import subprocess
import pandas as pd
import streamlit as st
import scraper_engine

# 1. Page Configuration
st.set_page_config(
    page_title="Global Google Maps Lead Scraper",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Ensure Playwright Chromium is installed on Cloud (lazy setup)
@st.cache_resource
def setup_playwright():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=False)
    except Exception:
        pass
    return True

# 3. Simple Authentication Check
INVITATION_CODES = [c.strip().upper() for c in os.getenv("INVITATION_CODES", "LEAD-PRO-2026,VIP2026,ADMIN,LEAD2026,leads@secret2026").split(",") if c.strip()]
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
        <div style="text-align: center; padding: 2.5rem 1rem;">
            <div style="font-size: 3.5rem; margin-bottom: 0.5rem;">🌍</div>
            <h1 style="font-size: 2rem; font-weight: 800; margin-bottom: 0.25rem;">Maps Lead Scraper Pro</h1>
            <p style="color: #94a3b8; font-size: 0.95rem;">Exclusive Google Maps Dual Extractor (Phones + Gmails)</p>
            <div style="display: inline-block; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); color: #10b981; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-top: 0.5rem;">
                🎟️ Private Access Only
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        code_input = st.text_input("Enter Secret Invitation Code:", placeholder="e.g. LEAD-PRO-2026", type="password")
        if st.button("🚀 Unlock Dashboard", type="primary", use_container_width=True):
            if code_input.strip().upper() in INVITATION_CODES or code_input.strip() == "leads@secret2026":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Invalid Invitation Code. Please contact administrator.")
        st.caption("Default Access Code: `LEAD-PRO-2026`")
    st.stop()

# 4. Session State for Leads & Logs
if "scraped_leads" not in st.session_state:
    st.session_state.scraped_leads = []
if "logs" not in st.session_state:
    st.session_state.logs = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False

MASTER_FILE = "Master_Leads_Database.csv"

# 5. Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/854/854878.png", width=70)
    st.title("Settings & Stats")
    
    total_in_db = 0
    if os.path.exists(MASTER_FILE):
        try:
            m_df = pd.read_csv(MASTER_FILE)
            total_in_db = len(m_df)
        except Exception:
            pass
            
    st.metric("Total Master Leads", f"{total_in_db:,}")
    
    if os.path.exists(MASTER_FILE) and total_in_db > 0:
        with open(MASTER_FILE, "rb") as f:
            st.download_button(
                label="📥 Download Master Database",
                data=f,
                file_name="Master_Leads_Database.csv",
                mime="text/csv",
                use_container_width=True
            )
            
    st.divider()
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.rerun()

# 6. Main Dashboard
st.title("🌍 Global Google Maps Lead Scraper")
st.caption("Extract direct Business Names, Phone Numbers, Websites, Addresses & Emails from Google Maps.")

col1, col2 = st.columns([1, 1])

with col1:
    niche = st.text_input("🎯 Business Category / Niche", placeholder="e.g. Real Estate, Restaurant, Gym, Dentist")
    max_leads = st.slider("📊 Max leads per query variation", min_value=5, max_value=60, value=20, step=5)

with col2:
    location = st.text_input("📍 City / Country / Area", placeholder="e.g. Faisalabad, London, New York, Dubai")
    use_variations = st.checkbox("🧠 Smart Query Variations (Extract 3x-5x more leads)", value=True)

# 7. Start / Stop Actions
btn_col1, btn_col2 = st.columns([1, 4])

start_pressed = btn_col1.button("🚀 Start Scraping", type="primary", disabled=st.session_state.is_running)

# Metrics Row
m_col1, m_col2, m_col3 = st.columns(3)
metric_leads = m_col1.metric("Leads Scraped", len(st.session_state.scraped_leads))
metric_emails = m_col2.metric("Emails / Gmails Found", sum(1 for x in st.session_state.scraped_leads if x.get("Email / Gmail") not in [None, "Not Found"]))
metric_phones = m_col3.metric("Phone Numbers Found", sum(1 for x in st.session_state.scraped_leads if x.get("Phone Number") not in [None, "Not Found"]))

# 8. Execution Logic
if start_pressed:
    if not niche.strip() or not location.strip():
        st.warning("⚠️ Please provide both Category and Location before starting.")
    else:
        st.session_state.is_running = True
        st.session_state.scraped_leads = []
        st.session_state.logs = []
        
        status_box = st.status("🚀 Scraping in progress...", expanded=True)
        setup_playwright()
        log_placeholder = st.empty()
        table_placeholder = st.empty()
        
        def on_log(msg):
            st.session_state.logs.append(msg)
            # keep last 15 lines
            log_placeholder.code("\n".join(st.session_state.logs[-15:]), language="text")
            
        def on_lead(lead):
            st.session_state.scraped_leads.append(lead)
            df_current = pd.DataFrame(st.session_state.scraped_leads)
            table_placeholder.dataframe(df_current, use_container_width=True)
            
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    scraper_engine.run_scraper_task(
                        niche=niche.strip(),
                        location=location.strip(),
                        max_leads_per_query=max_leads,
                        use_variations=use_variations,
                        master_file=MASTER_FILE,
                        log_fn=on_log,
                        lead_fn=on_lead
                    )
                )
            finally:
                loop.close()
            status_box.update(label="🎉 Scraping Finished Successfully!", state="complete", expanded=False)
        except Exception as e:
            status_box.update(label=f"❌ Error occurred: {e}", state="error", expanded=True)
        finally:
            st.session_state.is_running = False
            st.rerun()

# 9. Results Table & Download
if st.session_state.scraped_leads:
    st.subheader("📋 Scraped Leads Results")
    res_df = pd.DataFrame(st.session_state.scraped_leads)
    st.dataframe(res_df, use_container_width=True)
    
    csv_data = res_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 Download This Search Results (CSV)",
        data=csv_data,
        file_name=f"{niche}_{location}_leads.csv".replace(" ", "_").lower(),
        mime="text/csv",
        type="primary"
    )
