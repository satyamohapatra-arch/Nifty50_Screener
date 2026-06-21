"""
app.py — Nifty 50 Algorithmic Equity Screener
Paterson Securities | Data Analytics Internship Project

Changes v2:
  1. Tickers loaded from ind_nifty50list.csv (no hardcoding)
  2. "Stock Detail" tab renamed to "Backtesting"
  3. Custom filters now support column-vs-column comparisons
  4. New "Performance Metrics" tab with CAGR, Sharpe, Sortino, Calmar,
     Max Drawdown, Win Rate, Profit Factor
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

# ── LOAD TICKERS FROM CSV ─────────────────────────────────────────────────────

TICKER_CSV = "ind_nifty50list.csv"

@st.cache_data
def load_ticker_meta(csv_path: str = TICKER_CSV):
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Symbol"])
    tickers    = df["Symbol"].str.strip().tolist()
    sector_map = dict(zip(df["Symbol"].str.strip(), df["Industry"].str.strip()))
    company_map= dict(zip(df["Symbol"].str.strip(), df["Company Name"].str.strip()))
    return tickers, sector_map, company_map

try:
    NIFTY50_TICKERS, SECTOR_MAP, COMPANY_MAP = load_ticker_meta()
except Exception:
    NIFTY50_TICKERS, SECTOR_MAP, COMPANY_MAP = [], {}, {}

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Nifty 50 Screener | Paterson Securities",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────

SHEET_ID = "1YsfDm4dFFM8aUfOS7uvIWDvphkSM39xOtlalgTUgkhM"
SCOPES   = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
PRESETS_FILE = "presets_nifty50.json"

# Numeric indicator definitions  {label: (col, min, max, default)}
NUMERIC_INDICATORS = {
    "Close Price":    ("Close",      0,     10000,  500),
    "Open Price":     ("Open",       0,     10000,  500),
    "Volume":         ("Volume",     0,     5e7,    1e6),
    "Returns (%)":    ("Returns",   -15,    15,     0),
    "EMA 10":         ("EMA_10",     0,     10000,  500),
    "EMA 20":         ("EMA_20",     0,     10000,  500),
    "SMA 50":         ("SMA_50",     0,     10000,  500),
    "Supertrend Val": ("Supertrend", 0,     10000,  500),
    "RSI 14":         ("RSI_14",     0,     100,    50),
    "MACD Line":      ("MACD_line", -50,    50,     0),
    "MACD Signal":    ("MACD_signal",-50,   50,     0),
    "MACD Histogram": ("MACD_hist", -50,    50,     0),
    "Stoch K":        ("Stoch_K",    0,     100,    50),
    "Stoch D":        ("Stoch_D",    0,     100,    50),
    "ATR 14":         ("ATR_14",     0,     300,    30),
    "BB Upper":       ("BB_Upper",   0,     10000,  500),
    "BB Middle":      ("BB_Middle",  0,     10000,  500),
    "BB Lower":       ("BB_Lower",   0,     10000,  500),
    "Bollinger %b":   ("BB_pctB",    0,     1,      0.5),
    "OBV":            ("OBV",       -5e8,   5e8,    0),
    "VWAP":           ("VWAP",       0,     10000,  500),
    "ADX 14":         ("ADX_14",     0,     100,    25),
    "DI Plus":        ("DI_Plus",    0,     60,     25),
    "DI Minus":       ("DI_Minus",   0,     60,     25),
}

# Text indicator definitions
TEXT_INDICATORS = {
    "Supertrend Signal":  ("Supertrend_Signal", ["BUY","SELL"]),
    "Absolute Longs Flag":("Absolute_Longs",    ["YES","NO"]),
    "Bottom Fishing Flag":("Bottom_Fishing",    ["YES","NO"]),
}

ALL_INDICATORS = {**NUMERIC_INDICATORS, **TEXT_INDICATORS}

# Column list used in col-vs-col filter picker
NUMERIC_COLS = [v[0] for v in NUMERIC_INDICATORS.values()]

STRATEGY_PRESETS = {
    "🚀 Absolute Longs": {
        "description": "High-conviction trend-following. Full bullish convergence across EMA, RSI, MACD, and Supertrend.",
        "filters": [{"label":"Absolute Longs Flag","col":"Absolute_Longs","op":"==","val":"YES","mode":"value"}],
        "flag_col": "Absolute_Longs",
        "logic":    "AND",
        "color":    "#008a58",
    },
    "🎣 Bottom-Fishing": {
        "description": "Counter-trend reversal. Short-term bullish momentum while Supertrend macro regime is still bearish.",
        "filters": [{"label":"Bottom Fishing Flag","col":"Bottom_Fishing","op":"==","val":"YES","mode":"value"}],
        "flag_col": "Bottom_Fishing",
        "logic":    "AND",
        "color":    "#c24141",
    },
}

# ── STYLES ────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stHeader"],
[data-testid="stSidebar"] {
    background-color: #f8f9fa !important;
    color: #1a1a1a !important;
}
[data-testid="stTabs"] button {
    color: #444444 !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    background: transparent !important;
    border: none !important;
    padding: 10px 20px !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #1a1a1a !important;
    border-bottom: 3px solid #2e75b6 !important;
}
[data-testid="stTabs"] button:hover { color: #2e75b6 !important; background: rgba(46,117,182,0.06) !important; }
section[data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1px solid #e0e0e0 !important; }
[data-testid="metric-container"] { background:#ffffff !important; border:1px solid #e0e0e0 !important; border-radius:10px !important; padding:14px !important; }
[data-testid="stMetricLabel"]    { color:#666666 !important; font-size:11px !important; text-transform:uppercase; }
[data-testid="stMetricValue"]    { color:#1a1a1a !important; font-size:28px !important; font-weight:700 !important; }
.stButton button { border-radius:8px !important; font-weight:600 !important; font-size:13px !important; border:1px solid #d0d0d0 !important; background:#ffffff !important; color:#1a1a1a !important; }
.stButton button[kind="primary"] { background:#2e75b6 !important; color:#ffffff !important; border:none !important; }

/* Screener table */
.tbl-wrap { overflow-x:auto; overflow-y:auto; max-height:65vh; background:#ffffff; border:1px solid #e0e0e0; border-radius:10px; }
.screener-table { width:100%; border-collapse:collapse; min-width:1100px; font-size:13px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
.screener-table th { position:sticky; top:0; z-index:5; background:#f4f6f8; color:#666666; text-transform:uppercase; letter-spacing:.05em; font-size:11px; font-weight:700; padding:11px 14px; text-align:left; border-bottom:2px solid #e0e0e0; white-space:nowrap; }
.screener-table td { padding:11px 14px; border-bottom:1px solid #f0f0f0; color:#1a1a1a; white-space:nowrap; }
.screener-table tr:hover td { background:#f8f9fa; }

/* Badges */
.badge-buy  { display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;background:#e6f4ee;color:#008a58;font-size:11px;font-weight:700; }
.badge-sell { display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;background:#fdecea;color:#c24141;font-size:11px;font-weight:700; }
.badge-yes  { display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;background:#e8f0fb;color:#2e75b6;font-size:11px;font-weight:700; }
.badge-no   { color:#cccccc;font-size:12px; }
.up  { color:#008a58;font-weight:600; }
.dn  { color:#c24141;font-weight:600; }
.neu { color:#888888; }

/* Preset cards */
.preset-card { background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:14px 16px;margin-bottom:10px; }
.preset-title { font-weight:700;font-size:15px;margin-bottom:4px; }
.preset-desc  { font-size:12px;color:#888888;line-height:1.5; }

/* Performance metric cards */
.perf-card { background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:20px;text-align:center;transition:box-shadow .2s; }
.perf-card:hover { box-shadow:0 4px 16px rgba(0,0,0,.08); }
.perf-label { font-size:11px;font-weight:700;color:#888888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px; }
.perf-value { font-size:2rem;font-weight:700;color:#1a1a1a; }
.perf-sub   { font-size:11px;color:#aaaaaa;margin-top:4px; }
.perf-good  { color:#008a58; }
.perf-bad   { color:#c24141; }
.perf-neu   { color:#2e75b6; }

/* Filter tag pills */
.filter-pill { display:inline-block;background:#e8f0fb;color:#2e75b6;border-radius:6px;padding:3px 8px;font-size:11px;font-weight:600;margin:2px; }

::-webkit-scrollbar { width:5px; height:5px; }
::-webkit-scrollbar-thumb { background:#d0d0d0; border-radius:10px; }
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
        v   = float(val)
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
        try: creds_json = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]
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
    gc = get_gc()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet(0)
    df = gd.get_as_dataframe(ws, evaluate_formulas=True, dtype=str)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    skip = {"Date","Stock","Sector","Supertrend_Signal","Absolute_Longs","Bottom_Fishing"}
    for c in df.columns:
        if c not in skip:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# ── FILTER ENGINE (supports value AND column-vs-column) ───────────────────────

def apply_filters(df, filters, logic):
    if not filters:
        return df
    masks = []
    for f in filters:
        col  = f["col"]
        op   = f["op"]
        mode = f.get("mode", "value")     # "value" | "column"

        if col not in df.columns:
            continue

        if mode == "column":
            # Compare two numeric columns
            col2 = f["val"]               # val stores the second column name
            if col2 not in df.columns:
                continue
            s1 = pd.to_numeric(df[col],  errors="coerce")
            s2 = pd.to_numeric(df[col2], errors="coerce")
            if   op == ">":  masks.append(s1 >  s2)
            elif op == "<":  masks.append(s1 <  s2)
            elif op == ">=": masks.append(s1 >= s2)
            elif op == "<=": masks.append(s1 <= s2)
            elif op == "==": masks.append(s1 == s2)
        else:
            # Original value comparison
            val = f["val"]
            if op == "==" and isinstance(val, str):
                masks.append(df[col].astype(str).str.upper() == val.upper())
            elif op == ">":
                masks.append(pd.to_numeric(df[col], errors="coerce") >  float(val))
            elif op == "<":
                masks.append(pd.to_numeric(df[col], errors="coerce") <  float(val))
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

# ── PERFORMANCE METRICS ENGINE ────────────────────────────────────────────────

RISK_FREE_RATE = 0.065          # 6.5% annualised (approx Indian 91-day T-bill)
TRADING_DAYS   = 252

def compute_perf_metrics(price_series: pd.Series, rfr: float = RISK_FREE_RATE) -> dict:
    """
    Given a daily Close price series (sorted ascending), return a dict of metrics.
    rfr: annualised risk-free rate (e.g. 0.065 for 6.5%)
    """
    prices = price_series.dropna()
    if len(prices) < 20:
        return {}

    daily_ret = prices.pct_change().dropna()
    n_days    = len(prices)
    n_years   = n_days / TRADING_DAYS

    # ── CAGR ──────────────────────────────────────────────────────────────────
    cagr = (prices.iloc[-1] / prices.iloc[0]) ** (1 / max(n_years, 0.01)) - 1

    # ── Sharpe Ratio ──────────────────────────────────────────────────────────
    excess        = daily_ret - rfr / TRADING_DAYS
    sharpe        = (excess.mean() / (excess.std() + 1e-10)) * np.sqrt(TRADING_DAYS)

    # ── Sortino Ratio ─────────────────────────────────────────────────────────
    downside      = daily_ret[daily_ret < 0]
    downside_std  = downside.std() * np.sqrt(TRADING_DAYS)
    ann_excess    = daily_ret.mean() * TRADING_DAYS - rfr
    sortino       = ann_excess / (downside_std + 1e-10)

    # ── Max Drawdown ──────────────────────────────────────────────────────────
    cumulative    = (1 + daily_ret).cumprod()
    rolling_max   = cumulative.cummax()
    drawdown      = (cumulative - rolling_max) / rolling_max
    max_drawdown  = drawdown.min()            # negative number

    # ── Calmar Ratio ──────────────────────────────────────────────────────────
    calmar        = cagr / (abs(max_drawdown) + 1e-10)

    # ── Win Rate ──────────────────────────────────────────────────────────────
    win_rate      = (daily_ret > 0).sum() / max(len(daily_ret), 1)

    # ── Profit Factor ─────────────────────────────────────────────────────────
    gross_profit  = daily_ret[daily_ret > 0].sum()
    gross_loss    = abs(daily_ret[daily_ret < 0].sum())
    profit_factor = gross_profit / (gross_loss + 1e-10)

    # ── Volatility (annualised) ───────────────────────────────────────────────
    volatility    = daily_ret.std() * np.sqrt(TRADING_DAYS)

    # ── Best / Worst Day ──────────────────────────────────────────────────────
    best_day      = daily_ret.max()
    worst_day     = daily_ret.min()

    # ── Total Return ──────────────────────────────────────────────────────────
    total_return  = (prices.iloc[-1] / prices.iloc[0]) - 1

    return dict(
        cagr          = cagr,
        sharpe        = sharpe,
        sortino       = sortino,
        calmar        = calmar,
        max_drawdown  = max_drawdown,
        win_rate      = win_rate,
        profit_factor = profit_factor,
        volatility    = volatility,
        best_day      = best_day,
        worst_day     = worst_day,
        total_return  = total_return,
        n_days        = n_days,
        n_years       = n_years,
    )

def perf_card_html(label, value_str, sub="", color_class="perf-neu"):
    return f"""
    <div class="perf-card">
        <div class="perf-label">{label}</div>
        <div class="perf-value {color_class}">{value_str}</div>
        <div class="perf-sub">{sub}</div>
    </div>"""

# ── SESSION STATE ─────────────────────────────────────────────────────────────

for key, default in [
    ("filters",       []),
    ("logic",         "AND"),
    ("presets",       load_presets()),
    ("active_preset", None),
    ("filter_mode",   "value"),   # "value" | "column"
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <div style="font-size:26px">📊</div>
        <div>
            <div style="font-size:1.2rem;font-weight:700;color:#1a1a1a">Nifty 50</div>
            <div style="font-size:11px;color:#888888">Algorithmic Screener · Paterson Securities</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # ── Strategy presets ──────────────────────────────────────────────────────
    st.markdown("**⚡ Strategy Presets**")
    for preset_name, preset in STRATEGY_PRESETS.items():
        is_active  = st.session_state.active_preset == preset_name
        border_col = preset["color"] if is_active else "#e0e0e0"
        bg_col     = ("#f0faf5" if "Longs" in preset_name else "#fdf0f0") if is_active else "#ffffff"
        st.markdown(f"""
        <div class="preset-card" style="border-color:{border_col};background:{bg_col}">
            <div class="preset-title" style="color:{preset['color']}">{preset_name}</div>
            <div class="preset-desc">{preset['description']}</div>
        </div>""", unsafe_allow_html=True)
        ca, cb = st.columns(2)
        with ca:
            if st.button("Apply", key=f"apply_{preset_name}", use_container_width=True, type="primary"):
                st.session_state.filters       = preset["filters"].copy()
                st.session_state.logic         = preset["logic"]
                st.session_state.active_preset = preset_name
                st.rerun()
        with cb:
            if st.button("Clear", key=f"clear_{preset_name}", use_container_width=True):
                if st.session_state.active_preset == preset_name:
                    st.session_state.filters       = []
                    st.session_state.active_preset = None
                    st.rerun()

    st.divider()

    # ── Custom Filters ────────────────────────────────────────────────────────
    st.markdown("**🔧 Custom Filters**")

    # Toggle: value filter vs column-vs-column
    filter_mode = st.radio(
        "Filter type",
        ["Value", "Column vs Column"],
        horizontal=True,
        label_visibility="collapsed",
        key="filter_mode_radio",
    )

    if filter_mode == "Value":
        sel            = st.selectbox("Indicator", list(ALL_INDICATORS.keys()), label_visibility="collapsed")
        is_text        = sel in TEXT_INDICATORS
        col_name       = ALL_INDICATORS[sel][0]

        if is_text:
            op  = "=="
            val = st.selectbox("Value", ALL_INDICATORS[sel][1])
        else:
            _, vmin, vmax, vdefault = ALL_INDICATORS[sel]
            op  = st.selectbox("Operator", [">","<",">=","<="])
            val = st.number_input("Threshold", value=float(vdefault), step=0.1, format="%.2f")

        if st.button("＋ Add Filter", use_container_width=True, type="primary"):
            st.session_state.filters.append({
                "label": sel,
                "col":   col_name,
                "op":    op,
                "val":   val,
                "mode":  "value",
            })
            st.session_state.active_preset = None
            st.rerun()

    else:   # Column vs Column
        col_labels = list(NUMERIC_INDICATORS.keys())
        col_A_lbl  = st.selectbox("Column A",    col_labels,                      label_visibility="collapsed")
        op_col     = st.selectbox("Operator",    [">","<",">=","<=","=="],         key="col_op")
        col_B_lbl  = st.selectbox("Column B",    col_labels, index=1,             label_visibility="collapsed")
        col_A      = NUMERIC_INDICATORS[col_A_lbl][0]
        col_B      = NUMERIC_INDICATORS[col_B_lbl][0]

        st.caption(f"Filter: **{col_A_lbl}** {op_col} **{col_B_lbl}**")

        if st.button("＋ Add Column Filter", use_container_width=True, type="primary"):
            st.session_state.filters.append({
                "label": f"{col_A_lbl} {op_col} {col_B_lbl}",
                "col":   col_A,
                "op":    op_col,
                "val":   col_B,   # second column stored in val
                "mode":  "column",
            })
            st.session_state.active_preset = None
            st.rerun()

    st.divider()

    st.markdown("**Filter Logic**")
    st.session_state.logic = st.radio(
        "", ["AND","OR"], horizontal=True,
        index=0 if st.session_state.logic == "AND" else 1,
        label_visibility="collapsed",
    )

    if st.session_state.filters:
        st.markdown("**Active Filters**")
        to_remove = []
        for i, f in enumerate(st.session_state.filters):
            c1, c2 = st.columns([4,1])
            with c1:
                mode_tag = "🔀" if f.get("mode") == "column" else "🔢"
                v = f["val"] if (isinstance(f["val"], str) and f.get("mode")=="column") else \
                    (f["val"] if isinstance(f["val"], str) else f"{f['val']:.2f}")
                st.caption(f"{mode_tag} `{f['label']}` {f['op']} {v}")
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

    # ── Saved presets ─────────────────────────────────────────────────────────
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
                    st.session_state.filters       = pd_["filters"].copy()
                    st.session_state.logic         = pd_.get("logic","AND")
                    st.session_state.active_preset = None
                    st.rerun()
            with pc2:
                if st.button("✕", key=f"del_{pn}"):
                    del st.session_state.presets[pn]
                    save_presets(st.session_state.presets)
                    st.rerun()

    st.divider()

    st.markdown("**☁ Data Refresh**")
    if st.button("Run Screener Now", use_container_width=True, type="primary"):
        with st.spinner("Fetching data & computing indicators... (3–5 min)"):
            try:
                import screener
                logs = []
                screener.run(log=lambda s: logs.append(s))
                st.cache_data.clear()
                st.success("Done!")
                for l in logs[-5:]:
                    st.caption(l)
            except Exception as e:
                import traceback
                st.error(traceback.format_exc())

    st.link_button(
        "↗ Open Google Sheet",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
        use_container_width=True,
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────

tab_screen, tab_backtest, tab_perf, tab_heatmap = st.tabs([
    "📋 Screener",
    "🔍 Backtesting",
    "📈 Performance Metrics",
    "🗺 Sector Heatmap",
])

with st.spinner("Loading data..."):
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

filtered  = apply_filters(df, st.session_state.filters, st.session_state.logic)
last_date = df["Date"].max() if "Date" in df.columns else "—"
buy_count = (df["Supertrend_Signal"].astype(str).str.upper() == "BUY").sum() if "Supertrend_Signal" in df.columns else 0
al_count  = (df["Absolute_Longs"].astype(str).str.upper()   == "YES").sum() if "Absolute_Longs"    in df.columns else 0
bf_count  = (df["Bottom_Fishing"].astype(str).str.upper()   == "YES").sum() if "Bottom_Fishing"     in df.columns else 0

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCREENER
# ═══════════════════════════════════════════════════════════════════════════════

with tab_screen:
    st.markdown("## Nifty 50 Screener")
    st.caption(f"Multi-indicator filter · {st.session_state.logic} logic · Data as of {last_date}")

    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    k1.metric("Total Stocks",   len(df))
    k2.metric("Matching",       len(filtered))
    k3.metric("Supertrend BUY", int(buy_count))
    k4.metric("Absolute Longs", int(al_count))
    k5.metric("Bottom-Fishing", int(bf_count))

    st.divider()

    if filtered.empty:
        st.info("No stocks match the active filters.")
    else:
        s1, s2, _ = st.columns([3, 2, 5])
        with s1:
            sort_by  = st.selectbox("Sort by", ["Returns","Close","RSI_14","ADX_14","MACD_hist","Volume"])
        with s2:
            sort_asc = st.selectbox("Order", ["High → Low","Low → High"])

        if sort_by in filtered.columns:
            filtered = filtered.sort_values(sort_by, ascending=(sort_asc == "Low → High"))

        rows = []
        for _, row in filtered.iterrows():
            stock  = str(row.get("Stock","")).replace(".NS","")
            sector = str(row.get("Sector","—"))
            company= COMPANY_MAP.get(stock, stock)
            rows.append(f"""<tr>
                <td><strong>{stock}</strong><br><span style='font-size:11px;color:#aaa'>{company}</span></td>
                <td style="color:#888888;font-size:12px">{sector}</td>
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

        st.markdown(f"""
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
        </div>""", unsafe_allow_html=True)

        st.caption(f"{len(filtered)} stocks · {st.session_state.logic} logic")
        st.download_button(
            "⬇ Download CSV", filtered.to_csv(index=False),
            file_name=f"nifty50_{last_date}.csv", mime="text/csv",
        )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — BACKTESTING  (formerly Stock Detail)
