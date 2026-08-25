"""
data_fetcher.py
===============
100% LIVE Angel One SmartAPI data feed.
NO hardcoded data, NO JSON files, NO mock prices, NO yfinance.

Flow:
  1. Token list → fetched live from Angel One scrip master API (fo_stocks.py)
  2. OHLCV candles → fetched live from Angel One getCandleData API
  3. LTP → fetched live from Angel One ltpData API
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from core.angel_client import AngelClient
from core.fo_stocks import fetch_fo_stock_list


class DataFetcher:
    """
    Fetches 100% live OHLCV + LTP data from Angel One SmartAPI.

    Parameters
    ----------
    client        : AngelClient  – authenticated Angel One SmartAPI client
    interval      : str          – candle interval (ONE_DAY recommended)
    history_days  : int          – days of history to load
    exchange      : str          – 'NSE'
    rate_delay    : float        – seconds between candle API calls (rate limit)
    max_stocks    : int          – max number of stocks to scan per run
    """

    def __init__(
        self,
        client: AngelClient,
        interval: str = "ONE_DAY",
        history_days: int = 100,
        exchange: str = "NSE",
        rate_delay: float = 0.4,
        max_stocks: int = 50,
    ):
        self.client = client
        self.interval = interval
        self.history_days = history_days
        self.exchange = exchange
        self.rate_delay = rate_delay
        self.max_stocks = max_stocks
        self._cache: Dict[str, pd.DataFrame] = {}

    def _date_range(self):
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=self.history_days + 5)
        return (
            from_dt.strftime("%Y-%m-%d %H:%M"),
            to_dt.strftime("%Y-%m-%d %H:%M"),
        )

    def fetch_ohlcv_single(self, symbol: str, token: str, retries: int = 2) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV candles for one stock from Angel One SmartAPI.
        Returns a cleaned DataFrame or None if data is unavailable.
        Includes retry logic for rate limit errors.
        """
        from_date, to_date = self._date_range()

        for attempt in range(retries + 1):
            raw = self.client.get_candles(
                exchange=self.exchange,
                symbol_token=str(token),
                interval=self.interval,
                from_date=from_date,
                to_date=to_date,
            )

            if raw:
                break
            
            # If rate limited and retries left, wait and try again
            if attempt < retries:
                wait_time = 2 * (attempt + 1)  # 2s, 4s progressive backoff
                logger.debug(f"Rate limit hit for {symbol}, retry {attempt+1}/{retries} after {wait_time}s...")
                time.sleep(wait_time)
        
        if not raw:
            return None

        try:
            df = pd.DataFrame(
                raw, columns=["date", "open", "high", "low", "close", "volume"]
            )
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df.dropna(inplace=True)
            return df if len(df) >= 20 else None
        except Exception as e:
            logger.warning(f"Parse error [{symbol}]: {e}")
            return None

    def fetch_ltp(self, symbol: str, token: str) -> Optional[float]:
        """Fetch current live LTP from Angel One SmartAPI."""
        try:
            resp = self.client.get_ltp(self.exchange, symbol + "-EQ", str(token))
            if resp.get("status") and resp.get("data"):
                ltp = resp["data"].get("ltp")
                logger.debug(f"LTP for {symbol}: ₹{ltp:.2f}")
                return ltp
        except Exception as e:
            logger.warning(f"LTP error [{symbol}]: {e}")
        return None

    def fetch_all_ohlcv(self) -> Dict[str, pd.DataFrame]:
        """
        Fetch live OHLCV data for NSE F&O stocks from Angel One SmartAPI.

        Steps:
          1. Fetch live F&O stock list + tokens from Angel One scrip master API
          2. Fetch OHLCV candles for each stock (with rate-limit delay)
          3. Patch the last close with live LTP from Angel One

        Returns dict[symbol -> DataFrame]
        """
        # Step 1: Get live F&O stock list from Angel One scrip master (no hardcode)
        stock_list = fetch_fo_stock_list()
        if not stock_list:
            logger.error("❌ Could not fetch F&O stock list from Angel One API!")
            return {}

        stocks = stock_list[: self.max_stocks]
        total = len(stocks)
        results: Dict[str, pd.DataFrame] = {}

        logger.info(
            f"📡 Angel One SmartAPI: Fetching LIVE data for {total} NSE F&O stocks..."
        )

        # Step 2: Fetch OHLCV candles stock by stock
        for i, s in enumerate(stocks, 1):
            sym = s["symbol"]
            tok = s["token"]

            df = self.fetch_ohlcv_single(sym, tok)
            if df is not None:
                results[sym] = df
                logger.debug(
                    f"[{i}/{total}] ✅ {sym}: {len(df)} candles | "
                    f"Last Close ₹{df['close'].iloc[-1]:.2f}"
                )
            else:
                logger.warning(f"[{i}/{total}] ⚠️  {sym}: No candle data")

            # Respect Angel One rate limit (~2-3 req/sec for candle API)
            time.sleep(self.rate_delay)

        # Step 3: Patch last close with live LTP for accurate current price
        logger.info("🔄 Patching live LTP into last candle close prices...")
        patched_count = 0
        for s in stocks:
            sym = s["symbol"]
            tok = s["token"]
            if sym not in results:
                continue
            
            old_close = results[sym]["close"].iloc[-1]
            ltp = self.fetch_ltp(sym, tok)
            
            if ltp and ltp > 0:
                results[sym].loc[results[sym].index[-1], "close"] = ltp
                patched_count += 1
                logger.debug(f"✓ {sym}: {old_close:.2f} → {ltp:.2f}")
            else:
                logger.warning(f"✗ {sym}: LTP fetch failed, using candle close {old_close:.2f}")
            
            time.sleep(0.05)

        logger.success(
            f"🟢 Angel One SmartAPI: {len(results)}/{total} stocks loaded with LIVE data | "
            f"LTP patched: {patched_count}/{len(results)}"
        )
        self._cache = results
        return results

    def get_cached(self) -> Dict[str, pd.DataFrame]:
        return self._cache
