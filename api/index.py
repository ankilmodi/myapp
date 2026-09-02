"""
api/index.py
============
Vercel serverless handler with LIVE intraday stock picks
- Always shows FRESHEST Top 5 ranked by score on every refresh
- Day-wise profit tracking (per-stock & total)
- NEW badge when a stock enters top 5
- Live JS countdown timer for next refresh
"""

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import sys
import os
import json
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import with error handling
IMPORTS_OK = True
import_errors = []

try:
    import pyotp
except Exception as e:
    IMPORTS_OK = False
    import_errors.append(f"pyotp: {str(e)}")

try:
    from SmartApi import SmartConnect
except Exception as e:
    IMPORTS_OK = False
    import_errors.append(f"SmartApi: {str(e)}")

# ─── Cache ─────────────────────────────────────────────────────────────────────
# TTL = 300s (5 min) — Angel One rate limit is ~3 req/sec across all endpoints.
# Vercel is stateless so _cache resets per cold-start, but within a warm instance
# this prevents hammering the API on every page hit.
_cache = {
    "data": None,
    "timestamp": None,
    "ttl": 300,          # 5 minutes between live API calls
    "stale": False,      # True when we're serving old data due to a rate-limit hit
    "stale_reason": "",  # Human-readable reason shown in UI
}

# ─── Day-wise profit tracker ──────────────────────────────────────────────────
# Stores per-stock profit across refreshes within one trading day
# Structure: { "YYYY-MM-DD": { "SYMBOL": {"entry": x, "profit_history": [...], "sessions": n} } }
_day_profit = {
    "date": None,
    "stocks": {}        # symbol -> {entry_price, realized_profit, sessions}
}

# Previous top-5 symbols (to detect NEW entries)
_prev_top5 = []


# ─────────────────────────────────────────────────────────────────────────────
#  INDICATOR CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_rsi(prices, period=14):
    if len(prices) < period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change); losses.append(0)
        else:
            gains.append(0); losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price * k) + (ema * (1 - k))
    return round(ema, 2)


def calculate_vwap(candles):
    if not candles:
        return 0
    total_pv = total_vol = 0
    for c in candles:
        typical = (float(c[2]) + float(c[3]) + float(c[4])) / 3
        vol = float(c[5])
        total_pv += typical * vol
        total_vol += vol
    return round(total_pv / total_vol, 2) if total_vol > 0 else 0


def calculate_adx(candles, period=14):
    if len(candles) < period + 1:
        return 25, 20, 15
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(candles)):
        high = float(candles[i][2]); low = float(candles[i][3])
        prev_close = float(candles[i - 1][4])
        prev_high = float(candles[i - 1][2]); prev_low = float(candles[i - 1][3])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        plus_dm = max(high - prev_high, 0) if (high - prev_high) > (prev_low - low) else 0
        minus_dm = max(prev_low - low, 0) if (prev_low - low) > (high - prev_high) else 0
        plus_dm_list.append(plus_dm); minus_dm_list.append(minus_dm)
    atr = sum(tr_list[-period:]) / period
    plus_di  = (sum(plus_dm_list[-period:]) / period / atr * 100) if atr > 0 else 0
    minus_di = (sum(minus_dm_list[-period:]) / period / atr * 100) if atr > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return round(dx, 2), round(plus_di, 2), round(minus_di, 2)


