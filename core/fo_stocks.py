"""
fo_stocks.py
============
Fetches LIVE NSE F&O stock list + tokens directly from Angel One scrip master API.
NO hardcoded data. Everything fetched live at runtime.

Strategy:
  1. Fetch scrip master from Angel One API (public URL, no auth)
  2. Extract F&O-eligible symbols from NFO segment (FUTSTK instrument type)
  3. Cross-reference with NSE cash segment to get correct equity tokens
"""

import requests
from loguru import logger
from typing import List, Dict

# Angel One official public scrip master URL (no authentication required)
ANGEL_SCRIP_MASTER_URL = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
)

_fo_stock_list: List[Dict] = []
_token_map: Dict[str, str] = {}
_loaded = False


def fetch_fo_stock_list(force_refresh: bool = False) -> List[Dict]:
    """
    Fetches live NSE F&O stock list from Angel One scrip master API.

    Steps:
      1. Download scrip master JSON from Angel One API
      2. Find all unique F&O stock symbols (from NFO FUTSTK segment)
      3. Map each symbol to its NSE cash-segment token (for candle/LTP API calls)

    Returns list of dicts: [{"symbol": ..., "token": ..., "name": ..., "lotsize": ...}]
    Cached in memory after first fetch.
    """
    global _fo_stock_list, _token_map, _loaded

    if _loaded and _fo_stock_list and not force_refresh:
        return _fo_stock_list

    logger.info("🌐 Fetching live NSE F&O stock list from Angel One scrip master API...")

    try:
        resp = requests.get(ANGEL_SCRIP_MASTER_URL, timeout=30)
        resp.raise_for_status()
        all_scrips = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch Angel One scrip master: {e}")
        return []

    # ── Step 1: Collect F&O symbols + lot sizes from NFO FUTSTK segment ──────
    # NFO futures segment has the authoritative list of F&O eligible stocks
    fo_meta: Dict[str, dict] = {}  # symbol -> {lotsize, name}
    for item in all_scrips:
        if item.get("exch_seg") != "NFO":
            continue
        if item.get("instrumenttype") != "FUTSTK":
            continue
        sym = item.get("name", "").strip()       # name = underlying stock symbol
        lotsize = item.get("lotsize", "1")
        if not sym:
            continue
        if sym not in fo_meta:
            try:
                ls = int(lotsize)
            except (ValueError, TypeError):
                ls = 1
            fo_meta[sym] = {"lotsize": ls, "name": sym}

    logger.info(f"Found {len(fo_meta)} F&O eligible symbols in NFO segment")

    # ── Step 2: Get NSE cash-segment tokens for each F&O symbol ──────────────
    nse_tokens: Dict[str, dict] = {}  # symbol -> {token, full_name}
    for item in all_scrips:
        if item.get("exch_seg") != "NSE":
            continue
        if item.get("expiry", ""):
            continue
        sym = item.get("symbol", "")
        if not sym.endswith("-EQ"):
            continue
        clean = sym.replace("-EQ", "")
        if clean in fo_meta and clean not in nse_tokens:
            nse_tokens[clean] = {
                "token": item.get("token", ""),
                "full_name": item.get("name", clean),
            }

    # ── Step 3: Build final list (skip test/dummy instruments) ───────────────
    stocks = []
    for sym, meta in sorted(fo_meta.items()):
        # Skip NSE test instruments (e.g. 011NSETEST, 021NSETEST)
        if "NSETEST" in sym or sym.startswith("0") and sym[0].isdigit():
            continue
        nse_info = nse_tokens.get(sym)
        if not nse_info or not nse_info["token"]:
            continue
        stocks.append({
            "symbol": sym,
            "token": nse_info["token"],
            "name": nse_info["full_name"] or sym,
            "lotsize": meta["lotsize"],
        })

    _fo_stock_list = stocks
    _token_map = {s["symbol"]: s["token"] for s in stocks}
    _loaded = True

    logger.success(f"✅ {len(stocks)} NSE F&O stocks loaded live from Angel One API")
    return stocks


def get_token_map() -> Dict[str, str]:
    """Returns dict: symbol -> NSE cash-segment token"""
    if not _loaded:
        fetch_fo_stock_list()
    return _token_map
