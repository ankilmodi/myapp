"""
data_fetcher.py
===============
Fetches live OHLCV data + LTP for all 209 NSE F&O stocks
exclusively using Angel One SmartAPI.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from loguru import logger

from core.angel_client import AngelClient
from core.fo_stocks import FO_STOCK_LIST


class DataFetcher:
    """
    Fetches live OHLCV data + LTP for NSE F&O stocks using Angel One SmartAPI.

    Parameters
    ----------
    client        : AngelClient  – authenticated Angel One SmartAPI client
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

    def _date_range(self):
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=self.history_days + 5)
        return (
            from_dt.strftime("%Y-%m-%d %H:%M"),
            to_dt.strftime("%Y-%m-%d %H:%M"),
        )

    def fetch_ohlcv(self, symbol: str, token: str) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data for one stock using Angel One SmartAPI.
        Returns DataFrame with columns: [date, open, high, low, close, volume]
        """
        if not self.client:
            return None

        from_date, to_date = self._date_range()
        raw = self.client.get_candles(
            exchange=self.exchange,
            symbol_token=str(token),
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
            if len(df) >= 20:
                return df
            return None
        except Exception as e:
            logger.warning(f"Parse error for {symbol}: {e}")
            return None

    def fetch_ltp(self, symbol: str, token: str) -> Optional[dict]:
        """Fetch current live LTP + volume for a stock using Angel One SmartAPI."""
        if not self.client:
            return None
        resp = self.client.get_ltp(self.exchange, symbol, str(token))
        if resp.get("status"):
            return resp.get("data", {})
        return None

    def fetch_all_ohlcv(
        self,
        stocks: Optional[List[dict]] = None,
        max_workers: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV data using Angel One SmartAPI in parallel threads.
        Returns dict[symbol -> DataFrame].
        """
        target_stocks = stocks if stocks is not None else FO_STOCK_LIST
        results = {}
        total = len(target_stocks)

        logger.info(f"Fetching Angel One Live API data for {total} stocks...")

        def fetch_single(s):
            sym = s["symbol"]
            tok = s["token"]
            df = self.fetch_ohlcv(sym, tok)
            if df is not None and len(df) >= 20:
                return sym, df
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_single, s) for s in target_stocks]
            for f in futures:
                res = f.result()
                if res:
                    results[res[0]] = res[1]

        logger.success(f"Angel One SmartAPI: Fetched {len(results)}/{total} stocks successfully.")
        self._cache = results
        return results

    def fetch_all_ltp(self, stocks: Optional[List[dict]] = None) -> Dict[str, dict]:
        """Fetch current LTP for all stocks via Angel One SmartAPI."""
        target_stocks = stocks if stocks is not None else FO_STOCK_LIST
        results = {}
        for s in target_stocks:
            ltp = self.fetch_ltp(s["symbol"], s["token"])
            if ltp:
                results[s["symbol"]] = ltp
        return results

    def get_cached(self) -> Dict[str, pd.DataFrame]:
        return self._cache
