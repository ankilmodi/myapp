"""
screener.py
===========
Runs the Best-Buy formula across all 209 F&O stocks
and returns a ranked DataFrame.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import pandas as pd
from loguru import logger

from core.fo_stocks import FO_STOCK_LIST
from scanner.best_buy_formula import calculate_score


class FOScreener:
    """
    Runs the Best-Buy scoring formula on all 209 F&O stocks.

    Usage:
        screener = FOScreener()
        results_df = screener.run(ohlcv_data)
        top_buys = screener.top_picks(results_df, n=20)
    """

    def __init__(self, min_score: float = 40.0, top_n: int = 20):
        self.min_score = min_score
        self.top_n = top_n
        # OI data store (symbol -> {prev_oi, curr_oi})
        self._oi_store: Dict[str, dict] = {}

    def update_oi(self, oi_data: Dict[str, dict]):
        """Update OI data (from live feed or mock)."""
        self._oi_store = oi_data

    def _score_one(self, symbol: str, df: pd.DataFrame) -> dict:
        """Score a single stock."""
        oi = self._oi_store.get(symbol, {"prev": 0, "curr": 0})
        return calculate_score(
            symbol=symbol,
            df=df,
            prev_oi=oi.get("prev", 0),
            curr_oi=oi.get("curr", 0),
        )

    def run(
        self,
        ohlcv_data: Dict[str, pd.DataFrame],
        use_threads: bool = True,
        max_workers: int = 8,
    ) -> pd.DataFrame:
        """
        Score all stocks and return ranked DataFrame.

        Parameters
        ----------
        ohlcv_data   : dict[symbol -> DataFrame]
        use_threads  : bool – use ThreadPoolExecutor for speed
        max_workers  : int  – number of threads

        Returns
        -------
        pd.DataFrame sorted by score descending
        """
        results = []

        if use_threads:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._score_one, sym, df): sym
                    for sym, df in ohlcv_data.items()
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        sym = futures[future]
                        logger.warning(f"Thread error for {sym}: {e}")
        else:
            for sym, df in ohlcv_data.items():
                results.append(self._score_one(sym, df))

        if not results:
            logger.warning("No results to display!")
            return pd.DataFrame()

        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values("score", ascending=False)
        df_results = df_results.reset_index(drop=True)
        df_results.index += 1  # 1-based rank

        logger.success(
            f"Screened {len(df_results)} stocks | "
            f"Best: {df_results.iloc[0]['symbol']} ({df_results.iloc[0]['score']:.1f}/100)"
        )
        return df_results

    def top_picks(self, df: pd.DataFrame, n: int = None) -> pd.DataFrame:
        """Return top N best-buy picks above min_score."""
        n = n or self.top_n
        filtered = df[df["score"] >= self.min_score]
        return filtered.head(n)

    def buy_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return only STRONG BUY and BUY signals."""
        return df[df["score"] >= 60].copy()

    def summary_stats(self, df: pd.DataFrame) -> dict:
        """Return summary statistics for a screener run."""
        if df.empty:
            return {}
        return {
            "total_screened": len(df),
            "strong_buy": len(df[df["score"] >= 80]),
            "buy": len(df[(df["score"] >= 60) & (df["score"] < 80)]),
            "watch": len(df[(df["score"] >= 40) & (df["score"] < 60)]),
            "avoid": len(df[df["score"] < 40]),
            "avg_score": round(df["score"].mean(), 1),
            "top_symbol": df.iloc[0]["symbol"] if not df.empty else "N/A",
            "top_score": df.iloc[0]["score"] if not df.empty else 0,
        }
