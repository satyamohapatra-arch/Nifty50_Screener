"""
app.py — Nifty 50 Algorithmic Equity Screener
Paterson Securities | Data Analytics Internship Project

Features:
  - 12-indicator multi-factor screener with AND/OR logic
  - One-click strategy presets: Absolute Longs & Bottom-Fishing
  - Stock detail view: price chart + all indicator values
  - Sector heatmap of flagged stocks
  - CSV download
"""

import streamlit as st
import pandas as pd
import numpy as np
import json, os
import gspread
from google.oauth2.service_account import Credentials
import gspread_dataframe as gd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty 50 Screener | Paterson Securities",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
SHEET_ID = "1YsfDm4dFFM8aUfOS7uvIWDvphkSM39xOtlalgTUgkhM"   # ← replace with your sheet ID - {completed}
SCOPES   = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
PRESETS_FILE = "presets_nifty50.json"

# All filterable indicators
ALL_INDICATORS = {
    # Price
    "Close Price":        ("Close",            0,    10000,  500),
    "Open Price":         ("Open",             0,    10000,  500),
    "Volume":             ("Volume",           0,    5e7,    1e6),
    "Returns (%)":        ("Returns",         -15,   15,     0),
    # Trend
    "EMA 10":             ("EMA_10",           0,    10000,  500),
    "EMA 20":             ("EMA_20",           0,    10000,  500),
    "SMA 50":             ("SMA_50",           0,    10000,  500),
    "Supertrend Signal":  ("Supertrend_Signal",None,  None,  None),
    "Supertrend Value":   ("Supertrend",       0,    10000,  500),
    # Momentum
    "RSI 14":             ("RSI_14",           0,    100,    50),
    "MACD Line":          ("MACD_line",       -50,   50,     0),
    "MACD Signal":        ("MACD_signal",     -50,   50,     0),
    "MACD Histogram":     ("MACD_hist",       -50,   50,     0),
    "Stoch K":            ("Stoch_K",          0,    100,    50),
    "Stoch D":            ("Stoch_D",          0,    100,    50),
    # Volatility
    "ATR 14":             ("ATR_14",           0,    300,    30),
    "BB Upper":           ("BB_Upper",         0,    10000,  500),
    "BB Middle":          ("BB_Middle",        0,    10000,  500),
    "BB Lower":           ("BB_Lower",         0,    10000,  500),
    "Bollinger %b":       ("BB_pctB",          0,    1,      0.5),
    # Volume
    "OBV":                ("OBV",             -5e8,  5e8,    0),
    "VWAP":               ("VWAP",             0,    10000,  500),
    # Trend Strength
    "ADX 14":             ("ADX_14",           0,    100,    25),
    "DI Plus":            ("DI_Plus",          0,    60,     25),
    "DI Minus":           ("DI_Minus",         0,    60,     25),
    # Strategy flags
    "Absolute Longs Flag":("Absolute_Longs",  None,  None,  None),
    "Bottom Fishing Flag":("Bottom_Fishing",  None,  None,  None),
}

# Strategy presets
STRATEGY_PRESETS = {
    "🚀 Absolute Longs": {
        "description": "High-conviction trend-following. Full bullish convergence across EMA, RSI, MACD, and Supertrend.",
        "filters": [
            {"label": "Supertrend Signal", "col": "Supertrend_Signal", "op": "==", "val": "BUY"},
            {"label": "RSI 14",            "col": "RSI_14",            "op": ">",  "val": 50},
            {"label": "MACD Histogram",    "col": "MACD_hist",         "op": ">",  "val": 0},
        ],
        "flag_col": "Absolute_Longs",
        "logic": "AND",
        "color": "#008a58",
    },
    "🎣 Bottom-Fishing": {
        "description": "Counter-trend reversal. Short-term bullish momentum while Supertrend macro regime is still bearish.",
        "filters": [
            {"label": "Supertrend Signal", "col": "Supertrend_Signal", "op": "==", "val": "SELL"},
            {"label": "RSI 14",            "col": "RSI_14",            "op": ">",  "val": 50},
            {"label": "MACD Histogram",    "col": "MACD_hist",         "op": ">",  "val": 0},
        ],
        "flag_col": "Bottom_Fishing",
        "logic": "AND",
        "color": "#c24141",
    },
}

