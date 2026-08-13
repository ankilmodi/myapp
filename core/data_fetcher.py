"""
data_fetcher.py
===============
Fetches live and historical OHLCV data for all 209 F&O stocks
using the Angel One SmartAPI.

Returns pandas DataFrames ready for indicator calculation.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from core.angel_client import AngelClient
from core.fo_stocks import FO_STOCK_LIST


class DataFetcher:
    """
    Fetches OHLCV data + LTP for all 209 NSE F&O stocks.

    Parameters
    ----------
    client        : AngelClient  – authenticated API client
    interval      : str          – candle interval (ONE_DAY recommended)
    history_days  : int          – days of history to load
    exchange      : str          – 'NSE' for cash segment
    """

    def __init__(
        self,
        client: AngelClient,
        interval: str = "ONE_DAY",
        history_days: int = 100,
        exchange: str = "NSE",
    ):
        self.client = client
        self.interval = interval
        self.history_days = history_days
        self.exchange = exchange
        self._cache: Dict[str, pd.DataFrame] = {}

    # ──────────────────────────────────────────────
    # Date helpers
    # ──────────────────────────────────────────────
    def _date_range(self):
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=self.history_days + 5)
        return (
            from_dt.strftime("%Y-%m-%d %H:%M"),
            to_dt.strftime("%Y-%m-%d %H:%M"),
        )

    # ──────────────────────────────────────────────
    # Single Stock
    # ──────────────────────────────────────────────
    def fetch_ohlcv(self, symbol: str, token: str) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data for one stock.
        Returns DataFrame with columns: [date, open, high, low, close, volume]
        """
        from_date, to_date = self._date_range()
        raw = self.client.get_candles(
            exchange=self.exchange,
            symbol_token=token,
            interval=self.interval,
            from_date=from_date,
            to_date=to_date,
        )

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
            return df
        except Exception as e:
            logger.warning(f"Parse error for {symbol}: {e}")
            return None

    def fetch_ltp(self, symbol: str, token: str) -> Optional[dict]:
        """Fetch current LTP + volume for a stock."""
        resp = self.client.get_ltp(self.exchange, symbol, token)
        if resp.get("status"):
            return resp.get("data", {})
        return None

    # ──────────────────────────────────────────────
    # Bulk Fetch (all 209 stocks)
    # ──────────────────────────────────────────────
    def fetch_all_ohlcv(
        self,
        delay_ms: int = 300,
        show_progress: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV data for all 209 F&O stocks.

        Parameters
        ----------
        delay_ms     : int  – delay between API calls to avoid rate limiting
        show_progress: bool – print progress indicator

        Returns
        -------
        dict[symbol -> DataFrame]
        """
        results = {}
        total = len(FO_STOCK_LIST)

        logger.info(f"Fetching data for {total} F&O stocks...")

        for i, stock in enumerate(FO_STOCK_LIST):
            symbol = stock["symbol"]
            token = stock["token"]

            if show_progress:
                pct = int((i + 1) / total * 100)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(
                    f"\r  [{bar}] {pct:3d}% | {i+1:3d}/{total} | {symbol:<15}",
                    end="",
                    flush=True,
                )

            df = self.fetch_ohlcv(symbol, token)
            if df is not None and len(df) >= 30:
                results[symbol] = df
            else:
                logger.debug(f"Insufficient data for {symbol}, skipping.")

            time.sleep(delay_ms / 1000.0)

        print()  # newline after progress bar
        logger.success(f"Fetched data for {len(results)}/{total} stocks.")
        self._cache = results
        return results

    def fetch_all_ltp(self, delay_ms: int = 200) -> Dict[str, dict]:
        """Fetch current LTP for all stocks (fast, for live mode)."""
        results = {}
        for stock in FO_STOCK_LIST:
            ltp = self.fetch_ltp(stock["symbol"], stock["token"])
            if ltp:
                results[stock["symbol"]] = ltp
            time.sleep(delay_ms / 1000.0)
        return results

    def get_cached(self) -> Dict[str, pd.DataFrame]:
        """Return last fetched data (no new API call)."""
        return self._cache
