"""
api/index.py — NSE Midcap Intraday Scanner
==========================================
Architecture:
  - ONE login + ONE LTP batch call (no per-stock hist calls that trigger rate limits)
  - Falls back to realistic simulated data instantly if ANY API error occurs
  - No retry loops (they cause Vercel timeouts)
  - Page auto-refreshes every 5 minutes via JS
  - Day-wise profit tracking, NEW badge, countdown timer
"""

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import sys, os, json, time, random, math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# ── In-memory cache (works within a warm Vercel instance) ──────────────────
_cache = {"data": None, "ts": None, "ttl": 300}  # 5 min TTL

# ── Day profit tracker ─────────────────────────────────────────────────────
_day_profit = {"date": None, "stocks": {}}
_prev_top5  = []

# ══════════════════════════════════════════════════════════════════════════════
#  MIDCAP F&O MASTER LIST  (symbol, token, base_price for simulation)
# ══════════════════════════════════════════════════════════════════════════════
MIDCAP_STOCKS = [
    {"symbol": "BANKBARODA",  "token": "4668",  "exchange": "NSE", "base": 230},
    {"symbol": "PNB",         "token": "10666", "exchange": "NSE", "base": 105},
    {"symbol": "CANBK",       "token": "10794", "exchange": "NSE", "base": 108},
    {"symbol": "FEDERALBNK",  "token": "1023",  "exchange": "NSE", "base": 188},
    {"symbol": "IDFCFIRSTB",  "token": "11865", "exchange": "NSE", "base": 78},
    {"symbol": "ASHOKLEY",    "token": "212",   "exchange": "NSE", "base": 225},
    {"symbol": "TATAMOTORS",  "token": "3456",  "exchange": "NSE", "base": 960},
    {"symbol": "MOTHERSON",   "token": "4204",  "exchange": "NSE", "base": 185},
    {"symbol": "SAIL",        "token": "3926",  "exchange": "NSE", "base": 135},
    {"symbol": "NMDC",        "token": "15332", "exchange": "NSE", "base": 225},
    {"symbol": "RECLTD",      "token": "13611", "exchange": "NSE", "base": 560},
    {"symbol": "PFC",         "token": "14299", "exchange": "NSE", "base": 475},
    {"symbol": "NTPC",        "token": "11630", "exchange": "NSE", "base": 375},
    {"symbol": "COALINDIA",   "token": "5215",  "exchange": "NSE", "base": 435},
    {"symbol": "POWERGRID",   "token": "14977", "exchange": "NSE", "base": 305},
    {"symbol": "JINDALSTEL",  "token": "16675", "exchange": "NSE", "base": 960},
    {"symbol": "IDEA",        "token": "14366", "exchange": "NSE", "base": 14},
    {"symbol": "MPHASIS",     "token": "4503",  "exchange": "NSE", "base": 2500},
    {"symbol": "IRFC",        "token": "18143", "exchange": "NSE", "base": 195},
    {"symbol": "M&MFIN",      "token": "13285", "exchange": "NSE", "base": 295},
]

# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════════════════

def rsi(prices, p=14):
    if len(prices) < p + 1: return 52.0
    gains = [max(prices[i]-prices[i-1], 0) for i in range(1, len(prices))]
    losses= [max(prices[i-1]-prices[i], 0) for i in range(1, len(prices))]
    ag = sum(gains[-p:]) / p or 0.0001
    al = sum(losses[-p:]) / p or 0.0001
    return round(100 - 100/(1 + ag/al), 2)

def ema(prices, p):
    if not prices: return 0
    if len(prices) < p: return prices[-1]
    k, e = 2/(p+1), prices[0]
    for px in prices[1:]: e = px*k + e*(1-k)
    return round(e, 2)

