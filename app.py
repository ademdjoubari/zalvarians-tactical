import streamlit as st
import pandas as pd
import requests
import re
from supabase import create_client, Client
from requests_oauthlib import OAuth2Session
from pyvis.network import Network
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 🛡️ SECURE CREDENTIALS FROM STREAMLIT SECRETS ---
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    CLIENT_ID = st.secrets["CLIENT_ID"]
    SECRET_KEY = st.secrets["SECRET_KEY"]
except Exception as e:
    st.error("⚠️ CRITICAL ERROR: Missing Secrets in Streamlit Settings.")
    st.info("Go to Settings > Secrets and add SUPABASE_URL, SUPABASE_KEY, CLIENT_ID, and SECRET_KEY.")
    st.stop()

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CONFIG & CONSTANTS ---
CALLBACK_URL = "https://zalvarians-tactical-ex8pp9wvn8kvnhn3t2qf8p.streamlit.app/"
TARGET_ALLIANCE_ID = 99014405 
SCOPES = ["esi-location.read_location.v1"]

# --- INTEL SCRAPER ---
@st.cache_data(ttl=604800)
def get_wh_intel(system_name):
    sys_name = system_name.upper().strip()
    if not (sys_name.startswith('J') and any(c.isdigit() for c in sys_name)) and sys_name != "THERA":
        return {"class": "K-Space", "effect": "None", "statics": []}
    try:
        url = f"http://anoik.is/systems/{sys_name}"
        res = requests.get(url, timeout=5)
        text = res.text
        wh_class = re.search(r'Class\s+([1-6]|12|13|14|15|16|17|18)', text)
        wh_class = f"C{wh_class.group(1)}" if wh_class else "Unknown"
        effect = "None"
        for eff in ["Pulsar", "Black Hole", "Cataclysmic Variable", "Magnetar", "Red Giant", "Wolf-Rayet"]:
            if eff in text: effect = eff; break
        statics = re.findall(r'href="/wormholes/([A-Z0-9]{4})"', text)
        return {"class": wh_class, "effect": effect, "statics": list(set([s for s in statics if s != 'K162']))}
    except: return None

# --- UI CONFIG ---
st.set_page_config(page_title="Zalvarians Alliance Command", layout="wide", page_icon="🛡️")

# --- AUTHENTICATION FLOW ---
if "token" not in st.session_state:
    st.title("🛡️ ZALVARIANS ALLIANCE LOGIN")
    esi = OAuth2Session(CLIENT_ID, redirect_uri=CALLBACK_URL, scope=SCOPES)
    login_url, _ = esi.authorization_url("https://login.eveonline.com/v2/oauth/authorize")
    
    st.markdown(f'''
        <div style="text-align: center; margin-top: 50px;">
            <a href="{login_url}" target="_self">
                <button style="padding:25px; background:#b30000; color:white; border:none; border-radius:8px; cursor:pointer; width:350px; font-weight:bold; font-size:20px; box-shadow: 0px 4px 15px rgba(255,0,0,0.3);">
                    CONNECT TO TACTICAL OVERLAY
                </button>
            </a>
            <p style="margin-top:20px; color:#888;">Authorized for Zalvarians Alliance (99014405) Only</p>
        </div>
    ''', unsafe_allow_html=True)
    
    if "code" in st.query_params:
        token = esi.fetch_token("https://login.eveonline.com/v2/oauth/token", code=st.query_params["code"], client_secret=SECRET_KEY)
        res = requests.get("https://login.eveonline.com/v2/oauth/verify", headers={"Authorization": f"Bearer {token['access_token']}"})
        char_data = res.json()
        
        # Alliance Gatekeeper
        detail = requests.get(f"https://esi.evetech.net/latest/characters/{char_data['CharacterID']}/").json()
        if detail.get('alliance_id') == TARGET_ALLIANCE_ID:
            st.session_state.token = token
            st.session_state.char_info = char_data
            st.rerun()
        else:
            st.error(f"ACCESS DENIED: Your Alliance ID ({detail.get('alliance_id')}) is not authorized.")
