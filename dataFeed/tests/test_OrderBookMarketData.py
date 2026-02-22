import json

import pytest

from dataFeed.struct.OrderBookMarketData import OrderBookMarketData


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

def test_instantiation_all_fields():
    ob = OrderBookMarketData(
        asset_id="abc123",
        timestamp=1700000000.0,
        bids=[(0.55, 100.0), (0.50, 200.0)],
        asks=[(0.60, 150.0), (0.65, 80.0)],
        best_bid=0.55,
        best_ask=0.60,
        mid_price=0.575,
        spread=0.05,
        bid_volume=300.0,
        ask_volume=230.0,
        weighted_mid=0.574,
        imbalance=0.132,
    )
    assert ob.asset_id == "abc123"
    assert ob.timestamp == 1700000000.0
    assert len(ob.bids) == 2
    assert len(ob.asks) == 2
    assert ob.best_bid == 0.55
    assert ob.best_ask == 0.60


def test_instantiation_required_fields_only():
    ob = OrderBookMarketData(asset_id="x", timestamp=1.0)
    assert ob.asset_id == "x"
    assert ob.timestamp == 1.0
    assert ob.bids == []
    assert ob.asks == []
    assert ob.best_bid is None
    assert ob.best_ask is None
    assert ob.mid_price is None
    assert ob.spread is None
    assert ob.bid_volume == 0.0
    assert ob.ask_volume == 0.0
    assert ob.weighted_mid is None
    assert ob.imbalance is None


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_to_dict_full():
    ob = OrderBookMarketData(
        asset_id="abc123",
        timestamp=1700000000.0,
        bids=[(0.55, 100.0), (0.50, 200.0)],
        asks=[(0.60, 150.0)],
        best_bid=0.55,
        best_ask=0.60,
        mid_price=0.575,
        spread=0.05,
        bid_volume=300.0,
        ask_volume=150.0,
        weighted_mid=0.574,
        imbalance=0.333,
    )
    d = ob.to_dict()
    assert d["asset_id"] == "abc123"
    assert d["timestamp"] == 1700000000.0
    assert d["bids"] == [[0.55, 100.0], [0.50, 200.0]]
    assert d["asks"] == [[0.60, 150.0]]
    assert d["best_bid"] == 0.55
    assert d["best_ask"] == 0.60
    assert d["mid_price"] == 0.575
    assert d["spread"] == 0.05
    assert d["bid_volume"] == 300.0
    assert d["ask_volume"] == 150.0
    assert d["weighted_mid"] == 0.574
    assert d["imbalance"] == 0.333


def test_to_dict_tuples_become_lists():
    ob = OrderBookMarketData(
        asset_id="x",
        timestamp=1.0,
        bids=[(0.5, 10.0)],
        asks=[(0.6, 20.0)],
    )
    d = ob.to_dict()
    assert d["bids"] == [[0.5, 10.0]]
    assert d["asks"] == [[0.6, 20.0]]
    assert isinstance(d["bids"][0], list)
    assert isinstance(d["asks"][0], list)


def test_to_dict_includes_none_fields():
    ob = OrderBookMarketData(asset_id="x", timestamp=1.0)
    d = ob.to_dict()
    assert d["best_bid"] is None
    assert d["best_ask"] is None
    assert d["mid_price"] is None
    assert d["spread"] is None
    assert d["weighted_mid"] is None
    assert d["imbalance"] is None


def test_to_dict_has_all_keys():
    ob = OrderBookMarketData(asset_id="x", timestamp=1.0)
    d = ob.to_dict()
    expected_keys = {
        "asset_id", "timestamp", "bids", "asks",
        "best_bid", "best_ask", "mid_price", "spread",
        "bid_volume", "ask_volume", "weighted_mid", "imbalance",
    }
    assert set(d.keys()) == expected_keys


def test_to_dict_empty_bids_asks():
    ob = OrderBookMarketData(asset_id="x", timestamp=1.0)
    d = ob.to_dict()
    assert d["bids"] == []
    assert d["asks"] == []


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------

def test_to_json_roundtrip():
    ob = OrderBookMarketData(
        asset_id="abc123",
        timestamp=1700000000.0,
        bids=[(0.55, 100.0)],
        asks=[(0.60, 150.0)],
        best_bid=0.55,
        best_ask=0.60,
    )
    parsed = json.loads(ob.to_json())
    assert parsed == ob.to_dict()