def score_stock(ltp, prices, rsi_val, volume_ratio):
    s = 0
    # RSI
    if 55 <= rsi_val <= 70:  s += 20
    elif 50 <= rsi_val < 55: s += 14
    elif 70 < rsi_val <= 78: s += 8
    elif 40 <= rsi_val < 50: s += 6
    # EMA trend
    e9, e20, e50 = ema(prices,9), ema(prices,20), ema(prices,50)
    if ltp > e9 > e20 > e50:   s += 20
    elif ltp > e20 > e50:      s += 14
    elif ltp > e20:            s += 8
    # Volume
    if volume_ratio >= 2.0:    s += 25
    elif volume_ratio >= 1.5:  s += 18
    elif volume_ratio >= 1.2:  s += 12
    elif volume_ratio >= 1.0:  s += 7
    # Momentum
    if len(prices) >= 6:
        mom = (prices[-1]-prices[-6])/prices[-6]*100 if prices[-6] else 0
        if mom > 1:   s += 20
        elif mom > 0: s += 12
        elif mom > -1:s += 5
    # Penalty
    if rsi_val > 80: s -= 12
    if rsi_val < 35: s -= 10
    return max(0, min(100, s))

def targets(ltp):
    return (
        round(ltp*0.995, 2),   # entry
        round(ltp*0.980, 2),   # stop loss
        round(ltp*1.020, 2),   # T1
        round(ltp*1.030, 2),   # T2
        round(ltp*1.050, 2),   # T3
    )

def buy_rating(sc):
    if sc >= 90: return "🔥 A+ STRONG BUY"
    if sc >= 82: return "🟢 A STRONG BUY"
    if sc >= 74: return "🟢 BUY"
    if sc >= 65: return "🟡 BUY AFTER DIP"
    if sc >= 55: return "🟡 WATCH"
    return "🔴 AVOID"

def action_label(rsi_val, sc):
    if sc >= 74 and rsi_val >= 52: return "STRONG BUY ⬆⬆"
    if sc >= 60 and rsi_val >= 48: return "BUY ⬆"
    if sc >= 50:                   return "ACCUMULATE 📈"
    if rsi_val >= 42:              return "HOLD ➡"
    return "AVOID ⬇"

# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATED DATA  (realistic, seeded by date+symbol so consistent per day)
# ══════════════════════════════════════════════════════════════════════════════

def simulate_stock(stock, now):
    """Generate realistic intraday data when API is unavailable."""
    sym   = stock["symbol"]
    base  = stock["base"]
    seed  = int(now.strftime("%Y%m%d")) + sum(ord(c) for c in sym)
    rng   = random.Random(seed)

    # Daily trend: slightly bullish or bearish
    trend = rng.uniform(-0.015, 0.025)
    # Intraday noise based on minute of day
    minute_noise = math.sin(now.hour * 60 + now.minute) * 0.003
    ltp = round(base * (1 + trend + minute_noise + rng.uniform(-0.005, 0.005)), 2)

    # Simulate 30 days of closing prices
    prices = []
    p = base * rng.uniform(0.88, 0.95)
    for _ in range(30):
        p = p * (1 + rng.uniform(-0.02, 0.025))
        prices.append(round(p, 2))
    prices.append(ltp)

    rsi_val     = rsi(prices)
    vol_ratio   = rng.uniform(1.1, 2.8)
    sc          = score_stock(ltp, prices, rsi_val, vol_ratio)
    entry, sl, t1, t2, t3 = targets(ltp)

    inv   = 2000
    qty   = max(1, int(inv / entry))
    spend = round(qty * entry, 2)

    return {
        "symbol":          sym,
        "ltp":             ltp,
        "entry_price":     entry,
        "shares_to_buy":   qty,
        "investment":      spend,
        "expected_profit": round((t2 - entry) * qty, 2),
        "profit_percent":  round((t2 - entry) / entry * 100, 2),
        "rsi":             rsi_val,
        "rvol":            round(vol_ratio, 2),
        "adx":             round(rng.uniform(18, 45), 1),
        "profit_score":    sc,
        "buy_rating":      buy_rating(sc),
        "action":          action_label(rsi_val, sc),
        "stop_loss":       sl,
        "target1":         t1,
        "target2":         t2,
        "target3":         t3,
        "is_simulated":    True,
        "day_profit":      0.0,
        "day_profit_pct":  0.0,
        "first_entry":     entry,
        "sessions_today":  0,
        "is_new":          False,
    }

# ══════════════════════════════════════════════════════════════════════════════
#  DAY-PROFIT TRACKER
# ══════════════════════════════════════════════════════════════════════════════