else:
    # Auto-refresh every 15 seconds
    st_autorefresh(interval=15000, key="esi_ping")
    char_name = st.session_state.char_info['CharacterName']
    char_id = st.session_state.char_info['CharacterID']
    
    # --- SIDEBAR: STATUS & MAP SELECTION ---
    st.sidebar.title("🛰️ System Health")
    try:
        supabase.table("maps").select("id").limit(1).execute()
        st.sidebar.success("✅ Supabase Online")
    except:
        st.sidebar.error("❌ Supabase Offline")

    st.sidebar.divider()
    
    # Load Maps
    maps_resp = supabase.table("maps").select("*").execute()
    maps_df = pd.DataFrame(maps_resp.data)
    if maps_df.empty:
        supabase.table("maps").insert({"name": "Main Chain"}).execute()
        st.rerun()
    
    selected_map_name = st.sidebar.selectbox("Active Map:", maps_df['name'])
    curr_map_id = int(maps_df[maps_df['name'] == selected_map_name]['id'].iloc[0])
    
    with st.sidebar.expander("➕ New Map Layer"):
        new_map_input = st.text_input("Map Name")
        if st.button("Create Map"):
            supabase.table("maps").insert({"name": new_map_input}).execute()
            st.rerun()

    # --- LOCATION TRACKING ---
    headers = {"Authorization": f"Bearer {st.session_state.token['access_token']}"}
    loc_res = requests.get(f"https://esi.evetech.net/latest/characters/{char_id}/location/", headers=headers)
    
    current_sys_id = None
    current_sys_name = "Unknown"
    if loc_res.status_code == 200:
        current_sys_id = str(loc_res.json()['solar_system_id'])
        current_sys_name = requests.get(f"https://esi.evetech.net/latest/universe/systems/{current_sys_id}/").json().get('name', 'Unknown')
        
        st.sidebar.info(f"Pilot: {char_name}\nLoc: {current_sys_name}")

        if "last_sys" not in st.session_state: st.session_state.last_sys = current_sys_id
        
        if current_sys_id != st.session_state.last_sys:
            # Automatic Jump Sync
            supabase.table("systems").upsert({"id": current_sys_id, "name": current_sys_name, "map_id": curr_map_id, "type": "Auto"}).execute()
            supabase.table("links").insert({"source": st.session_state.last_sys, "target": current_sys_id, "map_id": curr_map_id}).execute()
            st.session_state.last_sys = current_sys_id
            st.toast(f"Logged Jump to {current_sys_name}")

    # --- MAIN VIEW: MAP & CONTROLS ---
    col_map, col_ctrl = st.columns([3, 1])

    with col_map:
        # Pull Cloud Data
        sys_resp = supabase.table("systems").select("*").eq("map_id", curr_map_id).execute()
        link_resp = supabase.table("links").select("*").eq("map_id", curr_map_id).execute()
        nodes_df = pd.DataFrame(sys_resp.data)
        edges_df = pd.DataFrame(link_resp.data)

        if not nodes_df.empty:
            net = Network(height="750px", width="100%", bgcolor="#0b0d11", font_color="white")
            for _, r in nodes_df.iterrows():
                sid = str(r['id'])
                # Red for your current location, gray for others
                color = "#ff0000" if sid == current_sys_id else "#444444"
                net.add_node(sid, label=r['name'], color=color, size=25)
            
            if not edges_df.empty:
                for _, r in edges_df.iterrows():
                    net.add_edge(str(r['source']), str(r['target']), color="#888888")
            
            net.save_graph("shared_map.html")
            components.html(open("shared_map.html", 'r', encoding='utf-8').read(), height=760)
        else:
            st.info("Map Layer is empty. Start jumping or use 'Force Position' to begin.")

    with col_ctrl:
        st.subheader("🔍 Tactical Intel")
        if not nodes_df.empty:
            target_sys = st.selectbox("Inspect System:", nodes_df['name'])
            intel = get_wh_intel(target_sys)
            if intel:
                st.write(f"**Class:** {intel['class']}")
                if intel['effect'] != "None":
                    st.error(f"**Effect:** {intel['effect']}")
                st.write(f"**Statics:** {', '.join(intel.get('statics', []))}")
        
        st.divider()
        st.subheader("🛠️ Field Tools")
        
        if st.button("📍 Force Current Position"):
            supabase.table("systems").upsert({"id": current_sys_id, "name": current_sys_name, "map_id": curr_map_id, "type": "Manual"}).execute()
            st.rerun()

        with st.expander("🛠️ Manual Add / Link"):
            m_name = st.text_input("System Name (J-Code/K-Space)")
            if st.button("Add to Map"):
                supabase.table("systems").upsert({"id": m_name, "name": m_name, "map_id": curr_map_id, "type": "Manual"}).execute()
                st.rerun()
            
            if not nodes_df.empty:
                s_l = st.selectbox("Link From:", nodes_df['name'], key="sl")
                d_l = st.selectbox("Link To:", nodes_df['name'], key="dl")
                if st.button("🔗 Create Link"):
                    sid = nodes_df[nodes_df['name'] == s_l]['id'].iloc[0]
                    did = nodes_df[nodes_df['name'] == d_l]['id'].iloc[0]
                    supabase.table("links").insert({"source": str(sid), "target": str(did), "map_id": curr_map_id}).execute()
                    st.rerun()

        st.divider()
        if not nodes_df.empty:
            if st.button("🗑️ Delete Selected System"):
                sid = nodes_df[nodes_df['name'] == target_sys]['id'].iloc[0]
                supabase.table("systems").delete().eq("id", sid).eq("map_id", curr_map_id).execute()
                st.rerun()

        if st.button("⚠️ Wipe Map Content", type="primary"):
            supabase.table("systems").delete().eq("map_id", curr_map_id).execute()
            st.rerun()

        if st.sidebar.button("🚪 Logout"):
            del st.session_state.token
            st.rerun()
