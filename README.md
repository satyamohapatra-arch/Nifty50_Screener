# Nifty 50 Algorithmic Equity Screener
**Paterson Securities | Data Analytics Internship Project**

A systematic, multi-indicator equity screening dashboard for the Nifty 50 universe, implementing two algorithmic trading strategies:
- **Absolute Longs** — Aggressive trend-following (full indicator convergence)
- **Bottom-Fishing** — Early structural reversal detection (indicator divergence)

---

## Project Structure

```
nifty50-screener/
├── screener.py          # Data pipeline: OHLCV fetch + 12 indicators → Google Sheets
├── app.py               # Streamlit dashboard: screener + detail view + heatmap
├── requirements.txt
└── README.md
```

---

## Indicators Computed (12)

| # | Indicator | Category |
|---|-----------|----------|
| 1 | EMA 10 & 20 | Trend |
| 2 | SMA 50 | Trend |
| 3 | Supertrend (ATR-based) | Trend / Regime |
| 4 | RSI 14 | Momentum |
| 5 | MACD + Histogram | Momentum |
| 6 | Stochastics (K & D) | Momentum |
| 7 | ATR 14 | Volatility |
| 8 | Bollinger Bands + %b | Volatility |
| 9 | OBV | Volume |
| 10 | VWAP | Volume |
| 11 | ADX 14 | Trend Strength |
| 12 | DI+ / DI- | Trend Strength |

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/nifty50-screener.git
cd nifty50-screener
pip install -r requirements.txt
```

### 2. Google Sheets setup
1. Create a new Google Sheet (note the Sheet ID from the URL)
2. Create a Google Cloud service account and download `service_account.json`
3. Share the sheet with the service account email
4. Replace `YOUR_GOOGLE_SHEET_ID_HERE` in both `screener.py` and `app.py`

### 3. Run the data pipeline
```bash
python screener.py
```
This fetches ~4 years of OHLCV data for all 50 Nifty 50 stocks, computes all 12 indicators, and pushes the latest snapshot to Google Sheets. Takes 3–5 minutes on first run.

### 4. Launch the dashboard
```bash
streamlit run app.py
```

---

## Streamlit Cloud Deployment
1. Push to GitHub
2. Connect repo on share.streamlit.io
3. Add secret in Streamlit Cloud settings:
   - Key: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Value: contents of your `service_account.json`
4. Set up a GitHub Action (or manual trigger from sidebar) to refresh data daily

---

## Strategy Logic

### 🚀 Absolute Longs (Trend-Following)
```
EMA_10 > EMA_20  AND  RSI_14 > 50  AND  MACD_hist > 0  AND  Supertrend = 'BUY'
```
Full bullish convergence. High win rate. Suited to bull markets.

### 🎣 Bottom-Fishing (Mean Reversion)
```
EMA_10 > EMA_20  AND  RSI_14 > 50  AND  MACD_hist > 0  AND  Supertrend = 'SELL'
```
Short-term momentum vs. macro bearish regime divergence. Asymmetric R:R (1:3+). Suited to post-correction phases.
