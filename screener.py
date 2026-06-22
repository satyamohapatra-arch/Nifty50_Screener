"""
screener.py — Nifty 50 Screener Data Pipeline

Fetches OHLCV from Yahoo Finance, computes 12 indicators, pushes to Google Sheets.
Tickers are loaded dynamically from ind_nifty50list.csv (NSE official list).

Indicators:
  Trend    : EMA_10, EMA_20, SMA_50, Supertrend
  Momentum : RSI_14, MACD_hist, MACD_line, MACD_signal, Stoch_K, Stoch_D
  Volatility: ATR_14, BB_Upper, BB_Middle, BB_Lower, BB_pctB
  Volume   : OBV, VWAP (daily approx)
  Trend Str: ADX_14, DI_Plus, DI_Minus
"""

import os, json, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import gspread
import gspread_dataframe as gd
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import zoneinfo

# ── CONFIG ────────────────────────────────────────────────────────────────────

SHEET_ID    = "1YsfDm4dFFM8aUfOS7uvIWDvphkSM39xOtlalgTUgkhM"
MASTER_CSV  = "nifty50_master.csv"
TICKER_CSV  = "ind_nifty50list.csv"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# ── LOAD TICKERS FROM CSV ─────────────────────────────────────────────────────

def load_tickers(csv_path: str = TICKER_CSV):
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Symbol"])
    tickers    = df["Symbol"].str.strip().tolist()
    symbols    = [t + ".NS" for t in tickers]
    sector_map = dict(zip(df["Symbol"].str.strip(), df["Industry"].str.strip()))
    return tickers, symbols, sector_map


NIFTY50_TICKERS, NIFTY50_SYMBOLS, SECTOR_MAP = load_tickers()

OUTPUT_COLS = [
    "Date","Stock","Sector",
    "Open","High","Low","Close","Volume",
    "Prev_Close","Returns",
    "EMA_10","EMA_20","SMA_50","Supertrend","Supertrend_Signal",
    "RSI_14","MACD_line","MACD_signal","MACD_hist",
    "Stoch_K","Stoch_D",
    "ATR_14","BB_Upper","BB_Middle","BB_Lower","BB_pctB",
    "OBV","VWAP",
    "ADX_14","DI_Plus","DI_Minus",
    "Absolute_Longs","Bottom_Fishing",
]

# ── AUTH ──────────────────────────────────────────────────────────────────────

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if creds_json:
        info = json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)
    else:
        with open("service_account.json") as f:
            info = json.load(f)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    # gspread >= 5: gspread.authorize() removed — use Client directly
    return gspread.Client(auth=creds)

# ── DATE ──────────────────────────────────────────────────────────────────────

def last_trading_day():
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    day = now if now >= market_close else now - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────