def calculate_momentum(prices, period=5):
    if len(prices) < period + 1:
        return 0
    return round(((prices[-1] - prices[-period - 1]) / prices[-period - 1]) * 100, 2)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0
    tr_list = []
    for i in range(1, len(candles)):
        high = float(candles[i][2]); low = float(candles[i][3])
        prev_close = float(candles[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return round(sum(tr_list[-period:]) / period, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  SIGNALS
# ─────────────────────────────────────────────────────────────────────────────

def get_smart_money_signal(rsi):
    if rsi >= 65:  return "INSTITUTIONAL BUY FLOW"
    elif rsi >= 55: return "Accumulation Phase"
    elif rsi >= 45: return "Consolidation"
    elif rsi >= 35: return "Distribution Phase"
    else:           return "INSTITUTIONAL SELL FLOW"


def get_action_verdict(rsi, smart_signal):
    if rsi >= 50 and "BUY FLOW" in smart_signal: return "STRONG BUY ⬆⬆"
    elif rsi >= 50:                               return "BUY ⬆"
    elif rsi >= 40 and "BUY FLOW" in smart_signal: return "ACCUMULATE 📈"
    elif rsi >= 40:                               return "HOLD ➡"
    else:                                         return "AVOID ⬇"


def get_buy_rating(score):
    if score >= 90:   return "🔥 A+ STRONG BUY"
    elif score >= 85: return "🟢 A STRONG BUY"
    elif score >= 80: return "🟢 BUY"
    elif score >= 75: return "🟡 BUY AFTER CONFIRMATION"
    elif score >= 70: return "🟡 WATCH"
    else:             return "🔴 AVOID"


def calculate_targets(ltp):
    entry_price = round(ltp * 0.995, 2)
    target1     = round(ltp * 1.02, 2)
    target2     = round(ltp * 1.03, 2)
    target3     = round(ltp * 1.05, 2)
    stop_loss   = round(ltp * 0.98, 2)
    return entry_price, stop_loss, target1, target2, target3


# ─────────────────────────────────────────────────────────────────────────────
#  ADVANCED SCORE
# ─────────────────────────────────────────────────────────────────────────────

def calculate_advanced_score(stock_data, prices, candles, avg_volume):
    score = 0
    ltp = stock_data['ltp']
    rsi = stock_data['rsi']

    # 1. RSI (15 pts)
    if 60 <= rsi <= 70:    score += 15
    elif 55 <= rsi < 60:   score += 12
    elif 50 <= rsi < 55:   score += 10
    elif 70 < rsi <= 75:   score += 8
    elif 40 <= rsi < 50:   score += 6

    # 2. EMA (15 pts)
    ema9  = calculate_ema(prices, 9)
    ema20 = calculate_ema(prices, 20)
    ema50 = calculate_ema(prices, 50)
    stock_data.update({'ema9': ema9, 'ema20': ema20, 'ema50': ema50})
    if ltp > ema9 > ema20 > ema50: score += 15
    elif ltp > ema20 > ema50:      score += 12
    elif ltp > ema20:              score += 8
    elif ltp > ema50:              score += 5

    # 3. VWAP (15 pts)
    vwap = calculate_vwap(candles)
    stock_data['vwap'] = vwap
    dist = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0
    if ltp > vwap and 0 < dist < 3:   score += 15
    elif ltp > vwap and dist < 5:     score += 10
    elif ltp > vwap:                  score += 5
    elif abs(dist) < 0.5:             score += 7

    # 4. ADX (15 pts)
    adx, plus_di, minus_di = calculate_adx(candles)
    stock_data.update({'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di})
    if adx >= 25 and plus_di > minus_di:   score += 15
    elif adx >= 20 and plus_di > minus_di: score += 12
    elif adx >= 15 and plus_di > minus_di: score += 8
    elif plus_di > minus_di:              score += 5

    # 5. Volume/RVOL (20 pts)
    current_volume = sum([float(c[5]) for c in candles[-5:]])
    rvol = current_volume / avg_volume if avg_volume > 0 else 1
    stock_data['rvol'] = round(rvol, 2)
    if rvol >= 2.0:   score += 20
    elif rvol >= 1.5: score += 16
    elif rvol >= 1.2: score += 12
    elif rvol >= 1.0: score += 8
    else:             score += 4

    # 6. Momentum (10 pts)
    m5  = calculate_momentum(prices, 5)
    m10 = calculate_momentum(prices, 10)
    stock_data['momentum'] = m5
    if m5 > 0 and m10 > 0: score += 10
    elif m5 > 0:            score += 6
    elif m10 > 0:           score += 4

    # 7. Smart Money (10 pts)
    if "BUY FLOW" in stock_data['smart_signal']:   score += 10
    elif "Accumulation" in stock_data['smart_signal']: score += 6
    elif "Consolidation" in stock_data['smart_signal']: score += 3

    # Penalties
    if rsi > 80:   score -= 10
    if dist > 5:   score -= 5

    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────────────────
#  DAY-WISE PROFIT TRACKER
# ─────────────────────────────────────────────────────────────────────────────

def update_day_profit(today, top5_stocks):
    """
    Called after every fetch. Accumulates intraday profit seen so far today.
    Returns enriched stocks with day_profit field and a day_total_profit.
    """
    global _day_profit

    # Reset on new day
    if _day_profit["date"] != today:
        _day_profit = {"date": today, "stocks": {}}

    day_total = 0.0

    for stock in top5_stocks:
        sym = stock["symbol"]
        ltp = stock["ltp"]
        entry = stock["entry_price"]
        shares = stock["shares_to_buy"]

        if sym not in _day_profit["stocks"]:
            # First time we see this stock today
            _day_profit["stocks"][sym] = {
                "first_entry": entry,
                "sessions": 0,
                "cumulative_profit": 0.0
            }

        rec = _day_profit["stocks"][sym]
        rec["sessions"] += 1

        # Profit this session = (ltp - first_entry) * shares
        session_profit = round((ltp - rec["first_entry"]) * shares, 2)
        rec["cumulative_profit"] = session_profit   # live running value

        stock["day_profit"]       = session_profit
        stock["day_profit_pct"]   = round((session_profit / (rec["first_entry"] * shares)) * 100, 2) if rec["first_entry"] > 0 and shares > 0 else 0
        stock["first_entry"]      = rec["first_entry"]
        stock["sessions_today"]   = rec["sessions"]

        day_total += session_profit

    return top5_stocks, round(day_total, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  RATE-LIMIT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _is_rate_limit_error(response_or_exception):
    """
    Angel One returns rate-limit errors in two ways:
      1. HTTP response body: b'Access denied because of exceeding access rate'
      2. JSON with errorcode like 'AB1004' or message containing 'rate'
    Returns True if either pattern is detected.
    """
    text = str(response_or_exception).lower()
    return (
        "access rate" in text
        or "rate limit" in text
        or "ab1004" in text
        or "exceeding" in text
        or "too many" in text
    )


def _fetch_with_retry(fn, *args, retries=3, base_delay=2.0, **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff on rate-limit errors.
    Returns (result, hit_rate_limit:bool)
    """
    for attempt in range(retries):
        try:
            result = fn(*args, **kwargs)
            # Angel One sometimes returns rate-limit text instead of JSON
            if isinstance(result, (str, bytes)) and _is_rate_limit_error(result):
                raise ValueError(f"Rate limit in response: {result}")
            return result, False
        except Exception as e:
            if _is_rate_limit_error(e):
                wait = base_delay * (2 ** attempt)   # 2s, 4s, 8s
                print(f"Rate limit hit (attempt {attempt+1}/{retries}), waiting {wait}s...")
                time.sleep(wait)
                if attempt == retries - 1:
                    return None, True   # all retries exhausted
            else:
                raise   # non-rate-limit error — bubble up
    return None, True


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN DATA FETCH — Always fresh top 5, rate-limit safe
# ─────────────────────────────────────────────────────────────────────────────

def get_live_stock_data():
    global _prev_top5

    if not IMPORTS_OK:
        return {"error": "Required libraries not available: " + ", ".join(import_errors),
                "stocks": [], "import_errors": import_errors}

    now        = datetime.now()
    today_date = now.strftime("%Y-%m-%d")

    # ── Serve cache if still fresh (5-minute window) ──────────────────────
    if _cache["data"] and _cache["timestamp"]:
        age = (now - _cache["timestamp"]).total_seconds()
        if age < _cache["ttl"]:
            # Inject live cache-age into the result so UI can show it
            cached = dict(_cache["data"])
            cached["cache_age_secs"] = int(age)
            cached["from_cache"]     = True
            cached["stale"]          = _cache.get("stale", False)
            cached["stale_reason"]   = _cache.get("stale_reason", "")
            cached["refresh_interval"] = _cache["ttl"]
            return cached

    api_key     = os.environ.get("ANGEL_API_KEY", "")
    client_id   = os.environ.get("ANGEL_CLIENT_ID", "")
    password    = os.environ.get("ANGEL_PASSWORD", "")
    totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "")

    if not all([api_key, client_id, password, totp_secret]):
        # Return stale cache with a notice rather than an empty error
        if _cache["data"]:
            stale = dict(_cache["data"])
            stale["stale"] = True
            stale["stale_reason"] = "Credentials not configured — showing last known data"
            stale["from_cache"]   = True
            return stale
        return {"error": "Credentials not configured", "stocks": []}

    try:
        # ── Single login session reused for ALL stock fetches ──────────────
        smart_api = SmartConnect(api_key=api_key)
        totp      = pyotp.TOTP(totp_secret).now()

        session_data, rate_hit = _fetch_with_retry(
            smart_api.generateSession, client_id, password, totp
        )

        if rate_hit or session_data is None:
            # Rate limit on login itself — serve stale cache
            if _cache["data"]:
                stale = dict(_cache["data"])
                stale["stale"]        = True
                stale["stale_reason"] = "Angel One rate limit on login — showing cached data"
                stale["from_cache"]   = True
                _cache["stale"]       = True
                _cache["stale_reason"] = stale["stale_reason"]
                return stale
            return {"error": "Rate limit hit and no cache available. Wait 1 minute.", "stocks": []}

        if not session_data.get("status"):
            return {"error": f"Login failed: {session_data.get('message', 'Unknown error')}", "stocks": []}

        # ── 20 High-Volume Midcap F&O stocks — best for intraday ──────────
        # Selected for: high liquidity, tight spreads, strong intraday moves
        stock_tokens = [
            # Midcap Banking & Finance
            {"symbol": "BANKBARODA",  "token": "4668",  "exchange": "NSE"},  # ~220  BoB
            {"symbol": "PNB",         "token": "10666", "exchange": "NSE"},  # ~100  Punjab National
            {"symbol": "CANBK",       "token": "10794", "exchange": "NSE"},  # ~100  Canara Bank
            {"symbol": "FEDERALBNK",  "token": "1023",  "exchange": "NSE"},  # ~185  Federal Bank
            {"symbol": "IDFCFIRSTB",  "token": "11865", "exchange": "NSE"},  # ~75   IDFC First

            # Auto & Ancillaries (Midcap)
            {"symbol": "ASHOKLEY",    "token": "212",   "exchange": "NSE"},  # ~220  Ashok Leyland
            {"symbol": "TATAMOTORS",  "token": "3456",  "exchange": "NSE"},  # ~950  Tata Motors
            {"symbol": "M&MFIN",      "token": "13285", "exchange": "NSE"},  # ~290  M&M Finance
            {"symbol": "MOTHERSON",   "token": "4204",  "exchange": "NSE"},  # ~180  Samvardhana

            # Infrastructure & PSU (Midcap)
            {"symbol": "SAIL",        "token": "3926",  "exchange": "NSE"},  # ~130  SAIL
            {"symbol": "NMDC",        "token": "15332", "exchange": "NSE"},  # ~220  NMDC
            {"symbol": "RECLTD",      "token": "13611", "exchange": "NSE"},  # ~550  REC
            {"symbol": "PFC",         "token": "14299", "exchange": "NSE"},  # ~470  Power Finance
            {"symbol": "IRFC",        "token": "13611", "exchange": "NSE"},  # ~200  Indian Railway Finance (use RECLTD token as fallback)

            # Energy & Commodities
            {"symbol": "NTPC",        "token": "11630", "exchange": "NSE"},  # ~370  NTPC
            {"symbol": "COALINDIA",   "token": "5215",  "exchange": "NSE"},  # ~430  Coal India
            {"symbol": "POWERGRID",   "token": "14977", "exchange": "NSE"},  # ~300  Power Grid

            # Telecom & IT (Midcap)
            {"symbol": "IDEA",        "token": "14366", "exchange": "NSE"},  # ~14   Vodafone Idea (penny-large vol)
            {"symbol": "MPHASIS",     "token": "4503",  "exchange": "NSE"},  # ~2500 Mphasis

            # Metals & Mining
            {"symbol": "JINDALSTEL",  "token": "16675", "exchange": "NSE"},  # ~950  Jindal Steel
        ]

        stocks_data   = []
        rate_hit_any  = False
        to_date       = now
        from_date     = to_date - timedelta(days=30)

        for stock in stock_tokens:
            try:
                # ── 0.5s delay between each stock to stay within rate limits ──
                time.sleep(0.5)

                hist_data, rl1 = _fetch_with_retry(
                    smart_api.getCandleData,
                    {
                        "exchange":    stock["exchange"],
                        "symboltoken": stock["token"],
                        "interval":    "ONE_DAY",
                        "fromdate":    from_date.strftime("%Y-%m-%d %H:%M"),
                        "todate":      to_date.strftime("%Y-%m-%d %H:%M"),
                    }
                )

                # Small gap between the two calls for the same stock
                time.sleep(0.3)

                ltp_data, rl2 = _fetch_with_retry(
                    smart_api.ltpData,
                    stock["exchange"], stock["symbol"], stock["token"]
                )

                if rl1 or rl2:
                    rate_hit_any = True
                    print(f"Rate limit on {stock['symbol']} — skipping")
                    continue

                if ltp_data and ltp_data.get("status") and ltp_data.get("data"):
                    ltp = ltp_data["data"].get("ltp", 0)
                    prices, candles, total_volume = [], [], 0

                    if hist_data and hist_data.get("status") and hist_data.get("data"):
                        candles = hist_data["data"]
                        for candle in candles:
                            prices.append(float(candle[4]))
                            total_volume += float(candle[5])

                    avg_volume   = total_volume / len(candles) if candles else 1
                    rsi          = calculate_rsi(prices) if prices else 50.0
                    smart_signal = get_smart_money_signal(rsi)
                    action       = get_action_verdict(rsi, smart_signal)
                    entry_price, stop_loss, t1, t2, t3 = calculate_targets(ltp)

                    investment_per_stock = 2000
                    shares            = int(investment_per_stock / entry_price)
                    actual_investment = shares * entry_price
                    profit_per_share  = t2 - entry_price
                    total_profit      = round(profit_per_share * shares, 2)
                    profit_pct        = round((profit_per_share / entry_price) * 100, 2)

                    stock_info = {
                        "symbol":          stock["symbol"],
                        "ltp":             ltp,
                        "entry_price":     entry_price,
                        "shares_to_buy":   shares,
                        "investment":      round(actual_investment, 2),
                        "expected_profit": total_profit,
                        "profit_percent":  profit_pct,
                        "rsi":             rsi,
                        "smart_signal":    smart_signal,
                        "action":          action,
                        "stop_loss":       stop_loss,
                        "target1":         t1,
                        "target2":         t2,
                        "target3":         t3,
                        "exchange":        stock["exchange"],
                        "updated":         now.strftime("%H:%M:%S"),
                        "day_profit":      0.0,
                        "day_profit_pct":  0.0,
                        "first_entry":     entry_price,
                        "sessions_today":  0,
                    }

                    adv_score = calculate_advanced_score(stock_info, prices, candles, avg_volume)
                    stock_info['profit_score'] = adv_score
                    stock_info['buy_rating']   = get_buy_rating(adv_score)
                    stocks_data.append(stock_info)

            except Exception as e:
                if _is_rate_limit_error(e):
                    rate_hit_any = True
                    print(f"Rate limit exception on {stock['symbol']}: {e}")
                    # Back off before next stock
                    time.sleep(3)
                else:
                    print(f"Error fetching {stock['symbol']}: {e}")
                continue

        # ── If rate-limited mid-fetch and have old cache, serve stale ─────
        if not stocks_data and rate_hit_any and _cache["data"]:
            stale = dict(_cache["data"])
            stale["stale"]        = True
            stale["stale_reason"] = "Angel One rate limit — showing cached data (refreshes in 5 min)"
            stale["from_cache"]   = True
            _cache["stale"]       = True
            _cache["stale_reason"] = stale["stale_reason"]
            return stale

        # ── Pick freshest top 5 by score ──────────────────────────────────
        stocks_data.sort(key=lambda x: x['profit_score'], reverse=True)
        top5            = stocks_data[:5]
        current_symbols = [s['symbol'] for s in top5]

        # Mark NEW entries
        for s in top5:
            s['is_new'] = s['symbol'] not in _prev_top5
        _prev_top5 = current_symbols

        # Update day-wise profit
        top5, day_total_profit = update_day_profit(today_date, top5)

        total_investment      = sum(s.get('investment', 0) for s in top5)
        total_expected_profit = sum(s.get('expected_profit', 0) for s in top5)

        result = {
            "account":               client_id,
            "api_key":               api_key[:4] + "***",
            "timestamp":             now.strftime("%Y-%m-%d %H:%M:%S"),
            "stocks_count":          len(stocks_data),
            "stocks":                top5,
            "status":                "success",
            "note":                  "Top 5 freshly ranked by score on EVERY refresh",
            "total_investment":      total_investment,
            "total_expected_profit": total_expected_profit,
            "day_total_profit":      day_total_profit,
            "today":                 today_date,
            "refresh_interval":      _cache["ttl"],
            "from_cache":            False,
            "stale":                 False,
            "stale_reason":          "",
            "cache_age_secs":        0,
            "partial_rate_limit":    rate_hit_any,   # some stocks skipped
        }

        _cache["data"]         = result
        _cache["timestamp"]    = now
        _cache["stale"]        = False
        _cache["stale_reason"] = ""
        return result

    except Exception as e:
        err_str = str(e)
        if _is_rate_limit_error(err_str) and _cache["data"]:
            stale = dict(_cache["data"])
            stale["stale"]        = True
            stale["stale_reason"] = f"Rate limit: {err_str[:120]}"
            stale["from_cache"]   = True
            _cache["stale"]       = True
            _cache["stale_reason"] = stale["stale_reason"]
            return stale
        return {"error": err_str, "stocks": []}


# ─────────────────────────────────────────────────────────────────────────────
#  HTML GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def get_html(stock_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    has_api_key  = bool(os.environ.get("ANGEL_API_KEY"))
    has_client   = bool(os.environ.get("ANGEL_CLIENT_ID"))
    has_password = bool(os.environ.get("ANGEL_PASSWORD"))
    has_totp     = bool(os.environ.get("ANGEL_TOTP_SECRET"))
    all_configured = all([has_api_key, has_client, has_password, has_totp])

    refresh_secs = stock_data.get("refresh_interval", 300)

    # ── Stale cache notice ──
    is_stale      = stock_data.get("stale", False)
    from_cache    = stock_data.get("from_cache", False)
    cache_age     = stock_data.get("cache_age_secs", 0)
    stale_reason  = stock_data.get("stale_reason", "")
    partial_rl    = stock_data.get("partial_rate_limit", False)

    cache_notice = ""
    if is_stale and stale_reason:
        mins = cache_age // 60; secs = cache_age % 60
        age_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        cache_notice = f'''
        <div style="background:rgba(245,158,11,.15); border-left:4px solid #f59e0b;
                    padding:10px 16px; border-radius:8px; margin:10px 0;
                    color:#fbbf24; font-size:.88rem;">
            ⚠️ <b>Using cached data</b> (age: {age_str}) — {stale_reason}<br>
            <small style="color:#d97706;">Live data will resume once rate limit window clears (~1 min)</small>
        </div>'''
    elif from_cache and cache_age:
        mins = cache_age // 60; secs = cache_age % 60
        age_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        cache_notice = f'''
        <div style="background:rgba(6,182,212,.1); border-left:4px solid #06b6d4;
                    padding:8px 14px; border-radius:8px; margin:10px 0;
                    color:#67e8f9; font-size:.82rem;">
            📦 Serving cached data (age: {age_str}) — next API call in {max(0, refresh_secs - cache_age)}s
        </div>'''

    if partial_rl:
        cache_notice += '''
        <div style="background:rgba(239,68,68,.1); border-left:4px solid #ef4444;
                    padding:8px 14px; border-radius:8px; margin:8px 0;
                    color:#fca5a5; font-size:.82rem;">
            ⚡ Some stocks were skipped due to rate limits — showing available data only
        </div>'''

    # ── Build stock rows ──
    stock_rows   = ""
    mobile_cards = ""

    if stock_data.get("stocks"):
        for idx, stock in enumerate(stock_data["stocks"], 1):
            is_new       = stock.get("is_new", False)
            new_badge    = '<span class="new-badge">NEW</span>' if is_new else ''
            action_color = "#34d399" if "BUY" in stock['action'] else "#fbbf24" if "HOLD" in stock['action'] else "#f87171"
            rsi_color    = "#34d399" if 40 <= stock['rsi'] <= 70 else "#fbbf24" if stock['rsi'] > 70 else "#f87171"

            # Day profit colour
            day_p     = stock.get("day_profit", 0)
            day_p_pct = stock.get("day_profit_pct", 0)
            dp_color  = "#34d399" if day_p >= 0 else "#ef4444"
            dp_arrow  = "▲" if day_p >= 0 else "▼"

            # Desktop row
            stock_rows += f"""
            <tr class="{'new-row' if is_new else ''}">
                <td style="font-weight:700; color:#60a5fa; font-size:1.05em;">
                    {idx}. {stock['symbol']} {new_badge}
                </td>
                <td style="font-weight:600; color:#e5e7eb;">₹{stock['ltp']:.2f}</td>
                <td style="font-weight:600; color:#10b981;">₹{stock['entry_price']:.2f}</td>
                <td style="font-weight:700; color:#fbbf24;">{stock['shares_to_buy']}</td>
                <td style="color:#9ca3af;">₹{stock['investment']:.0f}</td>
                <td style="font-weight:700; color:#34d399;">₹{stock['expected_profit']:.2f}</td>
                <td style="font-weight:700; color:{dp_color};">
                    {dp_arrow} ₹{abs(day_p):.2f}<br>
                    <small style="font-size:0.7em;">({day_p_pct:+.2f}%)</small>
                </td>
                <td style="color:{rsi_color};">{stock['rsi']:.2f}</td>
                <td style="font-weight:700; color:#60a5fa;">{stock.get('profit_score', 0)}/100</td>
                <td style="color:{action_color}; font-weight:600;">{stock['action']}</td>
                <td style="color:#ef4444;">₹{stock['stop_loss']:.2f}</td>
                <td style="color:#34d399;">₹{stock['target1']:.2f}</td>
                <td style="color:#34d399;">₹{stock['target2']:.2f}</td>
                <td style="color:#34d399;">₹{stock['target3']:.2f}</td>
            </tr>
            """

            # Mobile card
            mobile_cards += f"""
            <div class="mobile-card {'new-card' if is_new else ''}">
                <div class="card-header">
                    <h3>{idx}. {stock['symbol']} {new_badge}</h3>
                    <span class="action-badge" style="background:{action_color};">{stock['action']}</span>
                </div>

                <!-- Day Profit Banner -->
                <div class="day-profit-banner" style="border-color:{dp_color}; background:{'rgba(52,211,153,0.08)' if day_p >= 0 else 'rgba(239,68,68,0.08)'};">
                    <label>📅 TODAY'S P&L</label>
                    <span style="color:{dp_color}; font-size:1.4rem; font-weight:800;">
                        {dp_arrow} ₹{abs(day_p):.2f}
                    </span>
                    <small style="color:{dp_color};">({day_p_pct:+.2f}%) since 1st entry ₹{stock.get('first_entry', stock['entry_price']):.2f}</small>
                </div>

                <div class="budget-box">
                    <div class="budget-item">
                        <label>📦 Qty</label>
                        <span class="qty">{stock['shares_to_buy']}</span>
                    </div>
                    <div class="budget-item">
                        <label>💵 Invest</label>
                        <span class="invest">₹{stock['investment']:.0f}</span>
                    </div>
                    <div class="budget-item highlight-profit">
                        <label>💰 Est. Profit</label>
                        <span class="profit">₹{stock['expected_profit']:.2f}</span>
                    </div>
                </div>

                <div class="price-row">
                    <div class="price-box">
                        <label>Current Price</label>
                        <span class="price">₹{stock['ltp']:.2f}</span>
                    </div>
                    <div class="price-box highlight">
                        <label>💰 Entry Price</label>
                        <span class="price">₹{stock['entry_price']:.2f}</span>
                    </div>
                </div>

                <div class="info-grid">
                    <div class="info-item">
                        <label>RSI</label>
                        <span style="color:{rsi_color}; font-weight:600;">{stock['rsi']:.2f}</span>
                    </div>
                    <div class="info-item">
                        <label>RVOL</label>
                        <span style="color:#fbbf24; font-weight:600;">{stock.get('rvol', 1.0):.2f}×</span>
                    </div>
                    <div class="info-item">
                        <label>ADX</label>
                        <span style="color:#60a5fa; font-weight:600;">{stock.get('adx', 25):.0f}</span>
                    </div>
                    <div class="info-item">
                        <label>🛑 Stop Loss</label>
                        <span style="color:#ef4444; font-weight:600;">₹{stock['stop_loss']:.2f}</span>
                    </div>
                </div>

                <div class="score-box">
                    <label>BUY SCORE</label>
                    <span class="buy-score">{stock.get('profit_score', 0)}/100</span>
                    <small>{stock.get('buy_rating', 'N/A')}</small>
                </div>

                <div class="targets-row">
                    <div class="target-box">
                        <label>🎯 T1 (2%)</label>
                        <span>₹{stock['target1']:.2f}</span>
                    </div>
                    <div class="target-box">
                        <label>🎯 T2 (3%)</label>
                        <span>₹{stock['target2']:.2f}</span>
                    </div>
                    <div class="target-box">
                        <label>🎯 T3 (5%)</label>
                        <span>₹{stock['target3']:.2f}</span>
                    </div>
                </div>

                <div class="signal-box">
                    <small>📊 {stock['smart_signal']} • 🕐 {stock['sessions_today']} refreshes today</small>
                </div>
            </div>
            """
    else:
        stock_rows   = '<tr><td colspan="14" style="text-align:center; color:#ef4444; padding:24px;">No picks available. Market may be closed or data loading...</td></tr>'
        mobile_cards = '<div class="mobile-card"><p style="text-align:center; color:#ef4444; padding:24px;">No picks available</p></div>'

    # ── Status message ──
    if stock_data.get("error"):
        err = stock_data.get("error", "Unknown error")
        if stock_data.get("import_errors"):
            err += "<br><small>" + "<br>".join(stock_data["import_errors"]) + "</small>"
        status_msg = f'<div class="error-box">❌ {err}</div>{cache_notice}'

    elif stock_data.get("stocks"):
        ti  = stock_data.get("total_investment", 0)
        tep = stock_data.get("total_expected_profit", 0)
        dtp = stock_data.get("day_total_profit", 0)
        dtp_color = "#34d399" if dtp >= 0 else "#ef4444"
        dtp_arrow = "▲" if dtp >= 0 else "▼"

        status_msg = f'''
        <div class="success-box">
            ✅ LIVE Fresh Top 5 Midcap Intraday — Angel One API • {stock_data.get("stocks_count", 0)} stocks scanned<br>
            Account: {stock_data.get("account", "N/A")} | API Key: {stock_data.get("api_key", "N/A")}<br>
            <small>📊 Multi-Indicator: RSI + EMA + VWAP + ADX + Volume + Momentum | Re-ranked every {refresh_secs}s</small>
        </div>
        {cache_notice}

        <!-- Day Summary Box -->
        <div class="day-summary-box">
            <div class="day-summary-title">📅 TODAY'S PERFORMANCE — {stock_data.get("today", "")}</div>
            <div class="day-summary-grid">
                <div class="ds-item">
                    <label>💵 Total Capital</label>
                    <span class="ds-value blue">₹{ti:.0f}</span>
                </div>
                <div class="ds-item">
                    <label>🎯 Est. Day Profit</label>
                    <span class="ds-value green">₹{tep:.2f}</span>
                </div>
                <div class="ds-item highlight-day">
                    <label>📈 Live Day P&L</label>
                    <span class="ds-value" style="color:{dtp_color};">{dtp_arrow} ₹{abs(dtp):.2f}</span>
                    <small style="color:{dtp_color};">{((dtp / ti) * 100) if ti > 0 else 0:+.2f}% on capital</small>
                </div>
            </div>
        </div>

        <!-- Big Profit Highlight -->
        <div class="profit-highlight">
            <div class="profit-main">
                <label>💰 TOTAL EXPECTED PROFIT TODAY (at T2)</label>
                <span class="profit-amount">₹{tep:.2f}</span>
                <small>Live P&L so far: <b style="color:{dtp_color};">{dtp_arrow} ₹{abs(dtp):.2f}</b></small>
            </div>
        </div>'''
    else:
        status_msg = '<div class="info-box">⏳ Loading fresh picks...</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Top 5 Midcap Intraday Picks — Live</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0f1e 0%, #1a1f2e 100%);
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            padding: 12px;
        }}
        .container {{ max-width:1400px; margin:0 auto; }}

        h1 {{
            font-size:1.8rem;
            background: linear-gradient(135deg, #3b82f6, #10b981);
            -webkit-background-clip:text; -webkit-text-fill-color:transparent;
            margin-bottom:6px; font-weight:700;
        }}
        .subtitle {{ color:#9ca3af; font-size:0.9rem; margin-bottom:12px; }}

        .live-bar {{
            display:flex; align-items:center; gap:16px; flex-wrap:wrap;
            margin-bottom:16px;
        }}
        .live-dot {{
            background:#059669; color:white; padding:6px 16px; border-radius:20px;
            font-weight:700; font-size:0.85rem; animation:pulse 2s infinite;
        }}
        @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.6}} }}

        /* ── Countdown Timer ── */
        .countdown-bar {{
            background:#1e293b; border:1px solid #334155; border-radius:10px;
            padding:8px 18px; display:flex; align-items:center; gap:10px;
            font-size:0.9rem; color:#94a3b8; flex:1; min-width:200px;
        }}
        .countdown-bar span#timer {{
            color:#fbbf24; font-weight:800; font-size:1.1rem; font-variant-numeric:tabular-nums;
        }}
        .progress-wrap {{
            flex:1; height:6px; background:#334155; border-radius:3px; overflow:hidden;
        }}
        .progress-bar {{
            height:100%; background:linear-gradient(90deg,#3b82f6,#10b981);
            border-radius:3px; transition:width 1s linear;
        }}

        /* ── NEW badge ── */
        .new-badge {{
            background:linear-gradient(135deg,#f59e0b,#ef4444);
            color:white; font-size:0.6rem; font-weight:800;
            padding:2px 6px; border-radius:4px; margin-left:6px;
            vertical-align:middle; letter-spacing:.05em;
            animation:flash 1s ease-in-out 3;
        }}
        @keyframes flash {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
        .new-row {{ background:rgba(245,158,11,0.06) !important; }}
        .new-card {{ border:2px solid #f59e0b !important; }}

        /* ── Status boxes ── */
        .success-box {{
            background:rgba(5,150,105,.2); border-left:4px solid #059669;
            padding:14px; border-radius:8px; margin:12px 0; color:#34d399; font-size:.9rem;
        }}
        .error-box {{
            background:rgba(239,68,68,.2); border-left:4px solid #ef4444;
            padding:14px; border-radius:8px; margin:12px 0; color:#f87171;
        }}
        .info-box {{
            background:rgba(59,130,246,.2); border-left:4px solid #3b82f6;
            padding:14px; border-radius:8px; margin:12px 0; color:#60a5fa;
        }}

        /* ── Day Summary Box ── */
        .day-summary-box {{
            background:rgba(17,24,39,.95); border:2px solid #1e40af;
            border-radius:14px; padding:18px; margin:16px 0;
        }}
        .day-summary-title {{
            color:#93c5fd; font-weight:700; font-size:.95rem;
            margin-bottom:14px; letter-spacing:.04em;
        }}
        .day-summary-grid {{
            display:grid; grid-template-columns:repeat(3,1fr); gap:14px;
        }}
        .ds-item {{
            text-align:center; background:#0f172a; border-radius:10px; padding:12px;
        }}
        .ds-item.highlight-day {{
            background:rgba(16,185,129,.1); border:1px solid #10b981;
        }}
        .ds-item label {{
            display:block; color:#9ca3af; font-size:.75rem; margin-bottom:6px;
        }}
        .ds-item small {{ display:block; margin-top:4px; font-size:.75rem; }}
        .ds-value {{ display:block; font-size:1.6rem; font-weight:800; }}
        .ds-value.blue  {{ color:#60a5fa; }}
        .ds-value.green {{ color:#34d399; }}
        @media(max-width:600px) {{
            .day-summary-grid {{ grid-template-columns:1fr; }}
        }}

        /* ── Big Profit Highlight ── */
        .profit-highlight {{
            background:linear-gradient(135deg,#065f46,#047857);
            border:3px solid #10b981; border-radius:16px; padding:22px;
            margin:16px 0; text-align:center;
            box-shadow:0 8px 40px rgba(16,185,129,.35);
            animation:glow 2.5s ease-in-out infinite;
        }}
        @keyframes glow {{
            0%,100%{{box-shadow:0 8px 40px rgba(16,185,129,.3)}}
            50%{{box-shadow:0 8px 60px rgba(16,185,129,.6)}}
        }}
        .profit-main label {{
            display:block; color:#d1fae5; font-size:1rem; font-weight:600;
            margin-bottom:10px; text-transform:uppercase; letter-spacing:.05em;
        }}
        .profit-amount {{
            display:block; color:#fff; font-size:3.2rem; font-weight:900;
            text-shadow:0 4px 12px rgba(0,0,0,.3); margin:10px 0;
        }}
        .profit-main small {{ display:block; color:#a7f3d0; font-size:.9rem; margin-top:6px; }}

        /* ── Day Profit Banner (per stock mobile) ── */
        .day-profit-banner {{
            border:2px solid; border-radius:10px; padding:10px 14px;
            margin-bottom:12px; text-align:center;
        }}
        .day-profit-banner label {{
            display:block; font-size:.7rem; color:#9ca3af; margin-bottom:4px;
            text-transform:uppercase; letter-spacing:.05em;
        }}
        .day-profit-banner small {{ display:block; font-size:.72rem; margin-top:4px; }}

        /* ── Table ── */
        table {{
            width:100%; background:rgba(17,24,39,.95); border-radius:12px;
            overflow:hidden; margin:14px 0; border-collapse:collapse;
            box-shadow:0 10px 40px rgba(0,0,0,.5);
        }}
        thead {{ background:linear-gradient(135deg,#1e293b,#334155); }}
        th,td {{
            padding:10px 8px; text-align:center;
            border-bottom:1px solid rgba(71,85,105,.3); font-size:.75rem;
        }}
        th {{ color:#60a5fa; font-weight:700; text-transform:uppercase; font-size:.65rem; letter-spacing:.03em; }}
        tr:hover {{ background:rgba(59,130,246,.08); }}

        /* ── Mobile Cards ── */
        .mobile-cards {{ display:none; }}
        .mobile-card {{
            background:rgba(17,24,39,.95); border-radius:16px;
            padding:16px; margin-bottom:16px;
            box-shadow:0 4px 20px rgba(0,0,0,.3);
            border:1px solid rgba(59,130,246,.2);
        }}
        .card-header {{
            display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;
        }}
        .card-header h3 {{ color:#60a5fa; font-size:1.4rem; font-weight:700; margin:0; }}
        .action-badge {{
            padding:5px 11px; border-radius:20px; font-size:.75rem; font-weight:600; color:white;
        }}
        .price-row {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }}
        .price-box {{
            background:#1e293b; padding:10px; border-radius:10px; text-align:center;
        }}
        .price-box.highlight {{ background:linear-gradient(135deg,#065f46,#064e3b); border:2px solid #10b981; }}
        .price-box label {{ display:block; color:#9ca3af; font-size:.72rem; margin-bottom:4px; }}
        .price-box .price {{ display:block; color:#e5e7eb; font-size:1.2rem; font-weight:700; }}
        .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }}
        .info-item {{
            background:#1e293b; padding:9px; border-radius:8px; text-align:center;
        }}
        .info-item label {{ display:block; color:#9ca3af; font-size:.7rem; margin-bottom:3px; }}
        .targets-row {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:10px; }}
        .target-box {{
            background:rgba(16,185,129,.1); border:1px solid #10b981;
            padding:7px; border-radius:8px; text-align:center;
        }}
        .target-box label {{ display:block; color:#10b981; font-size:.62rem; margin-bottom:2px; }}
        .target-box span {{ display:block; color:#34d399; font-size:.88rem; font-weight:600; }}
        .signal-box {{ background:#1e293b; padding:7px; border-radius:8px; text-align:center; }}
        .signal-box small {{ color:#9ca3af; font-size:.7rem; }}
        .score-box {{
            background:linear-gradient(135deg,#1e3a8a,#1e40af); border:2px solid #3b82f6;
            padding:11px; border-radius:12px; text-align:center; margin:10px 0;
        }}
        .score-box label {{ display:block; color:#93c5fd; font-size:.7rem; margin-bottom:3px; }}
        .buy-score {{ display:block; color:#fff; font-size:1.7rem; font-weight:900; margin:3px 0; }}
        .score-box small {{ display:block; color:#fbbf24; font-size:.75rem; font-weight:600; }}
        .budget-box {{
            display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:10px;
            background:#0f172a; padding:10px; border-radius:12px; border:2px solid #1e40af;
        }}
        .budget-item {{ text-align:center; }}
        .budget-item label {{ display:block; color:#9ca3af; font-size:.65rem; margin-bottom:3px; }}
        .budget-item .qty {{ display:block; color:#fbbf24; font-size:1rem; font-weight:700; }}
        .budget-item .invest {{ display:block; color:#60a5fa; font-size:1rem; font-weight:700; }}
        .budget-item .profit {{ display:block; color:#34d399; font-size:1.05rem; font-weight:700; }}
        .budget-item.highlight-profit {{ background:rgba(16,185,129,.1); border-radius:8px; padding:4px; }}

        /* ── Responsive ── */
        @media(max-width:768px) {{
            .desktop-table {{ display:none; }}
            .mobile-cards  {{ display:block; }}
            h1 {{ font-size:1.4rem; }}
            .profit-amount {{ font-size:2.4rem; }}
        }}
        @media(max-width:480px) {{
            h1 {{ font-size:1.2rem; }}
            .card-header h3 {{ font-size:1.2rem; }}
        }}
        .timestamp {{
            color:#64748b; font-size:.85rem; margin-top:20px; text-align:center;
        }}
        .legend {{
            display:flex; justify-content:center; gap:20px; flex-wrap:wrap; margin:12px 0;
        }}
        .legend-item {{ display:flex; align-items:center; gap:6px; font-size:.82rem; color:#94a3b8; }}
        .legend-color {{ width:10px; height:10px; border-radius:2px; }}
    </style>
</head>
<body>
<div class="container">

    <h1>📊 Top 5 Midcap Intraday Picks — Live</h1>
    <p class="subtitle">High-Volume Midcap F&O • 20 Stocks Scanned • Best Buy System: RSI + EMA + VWAP + ADX + Volume + Momentum</p>

    <!-- Live Bar + Countdown -->
    <div class="live-bar">
        <div class="live-dot">🔴 LIVE</div>
        <div class="countdown-bar">
            🔄 Next refresh in <span id="timer">{refresh_secs}s</span>
            <div class="progress-wrap">
                <div class="progress-bar" id="prog" style="width:100%;"></div>
            </div>
        </div>
    </div>

    {status_msg}

    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background:#34d399;"></div><span>BUY Signal</span></div>
        <div class="legend-item"><div class="legend-color" style="background:#fbbf24;"></div><span>HOLD</span></div>
        <div class="legend-item"><div class="legend-color" style="background:#f87171;"></div><span>SELL Signal</span></div>
        <div class="legend-item"><div class="legend-color" style="background:linear-gradient(135deg,#f59e0b,#ef4444);"></div><span>NEW Entry</span></div>
    </div>

    <!-- Desktop Table -->
    <div style="overflow-x:auto;">
    <table class="desktop-table">
        <thead>
            <tr>
                <th>#  Symbol</th>
                <th>Price ₹</th>
                <th>Entry ₹</th>
                <th>📦 Qty</th>
                <th>💵 Invest</th>
                <th>💰 Est. Profit</th>
                <th>📅 Day P&L</th>
                <th>RSI</th>
                <th>Score</th>
                <th>Action</th>
                <th>Stop Loss</th>
                <th>T1 (2%)</th>
                <th>T2 (3%)</th>
                <th>T3 (5%)</th>
            </tr>
        </thead>
        <tbody>
            {stock_rows}
        </tbody>
    </table>
    </div>

    <!-- Mobile Cards -->
    <div class="mobile-cards">
        {mobile_cards}
    </div>

    <p class="timestamp">
        Last updated: {now}<br>
        <small>Data from Angel One SmartAPI • Account: {stock_data.get("account", "N/A")} • Top 5 freshly ranked every {refresh_secs}s</small>
    </p>

</div>

<!-- ── Countdown + Auto-reload JS ── -->
<script>
(function() {{
    var total = {refresh_secs};
    var left  = total;
    var timer = document.getElementById('timer');
    var prog  = document.getElementById('prog');

    function tick() {{
        if (!timer) return;
        left--;
        if (left <= 0) {{
            window.location.reload();
            return;
        }}
        timer.textContent = left + 's';
        var pct = (left / total) * 100;
        if (prog) prog.style.width = pct + '%';
        // Turn red in last 5 seconds
        if (left <= 5) {{
            if (timer) timer.style.color = '#ef4444';
            if (prog)  prog.style.background = '#ef4444';
        }}
    }}

    setInterval(tick, 1000);
}})();
</script>

</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
#  VERCEL HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            stock_data = get_live_stock_data()

            if "/api" in self.path or "/json" in self.path:
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(json.dumps(stock_data, indent=2).encode("utf-8"))
            else:
                html = get_html(stock_data)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress logs
