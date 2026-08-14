"""
best_buy_formula.py
===================
🏆 BEST BUY COMPOSITE SCORING FORMULA (Max: 100 Points)

Factor Breakdown:
┌─────────────────────────────────┬────────┬──────────────────────────────────────────┐
│ Factor                          │ Weight │ Logic                                    │
├─────────────────────────────────┼────────┼──────────────────────────────────────────┤
│ RSI(14) Momentum                │  20    │ RSI in 40-60 bullish momentum zone       │
│ MACD Crossover                  │  20    │ MACD > Signal + Histogram rising         │
│ EMA Trend (20/50/200)           │  15    │ Price > EMA20 > EMA50 > EMA200           │
│ Volume Surge                    │  15    │ Volume > 1.5× 20-day average             │
│ OI Build-Up (F&O)               │  15    │ OI rising + Price rising = Long Buildup  │
│ Supertrend (7,3)                │  10    │ Supertrend bullish (direction=1)         │
│ Near 52-Week High               │   5    │ Price within 15% of 52W high             │
├─────────────────────────────────┼────────┼──────────────────────────────────────────┤
│ TOTAL                           │ 100    │ Higher = Stronger Buy Signal             │
└─────────────────────────────────┴────────┴──────────────────────────────────────────┘

Score Interpretation:
  80–100 : 🔥 STRONG BUY
  60–79  : ✅ BUY
  40–59  : ⚠️  WATCH
  0–39   : ❌ AVOID
"""

import pandas as pd
from loguru import logger

from core.indicators import (
    atr,
    ema_trend_score,
    macd,
    near_52w_high,
    oi_buildup_score,
    rsi,
    supertrend,
    volume_surge,
)


# ─────────────────────────────────────────────────────────
# WEIGHTS  (must sum to 100)
# ─────────────────────────────────────────────────────────
WEIGHTS = {
    "rsi_momentum": 20,
    "macd_crossover": 20,
    "ema_trend": 15,
    "volume_surge": 15,
    "oi_buildup": 15,
    "supertrend": 10,
    "near_52w_high": 5,
}

assert sum(WEIGHTS.values()) == 100, "Weights must sum to 100!"


def _rsi_score(rsi_val: float) -> float:
    """
    RSI Scoring (max 1.0):
      RSI 45-55  → 1.0  (ideal momentum sweet spot)
      RSI 40-45 or 55-60 → 0.7
      RSI 35-40 or 60-65 → 0.4  (approaching oversold/overbought)
      RSI < 35 or > 65   → 0.0  (too extreme)
    """
    if 45 <= rsi_val <= 55:
        return 1.0
    elif 40 <= rsi_val < 45 or 55 < rsi_val <= 60:
        return 0.7
    elif 35 <= rsi_val < 40 or 60 < rsi_val <= 65:
        return 0.4
    elif rsi_val < 35:
        return 0.2  # Oversold – could bounce, partial credit
    else:
        return 0.0  # Overbought – avoid


