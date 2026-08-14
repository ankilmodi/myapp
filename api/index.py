"""
api/index.py
============
Vercel serverless handler — 100% Angel One SmartAPI live data.
NO hardcoded data, NO JSON files, NO mock prices.

Flow:
  1. Login to Angel One SmartAPI (live credentials from env vars)
  2. Fetch live NSE F&O stock list from Angel One scrip master API
  3. Fetch live OHLCV candles from Angel One getCandleData
  4. Patch live LTP from Angel One ltpData
  5. Run Best-Buy scoring formula
  6. Render HTML dashboard or return CSV
"""

import os
import sys
from http.server import BaseHTTPRequestHandler
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import yaml
import pandas as pd
from loguru import logger

from core.angel_client import AngelClient
from core.data_fetcher import DataFetcher
from scanner.screener import FOScreener
from output.report import generate_html_content, generate_csv_content

# ── In-memory cache ───────────────────────────────────────────────────────────
_cached_html: str = ""
_cached_csv: str = ""
_cached_time: datetime = None
CACHE_TTL_SECONDS = 90  # refresh every 90 seconds


def load_config() -> dict:
    """Load config.yaml if available (local dev). Env vars override in production."""
    config_path = os.path.join(root_dir, "config", "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def get_credentials() -> dict:
    """
    Read Angel One credentials from environment variables (Vercel production)
    or fall back to config.yaml (local dev). NO hardcoded values.
    """
    config = load_config()
    angel_cfg = config.get("angel", {})
    return {
        "api_key":     os.environ.get("ANGEL_API_KEY")     or angel_cfg.get("api_key", ""),
        "client_id":   os.environ.get("ANGEL_CLIENT_ID")   or angel_cfg.get("client_id", ""),
        "password":    os.environ.get("ANGEL_PASSWORD")     or angel_cfg.get("password", ""),
        "totp_secret": os.environ.get("ANGEL_TOTP_SECRET") or angel_cfg.get("totp_secret", ""),
    }


def _error_page(title: str, message: str) -> str:
    """Return a styled error page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NSE F&O Scanner — Error</title>
<style>
  body {{ background:#0a0f1e; color:#e5e7eb; font-family:Inter,sans-serif;
          display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .card {{ background:#111827; border:1px solid #1e2d40; border-radius:16px;
           padding:40px 48px; max-width:560px; text-align:center; }}
  h1 {{ color:#f87171; font-size:1.4rem; margin-bottom:12px; }}
  p  {{ color:#9ca3af; font-size:0.9rem; line-height:1.6; }}
  a  {{ color:#60a5fa; }}
</style>
</head>
<body>
  <div class="card">
    <h1>🔴 {title}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""


def refresh_data() -> tuple:
    """
    Full live data refresh using Angel One SmartAPI only.
    Returns (html_string, csv_string).
    """
    global _cached_html, _cached_csv, _cached_time

    now = datetime.now()

    # Serve from cache if fresh
    if _cached_html and _cached_time and (now - _cached_time).total_seconds() < CACHE_TTL_SECONDS:
        return _cached_html, _cached_csv

    # ── Step 1: Get credentials (env vars / config.yaml — no hardcoding) ──────
    creds = get_credentials()
    if not creds["api_key"] or not creds["client_id"]:
        html = _error_page(
            "Missing Credentials",
            "Angel One API credentials not configured.<br>"
            "Set <code>ANGEL_API_KEY</code>, <code>ANGEL_CLIENT_ID</code>, "
            "<code>ANGEL_PASSWORD</code>, <code>ANGEL_TOTP_SECRET</code> "
            "as Vercel environment variables."
        )
        return html, ""

    # ── Step 2: Login to Angel One SmartAPI ───────────────────────────────────
    client = AngelClient(
        api_key=creds["api_key"],
        client_id=creds["client_id"],
        password=creds["password"],
        totp_secret=creds["totp_secret"],
        demo_mode=False,
    )

    login_ok = client.login()

    if not login_ok:
        err = client.last_error or "Authentication failed"
        logger.error(f"Angel One login failed: {err}")
        html = _error_page(
            "Angel One Login Failed",
            f"Error: <strong>{err}</strong><br><br>"
            f"Please verify your TOTP secret key at "
            f"<a href='https://smartapi.angelone.in/enable-totp' target='_blank'>"
            f"smartapi.angelone.in/enable-totp</a> for Client ID: {creds['client_id']}"
        )
        _cached_html = html
        _cached_csv = ""
        _cached_time = now
        return html, ""

    status_banner = (
        f"<span style='color:#34d399; font-weight:600;'>"
        f"🟢 LIVE Angel One SmartAPI — Account: {client.client_id} | "
        f"Updated: {now.strftime('%d %b %Y %H:%M:%S')}"
        f"</span>"
    )
    logger.success(f"Angel One login OK: {client.client_id}")

    # ── Step 3: Fetch live data from Angel One (no hardcoded data) ────────────
    fetcher = DataFetcher(
        client=client,
        interval="ONE_DAY",
        history_days=100,
        rate_delay=0.4,
        max_stocks=50,
    )

    ohlcv_data = fetcher.fetch_all_ohlcv()

    if not ohlcv_data:
        html = _error_page(
            "No Market Data",
            f"Connected to Angel One ({client.client_id}) but no OHLCV data returned.<br>"
            "Market may be closed or API rate limit reached. Try again in 60 seconds."
        )
        _cached_html = html
        _cached_csv = ""
        _cached_time = now
        return html, ""

    # ── Step 4: Run Best-Buy screening formula ────────────────────────────────
    screener = FOScreener(min_score=30, top_n=20)
    results_df = screener.run(ohlcv_data, use_threads=True)
    stats = screener.summary_stats(results_df)
    top_df = screener.top_picks(results_df, n=20)

    logger.success(
        f"Screened {stats.get('total_screened', 0)} stocks | "
        f"Strong Buy: {stats.get('strong_buy', 0)} | "
        f"Buy: {stats.get('buy', 0)}"
    )

    # ── Step 5: Generate output (in-memory, no file writes) ───────────────────
    _cached_html = generate_html_content(top_df, stats, status_banner=status_banner)
    _cached_csv = "\ufeff" + generate_csv_content(top_df)  # BOM for Excel
    _cached_time = now

    return _cached_html, _cached_csv


# ── Vercel WSGI/HTTP handler ──────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            html, csv_data = refresh_data()

            # CSV / Excel download
            if any(x in self.path for x in ["format=csv", "download=csv", "download=excel", ".csv"]):
                date_str = datetime.now().strftime("%Y-%m-%d")
                fname = f"NSE_FO_Scanner_{date_str}.csv"
                self.send_response(200)
                self.send_header("Content-type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.end_headers()
                self.wfile.write((csv_data or "").encode("utf-8"))

            # HTML dashboard
            else:
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))

        except Exception as e:
            logger.exception(f"Handler error: {e}")
            self.send_response(500)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Internal Server Error: {e}".encode("utf-8"))

    def log_message(self, format, *args):
        logger.info(f"HTTP {self.path} — {args}")


if __name__ == "__main__":
    # Local test run
    html, csv_str = refresh_data()
    print(f"HTML size: {len(html)} bytes | CSV rows: {csv_str.count(chr(10))}")
