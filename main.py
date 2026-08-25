# -*- coding: utf-8 -*-
"""
main.py
=======
🚀 Angel One SmartAPI + NSE F&O Best Buy Scanner
Entry Point

Usage:
    python main.py              # Live mode (requires API key)
    python main.py --demo       # Demo mode (mock data, no API key needed)
    python main.py --once       # Run once and exit
    python main.py --top 10     # Show top 10 picks
"""

import argparse
import os
import time
from datetime import datetime

import sys
import io
import yaml

# ── Force UTF-8 output on Windows ────────────────────────────
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from loguru import logger

# ── Configure logger ───────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add("logs/scanner.log", rotation="10 MB", retention="7 days", level="DEBUG")

# ── Local imports ──────────────────────────────────────────────
from core.angel_client import AngelClient
from core.data_fetcher import DataFetcher
from scanner.screener import FOScreener
from output.report import print_rich_table, print_summary, save_csv, save_html_report

import threading
import http.server
import socketserver

os.makedirs("output", exist_ok=True)
os.makedirs("logs", exist_ok=True)


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        root = os.path.join(os.getcwd(), 'output')
        path = path.lstrip('/')
        if not path or path == 'index.html' or path == 'dashboard.html':
            return os.path.join(root, 'dashboard.html')
        return os.path.join(root, path)

    def log_message(self, format, *args):
        """Suppress HTTP access logs to keep output clean."""
        pass


