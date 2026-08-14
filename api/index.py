import os
import sys
from http.server import BaseHTTPRequestHandler
from datetime import datetime

# Add root directory to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import yaml
from core.angel_client import AngelClient
from core.data_fetcher import DataFetcher
from core.fo_stocks import FO_STOCK_LIST
from scanner.screener import FOScreener
from output.report import generate_html_content, generate_csv_content

_cached_html = None
_cached_csv = None
_cached_time = None

def load_config():
    config_path = os.path.join(root_dir, "config", "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}

def refresh_scanner_data():
    global _cached_html, _cached_csv, _cached_time
    now = datetime.now()
    
    # Cache in memory for 60 seconds
    if _cached_html and _cached_time and (now - _cached_time).total_seconds() < 60:
        return _cached_html, _cached_csv

    config = load_config()
    angel_cfg = config.get("angel", {})
    scanner_cfg = config.get("scanner", {})
    
    # Strictly Angel One SmartAPI Live Client
    api_key = os.environ.get("ANGEL_API_KEY") or angel_cfg.get("api_key", "")
    client_id = os.environ.get("ANGEL_CLIENT_ID") or angel_cfg.get("client_id", "")
    password = os.environ.get("ANGEL_PASSWORD") or angel_cfg.get("password", "")
    totp_secret = os.environ.get("ANGEL_TOTP_SECRET") or angel_cfg.get("totp_secret", "")

    client = AngelClient(
        api_key=api_key,
        client_id=client_id,
        password=password,
        totp_secret=totp_secret,
        demo_mode=False,
    )
    
    login_success = client.login()

    if login_success:
        status_banner = f"<span style='color:#34d399; font-weight:600;'>🟢 LIVE Angel One SmartAPI Feed Connected (Account: {client.client_id})</span>"
        fetcher = DataFetcher(client=client, interval="ONE_DAY", history_days=100)
        # Fetch live OHLCV data directly from Angel One SmartAPI
        ohlcv_data = fetcher.fetch_all_ohlcv(stocks=FO_STOCK_LIST[:50], max_workers=10)
        
        if ohlcv_data:
            screener = FOScreener(min_score=30, top_n=20)
            results_df = screener.run(ohlcv_data, use_threads=True)
            top_df = screener.top_picks(results_df, n=20)
            stats = screener.summary_stats(results_df)
            
            _cached_html = generate_html_content(top_df, stats, status_banner=status_banner)
            _cached_csv = "\ufeff" + generate_csv_content(top_df)
            _cached_time = now
            return _cached_html, _cached_csv
        else:
            msg = f"<span style='color:#f87171;'>⚠️ Connected to Angel One ({client.client_id}) but market data is unavailable (market closed or rate limited).</span>"
            empty_df = screener.top_picks(pd.DataFrame(), n=0) if 'screener' in locals() else pd.DataFrame()
            return generate_html_content(pd.DataFrame(), {"total_screened": 0, "strong_buy": 0, "buy": 0, "watch": 0, "avoid": 0, "avg_score": 0, "top_symbol": "N/A"}, status_banner=msg), ""
    else:
        err_msg = client.last_error or "Invalid credentials"
        status_banner = f"""
        <div style="width:100%; color:#f87171; font-weight:500;">
            <strong>🔴 Angel One Live API Authentication Failed:</strong> {err_msg}<br>
            <span style="font-size:0.8rem; color:#9ca3af;">Please ensure your TOTP secret key is active on <a href="https://smartapi.angelone.in/enable-totp" target="_blank" style="color:#60a5fa;">smartapi.angelone.in</a> for Client ID: <strong>{client_id}</strong>.</span>
        </div>"""
        
        empty_stats = {"total_screened": 0, "strong_buy": 0, "buy": 0, "watch": 0, "avoid": 0, "avg_score": 0, "top_symbol": "N/A"}
        _cached_html = generate_html_content(pd.DataFrame(), empty_stats, status_banner=status_banner)
        _cached_csv = ""
        _cached_time = now
        return _cached_html, _cached_csv

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            html, csv_data = refresh_scanner_data()
            if "format=csv" in self.path or self.path.endswith(".csv") or "download=csv" in self.path or "download=excel" in self.path:
                date_str = datetime.now().strftime("%Y-%m-%d")
                self.send_response(200)
                self.send_header('Content-type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="NSE_FO_Scanner_Results_{date_str}.csv"')
                self.end_headers()
                self.wfile.write(csv_data.encode('utf-8'))
            else:
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"Server Error: {e}".encode('utf-8'))

if __name__ == "__main__":
    html, csv_str = refresh_scanner_data()
    print("Execution complete! HTML size:", len(html))
