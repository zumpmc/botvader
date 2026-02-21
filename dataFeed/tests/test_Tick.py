import json

import pytest

from dataFeed.struct.Tick import Tick


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

def test_tick_instantiation_all_fields():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="coinbase", size=0.001, side="BUY")
    assert tick.timestamp == 1700000000.0
    assert tick.price == 68500.25
    assert tick.source == "coinbase"
    assert tick.size == 0.001
    assert tick.side == "BUY"


def test_tick_instantiation_required_fields_only():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="binance")
    assert tick.timestamp == 1700000000.0
    assert tick.price == 68500.25
    assert tick.source == "binance"
    assert tick.size is None
    assert tick.side is None


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_to_dict_full():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="coinbase", size=0.001, side="BUY")
    d = tick.to_dict()
    assert d == {
        "timestamp": 1700000000.0,
        "price": 68500.25,
        "source": "coinbase",
        "size": 0.001,
        "side": "BUY",
    }


def test_to_dict_includes_none_fields():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="binance")
    d = tick.to_dict()
    assert "size" in d
    assert "side" in d
    assert d["size"] is None
    assert d["side"] is None


def test_to_dict_has_all_keys():
    tick = Tick(timestamp=1.0, price=2.0, source="x")
    d = tick.to_dict()
    assert set(d.keys()) == {"timestamp", "price", "source", "size", "side"}


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------

def test_to_json_full():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="coinbase", size=0.001, side="BUY")
    parsed = json.loads(tick.to_json())
    assert parsed == tick.to_dict()


def test_to_json_minimal():
    tick = Tick(timestamp=1700000000.0, price=68500.25, source="kraken")
    parsed = json.loads(tick.to_json())
    assert parsed["timestamp"] == 1700000000.0
    assert parsed["price"] == 68500.25
    assert parsed["source"] == "kraken"
    assert parsed["size"] is None
    assert parsed["side"] is None


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------

def test_from_dict_full_roundtrip():
    original = Tick(timestamp=1700000000.0, price=68500.25, source="coinbase", size=0.001, side="BUY")
    reconstructed = Tick.from_dict(original.to_dict())
    assert reconstructed == original


def test_from_dict_minimal_roundtrip():
    original = Tick(timestamp=1700000000.0, price=68500.25, source="binance")
    reconstructed = Tick.from_dict(original.to_dict())
    assert reconstructed == original


def test_from_dict_with_string_numbers():
    d = {"timestamp": "1700000000.0", "price": "68500.25", "source": "test", "size": "0.5", "side": "SELL"}
    tick = Tick.from_dict(d)
    assert tick.timestamp == 1700000000.0
    assert tick.price == 68500.25
    assert tick.size == 0.5
    assert tick.side == "SELL"


def test_from_dict_without_optional_keys():
    d = {"timestamp": 1700000000.0, "price": 68500.25, "source": "kraken"}
    tick = Tick.from_dict(d)
    assert tick.size is None
    assert tick.side is None


def test_from_dict_with_explicit_none_values():
    d = {"timestamp": 1700000000.0, "price": 68500.25, "source": "binance", "size": None, "side": None}
    tick = Tick.from_dict(d)
    assert tick.size is None
    assert tick.side is None


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------

def test_tick_equality():
    a = Tick(timestamp=1.0, price=100.0, source="x", size=0.5, side="BUY")
    b = Tick(timestamp=1.0, price=100.0, source="x", size=0.5, side="BUY")
    assert a == b


def test_tick_inequality():
    a = Tick(timestamp=1.0, price=100.0, source="x")
    b = Tick(timestamp=1.0, price=200.0, source="x")
    assert a != b