def test_to_json_minimal():
    ob = OrderBookMarketData(asset_id="x", timestamp=1.0)
    parsed = json.loads(ob.to_json())
    assert parsed["asset_id"] == "x"
    assert parsed["timestamp"] == 1.0
    assert parsed["bids"] == []
    assert parsed["asks"] == []


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------

def test_from_dict_full_roundtrip():
    original = OrderBookMarketData(
        asset_id="abc123",
        timestamp=1700000000.0,
        bids=[(0.55, 100.0), (0.50, 200.0)],
        asks=[(0.60, 150.0)],
        best_bid=0.55,
        best_ask=0.60,
        mid_price=0.575,
        spread=0.05,
        bid_volume=300.0,
        ask_volume=150.0,
        weighted_mid=0.574,
        imbalance=0.333,
    )
    reconstructed = OrderBookMarketData.from_dict(original.to_dict())
    assert reconstructed == original


def test_from_dict_minimal_roundtrip():
    original = OrderBookMarketData(asset_id="x", timestamp=1.0)
    reconstructed = OrderBookMarketData.from_dict(original.to_dict())
    assert reconstructed == original


def test_from_dict_converts_lists_to_tuples():
    d = {
        "asset_id": "x",
        "timestamp": 1.0,
        "bids": [[0.5, 10.0], [0.4, 20.0]],
        "asks": [[0.6, 5.0]],
    }
    ob = OrderBookMarketData.from_dict(d)
    assert ob.bids == [(0.5, 10.0), (0.4, 20.0)]
    assert ob.asks == [(0.6, 5.0)]
    assert isinstance(ob.bids[0], tuple)


def test_from_dict_with_string_numbers():
    d = {
        "asset_id": "abc",
        "timestamp": "1700000000.0",
        "bids": [["0.55", "100"]],
        "asks": [["0.60", "150"]],
        "best_bid": "0.55",
        "best_ask": "0.60",
        "mid_price": "0.575",
        "spread": "0.05",
        "bid_volume": "300.0",
        "ask_volume": "150.0",
        "weighted_mid": "0.574",
        "imbalance": "0.333",
    }
    ob = OrderBookMarketData.from_dict(d)
    assert ob.timestamp == 1700000000.0
    assert ob.best_bid == 0.55
    assert ob.bids == [(0.55, 100.0)]


def test_from_dict_without_optional_keys():
    d = {"asset_id": "x", "timestamp": 1.0}
    ob = OrderBookMarketData.from_dict(d)
    assert ob.bids == []
    assert ob.asks == []
    assert ob.best_bid is None
    assert ob.best_ask is None


def test_from_dict_with_explicit_none_values():
    d = {
        "asset_id": "x",
        "timestamp": 1.0,
        "bids": [],
        "asks": [],
        "best_bid": None,
        "best_ask": None,
        "mid_price": None,
        "spread": None,
        "weighted_mid": None,
        "imbalance": None,
    }
    ob = OrderBookMarketData.from_dict(d)
    assert ob.best_bid is None
    assert ob.best_ask is None
    assert ob.mid_price is None


def test_from_dict_json_roundtrip():
    """Ensure to_json -> json.loads -> from_dict produces the original."""
    original = OrderBookMarketData(
        asset_id="abc123",
        timestamp=1700000000.0,
        bids=[(0.55, 100.0)],
        asks=[(0.60, 150.0)],
        best_bid=0.55,
        best_ask=0.60,
        mid_price=0.575,
        spread=0.05,
        bid_volume=100.0,
        ask_volume=150.0,
    )
    json_str = original.to_json()
    reconstructed = OrderBookMarketData.from_dict(json.loads(json_str))
    assert reconstructed == original


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------

def test_equality():
    a = OrderBookMarketData(asset_id="x", timestamp=1.0, bids=[(0.5, 10.0)])
    b = OrderBookMarketData(asset_id="x", timestamp=1.0, bids=[(0.5, 10.0)])
    assert a == b


def test_inequality():
    a = OrderBookMarketData(asset_id="x", timestamp=1.0)
    b = OrderBookMarketData(asset_id="y", timestamp=1.0)
    assert a != b