def download_nifty50(log=print):
    end_date  = last_trading_day()
    fetch_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    if os.path.exists(MASTER_CSV):
        existing   = pd.read_csv(MASTER_CSV, parse_dates=["Date"])
        last_date  = existing["Date"].max()
        start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        existing   = None
        start_date = "2020-01-01"

    if start_date > end_date:
        log("Data already up to date.")
        return pd.read_csv(MASTER_CSV, parse_dates=["Date"])

    log(f"Fetching {len(NIFTY50_SYMBOLS)} stocks from {start_date} → {end_date}")

    all_rows = []
    for sym in NIFTY50_SYMBOLS:
        try:
            df = yf.download(sym, start=start_date, end=fetch_end,
                             interval="1d", auto_adjust=False, progress=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()[["Date","Open","High","Low","Close","Volume"]]
            df["Stock"]  = sym
            ticker_name  = sym.replace(".NS","")
            df["Sector"] = SECTOR_MAP.get(ticker_name, "Other")
            all_rows.append(df)
        except Exception as e:
            log(f"  ✗ {sym}: {e}")

    if not all_rows:
        log("No new data fetched.")
        return existing if existing is not None else pd.DataFrame()

    new_data = pd.concat(all_rows, ignore_index=True)
    if existing is not None:
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Date","Stock"])
    else:
        combined = new_data

    combined.to_csv(MASTER_CSV, index=False)
    log(f"Master CSV: {len(combined):,} rows.")
    return combined

# ── INDICATORS ────────────────────────────────────────────────────────────────

def compute_indicators(data: pd.DataFrame) -> pd.DataFrame:
    data  = data.sort_values("Date").copy()
    close = data["Close"].astype(float)
    high  = data["High"].astype(float)
    low   = data["Low"].astype(float)
    vol   = data["Volume"].astype(float)

    data["EMA_10"] = close.ewm(span=10, adjust=False).mean()
    data["EMA_20"] = close.ewm(span=20, adjust=False).mean()
    data["SMA_50"] = close.rolling(50).mean()

    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    data["RSI_14"] = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-10)))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD_line"]   = ema12 - ema26
    data["MACD_signal"] = data["MACD_line"].ewm(span=9, adjust=False).mean()
    data["MACD_hist"]   = data["MACD_line"] - data["MACD_signal"]

    hl  = high - low
    hc  = (high - close.shift()).abs()
    lc  = (low  - close.shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    data["ATR_14"] = atr

    hl2_arr = ((high + low) / 2).values
    atr_arr = atr.values
    cl      = close.values
    n       = len(data)
    ub = np.full(n, np.nan)
    lb = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)

    for i in range(n):
        if np.isnan(atr_arr[i]) or np.isnan(hl2_arr[i]):
            continue
        raw_ub = hl2_arr[i] + 3.0 * atr_arr[i]
        raw_lb = hl2_arr[i] - 3.0 * atr_arr[i]
        if i == 0 or np.isnan(lb[i-1]) or np.isnan(ub[i-1]):
            lb[i] = raw_lb
            ub[i] = raw_ub
        else:
            lb[i] = raw_lb if (raw_lb > lb[i-1] or cl[i-1] < lb[i-1]) else lb[i-1]
            ub[i] = raw_ub if (raw_ub < ub[i-1] or cl[i-1] > ub[i-1]) else ub[i-1]
        if i == 0:
            direction[i] = 1
        elif direction[i-1] == -1 and cl[i] > ub[i]:
            direction[i] = 1
        elif direction[i-1] == 1 and cl[i] < lb[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]

    data["Supertrend"]        = np.where(direction == 1, lb, ub)
    data["Supertrend_Signal"] = ["BUY" if d == 1 else "SELL" for d in direction]

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    data["BB_Middle"] = bb_mid
    data["BB_Upper"]  = bb_mid + 2 * bb_std
    data["BB_Lower"]  = bb_mid - 2 * bb_std
    data["BB_pctB"]   = (close - data["BB_Lower"]) / (data["BB_Upper"] - data["BB_Lower"] + 1e-10)

    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    data["Stoch_K"] = 100 * (close - low14) / (high14 - low14 + 1e-10)
    data["Stoch_D"] = data["Stoch_K"].rolling(3).mean()

    obv = [0.0]
    for i in range(1, len(data)):
        if   cl[i] > cl[i-1]: obv.append(obv[-1] + vol.values[i])
        elif cl[i] < cl[i-1]: obv.append(obv[-1] - vol.values[i])
        else:                  obv.append(obv[-1])
    data["OBV"] = obv

    tp = (high + low + close) / 3
    data["VWAP"] = (tp * vol).cumsum() / (vol.cumsum() + 1e-10)

    up_move   = high.diff()
    down_move = (-low.diff())
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_tr       = tr.ewm(span=14, adjust=False).mean()
    smoothed_plus_dm  = plus_dm.ewm(span=14, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(span=14, adjust=False).mean()
    data["DI_Plus"]  = 100 * smoothed_plus_dm  / (smoothed_tr + 1e-10)
    data["DI_Minus"] = 100 * smoothed_minus_dm / (smoothed_tr + 1e-10)
    dx = 100 * (data["DI_Plus"] - data["DI_Minus"]).abs() / \
              (data["DI_Plus"] + data["DI_Minus"] + 1e-10)
    data["ADX_14"] = dx.ewm(span=14, adjust=False).mean()

    data["Prev_Close"] = close.shift(1)
    data["Returns"]    = close.pct_change() * 100

    data["Absolute_Longs"] = (
        (data["EMA_10"] > data["EMA_20"]) &
        (data["RSI_14"] > 50) &
        (data["MACD_hist"] > 0) &
        (data["Supertrend_Signal"] == "BUY")
    ).map({True: "YES", False: "NO"})

    data["Bottom_Fishing"] = (
        (data["EMA_10"] < data["EMA_20"]) &
        (data["RSI_14"] < 50) &
        (data["MACD_hist"] < 0) &
        (data["Supertrend_Signal"] == "SELL")
    ).map({True: "YES", False: "NO"})

    return data

# ── RUN ───────────────────────────────────────────────────────────────────────

def run(log=print):
    # 1. Download / update OHLCV
    master = download_nifty50(log=log)
    if master.empty:
        log("No data. Aborting.")
        return

    master["Date"] = pd.to_datetime(master["Date"])

    # 2. Compute indicators per stock
    # Loop explicitly — avoids pandas 2.x groupby.apply() dropping the
    # "Stock" column when it is used as the group key
    log("Computing indicators for all stocks...")
    frames = []
    for stock, grp in master.groupby("Stock"):
        result = compute_indicators(grp.copy())
        result["Stock"] = stock          # guarantee column survives
        frames.append(result)
    processed = pd.concat(frames, ignore_index=True)

    # 3. Take latest row per stock
    # Same fix: loop instead of groupby.apply()
    latest_frames = []
    for stock, grp in processed.groupby("Stock"):
        latest_frames.append(grp.sort_values("Date").iloc[[-1]])
    latest = pd.concat(latest_frames, ignore_index=True)

    # 4. Select and round output columns
    available        = [c for c in OUTPUT_COLS if c in latest.columns]
    latest           = latest[available].copy()
    num_cols         = latest.select_dtypes(include=[np.number]).columns
    latest[num_cols] = latest[num_cols].round(2)
    latest["Date"]   = pd.to_datetime(latest["Date"]).dt.strftime("%Y-%m-%d")

    log(f"Snapshot ready: {len(latest)} stocks")

    # 5. Push to Google Sheets
    log("Pushing to Google Sheets...")
    gc        = get_gspread_client()
    sh        = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
    worksheet.clear()
    gd.set_with_dataframe(worksheet, latest)
    log(f"Done. {len(latest)} rows pushed to sheet.")
    return latest


if __name__ == "__main__":
    run()
