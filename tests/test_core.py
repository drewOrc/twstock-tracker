"""Offline unit tests (no network). Run: python -m pytest -q"""
from datetime import date

import pandas as pd
import pytest

from app.datasources.mis import MISClient
from app.services import alerts
from app.services.indicators import compute_all, rsi, sma
from app.utils import parse_date_any, roc_compact_to_date, roc_to_date, to_float, to_int


def test_roc_dates():
    assert roc_to_date("115/10/01") == date(2026, 10, 1)
    assert roc_to_date("99/1/5") == date(2010, 1, 5)
    assert roc_compact_to_date("1151029") == date(2026, 10, 29)
    assert parse_date_any("2026/10/30") == date(2026, 10, 30)
    assert parse_date_any("20261030") == date(2026, 10, 30)
    assert roc_to_date("") is None


def test_number_parsing():
    assert to_float("2,490.00") == 2490.0
    assert to_float("+30.00") == 30.0
    assert to_float("--") is None
    assert to_float("X") is None
    assert to_int("20,666,092") == 20666092
    assert to_int("") is None


def test_mis_parse():
    msg = {
        "c": "2330", "n": "台積電", "ex": "tse", "z": "2370.0000", "o": "2380.0000", "h": "2380.0000",
        "l": "2360.0000", "y": "2415.0000", "v": "29562", "d": "20261030", "t": "13:30:00",
        "a": "2370.0000_2375.0000_", "b": "2365.0000_2360.0000_", "u": "2655.0000", "w": "2175.0000",
    }
    q = MISClient._parse(msg)
    assert q["code"] == "2330" and q["market"] == "TWSE"
    assert q["price"] == 2370.0 and q["prev_close"] == 2415.0
    assert q["change"] == -45.0 and q["change_pct"] == pytest.approx(-1.86, abs=0.01)
    assert q["bid"] == 2365.0 and q["ask"] == 2370.0
    assert q["trade_date"] == date(2026, 10, 30) and q["volume"] == 29562


def test_mis_parse_no_trade_uses_pz_then_midpoint():
    q = MISClient._parse({"c": "6488", "ex": "otc", "z": "-", "pz": "757.0000", "y": "750"})
    assert q["price"] == 757.0 and q["market"] == "TPEX"
    q2 = MISClient._parse({"c": "6488", "ex": "otc", "z": "-", "pz": "-", "a": "760.0_", "b": "758.0_", "y": "750"})
    assert q2["price"] == 759.0


def test_indicators():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert sma(s, 5).iloc[-1] == 8.0
    assert pd.isna(sma(s, 5).iloc[3])
    r = rsi(s, 3)
    assert r.iloc[-1] == 100.0  # monotonically rising
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=30).date,
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": range(100, 130),
            "volume": [1000] * 30,
        }
    )
    out = compute_all(df)
    assert {"ma5", "ma20", "rsi14", "k", "d", "macd_dif", "bb_upper", "vol_ma20"} <= set(out.columns)
    assert out["ma20"].iloc[-1] == pytest.approx(119.5)


def test_normalise_params():
    p = alerts.normalise_params("ma_cross", {"fast": "5", "slow": "20"})
    assert p == {"fast": 5, "slow": 20, "direction": "golden"}
    p = alerts.normalise_params("price_above", {"price": "2400"})
    assert p["price"] == 2400.0
    with pytest.raises(ValueError):
        alerts.normalise_params("price_above", {})
    with pytest.raises(ValueError):
        alerts.normalise_params("ma_cross", {"direction": "sideways"})
    with pytest.raises(ValueError):
        alerts.normalise_params("nope", {})


def test_rule_scopes():
    assert alerts.rule_scope("price_above") == alerts.INTRADAY
    assert alerts.rule_scope("institutional_streak") == alerts.DAILY
    for t, spec in alerts.RULE_TYPES.items():
        assert spec["scope"] in (alerts.INTRADAY, alerts.DAILY), t


def test_mi_index_sign_and_counts():
    from app.datasources.twse import _parse_counts, _sign

    assert _sign("<p style= color:red>+</p>") == 1
    assert _sign("<p style ='color:green'>-</p>") == -1
    assert _sign("X") is None
    assert _sign(" ") == 0
    c = _parse_counts([["上漲(漲停)", "3,381(16)", "232(7)"], ["下跌(跌停)", "11,943(85)", "737(3)"], ["持平", "753", "108"]])
    assert c["advance"] == 232 and c["limit_up"] == 7
    assert c["decline"] == 737 and c["limit_down"] == 3 and c["flat"] == 108


def test_sector_names():
    from app.services.industries import ETF_SECTOR, sector_name

    assert sector_name("2330", "24") == "半導體"
    assert sector_name("0050", None) == ETF_SECTOR
    assert sector_name("00878", None) == ETF_SECTOR
    assert sector_name("2330", None).startswith("未分類")