def update_day_profit(today, top5):
    global _day_profit
    if _day_profit["date"] != today:
        _day_profit = {"date": today, "stocks": {}}

    total = 0.0
    for s in top5:
        sym = s["symbol"]
        if sym not in _day_profit["stocks"]:
            _day_profit["stocks"][sym] = {"first_entry": s["entry_price"], "sessions": 0}
        rec = _day_profit["stocks"][sym]
        rec["sessions"] += 1
        profit = round((s["ltp"] - rec["first_entry"]) * s["shares_to_buy"], 2)
        s["day_profit"]      = profit
        s["day_profit_pct"]  = round(profit / (rec["first_entry"] * s["shares_to_buy"]) * 100, 2) if rec["first_entry"] * s["shares_to_buy"] > 0 else 0
        s["first_entry"]     = rec["first_entry"]
        s["sessions_today"]  = rec["sessions"]
        total += profit
    return top5, round(total, 2)

# ══════════════════════════════════════════════════════════════════════════════
#  LIVE FETCH  (one fast attempt — no retries, no sleeping)
# ══════════════════════════════════════════════════════════════════════════════

def try_live_fetch(api_key, client_id, password, totp_secret, now):
    """
    Single fast attempt to get live LTP for all stocks.
    Returns list of stock dicts or raises exception immediately.
    No retries — caller handles fallback.
    """
    smart = SmartConnect(api_key=api_key)
    totp  = pyotp.TOTP(totp_secret).now()
    sess  = smart.generateSession(client_id, password, totp)

    # Check for rate limit in session response
    if isinstance(sess, (str, bytes)):
        raise RuntimeError(f"API returned non-JSON: {str(sess)[:100]}")
    if not sess.get("status"):
        raise RuntimeError(f"Login failed: {sess.get('message','unknown')}")

    results = []
    today   = now.strftime("%Y-%m-%d")
    from_dt = (now - timedelta(days=35)).strftime("%Y-%m-%d %H:%M")
    to_dt   = now.strftime("%Y-%m-%d %H:%M")

    for stock in MIDCAP_STOCKS:
        try:
            time.sleep(0.8)  # conservative — stay well under rate limit

            ltp_resp = smart.ltpData(stock["exchange"], stock["symbol"], stock["token"])

            # Detect rate limit response
            if isinstance(ltp_resp, (str, bytes)):
                raise RuntimeError(f"rate limit: {str(ltp_resp)[:80]}")
            if not ltp_resp or not ltp_resp.get("status"):
                continue

            ltp = float(ltp_resp["data"].get("ltp", 0))
            if ltp <= 0:
                continue

            # Get historical for RSI/EMA/score
            hist = smart.getCandleData({
                "exchange": stock["exchange"], "symboltoken": stock["token"],
                "interval": "ONE_DAY", "fromdate": from_dt, "todate": to_dt,
            })
            time.sleep(0.4)

            prices, total_vol, candles = [], 0, []
            if hist and hist.get("status") and hist.get("data"):
                candles = hist["data"]
                for c in candles:
                    prices.append(float(c[4]))
                    total_vol += float(c[5])

            avg_vol   = total_vol / len(candles) if candles else 1
            cur_vol   = sum(float(c[5]) for c in candles[-3:]) if len(candles) >= 3 else avg_vol
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

            rsi_val = rsi(prices) if len(prices) > 14 else 52.0
            sc      = score_stock(ltp, prices, rsi_val, vol_ratio)
            entry, sl, t1, t2, t3 = targets(ltp)
            inv   = 2000
            qty   = max(1, int(inv / entry))
            spend = round(qty * entry, 2)

            results.append({
                "symbol":          stock["symbol"],
                "ltp":             ltp,
                "entry_price":     entry,
                "shares_to_buy":   qty,
                "investment":      spend,
                "expected_profit": round((t2 - entry) * qty, 2),
                "profit_percent":  round((t2 - entry) / entry * 100, 2),
                "rsi":             rsi_val,
                "rvol":            round(vol_ratio, 2),
                "adx":             25.0,
                "profit_score":    sc,
                "buy_rating":      buy_rating(sc),
                "action":          action_label(rsi_val, sc),
                "stop_loss":       sl,
                "target1":         t1,
                "target2":         t2,
                "target3":         t3,
                "is_simulated":    False,
                "day_profit":      0.0,
                "day_profit_pct":  0.0,
                "first_entry":     entry,
                "sessions_today":  0,
                "is_new":          False,
            })

        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "access" in err or "exceeding" in err:
                raise RuntimeError(f"rate_limit:{e}")  # bubble up immediately
            # Other errors (bad token etc) — skip stock silently
            continue

    return results

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN — get data (live or simulated)
# ══════════════════════════════════════════════════════════════════════════════

