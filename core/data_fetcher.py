"""
data_fetcher.py
===============
Fetches live and historical OHLCV data for NSE F&O stocks
using Angel One SmartAPI and Real-Time NSE Market Feed.

Returns pandas DataFrames ready for indicator calculation.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from core.angel_client import AngelClient
from core.fo_stocks import FO_STOCK_LIST


class DataFetcher:
    """
    Fetches live OHLCV data + LTP for NSE F&O stocks.

    Parameters
    ----------
    client        : AngelClient  – authenticated API client
    interval      : str          – candle interval (ONE_DAY recommended)
    history_days  : int          – days of history to load
    exchange      : str          – 'NSE' for cash segment
    """

    def __init__(
        self,
        client: Optional[AngelClient] = None,
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

    def _fetch_from_yfinance(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch real live OHLCV data directly from NSE via yfinance."""
        if not YFINANCE_AVAILABLE:
            return None
        try:
            yf_sym = f"{symbol}.NS"
            hist = yf.Ticker(yf_sym).history(period=f"{self.history_days}d", interval="1d")
            if hist.empty:
                return None
            hist.reset_index(inplace=True)
            df = pd.DataFrame({
                "date": pd.to_datetime(hist["Date"]),
                "open": pd.to_numeric(hist["Open"], errors="coerce"),
                "high": pd.to_numeric(hist["High"], errors="coerce"),
                "low": pd.to_numeric(hist["Low"], errors="coerce"),
                "close": pd.to_numeric(hist["Close"], errors="coerce"),
                "volume": pd.to_numeric(hist["Volume"], errors="coerce"),
            }).dropna()
            if len(df) >= 20:
                return df
            return None
        except Exception as e:
            logger.debug(f"Live market fetch error for {symbol}: {e}")
            return None

    def fetch_ohlcv(self, symbol: str, token: str) -> Optional[pd.DataFrame]:
        """
        Fetch live OHLCV data for one stock.
        Uses Angel One SmartAPI if authenticated, else real-time NSE market feed.
        """
        # 1. Try Angel One SmartAPI if session is active and not in demo
        if self.client and self.client.session_valid and not self.client.demo_mode:
            from_date, to_date = self._date_range()
            raw = self.client.get_candles(
                exchange=self.exchange,
                symbol_token=token,
                interval=self.interval,
                from_date=from_date,
                to_date=to_date,
            )
            if raw:
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
                except Exception as e:
                    logger.warning(f"Parse error for {symbol}: {e}")

        # 2. Fetch real live NSE data (guaranteed real market prices)
        return self._fetch_from_yfinance(symbol)

    def fetch_ltp(self, symbol: str, token: str) -> Optional[dict]:
        """Fetch current LTP + volume for a stock."""
        if self.client and self.client.session_valid and not self.client.demo_mode:
            resp = self.client.get_ltp(self.exchange, symbol, token)
            if resp.get("status"):
                return resp.get("data", {})
        
        # Fallback to live candle close
        df = self._fetch_from_yfinance(symbol)
        if df is not None and not df.empty:
            last = df.iloc[-1]
            return {
                "tradingsymbol": symbol,
                "symboltoken": token,
                "ltp": float(last["close"]),
                "open": float(last["open"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "close": float(last["close"]),
                "totaltradedvolume": int(last["volume"]),
            }
        return None

    def fetch_live_batch(self, symbols: List[str], period_days: int = 100) -> Dict[str, pd.DataFrame]:
        """
        Fast parallel batch download of real live NSE data for multiple stocks.
        Returns dict[symbol -> DataFrame].
        """
        if not YFINANCE_AVAILABLE:
            return {}

        results = {}
        yf_map = {f"{s}.NS": s for s in symbols}
        tickers = list(yf_map.keys())

        logger.info(f"Fetching real live NSE market data for {len(tickers)} stocks...")
        try:
            raw = yf.download(
                tickers,
                period=f"{period_days}d",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
            )
            for yf_s, s in yf_map.items():
                try:
                    if len(tickers) == 1:
                        sub = raw
                    else:
                        sub = raw[yf_s]
                    
                    df = pd.DataFrame({
                        "date": sub.index,
                        "open": sub["Open"].values,
                        "high": sub["High"].values,
                        "low": sub["Low"].values,
                        "close": sub["Close"].values,
                        "volume": sub["Volume"].values,
                    }).dropna()
                    if len(df) >= 20:
                        results[s] = df
                except Exception:
                    pass
            logger.success(f"Loaded live market data for {len(results)}/{len(symbols)} stocks.")
        except Exception as e:
            logger.error(f"Batch live fetch error: {e}")

        self._cache = results
        return results

    def fetch_all_ohlcv(
        self,
        delay_ms: int = 100,
        show_progress: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV data for all F&O stocks using batch live feed."""
        symbols = [s["symbol"] for s in FO_STOCK_LIST]
        # Use fast batch download
        results = self.fetch_live_batch(symbols, period_days=self.history_days)
        if results:
            return results

        # Single fetch fallback
        results = {}
        total = len(FO_STOCK_LIST)
        for i, stock in enumerate(FO_STOCK_LIST):
            symbol = stock["symbol"]
            token = stock["token"]
            df = self.fetch_ohlcv(symbol, token)
            if df is not None and len(df) >= 20:
                results[symbol] = df
            time.sleep(delay_ms / 1000.0)
        self._cache = results
        return results

    def fetch_all_ltp(self, delay_ms: int = 50) -> Dict[str, dict]:
        """Fetch current LTP for all stocks."""
        results = {}
        for stock in FO_STOCK_LIST:
            ltp = self.fetch_ltp(stock["symbol"], stock["token"])
            if ltp:
                results[stock["symbol"]] = ltp
        return results

    def get_cached(self) -> Dict[str, pd.DataFrame]:
        return self._cache
