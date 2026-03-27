import streamlit as st
import pandas as pd
import requests
import re
from supabase import create_client, Client
from requests_oauthlib import OAuth2Session
from pyvis.network import Network
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- ALLIANCE CLOUD CREDENTIALS ---
SUPABASE_URL = "https://gaeqckgnrdbanpchhaev.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdhZXFja2ducmRiYW5wY2hoYWV2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ2MjI0NDIsImV4cCI6MjA5MDE5ODQ0Mn0.TAPbXFoTgcms2rwcFbB_bUa74vkkecBgxQ-Gbyxn1xY"
CLIENT_ID = "6cb1bc3935e7423aa3b162933763e195"
SECRET_KEY = "HqNlRifvYkvKp9Ty8fVLGuYb6LzLXhwaMGRjmDPE"
CALLBACK_URL = "http://localhost:8501/"
TARGET_ALLIANCE_ID = 99014405 

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- INTEL SCRAPER ---
@st.cache_data(ttl=604800)
def get_wh_intel(system_name):
    sys_name = system_name.upper().strip()
    if not (sys_name.startswith('J') and any(c.isdigit() for c in sys_name)): return None
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

# --- UI ---
st.set_page_config(page_title="Zalvarians Command", layout="wide", page_icon="🛡️")

if "token" not in st.session_state:
    st.title("🛡️ ZALVARIANS ALLIANCE LOGIN")
    esi = OAuth2Session(CLIENT_ID, redirect_uri=CALLBACK_URL, scope=["esi-location.read_location.v1"])
    login_url, _ = esi.authorization_url("https://login.eveonline.com/v2/oauth/authorize")
    st.markdown(f'<a href="{login_url}" target="_self"><button style="padding:20px; background:#b30000; color:white; border:none; border-radius:5px; cursor:pointer; width:300px; font-weight:bold;">LOGIN WITH ESI</button></a>', unsafe_allow_html=True)
    
    if "code" in st.query_params:
        token = esi.fetch_token("https://login.eveonline.com/v2/oauth/token", code=st.query_params["code"], client_secret=SECRET_KEY)
        res = requests.get("https://login.eveonline.com/v2/oauth/verify", headers={"Authorization": f"Bearer {token['access_token']}"})
        char_data = res.json()
        detail = requests.get(f"https://esi.evetech.net/latest/characters/{char_data['CharacterID']}/").json()
        if detail.get('alliance_id') == TARGET_ALLIANCE_ID:
            st.session_state.token = token
            st.session_state.char_info = char_data
            st.rerun()
        else: st.error("Access Denied: 99014405 Members Only.")
else:
    st_autorefresh(interval=15000, key="esi_ping")
    char_id = st.session_state.char_info['CharacterID']
    
    # Map Selection
    maps_data = supabase.table("maps").select("*").execute()
    maps_df = pd.DataFrame(maps_data.data)
    selected_map_name = st.sidebar.selectbox("Active Map:", maps_df['name'])
    curr_map_id = int(maps_df[maps_df['name'] == selected_map_name]['id'].iloc[0])
    
    if st.sidebar.button("➕ Create New Map Layer"):
        new_m = st.sidebar.text_input("New Name:")
        if new_m: supabase.table("maps").insert({"name": new_m}).execute(); st.rerun()

    # Location Tracking
    headers = {"Authorization": f"Bearer {st.session_state.token['access_token']}"}
    loc_res = requests.get(f"https://esi.evetech.net/latest/characters/{char_id}/location/", headers=headers)
    
    current_sys_id = None
    current_sys_name = "Unknown"
    if loc_res.status_code == 200:
        current_sys_id = str(loc_res.json()['solar_system_id'])
        current_sys_name = requests.get(f"https://esi.evetech.net/latest/universe/systems/{current_sys_id}/").json().get('name', 'Unknown')
        if "last_sys" not in st.session_state: st.session_state.last_sys = current_sys_id
        if current_sys_id != st.session_state.last_sys:
            supabase.table("systems").upsert({"id": current_sys_id, "name": current_sys_name, "map_id": curr_map_id, "type": "Auto"}).execute()
            supabase.table("links").insert({"source": st.session_state.last_sys, "target": current_sys_id, "map_id": curr_map_id}).execute()
            st.session_state.last_sys = current_sys_id

    col_map, col_ctrl = st.columns([3, 1])

    with col_map:
        sys_resp = supabase.table("systems").select("*").eq("map_id", curr_map_id).execute()
        link_resp = supabase.table("links").select("*").eq("map_id", curr_map_id).execute()
        n_df = pd.DataFrame(sys_resp.data); e_df = pd.DataFrame(link_resp.data)

        if not n_df.empty:
            net = Network(height="700px", width="100%", bgcolor="#0b0d11", font_color="white")
            for _, r in n_df.iterrows():
                color = "#ff0000" if str(r['id']) == current_sys_id else "#444444"
                net.add_node(str(r['id']), label=r['name'], color=color)
            if not e_df.empty:
                for _, r in e_df.iterrows():
                    net.add_edge(str(r['source']), str(r['target']), color="#888888")
            net.save_graph("alliance_map.html")
            components.html(open("alliance_map.html", 'r', encoding='utf-8').read(), height=710)

    with col_ctrl:
        st.subheader("🔍 Intel & Tools")
        if not n_df.empty:
            target = st.selectbox("Select System:", n_df['name'])
            intel = get_wh_intel(target)
            if intel:
                st.write(f"Class: {intel['class']} | Effect: {intel['effect']}")
                st.write(f"Statics: {', '.join(intel.get('statics', []))}")
        
        # RESTORED OPTIONS
        st.markdown("---")
        if st.button("📍 Force Map Current Location"):
            supabase.table("systems").upsert({"id": current_sys_id, "name": current_sys_name, "map_id": curr_map_id, "type": "Manual"}).execute()
            st.rerun()

        with st.expander("🛠️ Manual Add / Link"):
            m_name = st.text_input("System Name (e.g. J123456)")
            if st.button("Add Manually"):
                supabase.table("systems").upsert({"id": m_name, "name": m_name, "map_id": curr_map_id, "type": "Manual"}).execute()
                st.rerun()
            if not n_df.empty:
                s_link = st.selectbox("Link From:", n_df['name'], key="s_l")
                d_link = st.selectbox("Link To:", n_df['name'], key="d_l")
                if st.button("🔗 Connect"):
                    sid = n_df[n_df['name'] == s_link]['id'].iloc[0]
                    did = n_df[n_df['name'] == d_link]['id'].iloc[0]
                    supabase.table("links").insert({"source": str(sid), "target": str(did), "map_id": curr_map_id}).execute()
                    st.rerun()

        if not n_df.empty:
            st.markdown("---")
            if st.button("🗑️ Delete Selected System"):
                sid = n_df[n_df['name'] == target]['id'].iloc[0]
                supabase.table("systems").delete().eq("id", sid).eq("map_id", curr_map_id).execute()
                st.rerun()

        if st.button("⚠️ Wipe Map Content", type="primary"):
            supabase.table("systems").delete().eq("map_id", curr_map_id).execute()
            st.rerun()

        if st.sidebar.button("🚪 Logout"):
            del st.session_state.token; st.rerun()