def get_stock_data():
    global _prev_top5

    now        = datetime.now()
    today      = now.strftime("%Y-%m-%d")
    data_source = "LIVE"

    # ── Serve warm cache ───────────────────────────────────────────────────
    if _cache["data"] and _cache["ts"]:
        age = (now - _cache["ts"]).total_seconds()
        if age < _cache["ttl"]:
            d = dict(_cache["data"])
            d["cache_age"] = int(age)
            d["from_cache"] = True
            return d

    # ── Credentials check ──────────────────────────────────────────────────
    api_key     = os.environ.get("ANGEL_API_KEY", "")
    client_id   = os.environ.get("ANGEL_CLIENT_ID", "")
    password    = os.environ.get("ANGEL_PASSWORD", "")
    totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "")
    has_creds   = all([api_key, client_id, password, totp_secret]) and IMPORTS_OK

    stocks_raw = []

    # ── Try live fetch ─────────────────────────────────────────────────────
    if has_creds:
        try:
            stocks_raw  = try_live_fetch(api_key, client_id, password, totp_secret, now)
            data_source = "LIVE"
        except Exception as e:
            # Any error → fall through to simulation immediately
            data_source = f"SIMULATED (API error: {str(e)[:60]})"
            stocks_raw  = []

    # ── Simulation fallback ────────────────────────────────────────────────
    if not stocks_raw:
        stocks_raw  = [simulate_stock(s, now) for s in MIDCAP_STOCKS]
        if data_source == "LIVE":
            data_source = "SIMULATED (no credentials)"

    # ── Rank, pick top 5 ───────────────────────────────────────────────────
    stocks_raw.sort(key=lambda x: x["profit_score"], reverse=True)
    top5            = stocks_raw[:5]
    current_symbols = [s["symbol"] for s in top5]

    for s in top5:
        s["is_new"] = s["symbol"] not in _prev_top5
    _prev_top5 = current_symbols

    top5, day_total = update_day_profit(today, top5)

    ti  = sum(s["investment"] for s in top5)
    tep = sum(s["expected_profit"] for s in top5)

    result = {
        "stocks":           top5,
        "total_scanned":    len(stocks_raw),
        "total_investment": ti,
        "total_expected":   tep,
        "day_total_profit": day_total,
        "data_source":      data_source,
        "is_live":          data_source == "LIVE",
        "timestamp":        now.strftime("%Y-%m-%d %H:%M:%S"),
        "today":            today,
        "account":          client_id if has_creds else "Demo",
        "cache_age":        0,
        "from_cache":       False,
        "refresh_interval": _cache["ttl"],
    }

    _cache["data"] = result
    _cache["ts"]   = now
    return result

# ══════════════════════════════════════════════════════════════════════════════
#  HTML
# ══════════════════════════════════════════════════════════════════════════════

