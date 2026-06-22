"""
app.py — Nifty 50 Algorithmic Equity Screener
Paterson Securities | Data Analytics Internship Project
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
import yfinance as yf
from datetime import datetime, timedelta

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty 50 Screener | Paterson Securities",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
SHEET_ID = "1YsfDm4dFFM8aUfOS7uvIWDvphkSM39xOtlalgTUgkhM"
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
PRESETS_FILE = "presets_nifty50.json"

NIFTY50_TICKERS = [
    "RELIANCE","TCS","HDFCBANK","BHARTIARTL","ICICIBANK",
    "INFOSYS","SBILIFE","HINDUNILVR","ITC","LT",
    "KOTAKBANK","HCLTECH","BAJFINANCE","MARUTI","AXISBANK",
    "ASIANPAINT","NESTLEIND","SUNPHARMA","TITAN","ULTRACEMCO",
    "WIPRO","NTPC","TECHM","POWERGRID","BAJAJFINSV",
    "ADANIENT","ADANIPORTS","ONGC","TATAMOTORS","TATASTEEL",
    "SBIN","M&M","JSWSTEEL","COALINDIA","DIVISLAB",
    "DRREDDY","BRITANNIA","CIPLA","APOLLOHOSP","EICHERMOT",
    "GRASIM","HEROMOTOCO","HINDALCO","INDUSINDBK","BPCL",
    "BAJAJ-AUTO","TRENT","BEL","SHRIRAMFIN","HDFCLIFE",
]
NIFTY50_SYMBOLS = [t + ".NS" for t in NIFTY50_TICKERS]

ALL_INDICATORS = {
    "Close Price":          ("Close",             0,    10000, 500),
    "Open Price":           ("Open",              0,    10000, 500),
    "Volume":               ("Volume",            0,    5e7,   1e6),
    "Returns (%)":          ("Returns",          -15,   15,    0),
    "EMA 10":               ("EMA_10",            0,    10000, 500),
    "EMA 20":               ("EMA_20",            0,    10000, 500),
    "SMA 50":               ("SMA_50",            0,    10000, 500),
    "Supertrend Signal":    ("Supertrend_Signal", None, None,  None),
    "Supertrend Value":     ("Supertrend",        0,    10000, 500),
    "RSI 14":               ("RSI_14",            0,    100,   50),
    "MACD Line":            ("MACD_line",        -50,   50,    0),
    "MACD Signal":          ("MACD_signal",      -50,   50,    0),
    "MACD Histogram":       ("MACD_hist",        -50,   50,    0),
    "Stoch K":              ("Stoch_K",           0,    100,   50),
    "Stoch D":              ("Stoch_D",           0,    100,   50),
    "ATR 14":               ("ATR_14",            0,    300,   30),
    "BB Upper":             ("BB_Upper",          0,    10000, 500),
    "BB Middle":            ("BB_Middle",         0,    10000, 500),
    "BB Lower":             ("BB_Lower",          0,    10000, 500),
    "Bollinger %b":         ("BB_pctB",           0,    1,     0.5),
    "OBV":                  ("OBV",              -5e8,  5e8,   0),
    "VWAP":                 ("VWAP",              0,    10000, 500),
    "ADX 14":               ("ADX_14",            0,    100,   25),
    "DI Plus":              ("DI_Plus",           0,    60,    25),
    "DI Minus":             ("DI_Minus",          0,    60,    25),
    "Absolute Longs Flag":  ("Absolute_Longs",   None, None,  None),
    "Bottom Fishing Flag":  ("Bottom_Fishing",   None, None,  None),
}

STRATEGY_PRESETS = {
    "🚀 Absolute Longs": {
        "description": "High-conviction trend-following. Full bullish convergence across EMA, RSI, MACD, and Supertrend.",
        "filters": [{"label": "Absolute Longs Flag", "col": "Absolute_Longs", "op": "==", "val": "YES"}],
        "flag_col": "Absolute_Longs",
        "logic": "AND",
        "color": "#008a58",
    },
    "🎣 Bottom-Fishing": {
        "description": "Counter-trend reversal. Short-term bullish momentum while Supertrend macro regime is still bearish.",
        "filters": [{"label": "Bottom Fishing Flag", "col": "Bottom_Fishing", "op": "==", "val": "YES"}],
        "flag_col": "Bottom_Fishing",
        "logic": "AND",
        "color": "#c24141",
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
    color: #444444 !important; font-weight: 600 !important;
    font-size: 14px !important; background: transparent !important;
    border: none !important; padding: 10px 20px !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #1a1a1a !important; border-bottom: 3px solid #2e75b6 !important;
}
[data-testid="stTabs"] button:hover { color: #2e75b6 !important; }
section[data-testid="stSidebar"] {
    background-color: #ffffff !important; border-right: 1px solid #e0e0e0 !important;
}
[data-testid="metric-container"] {
    background: #ffffff !important; border: 1px solid #e0e0e0 !important;
    border-radius: 10px !important; padding: 14px !important;
}
[data-testid="stMetricLabel"]  { color: #666666 !important; font-size: 11px !important; text-transform: uppercase; }
[data-testid="stMetricValue"]  { color: #1a1a1a !important; font-size: 28px !important; font-weight: 700 !important; }
.stButton button {
    border-radius: 8px !important; font-weight: 600 !important;
    font-size: 13px !important; border: 1px solid #d0d0d0 !important;
    background: #ffffff !important; color: #1a1a1a !important;
}
.stButton button[kind="primary"] {
    background: #2e75b6 !important; color: #ffffff !important; border: none !important;
}
.tbl-wrap {
    overflow-x: auto; overflow-y: auto; max-height: 65vh;
    background: #ffffff; border: 1px solid #e0e0e0; border-radius: 10px;
}
.screener-table {
    width: 100%; border-collapse: collapse;
    min-width: 1100px; font-size: 13px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.screener-table th {
    position: sticky; top: 0; z-index: 5;
    background: #f4f6f8; color: #666666;
    text-transform: uppercase; letter-spacing: .05em;
    font-size: 11px; font-weight: 700;
    padding: 11px 14px; text-align: left;
    border-bottom: 2px solid #e0e0e0; white-space: nowrap;
}
.screener-table td { padding: 11px 14px; border-bottom: 1px solid #f0f0f0; color: #1a1a1a; white-space: nowrap; }
.screener-table tr:hover td { background: #f8f9fa; }
.badge-buy  { display:inline-flex; align-items:center; padding:3px 10px; border-radius:999px; background:#e6f4ee; color:#008a58; font-size:11px; font-weight:700; }
.badge-sell { display:inline-flex; align-items:center; padding:3px 10px; border-radius:999px; background:#fdecea; color:#c24141; font-size:11px; font-weight:700; }
.badge-yes  { display:inline-flex; align-items:center; padding:3px 10px; border-radius:999px; background:#e8f0fb; color:#2e75b6; font-size:11px; font-weight:700; }
.badge-no   { color:#cccccc; font-size:12px; }
.up  { color:#008a58; font-weight:600; }
.dn  { color:#c24141; font-weight:600; }
.neu { color:#888888; }
.metric-card {
    background:#ffffff; border:1px solid #e0e0e0; border-radius:12px;
    padding:20px 24px; text-align:center;
}
.metric-card .mc-label { font-size:11px; color:#888888; text-transform:uppercase; letter-spacing:.05em; margin-bottom:6px; }
.metric-card .mc-value { font-size:2rem; font-weight:700; color:#1a1a1a; }
.metric-card .mc-value.positive { color:#008a58; }
.metric-card .mc-value.negative { color:#c24141; }
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-thumb { background: #d0d0d0; border-radius: 10px; }
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
    try: return f"{float(val):.{dec}f}"
    except: return str(val)

def ret_html(val):
    try:
        v = float(val)
        cls = "up" if v > 0 else ("dn" if v < 0 else "neu")
        return f'<span class="{cls}">{v:+.2f}%</span>'
    except: return "—"

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
    # gspread >= 6 — use Client directly instead of deprecated gspread.authorize()
    return gspread.Client(auth=creds)

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

# ── PERFORMANCE BACKTEST ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_backtest_data():
    """Fetch 1 year of OHLCV for all Nifty 50 stocks via yfinance."""
    end   = datetime.today()
    start = end - timedelta(days=365)
    all_frames = []
    progress = st.progress(0, text="Fetching price data...")
    for i, sym in enumerate(NIFTY50_SYMBOLS):
        try:
            df = yf.download(sym, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"),
                             interval="1d", auto_adjust=False, progress=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            df["Stock"] = sym
            all_frames.append(df)
        except Exception:
            pass
        progress.progress((i + 1) / len(NIFTY50_SYMBOLS),
                          text=f"Fetching {sym} ({i+1}/{len(NIFTY50_SYMBOLS)})...")
    progress.empty()
    if not all_frames:
        return pd.DataFrame()
    return pd.concat(all_frames, ignore_index=True)

def compute_bt_indicators(data):
    """Compute EMA10, EMA20, RSI14, Supertrend signal for backtest."""
    data = data.sort_values("Date").copy()
    close = data["Close"].astype(float)
    high  = data["High"].astype(float)
    low   = data["Low"].astype(float)

    data["EMA_10"] = close.ewm(span=10, adjust=False).mean()
    data["EMA_20"] = close.ewm(span=20, adjust=False).mean()

    delta    = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    data["RSI_14"] = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-10)))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    data["MACD_hist"] = macd_line - macd_line.ewm(span=9, adjust=False).mean()

    # Supertrend (ATR multiplier=3, span=7 — matching the Colab notebook)
    hl  = high - low
    hcp = (high - close.shift()).abs()
    lcp = (low  - close.shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    atr7 = tr.ewm(span=7, adjust=False).mean()
    hl2  = (high + low) / 2
    upper_band = (hl2 + 3 * atr7).values
    lower_band = (hl2 - 3 * atr7).values
    close_arr  = close.values
    n = len(data)
    supertrend = np.zeros(n)
    signal     = [""] * n
    supertrend[0] = upper_band[0]
    signal[0]     = "SELL"
    for i in range(1, n):
        if close_arr[i] > supertrend[i - 1]:
            supertrend[i] = lower_band[i]
            signal[i]     = "BUY"
        else:
            supertrend[i] = upper_band[i]
            signal[i]     = "SELL"
    data["Supertrend_Signal"] = signal

    data["Daily_Return"] = close.pct_change()
    return data

def run_backtest(raw_df, strategy="absolute_longs"):
    """
    Exact same logic as the notebook.
    strategy: 'absolute_longs' or 'bottom_fishing'
    Pool all stocks together, compute aggregate metrics.
    """
    # Loop per stock explicitly — avoids pandas 2.x groupby.apply()
    # swallowing the "Stock" column as the index key
    frames = []
    for stock, grp in raw_df.groupby("Stock"):
        result = compute_bt_indicators(grp.copy())
        result["Stock"] = stock
        frames.append(result)
    bt = pd.concat(frames, ignore_index=True)

    if strategy == "absolute_longs":
        bt["Position"] = (
            (bt["EMA_10"] > bt["EMA_20"]) &
            (bt["RSI_14"] > 50) &
            (bt["MACD_hist"] > 0) &
            (bt["Supertrend_Signal"] == "BUY")
        ).astype(int)
    else:  # bottom_fishing
        bt["Position"] = (
            (bt["EMA_10"] < bt["EMA_20"]) &
            (bt["RSI_14"] < 50) &
            (bt["MACD_hist"] < 0) &
            (bt["Supertrend_Signal"] == "SELL")
        ).astype(int)

    # Avoid look-ahead bias — same as notebook
    bt["Position"] = bt.groupby("Stock")["Position"].shift(1)

    bt["Strategy_Return"] = bt["Position"] * bt["Daily_Return"]

    returns = bt["Strategy_Return"].dropna()

    initial_capital = 100_000
    equity_curve    = initial_capital * (1 + returns).cumprod()

    years = len(returns) / 252
    cagr  = (equity_curve.iloc[-1] / initial_capital) ** (1 / years) - 1

    risk_free_rate = 0.06
    excess         = returns.mean() - risk_free_rate / 252

    sharpe  = np.sqrt(252) * excess / (returns.std() + 1e-10)
    downside = returns[returns < 0]
    sortino = np.sqrt(252) * excess / (downside.std() + 1e-10)

    rolling_max  = equity_curve.cummax()
    drawdown     = (equity_curve - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else np.inf

    trades       = bt.loc[bt["Position"] == 1, "Strategy_Return"].dropna()
    win_rate     = (trades > 0).sum() / len(trades) * 100 if len(trades) > 0 else 0
    gross_profit = trades[trades > 0].sum()
    gross_loss   = abs(trades[trades < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else np.inf

    # Benchmark — equal-weight buy & hold across all stocks
    benchmark_returns = bt.groupby("Date")["Daily_Return"].mean().dropna()
    benchmark_equity  = initial_capital * (1 + benchmark_returns).cumprod()
    bench_years       = len(benchmark_returns) / 252
    benchmark_cagr    = (benchmark_equity.iloc[-1] / initial_capital) ** (1 / bench_years) - 1

    metrics = {
        "CAGR %":           round(cagr * 100, 2),
        "Sharpe Ratio":     round(sharpe, 2),
        "Sortino Ratio":    round(sortino, 2),
        "Max Drawdown %":   round(max_drawdown * 100, 2),
        "Calmar Ratio":     round(calmar, 2),
        "Win Rate %":       round(win_rate, 2),
        "Profit Factor":    round(profit_factor, 2),
        "Benchmark CAGR %": round(benchmark_cagr * 100, 2),
    }

    # Build dated equity curve for chart (aggregate by date)
    eq_by_date = (
        bt.groupby("Date")["Strategy_Return"]
          .mean()
          .dropna()
    )
    eq_curve_chart = initial_capital * (1 + eq_by_date).cumprod()
    bench_chart    = initial_capital * (1 + benchmark_returns).cumprod()

    return metrics, eq_curve_chart, bench_chart, drawdown

# ── SESSION STATE ─────────────────────────────────────────────────────────────
for key, default in [
    ("filters", []), ("logic", "AND"), ("presets", load_presets()),
    ("active_preset", None),
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

    st.markdown("**⚡ Strategy Presets**")
    for preset_name, preset in STRATEGY_PRESETS.items():
        is_active = st.session_state.active_preset == preset_name
        border_col = preset["color"] if is_active else "#e0e0e0"
        bg_col = ("#f0faf5" if (is_active and "Longs" in preset_name)
                  else "#fdf0f0" if (is_active and "Fish" in preset_name)
                  else "#ffffff")
        st.markdown(f"""
        <div style="background:{bg_col};border:1px solid {border_col};border-radius:12px;
             padding:14px 16px;margin-bottom:10px">
          <div style="font-weight:700;font-size:15px;color:{preset['color']}">{preset_name}</div>
          <div style="font-size:12px;color:#888888;line-height:1.5">{preset['description']}</div>
        </div>""", unsafe_allow_html=True)
        ca, cb = st.columns(2)
        with ca:
            if st.button("Apply", key=f"apply_{preset_name}", use_container_width=True, type="primary"):
                st.session_state.filters = preset["filters"].copy()
                st.session_state.logic   = preset["logic"]
                st.session_state.active_preset = preset_name
                st.rerun()
        with cb:
            if st.button("Clear", key=f"clear_{preset_name}", use_container_width=True):
                if st.session_state.active_preset == preset_name:
                    st.session_state.filters = []
                    st.session_state.active_preset = None
                    st.rerun()

    st.divider()
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
    st.markdown("**Filter Logic**")
    st.session_state.logic = st.radio("", ["AND","OR"], horizontal=True,
        index=0 if st.session_state.logic == "AND" else 1, label_visibility="collapsed")

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
    st.link_button("↗ Open Google Sheet",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
        use_container_width=True)

# ── MAIN TABS ─────────────────────────────────────────────────────────────────
tab_screen, tab_detail, tab_heatmap, tab_perf = st.tabs([
    "📋 Screener", "🔍 Stock Detail", "🗺 Sector Heatmap", "📈 Performance"
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
al_count  = (df["Absolute_Longs"].astype(str).str.upper() == "YES").sum()   if "Absolute_Longs"    in df.columns else 0
bf_count  = (df["Bottom_Fishing"].astype(str).str.upper() == "YES").sum()   if "Bottom_Fishing"    in df.columns else 0

# ── TAB 1: SCREENER ───────────────────────────────────────────────────────────
with tab_screen:
    st.markdown("## Nifty 50 Screener")
    st.caption(f"Multi-indicator filter · {st.session_state.logic} logic · Data as of {last_date}")

    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    k1.metric("Total Stocks", len(df))
    k2.metric("Matching",     len(filtered))
    k3.metric("Supertrend BUY", int(buy_count))
    k4.metric("Absolute Longs", int(al_count))
    k5.metric("Bottom-Fishing", int(bf_count))
    st.divider()

    if filtered.empty:
        st.info("No stocks match the active filters.")
    else:
        s1, s2, _ = st.columns([3, 2, 5])
        with s1:
            sort_by = st.selectbox("Sort by", ["Returns","Close","RSI_14","ADX_14","MACD_hist","Volume"])
        with s2:
            sort_asc = st.selectbox("Order", ["High → Low","Low → High"])
        if sort_by in filtered.columns:
            filtered = filtered.sort_values(sort_by, ascending=(sort_asc == "Low → High"))

        rows = []
        for _, row in filtered.iterrows():
            stock  = str(row.get("Stock","")).replace(".NS","")
            sector = str(row.get("Sector","—"))
            rows.append(f"""<tr>
              <td><strong>{stock}</strong></td>
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
        st.download_button("⬇ Download CSV", filtered.to_csv(index=False),
            file_name=f"nifty50_{last_date}.csv", mime="text/csv")