# ═══════════════════════════════════════════════════════════════════════════════

with tab_backtest:
    st.markdown("## Backtesting")

    stock_options = sorted(df["Stock"].str.replace(".NS","").unique().tolist())
    selected      = st.selectbox("Select Stock", stock_options)

    if selected:
        full_sym = selected + ".NS"
        row_df   = df[df["Stock"].isin([full_sym, selected])]
        if not row_df.empty:
            row = row_df.iloc[0]
            company_name = COMPANY_MAP.get(selected, selected)
            st.markdown(
                f"### {selected} &nbsp;"
                f"<span style='font-size:14px;color:#888'>{company_name} · {row.get('Sector','')}</span>",
                unsafe_allow_html=True,
            )

            if os.path.exists("nifty50_master.csv"):
                hist = pd.read_csv("nifty50_master.csv", parse_dates=["Date"])
                hist = hist[hist["Stock"].isin([full_sym, selected])].sort_values("Date").tail(252)

                if not hist.empty:
                    # Candlestick + overlays
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(
                        x=hist["Date"], open=hist["Open"], high=hist["High"],
                        low=hist["Low"], close=hist["Close"], name="Price",
                        increasing_line_color="#008a58", decreasing_line_color="#c24141",
                    ))
                    hist["EMA10_p"] = hist["Close"].ewm(span=10, adjust=False).mean()
                    hist["EMA20_p"] = hist["Close"].ewm(span=20, adjust=False).mean()
                    hist["SMA50_p"] = hist["Close"].rolling(50).mean()
                    bb_mid   = hist["Close"].rolling(20).mean()
                    bb_std   = hist["Close"].rolling(20).std()
                    hist["BB_U"] = bb_mid + 2*bb_std
                    hist["BB_L"] = bb_mid - 2*bb_std

                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["EMA10_p"], name="EMA 10",
                                            line=dict(color="#2e75b6", width=1.5, dash="dot")))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["EMA20_p"], name="EMA 20",
                                            line=dict(color="#e07c00", width=1.5, dash="dot")))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["SMA50_p"], name="SMA 50",
                                            line=dict(color="#7030a0", width=1.5)))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["BB_U"], name="BB Upper",
                                            line=dict(color="rgba(0,138,88,.3)", width=1), showlegend=False))
                    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["BB_L"], name="BB Lower",
                                            line=dict(color="rgba(0,138,88,.3)", width=1),
                                            fill="tonexty", fillcolor="rgba(0,138,88,.05)", showlegend=False))
                    fig.update_layout(height=420, template="plotly_white",
                                      xaxis_rangeslider_visible=False,
                                      margin=dict(l=0,r=0,t=30,b=0),
                                      legend=dict(orientation="h", y=1.08),
                                      font=dict(size=11))
                    st.plotly_chart(fig, use_container_width=True)

                    # RSI sub-chart
                    delta = hist["Close"].diff()
                    ag    = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                    al_   = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                    hist["RSI_p"] = 100 - (100 / (1 + ag/(al_+1e-10)))
                    fig_rsi = go.Figure()
                    fig_rsi.add_trace(go.Scatter(x=hist["Date"], y=hist["RSI_p"], name="RSI 14",
                                                 line=dict(color="#2e75b6", width=1.5)))
                    fig_rsi.add_hline(y=70, line_dash="dash", line_color="#c24141", line_width=1)
                    fig_rsi.add_hline(y=50, line_dash="dot",  line_color="#888888", line_width=1)
                    fig_rsi.add_hline(y=30, line_dash="dash", line_color="#008a58", line_width=1)
                    fig_rsi.update_layout(height=160, template="plotly_white",
                                          margin=dict(l=0,r=0,t=10,b=0),
                                          showlegend=False, yaxis=dict(range=[0,100]),
                                          font=dict(size=11))
                    st.plotly_chart(fig_rsi, use_container_width=True)

            # Indicator snapshot
            st.markdown("#### Indicator Snapshot")
            ind_groups = {
                "📈 Trend":      [("EMA 10","EMA_10"),("EMA 20","EMA_20"),("SMA 50","SMA_50"),
                                   ("Supertrend","Supertrend"),("Supertrend Sig","Supertrend_Signal")],
                "⚡ Momentum":   [("RSI 14","RSI_14"),("MACD Line","MACD_line"),
                                   ("MACD Signal","MACD_signal"),("MACD Hist","MACD_hist"),
                                   ("Stoch K","Stoch_K"),("Stoch D","Stoch_D")],
                "🌊 Volatility": [("ATR 14","ATR_14"),("BB Upper","BB_Upper"),
                                   ("BB Middle","BB_Middle"),("BB Lower","BB_Lower"),("BB %b","BB_pctB")],
                "📦 Volume":     [("OBV","OBV"),("VWAP","VWAP")],
                "💪 Trend Str":  [("ADX 14","ADX_14"),("DI+","DI_Plus"),("DI-","DI_Minus")],
            }
            cols = st.columns(len(ind_groups), gap="small")
            for ci, (grp, inds) in enumerate(ind_groups.items()):
                with cols[ci]:
                    st.markdown(f"**{grp}**")
                    for label, ck in inds:
                        val = row.get(ck, None)
                        if val is None or (isinstance(val, float) and np.isnan(val)):
                            display = "—"
                        elif ck == "Supertrend_Signal":
                            display = "🟢 BUY" if str(val).upper()=="BUY" else "🔴 SELL"
                        else:
                            try:    display = f"{float(val):.2f}"
                            except: display = str(val)
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;
                                    padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:12px">
                            <span style="color:#888">{label}</span>
                            <span style="font-weight:600;color:#1a1a1a">{display}</span>
                        </div>""", unsafe_allow_html=True)

            # Strategy signal cards
            st.markdown("#### Strategy Signals")
            sc1, sc2 = st.columns(2)
            with sc1:
                al_val   = str(row.get("Absolute_Longs","NO")).upper()
                al_color = "#008a58" if al_val=="YES" else "#cccccc"
                st.markdown(f"""
                <div style="background:#fff;border:2px solid {al_color};border-radius:12px;
                            padding:18px;text-align:center">
                    <div style="font-weight:700;font-size:1rem;color:{al_color}">🚀 Absolute Longs</div>
                    <div style="font-size:1.8rem;font-weight:700;margin-top:8px;color:{al_color}">
                        {"✓ ACTIVE" if al_val=="YES" else "—"}</div>
                    <div style="font-size:11px;color:#888;margin-top:4px">Trend-following signal</div>
                </div>""", unsafe_allow_html=True)
            with sc2:
                bf_val   = str(row.get("Bottom_Fishing","NO")).upper()
                bf_color = "#c24141" if bf_val=="YES" else "#cccccc"
                st.markdown(f"""
                <div style="background:#fff;border:2px solid {bf_color};border-radius:12px;
                            padding:18px;text-align:center">
                    <div style="font-weight:700;font-size:1rem;color:{bf_color}">🎣 Bottom-Fishing</div>
                    <div style="font-size:1.8rem;font-weight:700;margin-top:8px;color:{bf_color}">
                        {"✓ ACTIVE" if bf_val=="YES" else "—"}</div>
                    <div style="font-size:11px;color:#888;margin-top:4px">Reversal signal</div>
                </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PERFORMANCE METRICS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_perf:
    st.markdown("## Performance Metrics")
    st.caption("Risk-adjusted return analysis computed from historical OHLCV data")

    if not os.path.exists("nifty50_master.csv"):
        st.warning("Historical data not found. Run the screener pipeline first to generate `nifty50_master.csv`.")
        st.stop()

    master_full = pd.read_csv("nifty50_master.csv", parse_dates=["Date"])

    # Stock selector
    pm_col1, pm_col2, pm_col3 = st.columns([3, 2, 3])
    with pm_col1:
        pm_stock_options = sorted(master_full["Stock"].str.replace(".NS","").unique().tolist())
        pm_selected      = st.selectbox("Select Stock", pm_stock_options, key="pm_stock")
    with pm_col2:
        period_map = {
            "1 Year":  252,
            "2 Years": 504,
            "3 Years": 756,
            "5 Years": 1260,
            "All":     99999,
        }
        pm_period = st.selectbox("Period", list(period_map.keys()), index=2, key="pm_period")
    with pm_col3:
        rfr_pct = st.number_input(
            "Risk-Free Rate (%)", value=6.5, min_value=0.0, max_value=20.0, step=0.1,
            help="Annualised risk-free rate (e.g. 91-day T-bill yield)",
        )
        rfr = rfr_pct / 100

    pm_sym  = pm_selected + ".NS"
    pm_hist = master_full[master_full["Stock"].isin([pm_sym, pm_selected])].sort_values("Date")
    pm_hist = pm_hist.tail(period_map[pm_period])

    if pm_hist.empty or len(pm_hist) < 20:
        st.warning("Not enough data for the selected stock / period.")
    else:
        m = compute_perf_metrics(pm_hist["Close"].astype(float), rfr=rfr)

        if not m:
            st.warning("Could not compute metrics — insufficient data.")
        else:
            company_name = COMPANY_MAP.get(pm_selected, pm_selected)
            sector_name  = SECTOR_MAP.get(pm_selected, "—")
            start_price  = pm_hist["Close"].iloc[0]
            end_price    = pm_hist["Close"].iloc[-1]
            start_date_s = pm_hist["Date"].iloc[0].strftime("%d %b %Y")
            end_date_s   = pm_hist["Date"].iloc[-1].strftime("%d %b %Y")

            st.markdown(f"""
            <div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:16px 20px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center">
                <div>
                    <span style="font-size:1.4rem;font-weight:700">{pm_selected}</span>
                    <span style="color:#888;font-size:13px;margin-left:10px">{company_name}</span>
                    <span style="background:#e8f0fb;color:#2e75b6;border-radius:6px;padding:2px 8px;font-size:11px;font-weight:700;margin-left:8px">{sector_name}</span>
                </div>
                <div style="text-align:right;font-size:12px;color:#888">
                    {start_date_s} → {end_date_s} &nbsp;·&nbsp; {m['n_days']} trading days
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ── Row 1: Primary metrics ─────────────────────────────────────────
            st.markdown("#### Return & Risk")
            r1c1, r1c2, r1c3, r1c4 = st.columns(4, gap="small")

            with r1c1:
                cagr_color = "perf-good" if m['cagr'] > 0 else "perf-bad"
                st.markdown(perf_card_html(
                    "CAGR",
                    f"{m['cagr']*100:+.2f}%",
                    f"Compound Annual Growth Rate",
                    cagr_color,
                ), unsafe_allow_html=True)

            with r1c2:
                tot_color = "perf-good" if m['total_return'] > 0 else "perf-bad"
                st.markdown(perf_card_html(
                    "Total Return",
                    f"{m['total_return']*100:+.2f}%",
                    f"₹{start_price:.0f} → ₹{end_price:.0f}",
                    tot_color,
                ), unsafe_allow_html=True)

            with r1c3:
                dd_color = "perf-bad" if m['max_drawdown'] < -0.20 else ("perf-neu" if m['max_drawdown'] < -0.10 else "perf-good")
                st.markdown(perf_card_html(
                    "Max Drawdown",
                    f"{m['max_drawdown']*100:.2f}%",
                    "Peak-to-trough decline",
                    dd_color,
                ), unsafe_allow_html=True)

            with r1c4:
                st.markdown(perf_card_html(
                    "Volatility",
                    f"{m['volatility']*100:.2f}%",
                    "Annualised std of daily returns",
                    "perf-neu",
                ), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Row 2: Ratio metrics ───────────────────────────────────────────
            st.markdown("#### Risk-Adjusted Ratios")
            r2c1, r2c2, r2c3 = st.columns(3, gap="small")

            with r2c1:
                sh_color = "perf-good" if m['sharpe'] > 1 else ("perf-neu" if m['sharpe'] > 0 else "perf-bad")
                st.markdown(perf_card_html(
                    "Sharpe Ratio",
                    f"{m['sharpe']:.2f}",
                    f"RFR: {rfr_pct:.1f}% · >1 is good",
                    sh_color,
                ), unsafe_allow_html=True)

            with r2c2:
                so_color = "perf-good" if m['sortino'] > 1.5 else ("perf-neu" if m['sortino'] > 0 else "perf-bad")
                st.markdown(perf_card_html(
                    "Sortino Ratio",
                    f"{m['sortino']:.2f}",
                    "Penalises downside risk only",
                    so_color,
                ), unsafe_allow_html=True)

            with r2c3:
                ca_color = "perf-good" if m['calmar'] > 0.5 else ("perf-neu" if m['calmar'] > 0 else "perf-bad")
                st.markdown(perf_card_html(
                    "Calmar Ratio",
                    f"{m['calmar']:.2f}",
                    "CAGR ÷ Max Drawdown",
                    ca_color,
                ), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Row 3: Trade stats ─────────────────────────────────────────────
            st.markdown("#### Trade Statistics")
            r3c1, r3c2, r3c3, r3c4 = st.columns(4, gap="small")

            with r3c1:
                wr_color = "perf-good" if m['win_rate'] > 0.55 else ("perf-neu" if m['win_rate'] > 0.45 else "perf-bad")
                st.markdown(perf_card_html(
                    "Win Rate",
                    f"{m['win_rate']*100:.1f}%",
                    "% of days with positive return",
                    wr_color,
                ), unsafe_allow_html=True)

            with r3c2:
                pf_color = "perf-good" if m['profit_factor'] > 1.5 else ("perf-neu" if m['profit_factor'] > 1 else "perf-bad")
                st.markdown(perf_card_html(
                    "Profit Factor",
                    f"{m['profit_factor']:.2f}",
                    "Gross profit ÷ Gross loss",
                    pf_color,
                ), unsafe_allow_html=True)

            with r3c3:
                st.markdown(perf_card_html(
                    "Best Day",
                    f"{m['best_day']*100:+.2f}%",
                    "Single-day max gain",
                    "perf-good",
                ), unsafe_allow_html=True)

            with r3c4:
                st.markdown(perf_card_html(
                    "Worst Day",
                    f"{m['worst_day']*100:+.2f}%",
                    "Single-day max loss",
                    "perf-bad",
                ), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Equity curve ──────────────────────────────────────────────────
            st.markdown("#### Equity Curve")
            pm_hist2       = pm_hist.copy()
            pm_hist2["DR"] = pm_hist2["Close"].astype(float).pct_change().fillna(0)
            pm_hist2["EQ"] = (1 + pm_hist2["DR"]).cumprod() * 100
            pm_hist2["DD"] = pm_hist2["EQ"] / pm_hist2["EQ"].cummax() - 1

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=pm_hist2["Date"], y=pm_hist2["EQ"],
                name="Equity (base 100)",
                line=dict(color="#2e75b6", width=2),
                fill="tozeroy", fillcolor="rgba(46,117,182,0.07)",
            ))
            fig_eq.update_layout(
                height=280, template="plotly_white",
                margin=dict(l=0,r=0,t=10,b=0),
                yaxis_title="Value (base 100)", showlegend=False,
                font=dict(size=11),
            )
            st.plotly_chart(fig_eq, use_container_width=True)

            # ── Drawdown chart ────────────────────────────────────────────────
            st.markdown("#### Drawdown Chart")
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=pm_hist2["Date"], y=pm_hist2["DD"] * 100,
                name="Drawdown %",
                line=dict(color="#c24141", width=1.5),
                fill="tozeroy", fillcolor="rgba(194,65,65,0.1)",
            ))
            fig_dd.update_layout(
                height=200, template="plotly_white",
                margin=dict(l=0,r=0,t=10,b=0),
                yaxis_title="Drawdown (%)", showlegend=False,
                font=dict(size=11),
            )
            st.plotly_chart(fig_dd, use_container_width=True)

            # ── Monthly Returns Heatmap ────────────────────────────────────────
            st.markdown("#### Monthly Returns Heatmap")
            pm_hist2["Month"] = pm_hist2["Date"].dt.month
            pm_hist2["Year"]  = pm_hist2["Date"].dt.year
            monthly = pm_hist2.groupby(["Year","Month"])["DR"].apply(
                lambda x: (1 + x).prod() - 1
            ).reset_index()
            monthly_pivot = monthly.pivot(index="Year", columns="Month", values="DR") * 100
            monthly_pivot.columns = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][:len(monthly_pivot.columns)]

            fig_mh = go.Figure(go.Heatmap(
                z=monthly_pivot.values,
                x=monthly_pivot.columns.tolist(),
                y=monthly_pivot.index.tolist(),
                colorscale=[[0,"#c24141"],[0.5,"#f5f5f5"],[1,"#008a58"]],
                zmid=0,
                text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row_] for row_ in monthly_pivot.values],
                texttemplate="%{text}",
                textfont={"size":10},
                hoverongaps=False,
            ))
            fig_mh.update_layout(
                height=250, margin=dict(l=0,r=0,t=10,b=0),
                font=dict(size=11),
                xaxis_side="bottom",
            )
            st.plotly_chart(fig_mh, use_container_width=True)

            # ── Summary table ─────────────────────────────────────────────────
            with st.expander("Full metrics table"):
                summary = pd.DataFrame([{
                    "Metric": "CAGR",              "Value": f"{m['cagr']*100:+.2f}%"},
                    {"Metric": "Total Return",      "Value": f"{m['total_return']*100:+.2f}%"},
                    {"Metric": "Annualised Volatility","Value": f"{m['volatility']*100:.2f}%"},
                    {"Metric": "Max Drawdown",      "Value": f"{m['max_drawdown']*100:.2f}%"},
                    {"Metric": "Sharpe Ratio",      "Value": f"{m['sharpe']:.4f}"},
                    {"Metric": "Sortino Ratio",     "Value": f"{m['sortino']:.4f}"},
                    {"Metric": "Calmar Ratio",      "Value": f"{m['calmar']:.4f}"},
                    {"Metric": "Win Rate",          "Value": f"{m['win_rate']*100:.2f}%"},
                    {"Metric": "Profit Factor",     "Value": f"{m['profit_factor']:.4f}"},
                    {"Metric": "Best Day",          "Value": f"{m['best_day']*100:+.2f}%"},
                    {"Metric": "Worst Day",         "Value": f"{m['worst_day']*100:+.2f}%"},
                    {"Metric": "Trading Days",      "Value": str(m['n_days'])},
                    {"Metric": "Period (years)",    "Value": f"{m['n_years']:.2f}"},
                ])
                st.dataframe(summary, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SECTOR HEATMAP
# ═══════════════════════════════════════════════════════════════════════════════

with tab_heatmap:
    st.markdown("## Sector Heatmap")
    st.caption("Average return and signal counts by sector")

    if "Sector" in df.columns and "Returns" in df.columns:
        heatmap_df = filtered if st.session_state.filters else df
        sector_stats = heatmap_df.groupby("Sector").agg(
            Stocks       = ("Stock","count"),
            Avg_Return   = ("Returns","mean"),
            BUY_Count    = ("Supertrend_Signal", lambda x: (x.astype(str).str.upper()=="BUY").sum()),
            AL_Count     = ("Absolute_Longs",    lambda x: (x.astype(str).str.upper()=="YES").sum()),
            BF_Count     = ("Bottom_Fishing",    lambda x: (x.astype(str).str.upper()=="YES").sum()),
        ).reset_index().sort_values("Avg_Return", ascending=False)

        fig_heat = px.bar(
            sector_stats, x="Sector", y="Avg_Return",
            color="Avg_Return",
            color_continuous_scale=["#c24141","#f5e6e6","#e6f4ee","#008a58"],
            color_continuous_midpoint=0,
            text=sector_stats["Avg_Return"].apply(lambda x: f"{x:+.2f}%"),
            title="Average Return % by Sector",
            labels={"Avg_Return":"Avg Return (%)"},
        )
        fig_heat.update_traces(textposition="outside")
        fig_heat.update_layout(height=380, template="plotly_white",
                               margin=dict(l=0,r=0,t=40,b=0),
                               coloraxis_showscale=False,
                               font=dict(size=11), xaxis_tickangle=-30)
        st.plotly_chart(fig_heat, use_container_width=True)

        h1, h2 = st.columns(2)
        with h1:
            fig_al = px.bar(
                sector_stats.sort_values("AL_Count", ascending=False),
                x="Sector", y="AL_Count",
                title="🚀 Absolute Longs by Sector",
                color_discrete_sequence=["#2e75b6"],
                labels={"AL_Count":"Count"},
            )
            fig_al.update_layout(height=300, template="plotly_white",
                                 margin=dict(l=0,r=0,t=40,b=0),
                                 font=dict(size=11), xaxis_tickangle=-30)
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
                                 margin=dict(l=0,r=0,t=40,b=0),
                                 font=dict(size=11), xaxis_tickangle=-30)
            st.plotly_chart(fig_bf, use_container_width=True)

        st.dataframe(
            sector_stats.rename(columns={
                "Avg_Return":"Avg Return %",
                "BUY_Count":"Supertrend BUY",
                "AL_Count":"Absolute Longs",
                "BF_Count":"Bottom-Fishing",
            }).style.format({"Avg Return %":"{:+.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Sector data not available. Run screener first.")