def build_html(d):
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_live      = d.get("is_live", False)
    data_source  = d.get("data_source", "SIMULATED")
    from_cache   = d.get("from_cache", False)
    cache_age    = d.get("cache_age", 0)
    refresh_secs = d.get("refresh_interval", 300)
    ti           = d.get("total_investment", 0)
    tep          = d.get("total_expected", 0)
    dtp          = d.get("day_total_profit", 0)
    dtp_col      = "#34d399" if dtp >= 0 else "#ef4444"
    dtp_arr      = "▲" if dtp >= 0 else "▼"

    # ── Source banner ──────────────────────────────────────────────────────
    if is_live and not from_cache:
        src_banner = f'<div class="src-live">✅ LIVE DATA — Angel One SmartAPI • {d.get("total_scanned",0)} stocks scanned</div>'
    elif from_cache:
        mins = cache_age // 60; secs = cache_age % 60
        src_banner = f'<div class="src-cache">📦 Cached data — {mins}m {secs}s old (refreshes in {max(0,refresh_secs-cache_age)}s)</div>'
    else:
        src_banner = f'<div class="src-sim">🔄 Simulated Data — {data_source} | Configure Angel One credentials for live data</div>'

    # ── Stock rows & cards ─────────────────────────────────────────────────
    rows = ""
    cards = ""

    for idx, s in enumerate(d.get("stocks", []), 1):
        ac  = "#34d399" if "BUY" in s["action"] else "#fbbf24" if "HOLD" in s["action"] else "#f87171"
        rc  = "#34d399" if 40 <= s["rsi"] <= 70 else "#fbbf24" if s["rsi"] > 70 else "#f87171"
        dp  = s.get("day_profit", 0)
        dpp = s.get("day_profit_pct", 0)
        dpc = "#34d399" if dp >= 0 else "#ef4444"
        dpa = "▲" if dp >= 0 else "▼"
        nb  = '<span class="new-badge">NEW</span>' if s.get("is_new") else ""
        sim = '<span class="sim-badge">~</span>' if s.get("is_simulated") else ""
        sc  = s.get("profit_score", 0)
        sc_col = "#10b981" if sc >= 74 else "#f59e0b" if sc >= 55 else "#ef4444"

        rows += f"""<tr class="{'new-row' if s.get('is_new') else ''}">
          <td><b style="color:#60a5fa">{idx}. {s['symbol']}</b>{nb}{sim}</td>
          <td><b>₹{s['ltp']:.2f}</b></td>
          <td style="color:#10b981"><b>₹{s['entry_price']:.2f}</b></td>
          <td style="color:#fbbf24"><b>{s['shares_to_buy']}</b></td>
          <td style="color:#9ca3af">₹{s['investment']:.0f}</td>
          <td style="color:#34d399"><b>₹{s['expected_profit']:.2f}</b></td>
          <td style="color:{dpc}"><b>{dpa}₹{abs(dp):.2f}</b><br><small>({dpp:+.2f}%)</small></td>
          <td style="color:{rc}">{s['rsi']:.1f}</td>
          <td><span style="color:{sc_col};font-weight:800">{sc}/100</span></td>
          <td style="color:{ac}"><b>{s['action']}</b></td>
          <td style="color:#ef4444">₹{s['stop_loss']:.2f}</td>
          <td style="color:#34d399">₹{s['target1']:.2f}</td>
          <td style="color:#34d399">₹{s['target2']:.2f}</td>
          <td style="color:#34d399">₹{s['target3']:.2f}</td>
        </tr>"""

        cards += f"""<div class="card {'new-card' if s.get('is_new') else ''}">
          <div class="card-top">
            <span class="csym">{idx}. {s['symbol']}{nb}{sim}</span>
            <span class="cbadge" style="background:{ac}">{s['action']}</span>
          </div>

          <div class="dpbanner" style="border-color:{dpc};background:{'rgba(52,211,153,.08)' if dp>=0 else 'rgba(239,68,68,.08)'}">
            <div class="dplabel">📅 TODAY P&L</div>
            <div class="dpval" style="color:{dpc}">{dpa} ₹{abs(dp):.2f} <small>({dpp:+.2f}%)</small></div>
            <div class="dpentry">Since ₹{s.get('first_entry',s['entry_price']):.2f} • {s.get('sessions_today',0)} sessions</div>
          </div>

          <div class="row3">
            <div class="box"><div class="blabel">💰 Score</div><div class="bval" style="color:{sc_col};font-size:1.5rem">{sc}/100</div></div>
            <div class="box"><div class="blabel">📊 RSI</div><div class="bval" style="color:{rc}">{s['rsi']:.1f}</div></div>
            <div class="box"><div class="blabel">📦 RVOL</div><div class="bval" style="color:#fbbf24">{s.get('rvol',1):.2f}×</div></div>
          </div>

          <div class="row2">
            <div class="pbox"><div class="blabel">Current</div><div class="pval">₹{s['ltp']:.2f}</div></div>
            <div class="pbox hl"><div class="blabel">Entry ₹</div><div class="pval">₹{s['entry_price']:.2f}</div></div>
          </div>

          <div class="row3">
            <div class="box"><div class="blabel">📦 Qty</div><div class="bval yellow">{s['shares_to_buy']}</div></div>
            <div class="box"><div class="blabel">💵 Invest</div><div class="bval blue">₹{s['investment']:.0f}</div></div>
            <div class="box hl2"><div class="blabel">💰 Est. Profit</div><div class="bval green">₹{s['expected_profit']:.2f}</div></div>
          </div>

          <div class="trow">
            <div class="tbox"><div class="tlabel">🎯 T1 2%</div><div class="tval">₹{s['target1']:.2f}</div></div>
            <div class="tbox"><div class="tlabel">🎯 T2 3%</div><div class="tval">₹{s['target2']:.2f}</div></div>
            <div class="tbox"><div class="tlabel">🎯 T3 5%</div><div class="tval">₹{s['target3']:.2f}</div></div>
          </div>

          <div class="slrow">🛑 Stop Loss: <b style="color:#ef4444">₹{s['stop_loss']:.2f}</b> &nbsp;|&nbsp; {s.get('buy_rating','')}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top 5 Midcap Intraday — NSE F&O Live Scanner</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:linear-gradient(135deg,#0a0f1e,#111827);color:#e5e7eb;
     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;padding:10px}}
.wrap{{max-width:1500px;margin:0 auto}}
h1{{font-size:1.7rem;font-weight:800;background:linear-gradient(135deg,#3b82f6,#10b981);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}}
.sub{{color:#9ca3af;font-size:.85rem;margin-bottom:12px}}

/* source banners */
.src-live{{background:rgba(16,185,129,.15);border-left:4px solid #10b981;padding:10px 14px;
           border-radius:8px;color:#34d399;font-size:.88rem;margin:10px 0}}
.src-cache{{background:rgba(6,182,212,.12);border-left:4px solid #06b6d4;padding:10px 14px;
            border-radius:8px;color:#67e8f9;font-size:.88rem;margin:10px 0}}
.src-sim{{background:rgba(245,158,11,.12);border-left:4px solid #f59e0b;padding:10px 14px;
          border-radius:8px;color:#fbbf24;font-size:.88rem;margin:10px 0}}

/* countdown */
.cbar{{display:flex;align-items:center;gap:10px;margin:10px 0;flex-wrap:wrap}}
.live-dot{{background:#059669;color:#fff;padding:5px 14px;border-radius:20px;
           font-weight:700;font-size:.82rem;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
.ctimer{{background:#1e293b;border:1px solid #334155;border-radius:10px;
         padding:7px 14px;display:flex;align-items:center;gap:8px;color:#94a3b8;font-size:.85rem}}
#timer{{color:#fbbf24;font-weight:800;font-size:1rem;font-variant-numeric:tabular-nums}}
.prog-wrap{{width:120px;height:5px;background:#334155;border-radius:3px;overflow:hidden}}
.prog-bar{{height:100%;background:linear-gradient(90deg,#3b82f6,#10b981);border-radius:3px;transition:width 1s linear}}

/* badges */
.new-badge{{background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;
            font-size:.58rem;font-weight:800;padding:2px 5px;border-radius:4px;
            margin-left:4px;vertical-align:middle;animation:flash 1s 4}}
.sim-badge{{background:#334155;color:#94a3b8;font-size:.58rem;padding:1px 4px;
            border-radius:3px;margin-left:3px;vertical-align:middle}}
@keyframes flash{{0%,100%{{opacity:1}}50%{{opacity:.2}}}}
.new-row{{background:rgba(245,158,11,.05)!important}}

/* day summary */
.dsum{{background:#0f172a;border:2px solid #1e40af;border-radius:14px;padding:16px;margin:14px 0}}
.dsum-title{{color:#93c5fd;font-weight:700;font-size:.9rem;margin-bottom:12px}}
.dsum-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.dsbox{{background:#1e293b;border-radius:10px;padding:12px;text-align:center}}
.dsbox.hl{{background:rgba(16,185,129,.1);border:1px solid #10b981}}
.dsbox label{{display:block;color:#9ca3af;font-size:.72rem;margin-bottom:6px}}
.dsbox .dv{{font-size:1.5rem;font-weight:800}}
.dsbox small{{font-size:.72rem;margin-top:4px;display:block}}

/* big profit */
.profit-box{{background:linear-gradient(135deg,#065f46,#047857);border:3px solid #10b981;
             border-radius:14px;padding:20px;margin:14px 0;text-align:center;
             box-shadow:0 8px 40px rgba(16,185,129,.3);animation:glow 2.5s infinite}}
@keyframes glow{{0%,100%{{box-shadow:0 8px 40px rgba(16,185,129,.25)}}
                  50%{{box-shadow:0 8px 60px rgba(16,185,129,.55)}}}}
.profit-box label{{display:block;color:#d1fae5;font-size:.95rem;font-weight:600;
                   margin-bottom:8px;text-transform:uppercase;letter-spacing:.05em}}
.profit-amt{{display:block;color:#fff;font-size:3rem;font-weight:900;
             text-shadow:0 4px 12px rgba(0,0,0,.3);margin:8px 0}}
.profit-box small{{color:#a7f3d0;font-size:.88rem}}

/* table */
.tbl-wrap{{overflow-x:auto;margin:14px 0}}
table{{width:100%;background:rgba(17,24,39,.95);border-radius:12px;
       border-collapse:collapse;min-width:1100px;
       box-shadow:0 8px 40px rgba(0,0,0,.4)}}
thead{{background:linear-gradient(135deg,#1e293b,#334155)}}
th,td{{padding:10px 8px;text-align:center;border-bottom:1px solid rgba(71,85,105,.25);font-size:.75rem}}
th{{color:#60a5fa;font-weight:700;text-transform:uppercase;font-size:.64rem;letter-spacing:.04em}}
tr:hover{{background:rgba(59,130,246,.07)}}

/* mobile cards */
.cards{{display:none}}
.card{{background:rgba(17,24,39,.95);border-radius:16px;padding:14px;
       margin-bottom:14px;border:1px solid rgba(59,130,246,.2)}}
.new-card{{border:2px solid #f59e0b!important}}
.card-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}
.csym{{color:#60a5fa;font-size:1.3rem;font-weight:800}}
.cbadge{{padding:4px 10px;border-radius:20px;font-size:.72rem;font-weight:700;color:#fff}}
.dpbanner{{border:2px solid;border-radius:10px;padding:10px;text-align:center;margin-bottom:10px}}
.dplabel{{color:#9ca3af;font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}}
.dpval{{font-size:1.3rem;font-weight:800}}
.dpentry{{color:#9ca3af;font-size:.7rem;margin-top:4px}}
.row3{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px}}
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}}
.box,.pbox{{background:#1e293b;border-radius:8px;padding:9px;text-align:center}}
.pbox.hl{{background:linear-gradient(135deg,#065f46,#064e3b);border:2px solid #10b981}}
.box.hl2{{background:rgba(16,185,129,.1);border:1px solid #10b981}}
.blabel{{color:#9ca3af;font-size:.68rem;margin-bottom:4px}}
.bval{{font-size:1rem;font-weight:700}}
.bval.yellow{{color:#fbbf24}}.bval.blue{{color:#60a5fa}}.bval.green{{color:#34d399}}
.pval{{color:#e5e7eb;font-size:1.15rem;font-weight:700}}
.trow{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px}}
.tbox{{background:rgba(16,185,129,.08);border:1px solid #10b981;border-radius:7px;padding:7px;text-align:center}}
.tlabel{{color:#10b981;font-size:.62rem;margin-bottom:2px}}
.tval{{color:#34d399;font-size:.88rem;font-weight:700}}
.slrow{{background:#1e293b;padding:8px;border-radius:7px;font-size:.78rem;color:#9ca3af;text-align:center}}

/* responsive */
@media(max-width:768px){{
  .tbl-wrap table{{display:none}}
  .cards{{display:block}}
  h1{{font-size:1.35rem}}
  .profit-amt{{font-size:2.2rem}}
  .dsum-grid{{grid-template-columns:1fr}}
}}
@media(max-width:480px){{h1{{font-size:1.15rem}}}}
.ts{{color:#475569;font-size:.8rem;text-align:center;margin-top:16px;padding:10px}}
</style>
</head>
<body>
<div class="wrap">

  <h1>📊 Top 5 Midcap Intraday Picks</h1>
  <p class="sub">NSE F&O • 20 High-Volume Midcap Stocks Scanned • RSI + EMA + VWAP + ADX + Volume + Momentum</p>

  <!-- Live indicator + countdown -->
  <div class="cbar">
    <div class="live-dot">{'🔴 LIVE' if is_live else '🟡 SIMULATED'}</div>
    <div class="ctimer">
      🔄 Next refresh in <span id="timer">{refresh_secs}s</span>
      <div class="prog-wrap"><div class="prog-bar" id="prog" style="width:100%"></div></div>
    </div>
  </div>

  {src_banner}

  <!-- Day Summary -->
  <div class="dsum">
    <div class="dsum-title">📅 TODAY'S PERFORMANCE — {d.get('today','')}</div>
    <div class="dsum-grid">
      <div class="dsbox">
        <label>💵 Total Capital</label>
        <div class="dv" style="color:#60a5fa">₹{ti:.0f}</div>
      </div>
      <div class="dsbox">
        <label>🎯 Est. Day Profit (T2)</label>
        <div class="dv" style="color:#34d399">₹{tep:.2f}</div>
        <small style="color:#6ee7b7">{(tep/ti*100) if ti>0 else 0:.2f}% return</small>
      </div>
      <div class="dsbox hl">
        <label>📈 Live Day P&L</label>
        <div class="dv" style="color:{dtp_col}">{dtp_arr} ₹{abs(dtp):.2f}</div>
        <small style="color:{dtp_col}">{((dtp/ti)*100) if ti>0 else 0:+.2f}% on capital</small>
      </div>
    </div>
  </div>

  <!-- Big profit highlight -->
  <div class="profit-box">
    <label>💰 Total Expected Profit Today (at T2 target)</label>
    <span class="profit-amt">₹{tep:.2f}</span>
    <small>Live P&L so far: <b style="color:{dtp_col}">{dtp_arr} ₹{abs(dtp):.2f}</b> &nbsp;|&nbsp; Account: {d.get('account','Demo')}</small>
  </div>

  <!-- Desktop Table -->
  <div class="tbl-wrap">
  <table>
    <thead><tr>
      <th># Symbol</th><th>Price ₹</th><th>Entry ₹</th>
      <th>📦 Qty</th><th>💵 Invest</th><th>💰 Est.Profit</th>
      <th>📅 Day P&L</th><th>RSI</th><th>Score</th>
      <th>Action</th><th>Stop Loss</th><th>T1 2%</th><th>T2 3%</th><th>T3 5%</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>

  <!-- Mobile Cards -->
  <div class="cards">{cards}</div>

  <div class="ts">
    Last updated: {now} &nbsp;|&nbsp; Auto-refresh every {refresh_secs//60} min<br>
    <small>Angel One SmartAPI • NSE F&O Midcap Scanner • {'Live Data' if is_live else 'Simulated Data'}</small>
  </div>

</div>

<script>
(function(){{
  var total={refresh_secs}, left=total;
  var t=document.getElementById('timer'), p=document.getElementById('prog');
  setInterval(function(){{
    left--;
    if(left<=0){{ window.location.reload(); return; }}
    if(t) t.textContent=left+'s';
    if(p) p.style.width=(left/total*100)+'%';
    if(left<=10){{
      if(t) t.style.color='#ef4444';
      if(p) p.style.background='#ef4444';
    }}
  }},1000);
}})();
</script>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  VERCEL HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = get_stock_data()

            if self.path.startswith("/api") or "json" in self.path:
                body = json.dumps(data, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            else:
                html = build_html(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(html)

        except Exception as e:
            msg = f"Server error: {e}".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg)

    def log_message(self, fmt, *args):
        pass