LOADING_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta http-equiv="refresh" content="5">
<title>NSE F&O Scanner — Loading...</title>
<style>
  body{margin:0;background:#0a0f1e;color:#e5e7eb;font-family:Inter,sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;}
  .box{text-align:center;}
  h1{font-size:2rem;color:#3b82f6;margin-bottom:12px;}
  p{color:#9ca3af;font-size:1rem;}
  .spinner{width:48px;height:48px;border:4px solid #1e2d40;
           border-top-color:#3b82f6;border-radius:50%;
           animation:spin 0.8s linear infinite;margin:24px auto;}
  @keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body><div class="box">
  <div class="spinner"></div>
  <h1>📈 NSE F&O Scanner</h1>
  <p>Scanning 289 F&O stocks... Dashboard will appear in ~60 seconds.</p>
  <p style="font-size:.8rem;margin-top:8px;color:#6b7280">Page auto-refreshes every 5 seconds.</p>
</div></body></html>"""


def start_web_server(port: int):
    os.makedirs("output", exist_ok=True)
    if not os.path.exists("output/dashboard.html"):
        with open("output/dashboard.html", "w", encoding="utf-8") as f:
            f.write(LOADING_HTML)

    handler = DashboardHandler
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            logger.info(f"🌍 Web server started on port {port}. Serving dashboard.")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Web server error: {e}")



# ─────────────────────────────────────────────────────────────
# Load Config
# ─────────────────────────────────────────────────────────────
def load_config(path: str = "config/config.yaml") -> dict:
    if not os.path.exists(path):
        example_path = path + ".example"
        if os.path.exists(example_path):
            with open(example_path, "r") as f:
                return yaml.safe_load(f)
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────
BANNER = """
=================================================================
   NSE F&O BEST BUY SCANNER  |  Angel One SmartAPI
   Multi-Factor: RSI + MACD + EMA + Volume + OI + Supertrend
   Screening 209 F&O stocks for top BUY opportunities
=================================================================
"""


# ─────────────────────────────────────────────────────────────
# Main scan function
# ─────────────────────────────────────────────────────────────
def run_scan(client: AngelClient, config: dict, top_n: int = 20):
    """Perform one full scan cycle."""
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting scan at {scan_time}")

    cfg = config["scanner"]
    weights_cfg = config.get("formula_weights", {})

    # ── 1. Fetch Data ──────────────────────────────────────
    fetcher = DataFetcher(
        client=client,
        interval=cfg.get("candle_interval", "ONE_DAY"),
        history_days=cfg.get("history_days", 100),
        rate_delay=0.3,  # 0.3 seconds between requests
        max_stocks=top_n,  # Fetch only the number of stocks we need
    )
    ohlcv_data = fetcher.fetch_all_ohlcv()  # No parameters needed

    if not ohlcv_data:
        logger.error("No data fetched. Check API connection.")
        return

    # ── 2. Run Screener ────────────────────────────────────
    screener = FOScreener(
        min_score=cfg.get("min_score", 50),
        top_n=top_n,
    )
    results_df = screener.run(ohlcv_data)
    top_df = screener.top_picks(results_df, n=top_n)
    stats = screener.summary_stats(results_df)

    # ── 3. Display Results ─────────────────────────────────
    print_rich_table(top_df, title=f"🏆 NSE F&O Best Buy — Top {top_n} | {scan_time}")
    print_summary(stats, timestamp=scan_time)

    # ── 4. Save Outputs ────────────────────────────────────
    out_cfg = config.get("output", {})
    if out_cfg.get("save_csv", True):
        save_csv(top_df, out_cfg.get("csv_path", "output/results.csv"))
    if out_cfg.get("save_html", True):
        html_path = save_html_report(
            top_df, stats,
            path=out_cfg.get("html_path", "output/dashboard.html")
        )
        logger.info(f"Open dashboard: file://{os.path.abspath(html_path)}")

    # ── 5. Telegram Alerts ─────────────────────────────────
    alert_cfg = config.get("alerts", {})
    if alert_cfg.get("telegram_enabled", False):
        from output.alerts import TelegramAlert
        telegram = TelegramAlert(
            alert_cfg["telegram_bot_token"],
            alert_cfg["telegram_chat_id"],
        )
        threshold = alert_cfg.get("alert_threshold", 70)
        alert_picks = results_df[results_df["score"] >= threshold].to_dict("records")
        if alert_picks:
            telegram.send_top_picks(alert_picks, timestamp=scan_time)

    return results_df


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────
def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description="Angel One F&O Best Buy Scanner - LIVE MODE ONLY")
    parser.add_argument("--once",  action="store_true", help="Run once and exit")
    parser.add_argument("--top",   type=int, default=20,  help="Number of top picks to display")
    parser.add_argument("--config",type=str, default="config/config.yaml", help="Path to config file")
    args = parser.parse_args()

    # ── Load Config ────────────────────────────────────────
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Could not load config: {e}")
        sys.exit(1)

    angel_cfg = config.get("angel", {})
    scanner_cfg = config.get("scanner", {})
    refresh_interval = scanner_cfg.get("refresh_interval", 60)

    # ── Detect cloud deployment (PORT env var) ─────────────
    port = os.environ.get("PORT")

    # ★ STEP 1: Start web server FIRST so health checks pass immediately
    if port:
        try:
            port_num = int(port)
            logger.info(f"PORT={port_num} detected. Starting web server immediately...")
            web_thread = threading.Thread(target=start_web_server, args=(port_num,), daemon=True)
            web_thread.start()
            time.sleep(1)   # give server a moment to bind
        except Exception as e:
            logger.error(f"Failed to start web server on port {port}: {e}")

    # ── Demo mode override (default: LIVE mode with real authentication) ────────────────────────────
    # ★ STEP 2: Create client and login with LIVE Angel One API ONLY
    logger.info("🔐 Running in LIVE MODE with real Angel One authentication...")
    
    client = AngelClient(
        api_key=os.environ.get("ANGEL_API_KEY") or angel_cfg.get("api_key", ""),
        client_id=os.environ.get("ANGEL_CLIENT_ID") or angel_cfg.get("client_id", ""),
        password=os.environ.get("ANGEL_PASSWORD") or angel_cfg.get("password", ""),
        totp_secret=os.environ.get("ANGEL_TOTP_SECRET") or angel_cfg.get("totp_secret", ""),
    )

    if not client.login():
        logger.error("❌ Login failed. Please check your credentials in config/config.yaml")
        logger.error("    Ensure API key, client ID, password, and TOTP secret are correct.")
        sys.exit(1)

    profile = client.get_profile()
    if profile.get("status"):
        logger.info(f"Account: {profile.get('data', {}).get('name', 'N/A')}")

    # ── Run scan ───────────────────────────────────────────
    refresh_interval = scanner_cfg.get("refresh_interval", 60)

    # ── Start Web Server if PORT environment variable is set ──
    port = os.environ.get("PORT")
    if port:
        try:
            port_num = int(port)
            logger.info(f"PORT environment variable found. Starting web server on port {port_num}...")
            web_thread = threading.Thread(target=start_web_server, args=(port_num,), daemon=True)
            web_thread.start()
        except Exception as e:
            logger.error(f"Failed to start web server on port {port}: {e}")

    # ── When deployed (PORT set), always loop to keep dashboard fresh ──
    if port:
        logger.info(f"☁️  Deployed mode: continuous scan every {refresh_interval}s. Dashboard auto-refreshes.")
        try:
            while True:
                run_scan(client, config, top_n=args.top)
                logger.info(f"Next scan in {refresh_interval}s...")
                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            logger.info("Scanner stopped.")
    elif args.once or demo_mode:
        run_scan(client, config, top_n=args.top)
    else:
        logger.info(f"Live mode: refreshing every {refresh_interval} seconds. Press Ctrl+C to stop.")
        try:
            while True:
                run_scan(client, config, top_n=args.top)
                logger.info(f"Next scan in {refresh_interval}s...")
                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            logger.info("Scanner stopped by user.")

    client.logout()
    logger.success("Done! Check output/dashboard.html for results.")


if __name__ == "__main__":
    main()
