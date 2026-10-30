"""Technical indicators on top of pandas. All functions accept/return pd.Series aligned to input index."""
from __future__ import annotations

import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = 100 - 100 / (1 + rs)
    return out.where(avg_loss != 0, 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    dif = ema(close, fast) - ema(close, slow)
    dea = dif.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = dif - dea
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})


def kd(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> pd.DataFrame:
    """Taiwan-style KD (stochastic with exponential smoothing: K = 2/3 K_prev + 1/3 RSV)."""
    ll = low.rolling(n, min_periods=n).min()
    hh = high.rolling(n, min_periods=n).max()
    rsv = ((close - ll) / (hh - ll).replace(0, float("nan")) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / k_smooth, adjust=False).mean()
    d = k.ewm(alpha=1 / d_smooth, adjust=False).mean()
    return pd.DataFrame({"k": k, "d": d})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * std, "lower": mid - k * std})


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """df needs columns: date, open, high, low, close, volume. Returns df with indicator columns appended."""
    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    for n in (5, 10, 20, 60, 120):
        df[f"ma{n}"] = sma(close, n)
    df["rsi14"] = rsi(close, 14)
    m = macd(close)
    df["macd_dif"], df["macd_dea"], df["macd_hist"] = m["dif"], m["dea"], m["hist"]
    k = kd(df["high"].astype(float), df["low"].astype(float), close)
    df["k"], df["d"] = k["k"], k["d"]
    b = bollinger(close)
    df["bb_mid"], df["bb_upper"], df["bb_lower"] = b["mid"], b["upper"], b["lower"]
    df["vol_ma20"] = sma(df["volume"].astype(float), 20)
    return df
