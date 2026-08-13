# 📈 Angel One SmartAPI — NSE F&O Best Buy Scanner

A complete Python package that connects to **Angel One SmartAPI** in real-time, screens all
**209 NSE F&O stocks**, applies a **multi-factor Best-Buy formula**, and produces a ranked
buy-signal dashboard.

---

## 📁 Project Structure

```
angel_fo_scanner/
├── config/
│   └── config.yaml          ← API keys & settings
├── core/
│   ├── angel_client.py      ← SmartAPI login, session, TOTP
│   ├── data_fetcher.py      ← Bulk OHLCV + LTP fetcher
│   ├── fo_stocks.py         ← 209 NSE F&O stock list
│   └── indicators.py        ← RSI, MACD, EMA, Supertrend, Volume, OI
├── scanner/
│   ├── best_buy_formula.py  ← 100-point composite scoring engine
│   └── screener.py          ← Multi-threaded screener
├── output/
│   ├── report.py            ← Rich CLI table + HTML dashboard
│   └── alerts.py            ← Telegram alert push
├── main.py                  ← Entry point
├── requirements.txt
└── README.md
```

---

## 🔢 Best-Buy Scoring Formula (100 Points)

| # | Factor | Weight | Logic |
|---|--------|--------|-------|
| 1 | RSI(14) Momentum | 20 pts | RSI in 40-60 bullish zone |
| 2 | MACD Crossover | 20 pts | MACD > Signal + histogram rising |
| 3 | EMA Trend | 15 pts | Price > EMA20 > EMA50 > EMA200 |
| 4 | Volume Surge | 15 pts | Current vol > 1.5x 20-day average |
| 5 | OI Build-Up | 15 pts | OI rising + Price rising = Long Build-Up |
| 6 | Supertrend (7,3) | 10 pts | Supertrend in bullish mode |
| 7 | Near 52W High | 5 pts | Price within 15% of 52-week high |

### Score Interpretation
| Score | Grade | Signal |
|-------|-------|--------|
| 80-100 | A+ | STRONG BUY |
| 60-79 | A/B+ | BUY |
| 40-59 | B/C | WATCH |
| 0-39 | D | AVOID |

---

## Step-by-Step Setup

### Step 1 - Install Python
Make sure Python 3.9+ is installed:
```bash
python --version
```

### Step 2 - Install Dependencies
```bash
cd c:\xampp\htdocs\myapp
pip install -r requirements.txt
```

### Step 3 - Get Angel One API Key
1. Log in to Angel One Developer Portal: https://smartapi.angelbroking.com/
2. Create a new app and copy your API Key
3. Enable TOTP in your Angel One account settings
4. Copy the TOTP Secret key shown during TOTP setup

### Step 4 - Configure API Keys
Edit config/config.yaml:
```yaml
angel:
  api_key: "YOUR_API_KEY_HERE"
  client_id: "YOUR_ANGEL_LOGIN_ID"
  password: "YOUR_LOGIN_PASSWORD"
  totp_secret: "YOUR_TOTP_SECRET_KEY"
```

### Step 5 - Test in Demo Mode (No API Key Needed!)
```bash
python main.py --demo
```

### Step 6 - Run Live Scan
```bash
python main.py
```

### Step 7 - View Dashboard
Open output/dashboard.html in your browser. It auto-refreshes every 60 seconds.

---

## Usage Examples

```bash
# Demo mode - mock data, no API key
python main.py --demo

# Run once and exit (live)
python main.py --once

# Show top 10 picks
python main.py --top 10

# Live auto-refresh mode (every 60s)
python main.py
```

---

## Telegram Alerts (Optional)

1. Create a Telegram bot via @BotFather
2. Get your bot token and chat ID
3. Update config.yaml:
```yaml
alerts:
  telegram_enabled: true
  telegram_bot_token: "123456:ABCdef..."
  telegram_chat_id: "-1001234567890"
  alert_threshold: 70
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ImportError: smartapi | Run pip install smartapi-python |
| Login fails | Check API key + TOTP secret in config.yaml |
| Empty results | Try --demo flag first |
| TOTP error | Re-scan QR code in Angel One app |
| Rate limit errors | Increase delay_ms in data_fetcher.py |

---

DISCLAIMER: For educational purposes only. Not financial advice.