def calculate_score(
    symbol: str,
    df: pd.DataFrame,
    prev_oi: float = 0.0,
    curr_oi: float = 0.0,
) -> dict:
    """
    Calculate composite Best-Buy score for a single stock.

    Parameters
    ----------
    symbol   : str          – stock symbol
    df       : pd.DataFrame – OHLCV data (min 30 rows recommended)
    prev_oi  : float        – previous day's Open Interest
    curr_oi  : float        – current Open Interest

    Returns
    -------
    dict with keys:
      symbol, score, grade, breakdown, indicators
    """
    if df is None or len(df) < 20:
        return _empty_result(symbol, "Insufficient data")

    breakdown = {}
    indicators_detail = {}

    try:
        # ── 1. RSI Momentum (20 pts) ──────────────────────────
        rsi_val = rsi(df)
        rsi_pts = _rsi_score(rsi_val) * WEIGHTS["rsi_momentum"]
        breakdown["RSI(14)"] = round(rsi_pts, 1)
        indicators_detail["rsi"] = rsi_val

        # ── 2. MACD Crossover (20 pts) ───────────────────────
        macd_data = macd(df)
        macd_pts = WEIGHTS["macd_crossover"] if macd_data["bullish_crossover"] else (
            WEIGHTS["macd_crossover"] * 0.4 if macd_data["histogram"] > 0 else 0
        )
        breakdown["MACD"] = round(macd_pts, 1)
        indicators_detail["macd"] = macd_data

        # ── 3. EMA Trend (15 pts) ────────────────────────────
        ema_frac = ema_trend_score(df)
        ema_pts = ema_frac * WEIGHTS["ema_trend"]
        breakdown["EMA Trend"] = round(ema_pts, 1)
        indicators_detail["ema_trend_fraction"] = round(ema_frac, 2)

        # ── 4. Volume Surge (15 pts) ─────────────────────────
        vol_data = volume_surge(df)
        if vol_data["surge"]:
            vol_pts = WEIGHTS["volume_surge"]
        elif vol_data["ratio"] >= 1.2:
            vol_pts = WEIGHTS["volume_surge"] * 0.6
        else:
            vol_pts = 0.0
        breakdown["Volume Surge"] = round(vol_pts, 1)
        indicators_detail["volume_ratio"] = vol_data["ratio"]

        # ── 5. OI Build-Up (15 pts) ──────────────────────────
        prev_price = df["close"].iloc[-2] if len(df) > 1 else df["close"].iloc[-1]
        curr_price = df["close"].iloc[-1]
        oi_data = oi_buildup_score(prev_oi, curr_oi, prev_price, curr_price)
        oi_pts = oi_data["score"] * WEIGHTS["oi_buildup"]
        breakdown["OI Build-Up"] = round(oi_pts, 1)
        indicators_detail["oi_signal"] = oi_data["signal"]

        # ── 6. Supertrend (10 pts) ───────────────────────────
        st_data = supertrend(df)
        st_pts = WEIGHTS["supertrend"] if st_data["bullish"] else 0.0
        breakdown["Supertrend"] = round(st_pts, 1)
        indicators_detail["supertrend"] = "Bullish ↑" if st_data["bullish"] else "Bearish ↓"

        # ── 7. Near 52-Week High (5 pts) ─────────────────────
        high_data = near_52w_high(df)
        if high_data["near"]:
            high_pts = WEIGHTS["near_52w_high"]
        elif high_data["diff_pct"] <= 25:
            high_pts = WEIGHTS["near_52w_high"] * 0.4
        else:
            high_pts = 0.0
        breakdown["52W High"] = round(high_pts, 1)
        indicators_detail["diff_from_52w_high"] = high_data["diff_pct"]

    except Exception as e:
        logger.warning(f"Scoring error for {symbol}: {e}")
        return _empty_result(symbol, str(e))

    # ── Final Score ───────────────────────────────────────
    total_score = sum(breakdown.values())
    total_score = round(min(total_score, 100), 1)

    # ── Additional Columns Calculation (Excel representation) ──
    # 1. SMC Signal
    vol_ratio = vol_data.get("ratio", 1.0)
    oi_signal = oi_data.get("signal", "")
    macd_bullish = macd_data.get("bullish_crossover", False)
    if vol_ratio >= 1.2 or oi_signal in ["Long Build-Up", "Short Covering"] or macd_bullish:
        smc_signal = "INSTITUTIONAL BUY FLOW"
    else:
        smc_signal = "RETAIL CONSOLIDATION"

    # 2. Action Verdict
    st_bullish = st_data.get("bullish", False)
    if rsi_val > 75:
        action_verdict = "SELL / BOOK PROFIT"
    elif 70 <= rsi_val <= 75:
        action_verdict = "HOLD"
    elif rsi_val < 45:
        action_verdict = "SELL / BOOK PROFIT"
    else: # RSI is between 45 and 70
        if st_bullish and macd_bullish and total_score >= 50:
            action_verdict = "BUY / ACCUMULATE"
        elif not st_bullish or not macd_bullish:
            action_verdict = "SELL / BOOK PROFIT"
        else:
            action_verdict = "HOLD"

    # 3. ATR
    atr_val = atr(df)

    # 4. Stop Loss & Targets
    st_val = st_data.get("value", 0.0)
    if st_bullish and st_val > 0 and st_val < curr_price:
        stop_loss = st_val
    else:
        stop_loss = round(curr_price - 1.5 * atr_val, 2)

    target_1 = round(curr_price + atr_val, 2)
    target_2 = round(curr_price + 2 * atr_val, 2)
    target_3 = round(curr_price + 3 * atr_val, 2)

    return {
        "symbol": symbol,
        "score": total_score,
        "grade": _grade(total_score),
        "signal": _signal(total_score),
        "ltp": round(curr_price, 2),
        "rsi": rsi_val,
        "smc_signal": smc_signal,
        "action_verdict": action_verdict,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "target_3": target_3,
        "breakdown": breakdown,
        "indicators": indicators_detail,
        "error": None,
    }


def _grade(score: float) -> str:
    if score >= 80:
        return "A+"
    elif score >= 70:
        return "A"
    elif score >= 60:
        return "B+"
    elif score >= 50:
        return "B"
    elif score >= 40:
        return "C"
    else:
        return "D"


def _signal(score: float) -> str:
    if score >= 80:
        return "🔥 STRONG BUY"
    elif score >= 60:
        return "✅ BUY"
    elif score >= 40:
        return "⚠️  WATCH"
    else:
        return "❌ AVOID"


def _empty_result(symbol: str, error: str) -> dict:
    return {
        "symbol": symbol,
        "score": 0.0,
        "grade": "N/A",
        "signal": "❌ NO DATA",
        "ltp": 0.0,
        "rsi": 0.0,
        "smc_signal": "N/A",
        "action_verdict": "HOLD",
        "stop_loss": 0.0,
        "target_1": 0.0,
        "target_2": 0.0,
        "target_3": 0.0,
        "breakdown": {},
        "indicators": {},
        "error": error,
    }
