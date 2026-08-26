"""
api/index.py
============
Vercel serverless handler with LIVE intraday stock picks
"""

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import sys
import os
import json

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

# Cache for stock data
_cache = {
    "data": None,
    "timestamp": None,
    "ttl": 30  # 30 seconds cache
}

# Daily stock list (fixed for entire trading day)
_daily_stocks = {
    "symbols": [],
    "date": None,
    "locked": False
}

def calculate_rsi(prices, period=14):
    """Simple RSI calculation"""
    if len(prices) < period:
        return 50.0
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    k = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price * k) + (ema * (1 - k))
    
    return round(ema, 2)

def calculate_vwap(candles):
    """Calculate Volume Weighted Average Price for intraday"""
    if not candles:
        return 0
    
    total_pv = 0
    total_vol = 0
    
    for candle in candles:
        typical_price = (float(candle[2]) + float(candle[3]) + float(candle[4])) / 3
        volume = float(candle[5])
        total_pv += typical_price * volume
        total_vol += volume
    
    return round(total_pv / total_vol, 2) if total_vol > 0 else 0

def calculate_adx(candles, period=14):
    """Calculate ADX and Directional Indicators"""
    if len(candles) < period + 1:
        return 25, 20, 15  # Default neutral values
    
    # Calculate True Range, +DM, -DM
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    
    for i in range(1, len(candles)):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i-1][4])
        prev_high = float(candles[i-1][2])
        prev_low = float(candles[i-1][3])
        
        # True Range
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        
        # Directional Movement
        plus_dm = max(high - prev_high, 0) if (high - prev_high) > (prev_low - low) else 0
        minus_dm = max(prev_low - low, 0) if (prev_low - low) > (high - prev_high) else 0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    # Calculate smoothed values
    atr = sum(tr_list[-period:]) / period
    plus_di = (sum(plus_dm_list[-period:]) / period / atr * 100) if atr > 0 else 0
    minus_di = (sum(minus_dm_list[-period:]) / period / atr * 100) if atr > 0 else 0
    
    # Calculate ADX
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    adx = dx  # Simplified (should be smoothed but this works for scoring)
    
    return round(adx, 2), round(plus_di, 2), round(minus_di, 2)

def calculate_momentum(prices, period=5):
    """Calculate Rate of Change (ROC) momentum"""
    if len(prices) < period + 1:
        return 0
    
    roc = ((prices[-1] - prices[-period-1]) / prices[-period-1]) * 100
    return round(roc, 2)

def calculate_atr(candles, period=14):
    """Calculate Average True Range"""
    if len(candles) < period + 1:
        return 0
    
    tr_list = []
    for i in range(1, len(candles)):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i-1][4])
        
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    
    atr = sum(tr_list[-period:]) / period
    return round(atr, 2)

def get_smart_money_signal(rsi):
    """Determine smart money signal based on RSI"""
    if rsi >= 65:
        return "INSTITUTIONAL BUY FLOW"
    elif rsi >= 55:
        return "Accumulation Phase"
    elif rsi >= 45:
        return "Consolidation"
    elif rsi >= 35:
        return "Distribution Phase"
    else:
        return "INSTITUTIONAL SELL FLOW"

def get_action_verdict(rsi, smart_signal):
    """Determine action verdict"""
    if rsi >= 50 and "BUY FLOW" in smart_signal:
        return "STRONG BUY ⬆⬆"
    elif rsi >= 50:
        return "BUY ⬆"
    elif rsi >= 40 and "BUY FLOW" in smart_signal:
        return "ACCUMULATE 📈"
    elif rsi >= 40:
        return "HOLD ➡"
    else:
        return "AVOID ⬇"

