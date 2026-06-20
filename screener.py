"""
screener.py — Nifty 50 Screener Data Pipeline
Fetches OHLCV from Yahoo Finance, computes 12 indicators, pushes to Google Sheets.

Indicators:
  Trend     : EMA_10, EMA_20, SMA_50, Supertrend
  Momentum  : RSI_14, MACD_hist, MACD_line, MACD_signal, Stoch_K, Stoch_D
  Volatility: ATR_14, BB_Upper, BB_Middle, BB_Lower, BB_pctB
  Volume    : OBV, VWAP (daily approx)
  Trend Str : ADX_14, DI_Plus, DI_Minus
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

SHEET_ID   = "1YsfDm4dFFM8aUfOS7uvIWDvphkSM39xOtlalgTUgkhM"
MASTER_CSV = "nifty50_master.csv"
SCOPES     = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Nifty 50 tickers (NSE)
NIFTY50_TICKERS = [
    "RELIANCE","TCS","HDFCBANK","BHARTIARTL","ICICIBANK",
    "INFY","SBILIFE","HINDUNILVR","ITC","LT",
    "KOTAKBANK","HCLTECH","BAJFINANCE","MARUTI","AXISBANK",
    "ASIANPAINT","NESTLEIND","SUNPHARMA","TITAN","ULTRACEMCO",
    "WIPRO","NTPC","TECHM","POWERGRID","BAJAJFINSV",
    "ADANIENT","ADANIPORTS","ONGC","TATAmotors","TATASTEEL",
    "SBIN","M&M","JSWSTEEL","COALINDIA","DIVISLAB",
    "DRREDDY","BRITANNIA","CIPLA","APOLLOHOSP","EICHERMOT",
    "GRASIM","HEROMOTOCO","HINDALCO","INDUSINDBK","BPCL",
    "BAJAJ-AUTO","TRENT","BEL","SHRIRAMFIN","HDFCLIFE",
]

NIFTY50_SYMBOLS = [t + ".NS" for t in NIFTY50_TICKERS]

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

SECTOR_MAP = {
    "RELIANCE":"Energy","TCS":"IT","HDFCBANK":"Banking","BHARTIARTL":"Telecom",
    "ICICIBANK":"Banking","INFY":"IT","SBILIFE":"Insurance","HINDUNILVR":"FMCG",
    "ITC":"FMCG","LT":"Capital Goods","KOTAKBANK":"Banking","HCLTECH":"IT",
    "BAJFINANCE":"NBFC","MARUTI":"Auto","AXISBANK":"Banking","ASIANPAINT":"Paints",
    "NESTLEIND":"FMCG","SUNPHARMA":"Pharma","TITAN":"Consumer","ULTRACEMCO":"Cement",
    "WIPRO":"IT","NTPC":"Power","TECHM":"IT","POWERGRID":"Power","BAJAJFINSV":"NBFC",
    "ADANIENT":"Conglomerate","ADANIPORTS":"Infrastructure","ONGC":"Energy",
    "TATAMOTOS":"Auto","TATASTEEL":"Metals","SBIN":"Banking","M&M":"Auto",
    "JSWSTEEL":"Metals","COALINDIA":"Energy","DIVISLAB":"Pharma","DRREDDY":"Pharma",
    "BRITANNIA":"FMCG","CIPLA":"Pharma","APOLLOHOSP":"Healthcare","EICHERMOT":"Auto",
    "GRASIM":"Cement","HEROMOTOCO":"Auto","HINDALCO":"Metals","INDUSINDBK":"Banking",
    "BPCL":"Energy","BAJAJ-AUTO":"Auto","TRENT":"Retail","BEL":"Defence",
    "SHRIRAMFIN":"NBFC","HDFCLIFE":"Insurance",
}

# ── AUTH ──────────────────────────────────────────────────────────────────────

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if creds_json:
        info = json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)
    else:
        with open("service_account.json") as f:
            info = json.load(f)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

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

    log(f"Fetching {len(NIFTY50_SYMBOLS)} stocks from {start_date} to {end_date}")
    all_rows = []

    for sym in NIFTY50_SYMBOLS:
        try:
            df = yf.download(sym, start=start_date, end=fetch_end,
                             interval="1d", auto_adjust=False,
                             progress=False, group_by="ticker")
            if df.empty:
                log(f"  ! {sym}: empty data, skipping")
                continue

            # Flatten MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join([c for c in col if c]).strip("_")
                              for col in df.columns]
                rename = {}
                for c in df.columns:
                    for base in ["Open","High","Low","Close","Volume","Adj Close"]:
                        if c.endswith(base):
                            rename[c] = base
                df = df.rename(columns=rename)

            df = df.reset_index()

            if "Date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "Date"})

            # Keep only needed columns
            keep = [c for c in ["Date","Open","High","Low","Close","Volume"] if c in df.columns]
            df = df[keep].copy()

            if "Close" not in df.columns:
                log(f"  ! {sym}: Close column missing, skipping")
                continue

            df["Stock"]  = sym
            ticker_name  = sym.replace(".NS","")
            df["Sector"] = SECTOR_MAP.get(ticker_name, "Other")
            all_rows.append(df)
            log(f"  ✓ {sym}: {len(df)} rows")

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

    # EMA
    data["EMA_10"] = close.ewm(span=10, adjust=False).mean()
    data["EMA_20"] = close.ewm(span=20, adjust=False).mean()

    # SMA
    data["SMA_50"] = close.rolling(50).mean()

    # RSI
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs       = avg_gain / (avg_loss + 1e-10)
    data["RSI_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD_line"]   = ema12 - ema26
    data["MACD_signal"] = data["MACD_line"].ewm(span=9, adjust=False).mean()
    data["MACD_hist"]   = data["MACD_line"] - data["MACD_signal"]

    # ATR
    hl  = high - low
    hc  = (high - close.shift()).abs()
    lc  = (low  - close.shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    data["ATR_14"] = atr

    # Supertrend
    hl2        = (high + low) / 2
    upper_band = hl2 + 3 * atr
    lower_band = hl2 - 3 * atr

    supertrend = [np.nan] * len(data)
    direction  = [1] * len(data)

    cl = close.values
    ub = upper_band.values.copy()
    lb = lower_band.values.copy()

    for i in range(1, len(data)):
        if np.isnan(atr.values[i]):
            continue

        lb[i] = lb[i] if (lb[i] > lb[i-1] or cl[i-1] < lb[i-1]) else lb[i-1]
        ub[i] = ub[i] if (ub[i] < ub[i-1] or cl[i-1] > ub[i-1]) else ub[i-1]

        if direction[i-1] == -1 and cl[i] > ub[i]:
            direction[i] = 1
        elif direction[i-1] == 1 and cl[i] < lb[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]

        supertrend[i] = lb[i] if direction[i] == 1 else ub[i]

    data["Supertrend"]        = supertrend
    data["Supertrend_Signal"] = ["BUY" if d == 1 else "SELL" for d in direction]

    # Bollinger Bands
    bb_mid            = close.rolling(20).mean()
    bb_std            = close.rolling(20).std()
    data["BB_Middle"] = bb_mid
    data["BB_Upper"]  = bb_mid + 2 * bb_std
    data["BB_Lower"]  = bb_mid - 2 * bb_std
    data["BB_pctB"]   = (close - data["BB_Lower"]) / (data["BB_Upper"] - data["BB_Lower"] + 1e-10)

    # Stochastics
    low14           = low.rolling(14).min()
    high14          = high.rolling(14).max()
    data["Stoch_K"] = 100 * (close - low14) / (high14 - low14 + 1e-10)
    data["Stoch_D"] = data["Stoch_K"].rolling(3).mean()

    # OBV
    obv = [0.0]
    for i in range(1, len(data)):
        if cl[i] > cl[i-1]:
            obv.append(obv[-1] + vol.values[i])
        elif cl[i] < cl[i-1]:
            obv.append(obv[-1] - vol.values[i])
        else:
            obv.append(obv[-1])
    data["OBV"] = obv

    # VWAP
    tp           = (high + low + close) / 3
    data["VWAP"] = (tp * vol).cumsum() / (vol.cumsum() + 1e-10)

    # ADX / DMI
    up_move   = high.diff()
    down_move = (-low.diff())
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    smoothed_tr       = tr.ewm(span=14, adjust=False).mean()
    smoothed_plus_dm  = plus_dm.ewm(span=14, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(span=14, adjust=False).mean()

    data["DI_Plus"]  = 100 * smoothed_plus_dm  / (smoothed_tr + 1e-10)
    data["DI_Minus"] = 100 * smoothed_minus_dm / (smoothed_tr + 1e-10)

    dx             = 100 * (data["DI_Plus"] - data["DI_Minus"]).abs() / \
                     (data["DI_Plus"] + data["DI_Minus"] + 1e-10)
    data["ADX_14"] = dx.ewm(span=14, adjust=False).mean()

    # Returns
    data["Prev_Close"] = close.shift(1)
    data["Returns"]    = close.pct_change() * 100

    # Strategy Flags
    data["Absolute_Longs"] = (
        (data["EMA_10"] > data["EMA_20"]) &
        (data["RSI_14"] > 50) &
        (data["MACD_hist"] > 0) &
        (data["Supertrend_Signal"] == "BUY")
    ).map({True: "YES", False: "NO"})

    data["Bottom_Fishing"] = (
        (data["EMA_10"] > data["EMA_20"]) &
        (data["RSI_14"] > 50) &
        (data["MACD_hist"] > 0) &
        (data["Supertrend_Signal"] == "SELL")
    ).map({True: "YES", False: "NO"})

    return data

# ── RUN ───────────────────────────────────────────────────────────────────────

def run(log=print):
    master = download_nifty50(log=log)
    if master.empty:
        log("No data. Aborting.")
        return

    master["Date"] = pd.to_datetime(master["Date"])

    log("Computing indicators for all stocks...")
    processed = (
        master.groupby("Stock", group_keys=False)
        .apply(compute_indicators)
    )

    latest = (
        processed.sort_values("Date")
        .groupby("Stock", group_keys=False)
        .apply(lambda x: x.iloc[-1])
        .reset_index(drop=True)
    )

    available = [c for c in OUTPUT_COLS if c in latest.columns]
    latest    = latest[available].copy()

    num_cols = latest.select_dtypes(include=[np.number]).columns
    latest[num_cols] = latest[num_cols].round(2)

    latest["Date"] = pd.to_datetime(latest["Date"]).dt.strftime("%Y-%m-%d")

    log(f"Snapshot ready: {len(latest)} stocks")

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
