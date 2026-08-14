import os
import sys
from http.server import BaseHTTPRequestHandler
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Add root directory to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import yaml
from core.angel_client import AngelClient
from core.data_fetcher import DataFetcher
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
    
    demo_mode = os.environ.get("DEMO_MODE", "false").lower() in ("1", "true", "yes") or scanner_cfg.get("demo_mode", False)
    client = AngelClient(
        api_key=os.environ.get("ANGEL_API_KEY") or angel_cfg.get("api_key", ""),
        client_id=os.environ.get("ANGEL_CLIENT_ID") or angel_cfg.get("client_id", ""),
        password=os.environ.get("ANGEL_PASSWORD") or angel_cfg.get("password", ""),
        totp_secret=os.environ.get("ANGEL_TOTP_SECRET") or angel_cfg.get("totp_secret", ""),
        demo_mode=demo_mode
    )
    status_banner = ""
    logged_in = client.login()
    if logged_in and not client.demo_mode:
        status_banner = f"<span style='color:#34d399; font-weight:600;'>🟢 LIVE Angel One SmartAPI Connected (Account: {client.client_id})</span>"
    elif client.last_error:
        status_banner = f"<span style='color:#f87171;'>⚠️ Angel One SmartAPI Notice: <strong>{client.last_error}</strong> &bull; Please check TOTP key from Angel One portal.</span>"

    fetcher = DataFetcher(client=client, interval="ONE_DAY", history_days=100)
    ohlcv_data = {}
    from core.fo_stocks import FO_STOCK_LIST
    
    def fetch_one(stock):
        sym = stock["symbol"]
        tok = stock["token"]
        df = fetcher.fetch_ohlcv(sym, tok)
        if df is not None and len(df) >= 20:
            return sym, df
        return None

    # Screen 50 stocks in parallel for instant sub-second response
    stocks_to_screen = FO_STOCK_LIST[:50]
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_one, s) for s in stocks_to_screen]
        for f in futures:
            res = f.result()
            if res:
                ohlcv_data[res[0]] = res[1]

    if ohlcv_data:
        screener = FOScreener(min_score=40, top_n=20)
        results_df = screener.run(ohlcv_data, use_threads=True)
        top_df = screener.top_picks(results_df, n=20)
        stats = screener.summary_stats(results_df)
        
        # Generate HTML and CSV in memory
        _cached_html = generate_html_content(top_df, stats, status_banner=status_banner)
        _cached_csv = "\ufeff" + generate_csv_content(top_df) # UTF-8 BOM for Excel
        _cached_time = now
        return _cached_html, _cached_csv

    return "<h1>Scanner initializing... Please refresh in a few seconds.</h1>", ""

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
    print(f"HTML generated successfully ({len(html)} bytes)")
    print(f"CSV generated successfully ({len(csv_str)} bytes)")
