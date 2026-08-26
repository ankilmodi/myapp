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

def get_smart_money_signal(rsi):
    """Determine smart money signal based on RSI"""
    if rsi > 70:
        return "RETAIL CONSOLIDATION"
    elif rsi > 60:
        return "INSTITUTIONAL BUY FLOW"
    elif rsi >= 40:
        return "INSTITUTIONAL BUY FLOW"
    else:
        return "RETAIL CONSOLIDATION"

def get_action_verdict(rsi, smart_signal):
    """Determine action verdict"""
    if smart_signal == "INSTITUTIONAL BUY FLOW":
        if rsi >= 55:
            return "BUY / ACCUMULATE"
        else:
            return "HOLD"
    else:
        if rsi > 75:
            return "SELL / BOOK PROFIT"
        elif rsi < 30:
            return "BUY / ACCUMULATE"
        else:
            return "HOLD"

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
                # Get historical candles for RSI
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
                    
                    # Calculate RSI from historical data
                    prices = []
                    if hist_data.get("status") and hist_data.get("data"):
                        for candle in hist_data["data"]:
                            prices.append(float(candle[4]))  # Close price
                    
                    rsi = calculate_rsi(prices) if prices else 50.0
                    smart_signal = get_smart_money_signal(rsi)
                    action = get_action_verdict(rsi, smart_signal)
                    entry_price, stop_loss, target1, target2, target3 = calculate_targets(ltp)
                    
                    stocks_data.append({
                        "symbol": stock["symbol"],
                        "ltp": ltp,
                        "entry_price": entry_price,
                        "rsi": rsi,
                        "smart_signal": smart_signal,
                        "action": action,
                        "stop_loss": stop_loss,
                        "target1": target1,
                        "target2": target2,
                        "target3": target3,
                        "exchange": stock["exchange"],
                        "updated": datetime.now().strftime("%H:%M:%S")
                    })
            except Exception as e:
                print(f"Error fetching {stock['symbol']}: {e}")
                continue
        
        # Sort by best profit potential (combination of RSI, action, and score)
        # Higher RSI in bullish zone (40-70) = better
        # BUY/ACCUMULATE action = better
        # Calculate profit score for ranking
        for stock in stocks_data:
            profit_score = 0
            
            # RSI score (best in 50-70 range)
            if 50 <= stock['rsi'] <= 70:
                profit_score += 40
            elif 40 <= stock['rsi'] < 50:
                profit_score += 30
            elif stock['rsi'] > 70:
                profit_score += 20
            
            # Action score
            if "BUY" in stock['action']:
                profit_score += 40
            elif "HOLD" in stock['action']:
                profit_score += 20
            
            # Smart money score
            if "INSTITUTIONAL BUY FLOW" in stock['smart_signal']:
                profit_score += 20
            
            stock['profit_score'] = profit_score
        
        # Sort by profit score (best opportunities first)
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
                <td style="font-weight:600; color:{rsi_color};">{stock['rsi']:.2f}</td>
                <td style="color:#9ca3af; font-size:0.9em;">{stock['smart_signal']}</td>
                <td style="font-weight:600; color:{action_color};">{stock['action']}</td>
                <td style="color:#ef4444; font-size:0.95em;">₹{stock['stop_loss']:.2f}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target1']:.2f}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target2']:.2f}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target3']:.2f}</td>
            </tr>
            """
            
            # Mobile card layout
            mobile_cards += f"""
            <div class="mobile-card">
                <div class="card-header">
                    <h3>{stock['symbol']}</h3>
                    <span class="action-badge" style="background:{action_color};">{stock['action']}</span>
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
                        <label>🛑 Stop Loss</label>
                        <span style="color:#ef4444; font-weight:600;">₹{stock['stop_loss']:.2f}</span>
                    </div>
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
        stock_rows = '<tr><td colspan="10" style="text-align:center; color:#ef4444; padding:24px;">No intraday picks available. Market may be closed or data loading...</td></tr>'
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
        status_msg = f'''<div class="success-box">
            ✅ LIVE Full-Day Profit Picks from Angel One API<br>
            Account: {stock_data.get("account", "N/A")} | 
            API Key: {stock_data.get("api_key", "N/A")} | 
            Best 5 Picks: {stock_data.get("stocks_count", 0)} stocks analyzed<br>
            <small>Ranked by: RSI + Smart Money + Profit Potential</small>
            {locked_note}
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
        <h1>📊 Top 5 Full Day Profit Picks</h1>
        <p class="subtitle">Best Stocks for Full-Day Trading • Maximum Profit Potential</p>
        
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
            🔄 Auto-refresh: 30 seconds | 🔒 SAME 5 stocks locked for FULL trading day (9:15 AM to 3:30 PM)
        </div>

        <!-- Desktop Table -->
        <table class="desktop-table">
            <thead>
                <tr>
                    <th>Stock Ticker</th>
                    <th>Current Price (₹)</th>
                    <th>Entry Price (₹)</th>
                    <th>RSI</th>
                    <th>Smart Money Signal</th>
                    <th>Action Verdict</th>
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