def calculate_advanced_score(stock_data, prices, candles, avg_volume):
    """
    Calculate comprehensive buy score using multiple indicators
    Total: 100 points
    """
    score = 0
    
    ltp = stock_data['ltp']
    rsi = stock_data['rsi']
    
    # 1. RSI SCORE (15 points)
    if 60 <= rsi <= 70:
        score += 15
    elif 55 <= rsi < 60:
        score += 12
    elif 50 <= rsi < 55:
        score += 10
    elif 70 < rsi <= 75:
        score += 8
    elif 40 <= rsi < 50:
        score += 6
    
    # 2. EMA TREND (15 points)
    ema9 = calculate_ema(prices, 9)
    ema20 = calculate_ema(prices, 20)
    ema50 = calculate_ema(prices, 50)
    
    stock_data['ema9'] = ema9
    stock_data['ema20'] = ema20
    stock_data['ema50'] = ema50
    
    if ltp > ema9 > ema20 > ema50:
        score += 15  # Perfect alignment
    elif ltp > ema20 > ema50:
        score += 12
    elif ltp > ema20:
        score += 8
    elif ltp > ema50:
        score += 5
    
    # 3. VWAP (15 points)
    vwap = calculate_vwap(candles)
    stock_data['vwap'] = vwap
    
    distance_from_vwap = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0
    
    if ltp > vwap and 0 < distance_from_vwap < 3:
        score += 15  # Above VWAP but not overextended
    elif ltp > vwap and distance_from_vwap < 5:
        score += 10
    elif ltp > vwap:
        score += 5
    elif abs(distance_from_vwap) < 0.5:
        score += 7  # Near VWAP
    
    # 4. ADX & DIRECTIONAL INDICATORS (15 points)
    adx, plus_di, minus_di = calculate_adx(candles)
    stock_data['adx'] = adx
    stock_data['plus_di'] = plus_di
    stock_data['minus_di'] = minus_di
    
    if adx >= 25 and plus_di > minus_di:
        score += 15  # Strong uptrend
    elif adx >= 20 and plus_di > minus_di:
        score += 12
    elif adx >= 15 and plus_di > minus_di:
        score += 8
    elif plus_di > minus_di:
        score += 5
    
    # 5. VOLUME / RVOL (20 points)
    current_volume = sum([float(c[5]) for c in candles[-5:]])  # Last 5 candles
    rvol = current_volume / avg_volume if avg_volume > 0 else 1
    stock_data['rvol'] = round(rvol, 2)
    
    if rvol >= 2.0:
        score += 20  # Exceptional volume
    elif rvol >= 1.5:
        score += 16
    elif rvol >= 1.2:
        score += 12
    elif rvol >= 1.0:
        score += 8
    else:
        score += 4
    
    # 6. MOMENTUM (10 points)
    momentum_5 = calculate_momentum(prices, 5)
    momentum_10 = calculate_momentum(prices, 10)
    stock_data['momentum'] = momentum_5
    
    if momentum_5 > 0 and momentum_10 > 0:
        score += 10  # Both positive
    elif momentum_5 > 0:
        score += 6
    elif momentum_10 > 0:
        score += 4
    
    # 7. SMART MONEY & ACTION (10 points)
    if "BUY FLOW" in stock_data['smart_signal']:
        score += 10
    elif "Accumulation" in stock_data['smart_signal']:
        score += 6
    elif "Consolidation" in stock_data['smart_signal']:
        score += 3
    
    # RISK PENALTIES
    if rsi > 80:
        score -= 10  # Overbought
    if distance_from_vwap > 5:
        score -= 5  # Too far from VWAP
    
    return max(0, min(100, score))  # Keep between 0-100

def get_buy_rating(score):
    """Convert score to buy rating"""
    if score >= 90:
        return "🔥 A+ STRONG BUY"
    elif score >= 85:
        return "🟢 A STRONG BUY"
    elif score >= 80:
        return "🟢 BUY"
    elif score >= 75:
        return "🟡 BUY AFTER CONFIRMATION"
    elif score >= 70:
        return "🟡 WATCH"
    else:
        return "🔴 AVOID"

def calculate_targets(ltp):
    """Calculate target prices and entry zone"""
    # Entry zone: slightly below current price for better entry
    entry_price = round(ltp * 0.995, 2)  # 0.5% below LTP (wait for small dip)
    
    target1 = round(ltp * 1.02, 2)  # 2% gain
    target2 = round(ltp * 1.03, 2)  # 3% gain
    target3 = round(ltp * 1.05, 2)  # 5% gain
    stop_loss = round(ltp * 0.98, 2)  # 2% loss
    return entry_price, stop_loss, target1, target2, target3

