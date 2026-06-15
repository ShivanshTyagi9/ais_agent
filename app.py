"""
AIS Vessel Intelligence — Streamlit Application
Chat interface with integrated map visualization.
"""

import os
import sys
import streamlit as st
from streamlit_folium import st_folium
import folium
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.agent_loop import run_agent
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="AIS Vessel Intelligence",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ──────────────────────────────────────────────
# Custom CSS for premium dark theme
# ──────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global styles */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Header */
    .main-header {
        background: linear-gradient(135deg, #0a1628 0%, #1a2744 50%, #0d2137 100%);
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        border: 1px solid rgba(59, 130, 246, 0.2);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
    }

    .main-header h1 {
        color: #e2e8f0;
        font-size: 28px;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
    }

    .main-header p {
        color: #94a3b8;
        font-size: 14px;
        margin: 4px 0 0 0;
    }

    /* Chat messages */
    .user-msg {
        background: linear-gradient(135deg, #1e3a5f 0%, #1a365d 100%);
        border-radius: 16px 16px 4px 16px;
        padding: 16px 20px;
        margin: 8px 0;
        color: #e2e8f0;
        border: 1px solid rgba(59, 130, 246, 0.15);
    }

    .assistant-msg {
        background: linear-gradient(135deg, #1a1f2e 0%, #151b2b 100%);
        border-radius: 16px 16px 16px 4px;
        padding: 16px 20px;
        margin: 8px 0;
        color: #cbd5e1;
        border: 1px solid rgba(148, 163, 184, 0.1);
    }

    .msg-role {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }

    .user-role { color: #60a5fa; }
    .assistant-role { color: #34d399; }

    /* Status bar */
    .status-bar {
        background: rgba(15, 23, 42, 0.8);
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 12px;
        color: #64748b;
        display: flex;
        gap: 16px;
        margin-bottom: 16px;
        border: 1px solid rgba(51, 65, 85, 0.3);
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
    }

    .status-dot.active { background: #34d399; }
    .status-dot.inactive { background: #ef4444; }

    /* Map container */
    .map-container {
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid rgba(59, 130, 246, 0.2);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
    }

    /* Suggested queries */
    .suggestion-chip {
        display: inline-block;
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.3);
        border-radius: 20px;
        padding: 6px 14px;
        margin: 4px;
        font-size: 12px;
        color: #93c5fd;
        cursor: pointer;
        transition: all 0.2s;
    }

    .suggestion-chip:hover {
        background: rgba(59, 130, 246, 0.2);
        border-color: rgba(59, 130, 246, 0.5);
    }

    /* Hide Streamlit defaults */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────
if 'messages' not in st.session_state:
    st.session_state.messages = []  # Chat display history

if 'conversation' not in st.session_state:
    st.session_state.conversation = None  # Agent conversation (with system prompt)

if 'current_map' not in st.session_state:
    st.session_state.current_map = None  # Path to current map HTML

# ──────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🚢 AIS Vessel Intelligence</h1>
    <p>AI-powered maritime vessel tracking, route analysis, and dark-activity detection</p>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Layout: Chat (left) + Map (right)
# ──────────────────────────────────────────────
chat_col, map_col = st.columns([1, 1], gap="large")

with chat_col:
    # Status bar
    api_key_set = bool(os.getenv('OPENAI_API_KEY')) and os.getenv('OPENAI_API_KEY') != 'your_openai_api_key_here'
    db_name = os.getenv('DB_NAME', 'ais_vessel_intel')

    dot_class = "active" if api_key_set else "inactive"
    st.markdown(f"""
    <div class="status-bar">
        <span><span class="status-dot {dot_class}"></span> OpenAI API</span>
        <span><span class="status-dot active"></span> DB: {db_name}</span>
        <span>Model: GPT-4o</span>
    </div>
    """, unsafe_allow_html=True)

    # Chat container
    chat_container = st.container(height=500)

    with chat_container:
        if not st.session_state.messages:
            st.markdown("""
            <div style="text-align: center; padding: 60px 20px; color: #64748b;">
                <div style="font-size: 48px; margin-bottom: 16px;">🚢</div>
                <div style="font-size: 16px; font-weight: 500; color: #94a3b8; margin-bottom: 8px;">
                    Ask me about vessel movements
                </div>
                <div style="font-size: 13px;">
                    Track vessels, detect dark activity, analyze voyages, and generate maps
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    st.markdown(f"""
                    <div class="user-msg">
                        <div class="msg-role user-role">You</div>
                        {msg["content"]}
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="assistant-msg">
                        <div class="msg-role assistant-role">🤖 AIS Analyst</div>
                        {msg["content"]}
                    </div>
                    """, unsafe_allow_html=True)

    # Suggested queries
    if not st.session_state.messages:
        st.markdown("**Try asking:**")
        suggestions = [
            "Where was OCEAN WARLOCK on Dec 24, 2025?",
            "Show me the track of MMSI 316004661",
            "Did any vessel go dark near lat 29.9, lon -93.2?",
            "What vessels were near -122.3, 47.5 around midnight Dec 24?",
            "Summarize the voyage of JACK BINION on Dec 24, 2025"
        ]
        cols = st.columns(2)
        for i, suggestion in enumerate(suggestions):
            with cols[i % 2]:
                if st.button(suggestion, key=f"sug_{i}", use_container_width=True):
                    st.session_state.pending_query = suggestion
                    st.rerun()

    # Chat input
    user_input = st.chat_input("Ask about vessel movements, dark activity, positions...")

    # Handle pending query from suggestion buttons
    if hasattr(st.session_state, 'pending_query') and st.session_state.pending_query:
        user_input = st.session_state.pending_query
        st.session_state.pending_query = None

    if user_input:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": user_input})

        if not api_key_set:
            st.session_state.messages.append({
                "role": "assistant",
                "content": "⚠️ OpenAI API key not set. Please add your key to the `.env` file."
            })
        else:
            # Run agent
            with st.spinner("🔍 Analyzing..."):
                result = run_agent(
                    user_input,
                    conversation_history=st.session_state.conversation
                )

            st.session_state.conversation = result["messages"]
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["response"]
            })

            # Update map if one was generated
            if result.get("map_files"):
                st.session_state.current_map = result["map_files"][-1]

        st.rerun()


with map_col:
    st.markdown("### 🗺️ Map View")

    if st.session_state.current_map and os.path.exists(st.session_state.current_map):
        # Load and display the Folium map
        with open(st.session_state.current_map, 'r', encoding='utf-8') as f:
            map_html = f.read()

        st.components.v1.html(map_html, height=560, scrolling=False)

        st.caption(f"📍 Map: `{os.path.basename(st.session_state.current_map)}`")

        # Download button
        with open(st.session_state.current_map, 'r', encoding='utf-8') as f:
            st.download_button(
                label="📥 Download Map HTML",
                data=f.read(),
                file_name=os.path.basename(st.session_state.current_map),
                mime="text/html"
            )
    else:
        # Placeholder map centered on the data area
        st.markdown("""
        <div style="
            background: linear-gradient(135deg, #0a1628 0%, #1a2744 100%);
            border-radius: 12px;
            height: 500px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            border: 1px solid rgba(59, 130, 246, 0.15);
        ">
            <div style="font-size: 64px; margin-bottom: 16px;">🗺️</div>
            <div style="color: #94a3b8; font-size: 14px; text-align: center;">
                Ask to visualize a vessel's track<br>
                <span style="font-size: 12px; color: #64748b;">
                    "Show me the track of OCEAN WARLOCK"
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Sidebar with quick tools
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    st.markdown("### OpenAI API Key")
    api_key_input = st.text_input(
        "API Key",
        value=os.getenv('OPENAI_API_KEY', ''),
        type="password",
        help="Enter your OpenAI API key"
    )
    if api_key_input and api_key_input != os.getenv('OPENAI_API_KEY'):
        os.environ['OPENAI_API_KEY'] = api_key_input
        st.success("API key updated for this session!")

    st.divider()

    st.markdown("### 🔄 Reset")
    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conversation = None
        st.session_state.current_map = None
        st.rerun()

    st.divider()

    st.markdown("### ℹ️ About")
    st.markdown("""
    **AIS Vessel Intelligence** is an AI-powered maritime
    analysis system that uses:
    - 📊 **PostgreSQL + PostGIS** for spatial queries
    - 🤖 **GPT-4o** for natural language understanding
    - 🗺️ **Folium** for interactive map visualization
    - 🚢 **8.6M+ AIS position reports**
    """)
