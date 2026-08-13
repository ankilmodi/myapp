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


def start_web_server(port: int):
    os.makedirs("output", exist_ok=True)
    if not os.path.exists("output/dashboard.html"):
        with open("output/dashboard.html", "w", encoding="utf-8") as f:
            f.write("<h1>Loading Scanner Dashboard... Please refresh in a few seconds.</h1>")

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
    )
    ohlcv_data = fetcher.fetch_all_ohlcv(delay_ms=300)

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

    parser = argparse.ArgumentParser(description="Angel One F&O Best Buy Scanner")
    parser.add_argument("--demo",  action="store_true", help="Run in demo/mock mode (no real API)")
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

    # ── Demo mode override ─────────────────────────────────
    demo_mode = args.demo or scanner_cfg.get("demo_mode", False)
    if demo_mode:
        logger.info("🎮 Running in DEMO MODE (mock data, no API call)")

    # ── Create Client ──────────────────────────────────────
    client = AngelClient(
        api_key=angel_cfg.get("api_key", "DEMO"),
        client_id=angel_cfg.get("client_id", "DEMO001"),
        password=angel_cfg.get("password", "demo123"),
        totp_secret=angel_cfg.get("totp_secret", "JBSWY3DPEHPK3PXP"),
        demo_mode=demo_mode,
    )

    # ── Login ──────────────────────────────────────────────
    if not client.login():
        logger.error("Login failed. Use --demo flag for demo mode.")
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

    if args.once or demo_mode:
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