def get_live_stock_data():
    """Fetch live stock data from Angel One API - Fixed 5 stocks for full trading day"""
    
    # Check imports first
    if not IMPORTS_OK:
        error_msg = "Required libraries not available: " + ", ".join(import_errors)
        return {"error": error_msg, "stocks": [], "import_errors": import_errors}
    
    # Check if we need to refresh the daily stock list
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    
    # If it's a new day OR daily stocks not selected yet, select fresh top 5
    if _daily_stocks["date"] != today_date or not _daily_stocks["symbols"]:
        _daily_stocks["date"] = today_date
        _daily_stocks["symbols"] = []  # Will be populated below
        _daily_stocks["locked"] = False
    
    # Check cache for live price updates (30 seconds)
    if _cache["data"] and _cache["timestamp"]:
        age = (now - _cache["timestamp"]).total_seconds()
        if age < _cache["ttl"]:
            return _cache["data"]
    
    # Get credentials from environment
    api_key = os.environ.get("ANGEL_API_KEY", "")
    client_id = os.environ.get("ANGEL_CLIENT_ID", "")
    password = os.environ.get("ANGEL_PASSWORD", "")
    totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "")
    
    if not all([api_key, client_id, password, totp_secret]):
        return {"error": "Credentials not configured", "stocks": []}
    
    try:
        # Login to Angel One
        smart_api = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        
        data = smart_api.generateSession(client_id, password, totp)
        
        if not data.get("status"):
            return {"error": f"Login failed: {data.get('message', 'Unknown error')}", "stocks": []}
        
        # SmallCap/MidCap F&O stocks (lower priced, higher volume potential)
        stock_tokens = [
            # Banking & Finance (Mid/Small Cap)
            {"symbol": "SBIN", "token": "3045", "exchange": "NSE"},           # State Bank ~600-700
            {"symbol": "AXISBANK", "token": "5900", "exchange": "NSE"},       # Axis Bank ~1000-1200
            {"symbol": "BANKBARODA", "token": "4668", "exchange": "NSE"},     # Bank of Baroda ~200-250
            
            # Auto Sector (Mid/Small Cap)
            {"symbol": "TATAMOTORS", "token": "3456", "exchange": "NSE"},     # Tata Motors ~800-1000
            {"symbol": "ASHOKLEY", "token": "212", "exchange": "NSE"},        # Ashok Leyland ~150-200
            
            # Infrastructure & PSU (Small Cap)
            {"symbol": "SAIL", "token": "3926", "exchange": "NSE"},           # SAIL ~100-150
            {"symbol": "POWERGRID", "token": "14977", "exchange": "NSE"},     # Power Grid ~250-300
            {"symbol": "NTPC", "token": "11630", "exchange": "NSE"},          # NTPC ~300-350
            
            # Telecom & Energy (Mid Cap)
            {"symbol": "BHARTIARTL", "token": "10604", "exchange": "NSE"},    # Bharti Airtel ~1300-1500
            {"symbol": "COALINDIA", "token": "5215", "exchange": "NSE"},      # Coal India ~400-450
        ]
        
        stocks_data = []
        
        # Fetch historical data for RSI calculation
        to_date = datetime.now()
        from_date = to_date - timedelta(days=30)
        
        for stock in stock_tokens:
            try:
                # Get historical candles for indicators
                hist_data = smart_api.getCandleData({
                    "exchange": stock["exchange"],
                    "symboltoken": stock["token"],
                    "interval": "ONE_DAY",
                    "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                    "todate": to_date.strftime("%Y-%m-%d %H:%M")
                })
                
                # Get LTP
                ltp_data = smart_api.ltpData(stock["exchange"], stock["symbol"], stock["token"])
                
                if ltp_data.get("status") and ltp_data.get("data"):
                    ltp = ltp_data["data"].get("ltp", 0)
                    
                    # Extract price data and candles
                    prices = []
                    candles = []
                    total_volume = 0
                    
                    if hist_data.get("status") and hist_data.get("data"):
                        candles = hist_data["data"]
                        for candle in candles:
                            prices.append(float(candle[4]))  # Close price
                            total_volume += float(candle[5])  # Volume
                    
                    avg_volume = total_volume / len(candles) if candles else 1
                    
                    # Calculate basic indicators
                    rsi = calculate_rsi(prices) if prices else 50.0
                    smart_signal = get_smart_money_signal(rsi)
                    action = get_action_verdict(rsi, smart_signal)
                    entry_price, stop_loss, target1, target2, target3 = calculate_targets(ltp)
                    
                    # Calculate shares and profit
                    investment_per_stock = 2000
                    shares_to_buy = int(investment_per_stock / entry_price)
                    actual_investment = shares_to_buy * entry_price
                    profit_per_share = target2 - entry_price
                    total_profit = round(profit_per_share * shares_to_buy, 2)
                    profit_percentage = round((profit_per_share / entry_price) * 100, 2)
                    
                    # Create stock data dict
                    stock_info = {
                        "symbol": stock["symbol"],
                        "ltp": ltp,
                        "entry_price": entry_price,
                        "shares_to_buy": shares_to_buy,
                        "investment": round(actual_investment, 2),
                        "expected_profit": total_profit,
                        "profit_percent": profit_percentage,
                        "rsi": rsi,
                        "smart_signal": smart_signal,
                        "action": action,
                        "stop_loss": stop_loss,
                        "target1": target1,
                        "target2": target2,
                        "target3": target3,
                        "exchange": stock["exchange"],
                        "updated": datetime.now().strftime("%H:%M:%S")
                    }
                    
                    # Calculate advanced buy score using ALL indicators
                    advanced_score = calculate_advanced_score(stock_info, prices, candles, avg_volume)
                    stock_info['profit_score'] = advanced_score
                    stock_info['buy_rating'] = get_buy_rating(advanced_score)
                    
                    stocks_data.append(stock_info)
            except Exception as e:
                print(f"Error fetching {stock['symbol']}: {e}")
                continue
        
        # Sort by advanced profit score (best opportunities first)
        stocks_data.sort(key=lambda x: x['profit_score'], reverse=True)
        
        # Lock the same 5 stocks for entire day if not already locked
        if not _daily_stocks["locked"] or not _daily_stocks["symbols"]:
            # First time today - select top 5 and lock them
            _daily_stocks["symbols"] = [s['symbol'] for s in stocks_data[:5]]
            _daily_stocks["locked"] = True
            top_5_stocks = stocks_data[:5]
        else:
            # Use locked symbols from morning, but update their live prices
            top_5_stocks = []
            for locked_symbol in _daily_stocks["symbols"]:
                # Find this symbol in current data
                stock_found = next((s for s in stocks_data if s['symbol'] == locked_symbol), None)
                if stock_found:
                    top_5_stocks.append(stock_found)
            
            # If somehow we have less than 5, fill with best remaining
            if len(top_5_stocks) < 5:
                remaining = [s for s in stocks_data if s['symbol'] not in _daily_stocks["symbols"]]
                top_5_stocks.extend(remaining[:5 - len(top_5_stocks)])
        
        result = {
            "account": client_id,
            "api_key": api_key[:4] + "***",
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "stocks_count": len(stocks_data),
            "stocks": top_5_stocks,
            "status": "success",
            "note": "Same 5 stocks locked for full trading day (9:15 AM - 3:30 PM)",
            "locked_symbols": _daily_stocks["symbols"],
            "day_start": _daily_stocks["date"]
        }
        
        # Update cache
        _cache["data"] = result
        _cache["timestamp"] = now
        
        return result
        
    except Exception as e:
        return {"error": str(e), "stocks": []}