# ── TAB 2: STOCK DETAIL ───────────────────────────────────────────────────────
with tab_detail:
    st.markdown("## Stock Detail View")
    stock_options = sorted(df["Stock"].str.replace(".NS","").unique().tolist())
    selected = st.selectbox("Select Stock", stock_options)

    if selected:
        full_sym = selected + ".NS"
        row = df[df["Stock"] == full_sym]
        if row.empty:
            row = df[df["Stock"] == selected]
        if not row.empty:
            row = row.iloc[0]
            st.markdown(f"### {selected} &nbsp; <span style='font-size:14px;color:#888'>{row.get('Sector','')}</span>",
                        unsafe_allow_html=True)

            # Fetch 1Y history live for the chart
            with st.spinner("Loading chart data..."):
                try:
                    end_dt   = datetime.today()
                    start_dt = end_dt - timedelta(days=365)
                    hist = yf.download(full_sym,
                                       start=start_dt.strftime("%Y-%m-%d"),
                                       end=end_dt.strftime("%Y-%m-%d"),
                                       interval="1d", auto_adjust=False, progress=False)
                    if isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = hist.columns.get_level_values(0)
                    hist = hist.reset_index()
                    chart_ok = not hist.empty
                except Exception:
                    chart_ok = False

            if chart_ok:
                hist["EMA10_p"] = hist["Close"].ewm(span=10, adjust=False).mean()
                hist["EMA20_p"] = hist["Close"].ewm(span=20, adjust=False).mean()
                hist["SMA50_p"] = hist["Close"].rolling(50).mean()
                bb_mid = hist["Close"].rolling(20).mean()
                bb_std = hist["Close"].rolling(20).std()
                hist["BB_U"] = bb_mid + 2 * bb_std
                hist["BB_L"] = bb_mid - 2 * bb_std

                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=hist["Date"], open=hist["Open"], high=hist["High"],
                    low=hist["Low"], close=hist["Close"], name="Price",
                    increasing_line_color="#008a58", decreasing_line_color="#c24141"))
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
                    xaxis_rangeslider_visible=False, margin=dict(l=0,r=0,t=30,b=0),
                    legend=dict(orientation="h", y=1.08), font=dict(size=11))
                st.plotly_chart(fig, use_container_width=True)

                # RSI sub-chart
                delta    = hist["Close"].diff()
                ag       = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                al_      = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                hist["RSI_p"] = 100 - (100 / (1 + ag / (al_ + 1e-10)))
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(x=hist["Date"], y=hist["RSI_p"], name="RSI 14",
                    line=dict(color="#2e75b6", width=1.5)))
                fig_rsi.add_hline(y=70, line_dash="dash", line_color="#c24141", line_width=1)
                fig_rsi.add_hline(y=50, line_dash="dot",  line_color="#888888", line_width=1)
                fig_rsi.add_hline(y=30, line_dash="dash", line_color="#008a58", line_width=1)
                fig_rsi.update_layout(height=160, template="plotly_white",
                    margin=dict(l=0,r=0,t=10,b=0), showlegend=False,
                    yaxis=dict(range=[0,100]), font=dict(size=11))
                st.plotly_chart(fig_rsi, use_container_width=True)
            else:
                st.info("Chart data unavailable for this stock.")

            # Indicator snapshot
            st.markdown("#### Indicator Snapshot")
            ind_groups = {
                "📈 Trend":     [("EMA 10","EMA_10"),("EMA 20","EMA_20"),("SMA 50","SMA_50"),
                                 ("Supertrend","Supertrend"),("Supertrend Sig","Supertrend_Signal")],
                "⚡ Momentum":  [("RSI 14","RSI_14"),("MACD Line","MACD_line"),
                                 ("MACD Signal","MACD_signal"),("MACD Hist","MACD_hist"),
                                 ("Stoch K","Stoch_K"),("Stoch D","Stoch_D")],
                "🌊 Volatility":[("ATR 14","ATR_14"),("BB Upper","BB_Upper"),
                                 ("BB Middle","BB_Middle"),("BB Lower","BB_Lower"),("BB %b","BB_pctB")],
                "📦 Volume":    [("OBV","OBV"),("VWAP","VWAP")],
                "💪 Trend Str": [("ADX 14","ADX_14"),("DI+","DI_Plus"),("DI-","DI_Minus")],
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
                            display = "🟢 BUY" if str(val).upper() == "BUY" else "🔴 SELL"
                        else:
                            try:    display = f"{float(val):.2f}"
                            except: display = str(val)
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;
                             padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:12px">
                          <span style="color:#888">{label}</span>
                          <span style="font-weight:600;color:#1a1a1a">{display}</span>
                        </div>""", unsafe_allow_html=True)

            st.markdown("#### Strategy Signals")
            sc1, sc2 = st.columns(2)
            with sc1:
                al_val   = str(row.get("Absolute_Longs","NO")).upper()
                al_color = "#008a58" if al_val == "YES" else "#cccccc"
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
                bf_color = "#c24141" if bf_val == "YES" else "#cccccc"
                st.markdown(f"""
                <div style="background:#fff;border:2px solid {bf_color};border-radius:12px;
                     padding:18px;text-align:center">
                  <div style="font-weight:700;font-size:1rem;color:{bf_color}">🎣 Bottom-Fishing</div>
                  <div style="font-size:1.8rem;font-weight:700;margin-top:8px;color:{bf_color}">
                    {"✓ ACTIVE" if bf_val=="YES" else "—"}</div>
                  <div style="font-size:11px;color:#888;margin-top:4px">Reversal signal</div>
                </div>""", unsafe_allow_html=True)

# ── TAB 3: SECTOR HEATMAP ─────────────────────────────────────────────────────
with tab_heatmap:
    st.markdown("## Sector Heatmap")
    st.caption("Average return and signal counts by sector")

    if "Sector" in df.columns and "Returns" in df.columns:
        heatmap_df   = filtered if st.session_state.filters else df
        sector_stats = heatmap_df.groupby("Sector").agg(
            Stocks      =("Stock","count"),
            Avg_Return  =("Returns","mean"),
            BUY_Count   =("Supertrend_Signal", lambda x: (x.astype(str).str.upper()=="BUY").sum()),
            AL_Count    =("Absolute_Longs",    lambda x: (x.astype(str).str.upper()=="YES").sum()),
            BF_Count    =("Bottom_Fishing",    lambda x: (x.astype(str).str.upper()=="YES").sum()),
        ).reset_index().sort_values("Avg_Return", ascending=False)

        fig_heat = px.bar(sector_stats, x="Sector", y="Avg_Return",
            color="Avg_Return",
            color_continuous_scale=["#c24141","#f5e6e6","#e6f4ee","#008a58"],
            color_continuous_midpoint=0,
            text=sector_stats["Avg_Return"].apply(lambda x: f"{x:+.2f}%"),
            title="Average Return % by Sector",
            labels={"Avg_Return":"Avg Return (%)"},
        )
        fig_heat.update_traces(textposition="outside")
        fig_heat.update_layout(height=380, template="plotly_white",
            margin=dict(l=0,r=0,t=40,b=0), coloraxis_showscale=False,
            font=dict(size=11), xaxis_tickangle=-30)
        st.plotly_chart(fig_heat, use_container_width=True)

        h1, h2 = st.columns(2)
        with h1:
            fig_al = px.bar(sector_stats.sort_values("AL_Count", ascending=False),
                x="Sector", y="AL_Count", title="🚀 Absolute Longs by Sector",
                color_discrete_sequence=["#2e75b6"], labels={"AL_Count":"Count"})
            fig_al.update_layout(height=300, template="plotly_white",
                margin=dict(l=0,r=0,t=40,b=0), font=dict(size=11), xaxis_tickangle=-30)
            st.plotly_chart(fig_al, use_container_width=True)
        with h2:
            fig_bf = px.bar(sector_stats.sort_values("BF_Count", ascending=False),
                x="Sector", y="BF_Count", title="🎣 Bottom-Fishing by Sector",
                color_discrete_sequence=["#c24141"], labels={"BF_Count":"Count"})
            fig_bf.update_layout(height=300, template="plotly_white",
                margin=dict(l=0,r=0,t=40,b=0), font=dict(size=11), xaxis_tickangle=-30)
            st.plotly_chart(fig_bf, use_container_width=True)

        st.dataframe(
            sector_stats.rename(columns={"Avg_Return":"Avg Return %","BUY_Count":"Supertrend BUY",
                "AL_Count":"Absolute Longs","BF_Count":"Bottom-Fishing"})
            .style.format({"Avg Return %":"{:+.2f}"}),
            use_container_width=True, hide_index=True)
    else:
        st.info("Sector data not available. Run screener first.")

# ── TAB 4: PERFORMANCE ────────────────────────────────────────────────────────
with tab_perf:
    st.markdown("## Strategy Performance")
    st.caption("Last 1 year · All Nifty 50 stocks pooled · Position shifted 1 day to avoid look-ahead bias")

    run_bt = st.button("▶ Run Backtest", type="primary")

    def _color(label, val):
        if "Drawdown" in label: return "negative" if val < 0 else "positive"
        if label in ("CAGR %","Sharpe Ratio","Sortino Ratio",
                     "Calmar Ratio","Win Rate %","Profit Factor",
                     "Benchmark CAGR %"):
            return "positive" if val > 0 else "negative"
        return ""

    def render_strategy_metrics(name, color, caption, metrics, eq_curve, bench_curve, drawdown_series):
        st.markdown(f"""
        <div style="border-left:4px solid {color};padding-left:14px;margin-bottom:8px">
          <div style="font-size:1.1rem;font-weight:700;color:{color}">{name}</div>
          <div style="font-size:12px;color:#888">{caption}</div>
        </div>""", unsafe_allow_html=True)

        labels = list(metrics.keys())
        values = list(metrics.values())

        row1 = st.columns(4, gap="small")
        row2 = st.columns(4, gap="small")
        for i, col in enumerate(row1):
            with col:
                lbl = labels[i]; val = values[i]
                cls = _color(lbl, val)
                st.markdown(f"""
                <div class="metric-card">
                  <div class="mc-label">{lbl}</div>
                  <div class="mc-value {cls}">{val:+.2f}</div>
                </div>""", unsafe_allow_html=True)
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        for i, col in enumerate(row2):
            with col:
                lbl = labels[i + 4]; val = values[i + 4]
                cls = _color(lbl, val)
                st.markdown(f"""
                <div class="metric-card">
                  <div class="mc-label">{lbl}</div>
                  <div class="mc-value {cls}">{val:+.2f}</div>
                </div>""", unsafe_allow_html=True)
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # Equity curve
        eq_df = pd.DataFrame({
            "Date":      eq_curve.index,
            "Strategy":  eq_curve.values,
            "Benchmark": bench_curve.reindex(eq_curve.index).values,
        }).dropna()
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=eq_df["Date"], y=eq_df["Strategy"],
            name=name, line=dict(color=color, width=2)))
        fig_eq.add_trace(go.Scatter(
            x=eq_df["Date"], y=eq_df["Benchmark"],
            name="Benchmark (Buy & Hold)", line=dict(color="#888888", width=1.5, dash="dot")))
        fig_eq.update_layout(
            title="Equity Curve — ₹1,00,000 Starting Capital",
            height=340, template="plotly_white",
            margin=dict(l=0,r=0,t=40,b=0),
            legend=dict(orientation="h", y=1.08),
            yaxis_tickprefix="₹", font=dict(size=11))
        st.plotly_chart(fig_eq, use_container_width=True)

        # Drawdown
        dd_df = drawdown_series.reset_index()
        dd_df.columns = ["Index","Drawdown"]
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=dd_df["Index"], y=dd_df["Drawdown"] * 100,
            fill="tozeroy", fillcolor="rgba(194,65,65,0.12)",
            line=dict(color="#c24141", width=1.5), name="Drawdown %"))
        fig_dd.update_layout(
            title="Drawdown %", height=200, template="plotly_white",
            margin=dict(l=0,r=0,t=40,b=0),
            yaxis_ticksuffix="%", font=dict(size=11), showlegend=False)
        st.plotly_chart(fig_dd, use_container_width=True)

    if run_bt:
        st.cache_data.clear()
        with st.spinner("Fetching 1 year of data for 50 stocks..."):
            raw_df = fetch_backtest_data()

        if raw_df.empty:
            st.error("Could not fetch price data. Check your internet connection.")
        else:
            with st.spinner("Running backtests for both strategies..."):
                al_metrics, al_eq, al_bench, al_dd = run_backtest(raw_df, strategy="absolute_longs")
                bf_metrics, bf_eq, bf_bench, bf_dd = run_backtest(raw_df, strategy="bottom_fishing")

            st.divider()

            # ── Side-by-side strategy tabs ────────────────────────────────────
            strat_tab_al, strat_tab_bf, strat_tab_cmp = st.tabs([
                "🚀 Absolute Longs", "🎣 Bottom-Fishing", "⚖ Comparison"
            ])

            with strat_tab_al:
                render_strategy_metrics(
                    name    = "🚀 Absolute Longs",
                    color   = "#008a58",
                    caption = "EMA10 > EMA20 · RSI > 50 · Supertrend BUY",
                    metrics = al_metrics,
                    eq_curve      = al_eq,
                    bench_curve   = al_bench,
                    drawdown_series = al_dd,
                )

            with strat_tab_bf:
                render_strategy_metrics(
                    name    = "🎣 Bottom-Fishing",
                    color   = "#c24141",
                    caption = "EMA10 < EMA20 · RSI < 50 · Supertrend SELL",
                    metrics = bf_metrics,
                    eq_curve      = bf_eq,
                    bench_curve   = bf_bench,
                    drawdown_series = bf_dd,
                )

            with strat_tab_cmp:
                st.markdown("#### Head-to-Head Comparison")
                cmp_df = pd.DataFrame({
                    "Metric":         list(al_metrics.keys()),
                    "Absolute Longs": [f"{v:+.2f}" for v in al_metrics.values()],
                    "Bottom-Fishing": [f"{v:+.2f}" for v in bf_metrics.values()],
                })
                st.dataframe(cmp_df, use_container_width=True, hide_index=True)

                # Overlay equity curves
                al_df = pd.DataFrame({"Date": al_eq.index, "Absolute Longs": al_eq.values})
                bf_df = pd.DataFrame({"Date": bf_eq.index, "Bottom-Fishing": bf_eq.values})
                bk_df = pd.DataFrame({"Date": al_bench.index, "Benchmark": al_bench.values})

                fig_cmp = go.Figure()
                fig_cmp.add_trace(go.Scatter(x=al_df["Date"], y=al_df["Absolute Longs"],
                    name="Absolute Longs", line=dict(color="#008a58", width=2)))
                fig_cmp.add_trace(go.Scatter(x=bf_df["Date"], y=bf_df["Bottom-Fishing"],
                    name="Bottom-Fishing", line=dict(color="#c24141", width=2)))
                fig_cmp.add_trace(go.Scatter(x=bk_df["Date"], y=bk_df["Benchmark"],
                    name="Benchmark", line=dict(color="#888888", width=1.5, dash="dot")))
                fig_cmp.update_layout(
                    title="Equity Curve Overlay — ₹1,00,000 Starting Capital",
                    height=380, template="plotly_white",
                    margin=dict(l=0,r=0,t=40,b=0),
                    legend=dict(orientation="h", y=1.08),
                    yaxis_tickprefix="₹", font=dict(size=11))
                st.plotly_chart(fig_cmp, use_container_width=True)
    else:
        st.info("Click **▶ Run Backtest** to fetch 1 year of data and compute performance metrics for both strategies.")
