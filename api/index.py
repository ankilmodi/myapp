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
    """Fetch live stock data from Angel One API"""
    
    # Check imports first
    if not IMPORTS_OK:
        error_msg = "Required libraries not available: " + ", ".join(import_errors)
        return {"error": error_msg, "stocks": [], "import_errors": import_errors}
    
    # Check cache
    now = datetime.now()
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
        
        result = {
            "account": client_id,
            "api_key": api_key[:4] + "***",
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "stocks_count": len(stocks_data),
            "stocks": stocks_data[:5],  # Top 5 best profit potential
            "status": "success",
            "note": "Top 5 stocks with best full-day profit potential"
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
    
    # Stock table HTML
    stock_rows = ""
    if stock_data.get("stocks"):
        for idx, stock in enumerate(stock_data["stocks"], 1):
            # Color coding for action
            action_color = "#34d399" if "BUY" in stock['action'] else "#fbbf24" if "HOLD" in stock['action'] else "#f87171"
            rsi_color = "#34d399" if 40 <= stock['rsi'] <= 70 else "#fbbf24" if stock['rsi'] > 70 else "#f87171"
            
            stock_rows += f"""
            <tr>
                <td style="font-weight:700; color:#60a5fa; font-size:1.1em;">{stock['symbol']}</td>
                <td style="font-weight:600; color:#e5e7eb; font-size:1.1em;">₹{stock['ltp']:.2f}</td>
                <td style="font-weight:600; color:#10b981; font-size:1.05em;">₹{stock['entry_price']:.2f}</td>
                <td style="font-weight:600; color:{rsi_color};">{stock['rsi']:.2f}</td>
                <td style="color:#9ca3af; font-size:0.9em;">{stock['smart_signal']}</td>
                <td style="font-weight:600; color:{action_color};">{stock['action']}</td>
                <td style="color:#ef4444; font-size:0.95em;">₹{stock['stop_loss']}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target1']}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target2']}</td>
                <td style="color:#34d399; font-size:0.95em;">₹{stock['target3']}</td>
            </tr>
            """
    else:
        stock_rows = '<tr><td colspan="10" style="text-align:center; color:#ef4444; padding:24px;">No intraday picks available. Market may be closed or data loading...</td></tr>'
    
    # Status message
    if stock_data.get("error"):
        error_detail = stock_data.get("error", "Unknown error")
        if stock_data.get("import_errors"):
            error_detail += "<br><small>Import errors: " + "<br>".join(stock_data["import_errors"]) + "</small>"
        status_msg = f'<div class="error-box">❌ {error_detail}</div>'
    elif stock_data.get("stocks"):
        status_msg = f'''<div class="success-box">
            ✅ LIVE Full-Day Profit Picks from Angel One API<br>
            Account: {stock_data.get("account", "N/A")} | 
            API Key: {stock_data.get("api_key", "N/A")} | 
            Best 5 Picks: {stock_data.get("stocks_count", 0)} stocks analyzed<br>
            <small>Ranked by: RSI + Smart Money + Profit Potential</small>
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
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 2.5rem;
            background: linear-gradient(135deg, #3b82f6, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
            font-weight: 700;
        }}
        .subtitle {{
            color: #9ca3af;
            font-size: 1.1rem;
            margin-bottom: 24px;
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
            overflow: hidden;
            margin: 24px 0;
            border-collapse: collapse;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }}
        thead {{
            background: linear-gradient(135deg, #1e293b, #334155);
        }}
        th, td {{
            padding: 16px 12px;
            text-align: center;
            border-bottom: 1px solid rgba(71, 85, 105, 0.3);
        }}
        th {{
            color: #60a5fa;
            font-weight: 700;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.05em;
        }}
        tr:hover {{
            background: rgba(59, 130, 246, 0.1);
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
            🔄 Auto-refresh: 30 seconds | Showing ONLY top 5 stocks with BEST full-day profit potential
        </div>

        <table>
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
