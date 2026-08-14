"""
indicators.py
=============
Technical indicator calculations for the Best-Buy Formula.

All functions accept a pandas DataFrame with columns:
    [date, open, high, low, close, volume]

Returns: float values or boolean signals
"""

import numpy as np
import pandas as pd
from loguru import logger


# ─────────────────────────────────────────
# RSI – Relative Strength Index (14)
# ─────────────────────────────────────────
def rsi(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate RSI(14). Returns current RSI value (0-100).

    Bullish zone for Best Buy: 40 - 60 (momentum building, not overbought)
    """
    if len(df) < period + 1:
        return 50.0
    close = df["close"].values.astype(float)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])

    for i in range(period, len(gain)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ─────────────────────────────────────────
# EMA – Exponential Moving Average
# ─────────────────────────────────────────
def ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate EMA for a given period."""
    return series.ewm(span=period, adjust=False).mean()


def ema_trend_score(df: pd.DataFrame) -> float:
    """
    Check if price is in a healthy uptrend:
      Price > EMA20 > EMA50 > EMA200
    Returns fraction of conditions met (0.0 – 1.0)
    """
    if len(df) < 200:
        return 0.0

    close = df["close"]
    e20 = ema(close, 20).iloc[-1]
    e50 = ema(close, 50).iloc[-1]
    e200 = ema(close, 200).iloc[-1]
    price = close.iloc[-1]

    conditions = [
        price > e20,
        e20 > e50,
        e50 > e200,
        price > e200,
    ]
    return sum(conditions) / len(conditions)


# ─────────────────────────────────────────
# MACD – Moving Average Convergence Divergence
# ─────────────────────────────────────────
def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    Calculate MACD.

    Returns dict:
      macd_line, signal_line, histogram, bullish_crossover (bool)
    """
    if len(df) < slow + signal:
        return {"macd_line": 0, "signal_line": 0, "histogram": 0, "bullish_crossover": False}

    close = df["close"]
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    current_hist = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0
    macd_val = macd_line.iloc[-1]
    sig_val = signal_line.iloc[-1]

    # Bullish crossover: MACD crossed above signal recently AND histogram rising
    bullish_crossover = (
        macd_val > sig_val and
        current_hist > 0 and
        current_hist > prev_hist
    )

    return {
        "macd_line": round(macd_val, 4),
        "signal_line": round(sig_val, 4),
        "histogram": round(current_hist, 4),
        "bullish_crossover": bullish_crossover,
    }


# ─────────────────────────────────────────
# SUPERTREND
# ─────────────────────────────────────────
def supertrend(df: pd.DataFrame, period: int = 7, multiplier: float = 3.0) -> dict:
    """
    Calculate Supertrend indicator.

    Returns:
      direction: 1 (bullish) or -1 (bearish)
      value    : current supertrend level
    """
    if len(df) < period + 1:
        return {"direction": -1, "value": 0.0, "bullish": False}

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # Average True Range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr = np.zeros(len(close))
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, len(close)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend_val = np.zeros(len(close))
    direction = np.ones(len(close))

    for i in range(1, len(close)):
        if atr[i] == 0:
            continue
        # Upper band
        if upper_band[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
            upper_band[i] = upper_band[i]
        else:
            upper_band[i] = upper_band[i - 1]
        # Lower band
        if lower_band[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
            lower_band[i] = lower_band[i]
        else:
            lower_band[i] = lower_band[i - 1]
        # Direction
        if supertrend_val[i - 1] == upper_band[i - 1]:
            if close[i] <= upper_band[i]:
                supertrend_val[i] = upper_band[i]
                direction[i] = -1
            else:
                supertrend_val[i] = lower_band[i]
                direction[i] = 1
        else:
            if close[i] >= lower_band[i]:
                supertrend_val[i] = lower_band[i]
                direction[i] = 1
            else:
                supertrend_val[i] = upper_band[i]
                direction[i] = -1

    current_dir = int(direction[-1])
    return {
        "direction": current_dir,
        "value": round(supertrend_val[-1], 2),
        "bullish": current_dir == 1,
    }


# ─────────────────────────────────────────
# VOLUME SURGE
# ─────────────────────────────────────────
def volume_surge(df: pd.DataFrame, avg_period: int = 20, threshold: float = 1.5) -> dict:
    """
    Check if today's volume is greater than threshold × average volume.

    Returns: surge_ratio and whether surge is detected
    """
    if len(df) < avg_period + 1:
        return {"ratio": 1.0, "surge": False}

    avg_vol = df["volume"].iloc[-(avg_period + 1):-1].mean()
    current_vol = df["volume"].iloc[-1]
    ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    return {
        "ratio": round(ratio, 2),
        "surge": ratio >= threshold,
    }


# ─────────────────────────────────────────
# 52-WEEK HIGH PROXIMITY
# ─────────────────────────────────────────
def near_52w_high(df: pd.DataFrame, proximity_pct: float = 15.0) -> dict:
    """
    Check if current price is within `proximity_pct`% of 52-week high.
    Uses available data (up to 252 trading days).
    """
    lookback = min(252, len(df))
    high_52w = df["high"].iloc[-lookback:].max()
    current = df["close"].iloc[-1]
    diff_pct = ((high_52w - current) / high_52w) * 100 if high_52w > 0 else 100

    return {
        "52w_high": round(high_52w, 2),
        "current": round(current, 2),
        "diff_pct": round(diff_pct, 2),
        "near": diff_pct <= proximity_pct,
    }


# ─────────────────────────────────────────
# OI BUILD-UP (F&O Specific)
# ─────────────────────────────────────────
def oi_buildup_score(prev_oi: float, curr_oi: float, prev_price: float, curr_price: float) -> dict:
    """
    OI Build-Up Analysis for F&O stocks:
      Long build-up: OI ↑ + Price ↑  → Bullish  (score: 1.0)
      Short covering: OI ↓ + Price ↑ → Mildly bullish (score: 0.5)
      Short build-up: OI ↑ + Price ↓ → Bearish  (score: 0.0)
      Long unwinding: OI ↓ + Price ↓ → Bearish  (score: 0.0)

    In demo mode (no OI data), returns neutral score.
    """
    oi_up = curr_oi > prev_oi
    price_up = curr_price > prev_price

    if oi_up and price_up:
        signal = "Long Build-Up"
        score = 1.0
    elif not oi_up and price_up:
        signal = "Short Covering"
        score = 0.5
    elif oi_up and not price_up:
        signal = "Short Build-Up"
        score = 0.0
    else:
        signal = "Long Unwinding"
        score = 0.0

    return {"signal": signal, "score": score, "oi_up": oi_up, "price_up": price_up}


# ─────────────────────────────────────────
# ATR – Average True Range (14)
# ─────────────────────────────────────────
def atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate ATR(14). Returns current ATR value.
    Used for Stop Loss and Target calculations.
    """
    if len(df) < period + 1:
        # Fallback to 2% of current price if data is insufficient
        return round(df["close"].iloc[-1] * 0.02, 2)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr_vals = np.zeros(len(close))
    atr_vals[period] = np.mean(tr[:period])
    for i in range(period + 1, len(close)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i - 1]) / period
    return round(atr_vals[-1], 2)