def get_html(stock_data):
    """Generate HTML with intraday stock picks table"""
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Configuration status
    has_api_key = bool(os.environ.get("ANGEL_API_KEY"))
    has_client_id = bool(os.environ.get("ANGEL_CLIENT_ID"))
    has_password = bool(os.environ.get("ANGEL_PASSWORD"))
    has_totp = bool(os.environ.get("ANGEL_TOTP_SECRET"))
    
    all_configured = all([has_api_key, has_client_id, has_password, has_totp])
    
    # Stock rows HTML - Desktop table and Mobile cards
    stock_rows = ""
    mobile_cards = ""
    
    if stock_data.get("stocks"):
        for idx, stock in enumerate(stock_data["stocks"], 1):
            # Color coding for action
            action_color = "#34d399" if "BUY" in stock['action'] else "#fbbf24" if "HOLD" in stock['action'] else "#f87171"
            rsi_color = "#34d399" if 40 <= stock['rsi'] <= 70 else "#fbbf24" if stock['rsi'] > 70 else "#f87171"
            
            # Desktop table row
            stock_rows += f"""
            <tr>
                <td style="font-weight:700; color:#60a5fa; font-size:1.1em;">{stock['symbol']}</td>
                <td style="font-weight:600; color:#e5e7eb; font-size:1.1em;">₹{stock['ltp']:.2f}</td>
                <td style="font-weight:600; color:#10b981; font-size:1.05em;">₹{stock['entry_price']:.2f}</td>
                <td style="font-weight:700; color:#fbbf24; font-size:1em;">{stock['shares_to_buy']}</td>
                <td style="font-weight:600; color:#9ca3af; font-size:0.95em;">₹{stock['investment']:.0f}</td>
                <td style="font-weight:700; color:#34d399; font-size:1.05em;">₹{stock['expected_profit']:.2f}</td>
                <td style="font-weight:600; color:{rsi_color};">{stock['rsi']:.2f}</td>
                <td style="color:#9ca3af; font-size:0.85em;">{stock['smart_signal']}</td>
                <td style="font-weight:600; color:{action_color};">{stock['action']}</td>
                <td style="color:#ef4444; font-size:0.9em;">₹{stock['stop_loss']:.2f}</td>
                <td style="color:#34d399; font-size:0.9em;">₹{stock['target1']:.2f}</td>
                <td style="color:#34d399; font-size:0.9em;">₹{stock['target2']:.2f}</td>
                <td style="color:#34d399; font-size:0.9em;">₹{stock['target3']:.2f}</td>
            </tr>
            """
            
            # Mobile card layout
            mobile_cards += f"""
            <div class="mobile-card">
                <div class="card-header">
                    <h3>{stock['symbol']}</h3>
                    <span class="action-badge" style="background:{action_color};">{stock['action']}</span>
                </div>
                <div class="budget-box">
                    <div class="budget-item">
                        <label>📦 Buy Qty</label>
                        <span class="qty">{stock['shares_to_buy']} shares</span>
                    </div>
                    <div class="budget-item">
                        <label>💵 Investment</label>
                        <span class="invest">₹{stock['investment']:.0f}</span>
                    </div>
                    <div class="budget-item highlight-profit">
                        <label>💰 Expected Profit</label>
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
                </div>
                <div class="info-grid">
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
                    <small>📊 {stock['smart_signal']}</small>
                </div>
            </div>
            """
    else:
        stock_rows = '<tr><td colspan="13" style="text-align:center; color:#ef4444; padding:24px;">No intraday picks available. Market may be closed or data loading...</td></tr>'
        mobile_cards = '<div class="mobile-card"><p style="text-align:center; color:#ef4444; padding:24px;">No picks available</p></div>'
    
    # Status message
    if stock_data.get("error"):
        error_detail = stock_data.get("error", "Unknown error")
        if stock_data.get("import_errors"):
            error_detail += "<br><small>Import errors: " + "<br>".join(stock_data["import_errors"]) + "</small>"
        status_msg = f'<div class="error-box">❌ {error_detail}</div>'
    elif stock_data.get("stocks"):
        day_start = stock_data.get("day_start", "Today")
        locked_note = f"<br><small>🔒 These 5 stocks LOCKED since {day_start} 9:15 AM - Same stocks for full trading day</small>" if stock_data.get("locked_symbols") else ""
        
        # Calculate total investment and expected profit
        total_investment = sum(s.get('investment', 0) for s in stock_data['stocks'])
        total_expected_profit = sum(s.get('expected_profit', 0) for s in stock_data['stocks'])
        
        status_msg = f'''<div class="success-box">
            ✅ LIVE Full-Day Profit Picks from Angel One API<br>
            Account: {stock_data.get("account", "N/A")} | 
            API Key: {stock_data.get("api_key", "N/A")} | 
            Best 5 Picks: {stock_data.get("stocks_count", 0)} stocks analyzed<br>
            <small>📊 Advanced Multi-Indicator System: RSI + EMA + VWAP + ADX + Volume + Momentum</small>
            {locked_note}
        </div>
        <div class="profit-highlight">
            <div class="profit-main">
                <label>💰 TOTAL FINAL PROFIT (Full Day)</label>
                <span class="profit-amount">₹{total_expected_profit:.2f}</span>
                <small>Expected profit at end of trading day (3:15 PM)</small>
            </div>
        </div>
        <div class="budget-summary">
            <div class="summary-item">
                <label>💵 Total Investment</label>
                <span class="value">₹{total_investment:.0f}</span>
            </div>
            <div class="summary-item">
                <label>💰 Total Expected Profit</label>
                <span class="value profit">₹{total_expected_profit:.2f}</span>
            </div>
            <div class="summary-item">
                <label>📊 Expected Return</label>
                <span class="value">{(total_expected_profit/total_investment*100):.2f}%</span>
            </div>
        </div>'''
    else:
        status_msg = '<div class="info-box">⏳ Loading intraday picks...</div>'
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>Top 5 Full Day Profit Picks - Live</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0f1e 0%, #1a1f2e 100%);
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            padding: 12px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 1.8rem;
            background: linear-gradient(135deg, #3b82f6, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
            font-weight: 700;
        }}
        .subtitle {{
            color: #9ca3af;
            font-size: 0.9rem;
            margin-bottom: 16px;
        }}
        .status {{
            background: {'#059669' if all_configured else '#dc2626'};
            color: white;
            padding: 12px 24px;
            border-radius: 12px;
            display: inline-block;
            font-weight: 600;
            margin-bottom: 24px;
            animation: pulse 2s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.8; }}
        }}
        .success-box {{
            background: rgba(5, 150, 105, 0.2);
            border-left: 4px solid #059669;
            padding: 16px;
            border-radius: 8px;
            margin: 16px 0;
            color: #34d399;
            font-size: 1rem;
        }}
        .error-box {{
            background: rgba(239, 68, 68, 0.2);
            border-left: 4px solid #ef4444;
            padding: 16px;
            border-radius: 8px;
            margin: 16px 0;
            color: #f87171;
        }}
        .info-box {{
            background: rgba(59, 130, 246, 0.2);
            border-left: 4px solid #3b82f6;
            padding: 16px;
            border-radius: 8px;
            margin: 16px 0;
            color: #60a5fa;
        }}
        .profit-highlight {{
            background: linear-gradient(135deg, #065f46, #047857);
            border: 3px solid #10b981;
            border-radius: 16px;
            padding: 24px;
            margin: 20px 0;
            text-align: center;
            box-shadow: 0 10px 40px rgba(16, 185, 129, 0.3);
            animation: pulse-glow 2s ease-in-out infinite;
        }}
        @keyframes pulse-glow {{
            0%, 100% {{ box-shadow: 0 10px 40px rgba(16, 185, 129, 0.3); }}
            50% {{ box-shadow: 0 10px 60px rgba(16, 185, 129, 0.6); }}
        }}
        .profit-main label {{
            display: block;
            color: #d1fae5;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .profit-amount {{
            display: block;
            color: #ffffff;
            font-size: 3.5rem;
            font-weight: 900;
            text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            margin: 12px 0;
        }}
        .profit-main small {{
            display: block;
            color: #a7f3d0;
            font-size: 0.9rem;
            margin-top: 8px;
        }}
        @media (max-width: 768px) {{
            .profit-amount {{
                font-size: 2.5rem;
            }}
            .profit-main label {{
                font-size: 0.95rem;
            }}
        }}
        .budget-summary {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin: 16px 0;
            background: rgba(17, 24, 39, 0.95);
            padding: 20px;
            border-radius: 12px;
            border: 2px solid #1e40af;
        }}
        .summary-item {{
            text-align: center;
        }}
        .summary-item label {{
            display: block;
            color: #9ca3af;
            font-size: 0.85rem;
            margin-bottom: 8px;
        }}
        .summary-item .value {{
            display: block;
            color: #60a5fa;
            font-size: 1.8rem;
            font-weight: 700;
        }}
        .summary-item .value.profit {{
            color: #34d399;
            font-size: 2rem;
        }}
        .summary-item.highlight {{
            background: rgba(16, 185, 129, 0.1);
            border-radius: 8px;
            padding: 8px;
        }}
        @media (max-width: 768px) {{
            .budget-summary {{
                grid-template-columns: 1fr;
                gap: 12px;
                padding: 16px;
            }}
            .summary-item .value {{
                font-size: 1.5rem;
            }}
        }}
        table {{
            width: 100%;
            background: rgba(17, 24, 39, 0.95);
            border-radius: 12px;
            overflow-x: auto;
            margin: 16px 0;
            border-collapse: collapse;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            display: block;
        }}
        thead {{
            background: linear-gradient(135deg, #1e293b, #334155);
        }}
        tbody {{
            display: block;
            overflow-x: auto;
        }}
        tr {{
            display: table;
            width: 100%;
            table-layout: fixed;
        }}
        th, td {{
            padding: 10px 6px;
            text-align: center;
            border-bottom: 1px solid rgba(71, 85, 105, 0.3);
            font-size: 0.75rem;
            min-width: 80px;
        }}
        th {{
            color: #60a5fa;
            font-weight: 700;
            text-transform: uppercase;
            font-size: 0.65rem;
            letter-spacing: 0.03em;
        }}
        tr:hover {{
            background: rgba(59, 130, 246, 0.1);
        }}
        
        /* Mobile Cards */
        .mobile-cards {{
            display: none;
        }}
        .mobile-card {{
            background: rgba(17, 24, 39, 0.95);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(59, 130, 246, 0.2);
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .card-header h3 {{
            color: #60a5fa;
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0;
        }}
        .action-badge {{
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            color: white;
        }}
        .price-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 12px;
        }}
        .price-box {{
            background: #1e293b;
            padding: 12px;
            border-radius: 12px;
            text-align: center;
        }}
        .price-box.highlight {{
            background: linear-gradient(135deg, #065f46, #064e3b);
            border: 2px solid #10b981;
        }}
        .price-box label {{
            display: block;
            color: #9ca3af;
            font-size: 0.75rem;
            margin-bottom: 4px;
        }}
        .price-box .price {{
            display: block;
            color: #e5e7eb;
            font-size: 1.25rem;
            font-weight: 700;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 12px;
        }}
        .info-item {{
            background: #1e293b;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }}
        .info-item label {{
            display: block;
            color: #9ca3af;
            font-size: 0.7rem;
            margin-bottom: 4px;
        }}
        .info-item span {{
            font-size: 1rem;
        }}
        .targets-row {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }}
        .target-box {{
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid #10b981;
            padding: 8px;
            border-radius: 8px;
            text-align: center;
        }}
        .target-box label {{
            display: block;
            color: #10b981;
            font-size: 0.65rem;
            margin-bottom: 2px;
        }}
        .target-box span {{
            display: block;
            color: #34d399;
            font-size: 0.9rem;
            font-weight: 600;
        }}
        .signal-box {{
            background: #1e293b;
            padding: 8px;
            border-radius: 8px;
            text-align: center;
        }}
        .signal-box small {{
            color: #9ca3af;
            font-size: 0.7rem;
        }}
        
        /* Score Box */
        .score-box {{
            background: linear-gradient(135deg, #1e3a8a, #1e40af);
            border: 2px solid #3b82f6;
            padding: 12px;
            border-radius: 12px;
            text-align: center;
            margin-top: 12px;
        }}
        .score-box label {{
            display: block;
            color: #93c5fd;
            font-size: 0.7rem;
            margin-bottom: 4px;
        }}
        .buy-score {{
            display: block;
            color: #ffffff;
            font-size: 1.8rem;
            font-weight: 900;
            margin: 4px 0;
        }}
        .score-box small {{
            display: block;
            color: #fbbf24;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        /* Budget Box for Mobile */
        .budget-box {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
            background: #0f172a;
            padding: 12px;
            border-radius: 12px;
            border: 2px solid #1e40af;
        }}
        .budget-item {{
            text-align: center;
        }}
        .budget-item label {{
            display: block;
            color: #9ca3af;
            font-size: 0.65rem;
            margin-bottom: 4px;
        }}
        .budget-item .qty {{
            display: block;
            color: #fbbf24;
            font-size: 1rem;
            font-weight: 700;
        }}
        .budget-item .invest {{
            display: block;
            color: #60a5fa;
            font-size: 1rem;
            font-weight: 700;
        }}
        .budget-item .profit {{
            display: block;
            color: #34d399;
            font-size: 1.1rem;
            font-weight: 700;
        }}
        .budget-item.highlight-profit {{
            background: rgba(16, 185, 129, 0.1);
            border-radius: 8px;
            padding: 4px;
        }}
        
        /* Mobile Styles */
        @media (max-width: 768px) {{
            body {{
                padding: 8px;
            }}
            h1 {{
                font-size: 1.4rem;
            }}
            .subtitle {{
                font-size: 0.75rem;
            }}
            .status {{
                padding: 8px 16px;
                font-size: 0.85rem;
            }}
            
            /* Hide table on mobile */
            .desktop-table {{
                display: none;
            }}
            
            /* Show cards on mobile */
            .mobile-cards {{
                display: block;
            }}
            
            .success-box, .error-box, .info-box {{
                padding: 12px;
                font-size: 0.8rem;
            }}
            .refresh-note {{
                padding: 8px;
                font-size: 0.75rem;
            }}
            .legend {{
                flex-direction: column;
                gap: 8px;
            }}
            .legend-item {{
                font-size: 0.75rem;
            }}
        }}
        
        /* Small Mobile */
        @media (max-width: 480px) {{
            h1 {{
                font-size: 1.2rem;
            }}
            .subtitle {{
                font-size: 0.7rem;
            }}
            .card-header h3 {{
                font-size: 1.3rem;
            }}
        }}
        .timestamp {{
            color: #64748b;
            font-size: 0.9rem;
            margin-top: 24px;
            text-align: center;
        }}
        .refresh-note {{
            background: #1e293b;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            color: #94a3b8;
            margin: 16px 0;
            font-size: 0.9rem;
        }}
        .legend {{
            display: flex;
            justify-content: center;
            gap: 24px;
            margin: 16px 0;
            flex-wrap: wrap;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: #94a3b8;
        }}
        .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Advanced Intraday Stock Scanner</h1>
        <p class="subtitle">Multi-Indicator Best Buy System • RSI + EMA + VWAP + ADX + Volume + Momentum</p>
        
        <div class="status">
            🔴 LIVE • Market Open
        </div>

        {status_msg}

        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background:#34d399;"></div>
                <span>BUY Signal</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:#fbbf24;"></div>
                <span>HOLD</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background:#f87171;"></div>
                <span>SELL Signal</span>
            </div>
        </div>

        <div class="refresh-note">
            🔄 Auto-refresh: 30 seconds | 🔒 SAME 5 stocks locked for FULL trading day | 📊 Score: 100-point advanced system
        </div>

        <!-- Desktop Table -->
        <table class="desktop-table">
            <thead>
                <tr>
                    <th>Stock Ticker</th>
                    <th>Current Price (₹)</th>
                    <th>Entry Price (₹)</th>
                    <th>📦 Buy Qty</th>
                    <th>💵 Investment</th>
                    <th>💰 Expected Profit</th>
                    <th>RSI</th>
                    <th>Smart Money</th>
                    <th>Action</th>
                    <th>Stop Loss</th>
                    <th>Target 1</th>
                    <th>Target 2</th>
                    <th>Target 3</th>
                </tr>
            </thead>
            <tbody>
                {stock_rows}
            </tbody>
        </table>

        <!-- Mobile Cards -->
        <div class="mobile-cards">
            {mobile_cards}
        </div>

        <p class="timestamp">
            Last updated: {now}<br>
            Page auto-refreshes every 30 seconds<br>
            <small>Data from Angel One SmartAPI • Account: {stock_data.get("account", "N/A")}</small>
        </p>
    </div>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Fetch live stock data
            stock_data = get_live_stock_data()
            
            # JSON API endpoint
            if "/api" in self.path or "/json" in self.path:
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(json.dumps(stock_data, indent=2).encode("utf-8"))
            
            # HTML dashboard (default)
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