# ── STYLES ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Syne:wght@600;700&display=swap');
:root {
    --bg: #f4f3ee; --bg2: #ffffff; --bg3: #eeede8; --bg4: #e4e3de;
    --border: rgba(0,0,0,0.08); --border2: rgba(0,0,0,0.14);
    --text: #1a1a14; --text2: #5a5950; --text3: #9a9990;
    --green: #008a58; --red: #c24141; --accent: #5a8a00;
    --radius: 10px; --radius-lg: 16px;
    --font-head: 'Syne', sans-serif; --font-mono: 'IBM Plex Mono', monospace;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background: var(--bg) !important; color: var(--text) !important;
    font-family: var(--font-mono);
}
.block-container { max-width:100%; padding:1.5rem 2rem 2rem 2rem; }
h1,h2,h3 { font-family: var(--font-head) !important; color:var(--text) !important; letter-spacing:-0.03em; }
h1 { font-size:2rem !important; font-weight:700 !important; }
section[data-testid="stSidebar"] { background:#f8f7f3 !important; border-right:1px solid rgba(0,0,0,0.06); }
[data-testid="metric-container"] {
    background:var(--bg2); border:1px solid var(--border);
    border-radius:var(--radius-lg); padding:16px;
}
[data-testid="stMetricLabel"] { color:var(--text3)!important; font-size:10px!important; text-transform:uppercase; letter-spacing:.06em; }
[data-testid="stMetricValue"] { font-family:var(--font-head)!important; font-size:28px!important; font-weight:700!important; }
.stButton button { border-radius:12px!important; min-height:42px; font-size:13px!important; font-weight:600!important; transition:all .15s; }
.stButton button[kind="primary"] {
    background:linear-gradient(135deg,#6fa81f,#5a8a00)!important;
    color:white!important; border:none!important; font-weight:700!important;
    box-shadow:0 4px 14px rgba(90,138,0,.18);
}
.stButton button:hover { border-color:rgba(90,138,0,.22)!important; background:#f7fbef!important; }
.stSelectbox div[data-baseweb="select"]>div, .stNumberInput input {
    background:#fcfcfa!important; border:1px solid rgba(0,0,0,.08)!important;
    border-radius:12px!important; min-height:44px!important;
}
.preset-card {
    background:white; border:1px solid rgba(0,0,0,.07); border-radius:14px;
    padding:16px 18px; margin-bottom:12px;
}
.preset-title { font-family:var(--font-head); font-weight:700; font-size:1rem; margin-bottom:4px; }
.preset-desc  { font-size:11px; color:var(--text3); line-height:1.5; }
.tbl-wrap { overflow-x:auto; overflow-y:auto; max-height:68vh; background:white; border:1px solid var(--border); border-radius:var(--radius-lg); }
.screener-table { width:100%; border-collapse:collapse; min-width:1100px; font-size:12px; }
.screener-table th {
    position:sticky; top:0; z-index:5; background:white;
    color:var(--text3); text-transform:uppercase; letter-spacing:.05em;
    font-size:10px; font-weight:600; padding:11px 12px;
    text-align:left; border-bottom:1px solid var(--border); white-space:nowrap;
}
.screener-table td { padding:11px 12px; border-bottom:1px solid var(--border); color:var(--text); white-space:nowrap; }
.screener-table tr:last-child td { border-bottom:none; }
.screener-table tr:hover td { background:var(--bg3); }
.badge-buy  { display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px; border:1px solid rgba(0,138,88,.18); background:rgba(0,138,88,.10); color:#008a58; font-size:10px; font-weight:700; text-transform:uppercase; }
.badge-sell { display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px; border:1px solid rgba(194,65,65,.18); background:rgba(194,65,65,.10); color:#c24141; font-size:10px; font-weight:700; text-transform:uppercase; }
.badge-yes  { display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px; border:1px solid rgba(90,138,0,.2); background:rgba(90,138,0,.10); color:#5a8a00; font-size:10px; font-weight:700; }
.badge-no   { color:#ccc; font-size:11px; }
.up { color:var(--green); font-weight:600; } .dn { color:var(--red); font-weight:600; } .neu { color:var(--text2); }
hr { border-color:rgba(0,0,0,.06)!important; margin:20px 0!important; }
::-webkit-scrollbar { width:5px; height:5px; }
::-webkit-scrollbar-thumb { background:var(--bg4); border-radius:10px; }
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def load_presets():
    if os.path.exists(PRESETS_FILE):
        with open(PRESETS_FILE) as f:
            return json.load(f)
    return {}

def save_presets(p):
    with open(PRESETS_FILE, "w") as f:
        json.dump(p, f)

def fmt(val, dec=2):
    if pd.isna(val): return "—"
    try:    return f"{float(val):.{dec}f}"
    except: return str(val)

def ret_html(val):
    try:
        v = float(val)
        cls = "up" if v > 0 else ("dn" if v < 0 else "neu")
        return f'<span class="{cls}">{v:+.2f}%</span>'
    except:
        return "—"

def signal_badge(val):
    v = str(val).upper()
    if v == "BUY":  return '<span class="badge-buy">BUY</span>'
    if v == "SELL": return '<span class="badge-sell">SELL</span>'
    return v

def flag_badge(val):
    v = str(val).upper()
    if v == "YES": return '<span class="badge-yes">✓ YES</span>'
    return '<span class="badge-no">—</span>'

# ── AUTH & DATA ───────────────────────────────────────────────────────────────

@st.cache_resource
def get_gc():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        try:    creds_json = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]
        except: pass
    if creds_json:
        info = json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)
    else:
        with open("service_account.json") as f:
            info = json.load(f)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=300)
def load_data():
    gc  = get_gc()
    sh  = gc.open_by_key(SHEET_ID)
    ws  = sh.get_worksheet(0)
    df  = gd.get_as_dataframe(ws, evaluate_formulas=True, dtype=str)
    df  = df.dropna(how="all").dropna(axis=1, how="all")
    skip = {"Date","Stock","Sector","Supertrend_Signal","Absolute_Longs","Bottom_Fishing"}
    for c in df.columns:
        if c not in skip:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# ── FILTER ENGINE ─────────────────────────────────────────────────────────────

def apply_filters(df, filters, logic):
    if not filters:
        return df
    masks = []
    for f in filters:
        col, op, val = f["col"], f["op"], f["val"]
        if col not in df.columns:
            continue
        if op == "==" and isinstance(val, str):
            masks.append(df[col].astype(str).str.upper() == val.upper())
        elif op == ">":
            masks.append(pd.to_numeric(df[col], errors="coerce") > float(val))
        elif op == "<":
            masks.append(pd.to_numeric(df[col], errors="coerce") < float(val))
        elif op == ">=":
            masks.append(pd.to_numeric(df[col], errors="coerce") >= float(val))
        elif op == "<=":
            masks.append(pd.to_numeric(df[col], errors="coerce") <= float(val))
    if not masks:
        return df
    combined = masks[0]
    for m in masks[1:]:
        combined = (combined & m) if logic == "AND" else (combined | m)
    return df[combined]

# ── SESSION STATE ─────────────────────────────────────────────────────────────

for key, default in [
    ("filters", []), ("logic", "AND"), ("presets", load_presets()),
    ("active_preset", None), ("detail_stock", None), ("view", "screener"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
      <div style="font-size:28px">📊</div>
      <div>
        <div style="font-family:'Syne',sans-serif;font-size:1.3rem;font-weight:700;letter-spacing:-.03em">Nifty 50</div>
        <div style="font-size:11px;color:#9a9990">Algorithmic Screener · Paterson Securities</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # ── STRATEGY PRESETS ──────────────────────────────────────────────────────
    st.markdown("**⚡ Strategy Presets**")

    for preset_name, preset in STRATEGY_PRESETS.items():
        is_active = st.session_state.active_preset == preset_name
        border_color = preset["color"] if is_active else "rgba(0,0,0,.07)"
        bg_color = f"rgba({','.join(str(int(preset['color'].lstrip('#')[i:i+2], 16)) for i in (0,2,4))},.06)" if is_active else "white"

        st.markdown(f"""
        <div class="preset-card" style="border-color:{border_color};background:{bg_color}">
            <div class="preset-title" style="color:{preset['color']}">{preset_name}</div>
            <div class="preset-desc">{preset['description']}</div>
        </div>
        """, unsafe_allow_html=True)

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Apply", key=f"apply_{preset_name}", use_container_width=True, type="primary"):
                st.session_state.filters = preset["filters"].copy()
                st.session_state.logic   = preset["logic"]
                st.session_state.active_preset = preset_name
                st.session_state.view    = "screener"
                st.rerun()
        with col_b:
            if st.button("Clear", key=f"clear_{preset_name}", use_container_width=True):
                if st.session_state.active_preset == preset_name:
                    st.session_state.filters = []
                    st.session_state.active_preset = None
                    st.rerun()

    st.divider()

    # ── CUSTOM FILTERS ────────────────────────────────────────────────────────
    st.markdown("**🔧 Custom Filters**")

    sel = st.selectbox("Indicator", list(ALL_INDICATORS.keys()), label_visibility="collapsed")
    col_name, vmin, vmax, vdefault = ALL_INDICATORS[sel]
    is_text = vmin is None

    if is_text:
        op  = "=="
        val = st.selectbox("Value", ["BUY","SELL","YES","NO"])
    else:
        op  = st.selectbox("Operator", [">","<",">=","<="])
        val = st.number_input("Threshold", value=float(vdefault), step=0.1, format="%.2f")

    if st.button("＋ Add Filter", use_container_width=True, type="primary"):
        st.session_state.filters.append({"label": sel, "col": col_name, "op": op, "val": val})
        st.session_state.active_preset = None
        st.rerun()

    st.divider()

    # Filter logic
    st.markdown("**Filter Logic**")
    st.session_state.logic = st.radio("", ["AND","OR"], horizontal=True,
        index=0 if st.session_state.logic == "AND" else 1, label_visibility="collapsed")

    # Active filters
    if st.session_state.filters:
        st.markdown("**Active Filters**")
        to_remove = []
        for i, f in enumerate(st.session_state.filters):
            c1, c2 = st.columns([4,1])
            with c1:
                v = f["val"] if isinstance(f["val"], str) else f"{f['val']:.2f}"
                st.caption(f"`{f['label']}` {f['op']} {v}")
            with c2:
                if st.button("✕", key=f"rm_{i}"):
                    to_remove.append(i)
        if to_remove:
            st.session_state.filters = [f for i,f in enumerate(st.session_state.filters) if i not in to_remove]
            st.rerun()
        if st.button("✕ Clear All", use_container_width=True):
            st.session_state.filters = []
            st.session_state.active_preset = None
            st.rerun()

    st.divider()

    # ── SAVED PRESETS ─────────────────────────────────────────────────────────
    st.markdown("**💾 My Saved Presets**")
    if st.session_state.filters:
        pname = st.text_input("Save as:", placeholder="e.g. RSI Momentum", label_visibility="collapsed")
        if st.button("Save Preset", use_container_width=True):
            if pname.strip():
                st.session_state.presets[pname.strip()] = {
                    "filters": st.session_state.filters.copy(),
                    "logic":   st.session_state.logic,
                }
                save_presets(st.session_state.presets)
                st.success(f'Saved "{pname.strip()}"')
                st.rerun()

    if st.session_state.presets:
        for pn, pd_ in list(st.session_state.presets.items()):
            pc1, pc2 = st.columns([3,1])
            with pc1:
                if st.button(f"▶ {pn}", key=f"load_{pn}", use_container_width=True):
                    st.session_state.filters = pd_["filters"].copy()
                    st.session_state.logic   = pd_.get("logic","AND")
                    st.session_state.active_preset = None
                    st.rerun()
            with pc2:
                if st.button("✕", key=f"del_{pn}"):
                    del st.session_state.presets[pn]
                    save_presets(st.session_state.presets)
                    st.rerun()

    st.divider()

    # ── RUN SCREENER ──────────────────────────────────────────────────────────
    st.markdown("**☁ Data Refresh**")
    if st.button("Run Screener Now", use_container_width=True, type="primary"):
        with st.spinner("Fetching data & computing indicators... (3–5 min)"):
            try:
                import screener
                logs = []
                screener.run(log=lambda s: logs.append(s))
                st.cache_data.clear()
                st.success("Done! Refresh to see new data.")
                for l in logs:
                    st.caption(l)
            except Exception as e:
                import traceback
                st.error(traceback.format_exc())

    st.link_button("↗ Open Google Sheet", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
                   use_container_width=True)

# ── MAIN ──────────────────────────────────────────────────────────────────────

# Nav tabs
tab_screen, tab_detail, tab_heatmap = st.tabs(["📋 Screener", "🔍 Stock Detail", "🗺 Sector Heatmap"])

# Load data
with st.spinner("Loading data from Google Sheets..."):
    try:
        df      = load_data()
        data_ok = True
    except Exception as e:
        st.error(f"Failed to load sheet: {e}")
        data_ok = False
        df      = pd.DataFrame()

if not data_ok or df.empty:
    st.warning("No data. Run the screener from the sidebar first.")
    st.stop()

# Apply filters
filtered    = apply_filters(df, st.session_state.filters, st.session_state.logic)
last_date   = df["Date"].max() if "Date" in df.columns else "—"
buy_count   = (df["Supertrend_Signal"].astype(str).str.upper() == "BUY").sum() if "Supertrend_Signal" in df.columns else 0
al_count    = (df["Absolute_Longs"].astype(str).str.upper() == "YES").sum() if "Absolute_Longs" in df.columns else 0
bf_count    = (df["Bottom_Fishing"].astype(str).str.upper() == "YES").sum() if "Bottom_Fishing" in df.columns else 0

# ── TAB 1: SCREENER ───────────────────────────────────────────────────────────
with tab_screen:
    st.markdown("# Nifty 50 Screener")
    st.caption(f"Multi-indicator filter · {st.session_state.logic} logic · Data as of {last_date}")

    # KPIs
    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    k1.metric("Total Stocks",     len(df))
    k2.metric("Matching",         len(filtered))
    k3.metric("Supertrend BUY",   int(buy_count))
    k4.metric("Absolute Longs",   int(al_count))
    k5.metric("Bottom-Fishing",   int(bf_count))

    st.divider()

    if filtered.empty:
        st.info("∅ No stocks match the active filters. Relax a threshold or switch to OR logic.")
    else:
        # Sort controls
        s1, s2, _ = st.columns([3, 2, 5])
        with s1:
            sort_by = st.selectbox("Sort by", ["Returns","Close","RSI_14","ADX_14","MACD_hist","Volume"], key="sort_col")
        with s2:
            sort_asc = st.selectbox("Order", ["High → Low","Low → High"], key="sort_dir")

        if sort_by in filtered.columns:
            filtered = filtered.sort_values(
                sort_by,
                ascending=(sort_asc == "Low → High")
            )

        # Build table
        rows = []
        for _, row in filtered.iterrows():
            stock   = str(row.get("Stock","")).replace(".NS","")
            sector  = str(row.get("Sector","—"))
            detail_btn = f'<a href="?detail={stock}" style="color:#5a8a00;font-size:11px;text-decoration:none">View →</a>'
            rows.append(f"""<tr>
              <td><strong>{stock}</strong></td>
              <td style="color:#9a9990;font-size:11px">{sector}</td>
              <td>{fmt(row.get('Close'))}</td>
              <td>{ret_html(row.get('Returns'))}</td>
              <td>{fmt(row.get('RSI_14'))}</td>
              <td>{fmt(row.get('MACD_hist'))}</td>
              <td>{fmt(row.get('ATR_14'))}</td>
              <td>{fmt(row.get('ADX_14'))}</td>
              <td>{fmt(row.get('BB_pctB'))}</td>
              <td>{signal_badge(row.get('Supertrend_Signal',''))}</td>
              <td>{flag_badge(row.get('Absolute_Longs',''))}</td>
              <td>{flag_badge(row.get('Bottom_Fishing',''))}</td>
            </tr>""")

        table_html = f"""
        <div class="tbl-wrap">
          <table class="screener-table">
            <thead><tr>
              <th>Stock</th><th>Sector</th><th>Close</th>
              <th>Return%</th><th>RSI</th><th>MACD Hist</th>
              <th>ATR</th><th>ADX</th><th>BB %b</th>
              <th>Supertrend</th><th>Abs Longs</th><th>Bot-Fish</th>
            </tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table>
        </div>"""

        st.markdown(table_html, unsafe_allow_html=True)
        st.caption(f"{len(filtered)} stocks · {st.session_state.logic} logic · sorted by {sort_by}")

        st.download_button(
            "⬇ Download CSV",
            filtered.to_csv(index=False),
            file_name=f"nifty50_screener_{last_date}.csv",
            mime="text/csv",
        )

# ── TAB 2: STOCK DETAIL ───────────────────────────────────────────────────────
with tab_detail:
    st.markdown("# Stock Detail View")

    stock_options = sorted(df["Stock"].str.replace(".NS","").unique().tolist())
    selected = st.selectbox("Select Stock", stock_options, key="detail_sel")

    if selected:
        full_sym = selected + ".NS"
        row = df[df["Stock"] == full_sym]
        if row.empty:
            row = df[df["Stock"] == selected]

        if not row.empty:
            row = row.iloc[0]

            # ── Price chart from master CSV ───────────────────────────────────
            st.markdown(f"### {selected}  <span style='font-size:14px;color:#9a9990'>{row.get('Sector','')}</span>", unsafe_allow_html=True)

            if os.path.exists("nifty50_master.csv"):
                hist = pd.read_csv("nifty50_master.csv", parse_dates=["Date"])
                hist = hist[hist["Stock"].isin([full_sym, selected])].sort_values("Date").tail(252)

                if not hist.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(
                        x=hist["Date"],
                        open=hist["Open"], high=hist["High"],
                        low=hist["Low"],   close=hist["Close"],
                        name="Price",
                        increasing_line_color="#008a58",
                        decreasing_line_color="#c24141",
                    ))
                    # Add EMA lines if available in latest
                    ema10 = float(row.get("EMA_10", np.nan))
                    ema20 = float(row.get("EMA_20", np.nan))
                    sma50 = float(row.get("SMA_50", np.nan))

                    # Compute rolling EMAs from hist for overlay
                    hist["EMA10_plot"] = hist["Close"].ewm(span=10, adjust=False).mean()
                    hist["EMA20_plot"] = hist["Close"].ewm(span=20, adjust=False).mean()
                    hist["SMA50_plot"] = hist["Close"].rolling(50).mean()
                    bb_mid = hist["Close"].rolling(20).mean()
                    bb_std = hist["Close"].rolling(20).std()
                    hist["BB_U"] = bb_mid + 2 * bb_std
                    hist["BB_L"] = bb_mid - 2 * bb_std

                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["EMA10_plot"],
                        name="EMA 10", line=dict(color="#5a8a00", width=1.5, dash="dot")))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["EMA20_plot"],
                        name="EMA 20", line=dict(color="#c28a00", width=1.5, dash="dot")))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["SMA50_plot"],
                        name="SMA 50", line=dict(color="#2e75b6", width=1.5)))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["BB_U"],
                        name="BB Upper", line=dict(color="rgba(90,138,0,.3)", width=1), showlegend=False))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["BB_L"],
                        name="BB Lower", line=dict(color="rgba(90,138,0,.3)", width=1),
                        fill="tonexty", fillcolor="rgba(90,138,0,.05)", showlegend=False))

                    fig.update_layout(
                        height=420, template="plotly_white",
                        xaxis_rangeslider_visible=False,
                        margin=dict(l=0, r=0, t=30, b=0),
                        paper_bgcolor="white", plot_bgcolor="white",
                        legend=dict(orientation="h", y=1.08),
                        font=dict(family="IBM Plex Mono", size=11),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # RSI sub-chart
                    hist["RSI_plot"] = None
                    delta = hist["Close"].diff()
                    gain  = delta.clip(lower=0)
                    loss  = (-delta).clip(lower=0)
                    ag    = gain.ewm(alpha=1/14, adjust=False).mean()
                    al_   = loss.ewm(alpha=1/14, adjust=False).mean()
                    rs    = ag / (al_ + 1e-10)
                    hist["RSI_plot"] = 100 - (100 / (1 + rs))

                    fig_rsi = go.Figure()
                    fig_rsi.add_trace(go.Scatter(x=hist["Date"], y=hist["RSI_plot"],
                        name="RSI 14", line=dict(color="#5a8a00", width=1.5)))
                    fig_rsi.add_hline(y=70, line_dash="dash", line_color="#c24141", line_width=1)
                    fig_rsi.add_hline(y=50, line_dash="dot",  line_color="#9a9990", line_width=1)
                    fig_rsi.add_hline(y=30, line_dash="dash", line_color="#008a58", line_width=1)
                    fig_rsi.update_layout(
                        height=160, template="plotly_white",
                        margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="white", plot_bgcolor="white",
                        showlegend=False, font=dict(family="IBM Plex Mono", size=11),
                        yaxis=dict(range=[0,100]),
                    )
                    st.plotly_chart(fig_rsi, use_container_width=True)

            else:
                st.info("Price chart unavailable — run screener first to generate master CSV.")

            # ── All indicator values ──────────────────────────────────────────
            st.markdown("#### Indicator Snapshot")
            ind_groups = {
                "📈 Trend": [
                    ("EMA 10",          "EMA_10"),
                    ("EMA 20",          "EMA_20"),
                    ("SMA 50",          "SMA_50"),
                    ("Supertrend",      "Supertrend"),
                    ("Supertrend Sig",  "Supertrend_Signal"),
                ],
                "⚡ Momentum": [
                    ("RSI 14",          "RSI_14"),
                    ("MACD Line",       "MACD_line"),
                    ("MACD Signal",     "MACD_signal"),
                    ("MACD Histogram",  "MACD_hist"),
                    ("Stoch K",         "Stoch_K"),
                    ("Stoch D",         "Stoch_D"),
                ],
                "🌊 Volatility": [
                    ("ATR 14",          "ATR_14"),
                    ("BB Upper",        "BB_Upper"),
                    ("BB Middle",       "BB_Middle"),
                    ("BB Lower",        "BB_Lower"),
                    ("BB %b",           "BB_pctB"),
                ],
                "📦 Volume": [
                    ("OBV",             "OBV"),
                    ("VWAP",            "VWAP"),
                ],
                "💪 Trend Strength": [
                    ("ADX 14",          "ADX_14"),
                    ("DI+",             "DI_Plus"),
                    ("DI-",             "DI_Minus"),
                ],
            }

            cols = st.columns(len(ind_groups), gap="small")
            for col_idx, (group_name, indicators) in enumerate(ind_groups.items()):
                with cols[col_idx]:
                    st.markdown(f"**{group_name}**")
                    for label, col_key in indicators:
                        val = row.get(col_key, None)
                        if val is None or (isinstance(val, float) and np.isnan(val)):
                            display = "—"
                        elif col_key == "Supertrend_Signal":
                            display = "🟢 BUY" if str(val).upper() == "BUY" else "🔴 SELL"
                        else:
                            try:    display = f"{float(val):.2f}"
                            except: display = str(val)
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;
                             padding:6px 0;border-bottom:1px solid rgba(0,0,0,.05);
                             font-size:12px;">
                          <span style="color:#9a9990">{label}</span>
                          <span style="font-weight:600">{display}</span>
                        </div>""", unsafe_allow_html=True)

            # Strategy signal
            st.markdown("#### Strategy Signals")
            sc1, sc2 = st.columns(2)
            with sc1:
                al_val = str(row.get("Absolute_Longs","NO")).upper()
                al_color = "#008a58" if al_val == "YES" else "#9a9990"
                st.markdown(f"""
                <div style="background:white;border:2px solid {al_color};border-radius:14px;padding:18px;text-align:center">
                  <div style="font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;color:{al_color}">🚀 Absolute Longs</div>
                  <div style="font-size:1.8rem;font-weight:700;margin-top:8px;color:{al_color}">{"✓ ACTIVE" if al_val=="YES" else "—"}</div>
                  <div style="font-size:11px;color:#9a9990;margin-top:4px">Trend-following signal</div>
                </div>""", unsafe_allow_html=True)
            with sc2:
                bf_val = str(row.get("Bottom_Fishing","NO")).upper()
                bf_color = "#c24141" if bf_val == "YES" else "#9a9990"
                st.markdown(f"""
                <div style="background:white;border:2px solid {bf_color};border-radius:14px;padding:18px;text-align:center">
                  <div style="font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;color:{bf_color}">🎣 Bottom-Fishing</div>
                  <div style="font-size:1.8rem;font-weight:700;margin-top:8px;color:{bf_color}">{"✓ ACTIVE" if bf_val=="YES" else "—"}</div>
                  <div style="font-size:11px;color:#9a9990;margin-top:4px">Reversal signal</div>
                </div>""", unsafe_allow_html=True)

# ── TAB 3: SECTOR HEATMAP ────────────────────────────────────────────────────
with tab_heatmap:
    st.markdown("# Sector Heatmap")
    st.caption("Average return and signal counts by sector")

    if "Sector" in df.columns and "Returns" in df.columns:
        heatmap_df = filtered if st.session_state.filters else df

        sector_stats = heatmap_df.groupby("Sector").agg(
            Stocks=("Stock","count"),
            Avg_Return=("Returns","mean"),
            BUY_Count=("Supertrend_Signal", lambda x: (x.astype(str).str.upper()=="BUY").sum()),
            AL_Count=("Absolute_Longs",  lambda x: (x.astype(str).str.upper()=="YES").sum()),
            BF_Count=("Bottom_Fishing",  lambda x: (x.astype(str).str.upper()=="YES").sum()),
        ).reset_index().sort_values("Avg_Return", ascending=False)

        # Returns heatmap
        fig_heat = px.bar(
            sector_stats, x="Sector", y="Avg_Return",
            color="Avg_Return",
            color_continuous_scale=["#c24141","#f5e6e6","#e6f5ee","#008a58"],
            color_continuous_midpoint=0,
            text=sector_stats["Avg_Return"].apply(lambda x: f"{x:+.2f}%"),
            title="Average Return % by Sector",
            labels={"Avg_Return":"Avg Return (%)"},
        )
        fig_heat.update_traces(textposition="outside")
        fig_heat.update_layout(
            height=380, template="plotly_white",
            margin=dict(l=0,r=0,t=40,b=0),
            paper_bgcolor="white", coloraxis_showscale=False,
            font=dict(family="IBM Plex Mono", size=11),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig_heat, use_container_width=True)

        # Signal distribution
        h1, h2 = st.columns(2)
        with h1:
            fig_al = px.bar(
                sector_stats.sort_values("AL_Count", ascending=False),
                x="Sector", y="AL_Count",
                title="🚀 Absolute Longs by Sector",
                color_discrete_sequence=["#5a8a00"],
                labels={"AL_Count":"Count"},
            )
            fig_al.update_layout(height=300, template="plotly_white",
                margin=dict(l=0,r=0,t=40,b=0), paper_bgcolor="white",
                font=dict(family="IBM Plex Mono", size=11), xaxis_tickangle=-30)
            st.plotly_chart(fig_al, use_container_width=True)

        with h2:
            fig_bf = px.bar(
                sector_stats.sort_values("BF_Count", ascending=False),
                x="Sector", y="BF_Count",
                title="🎣 Bottom-Fishing by Sector",
                color_discrete_sequence=["#c24141"],
                labels={"BF_Count":"Count"},
            )
            fig_bf.update_layout(height=300, template="plotly_white",
                margin=dict(l=0,r=0,t=40,b=0), paper_bgcolor="white",
                font=dict(family="IBM Plex Mono", size=11), xaxis_tickangle=-30)
            st.plotly_chart(fig_bf, use_container_width=True)

        # Table
        st.dataframe(
            sector_stats.rename(columns={
                "Avg_Return":"Avg Return %",
                "BUY_Count":"Supertrend BUY",
                "AL_Count":"Absolute Longs",
                "BF_Count":"Bottom-Fishing",
            }).style.format({"Avg Return %":"{:+.2f}"}),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("Sector data not available. Run screener first.")
