"""
api/index.py
============
Vercel serverless handler with LIVE stock data from Angel One API
"""

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import with error handling
try:
    import pyotp
    from SmartApi import SmartConnect
    IMPORTS_OK = True
except Exception as e:
    IMPORTS_OK = False
    print(f"Import error: {e}")

# Cache for stock data
_cache = {
    "data": None,
    "timestamp": None,
    "ttl": 30  # 30 seconds cache
}

def get_live_stock_data():
    """Fetch live stock data from Angel One API"""
    
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
    
    if not IMPORTS_OK:
        return {"error": "Required libraries not available", "stocks": []}
    
    try:
        # Login to Angel One
        smart_api = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        
        data = smart_api.generateSession(client_id, password, totp)
        
        if not data.get("status"):
            return {"error": f"Login failed: {data.get('message', 'Unknown error')}", "stocks": []}
        
        # Sample F&O stocks to fetch (top liquid stocks)
        stock_tokens = [
            {"symbol": "RELIANCE", "token": "2885", "exchange": "NSE"},
            {"symbol": "TCS", "token": "11536", "exchange": "NSE"},
            {"symbol": "HDFCBANK", "token": "1333", "exchange": "NSE"},
            {"symbol": "INFY", "token": "1594", "exchange": "NSE"},
            {"symbol": "ICICIBANK", "token": "4963", "exchange": "NSE"},
            {"symbol": "SBIN", "token": "3045", "exchange": "NSE"},
            {"symbol": "BHARTIARTL", "token": "10604", "exchange": "NSE"},
            {"symbol": "ITC", "token": "1660", "exchange": "NSE"},
            {"symbol": "KOTAKBANK", "token": "1922", "exchange": "NSE"},
            {"symbol": "LT", "token": "11483", "exchange": "NSE"},
            {"symbol": "AXISBANK", "token": "5900", "exchange": "NSE"},
            {"symbol": "WIPRO", "token": "3787", "exchange": "NSE"},
            {"symbol": "MARUTI", "token": "10999", "exchange": "NSE"},
            {"symbol": "TATAMOTORS", "token": "3456", "exchange": "NSE"},
            {"symbol": "ASIANPAINT", "token": "236", "exchange": "NSE"},
        ]
        
        stocks_data = []
        
        # Fetch LTP for each stock
        for stock in stock_tokens:
            try:
                ltp_data = smart_api.ltpData(stock["exchange"], stock["symbol"], stock["token"])
                
                if ltp_data.get("status") and ltp_data.get("data"):
                    price = ltp_data["data"].get("ltp", 0)
                    
                    stocks_data.append({
                        "symbol": stock["symbol"],
                        "ltp": price,
                        "exchange": stock["exchange"],
                        "updated": datetime.now().strftime("%H:%M:%S")
                    })
            except Exception as e:
                print(f"Error fetching {stock['symbol']}: {e}")
                continue
        
        result = {
            "account": client_id,
            "api_key": api_key[:4] + "***",
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "stocks_count": len(stocks_data),
            "stocks": stocks_data,
            "status": "success"
        }
        
        # Update cache
        _cache["data"] = result
        _cache["timestamp"] = now
        
        return result
        
    except Exception as e:
        return {"error": str(e), "stocks": []}


def get_html(stock_data):
    """Generate HTML with live stock data"""
    
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
            stock_rows += f"""
            <tr>
                <td>{idx}</td>
                <td style="font-weight:600; color:#60a5fa;">{stock['symbol']}</td>
                <td style="color:#34d399; font-weight:600;">₹{stock['ltp']:.2f}</td>
                <td>{stock['exchange']}</td>
                <td style="color:#94a3b8; font-size:0.85em;">{stock['updated']}</td>
            </tr>
            """
    else:
        stock_rows = '<tr><td colspan="5" style="text-align:center; color:#ef4444;">No stock data available</td></tr>'
    
    # Status message
    if stock_data.get("error"):
        status_msg = f'<div class="error-box">❌ {stock_data["error"]}</div>'
    elif stock_data.get("stocks"):
        status_msg = f'''<div class="success-box">
            ✅ Live data from Angel One API<br>
            Account: {stock_data.get("account", "N/A")} | 
            API Key: {stock_data.get("api_key", "N/A")} | 
            Stocks: {stock_data.get("stocks_count", 0)}
        </div>'''
    else:
        status_msg = '<div class="info-box">⏳ Waiting for data...</div>'
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>NSE F&O Scanner - Live Data</title>
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
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 2.5rem;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
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
        .config-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin: 24px 0;
        }}
        .config-item {{
            background: #1e293b;
            padding: 12px 16px;
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        table {{
            width: 100%;
            background: rgba(17, 24, 39, 0.8);
            border-radius: 12px;
            overflow: hidden;
            margin: 24px 0;
            border-collapse: collapse;
        }}
        thead {{
            background: #1e293b;
        }}
        th, td {{
            padding: 16px;
            text-align: left;
        }}
        th {{
            color: #60a5fa;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.05em;
        }}
        tr:nth-child(even) {{
            background: rgba(30, 41, 59, 0.3);
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
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 NSE F&O Scanner</h1>
        <p class="subtitle">Live Stock Data from Angel One API</p>
        
        <div class="status">
            🟢 {'All Credentials Configured' if all_configured else 'Credentials Missing'}
        </div>

        <div class="config-grid">
            <div class="config-item">
                <span>API Key</span>
                <span>{'✅' if has_api_key else '❌'}</span>
            </div>
            <div class="config-item">
                <span>Client ID</span>
                <span>{'✅' if has_client_id else '❌'}</span>
            </div>
            <div class="config-item">
                <span>Password</span>
                <span>{'✅' if has_password else '❌'}</span>
            </div>
            <div class="config-item">
                <span>TOTP Secret</span>
                <span>{'✅' if has_totp else '❌'}</span>
            </div>
        </div>

        {status_msg}

        <div class="refresh-note">
            🔄 Auto-refresh: 30 seconds | Cache TTL: 30 seconds
        </div>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Symbol</th>
                    <th>LTP (₹)</th>
                    <th>Exchange</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {stock_rows}
            </tbody>
        </table>

        <p class="timestamp">
            Last updated: {now}<br>
            Page auto-refreshes every 30 seconds
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
