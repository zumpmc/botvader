from __future__ import annotations

import threading
from typing import List, Optional

import pytest

from dataFeed.struct.OrderBookMarketData import OrderBookMarketData
from dataFeed.struct.OrderBookData import OrderBookData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snap(
    asset_id: str = "abc123",
    timestamp: float = 1700000000.0,
    bids: Optional[List] = None,
    asks: Optional[List] = None,
) -> OrderBookMarketData:
    return OrderBookMarketData(
        asset_id=asset_id,
        timestamp=timestamp,
        bids=bids or [(0.55, 100.0)],
        asks=asks or [(0.60, 150.0)],
        best_bid=0.55,
        best_ask=0.60,
    )


# ---------------------------------------------------------------------------
# export — empty
# ---------------------------------------------------------------------------

def test_export_empty():
    md = OrderBookData()
    result = md.export()
    assert result == []


# ---------------------------------------------------------------------------
# record + export
# ---------------------------------------------------------------------------

def test_record_and_export_single():
    md = OrderBookData()
    snap = _make_snap()
    md.record(snap)
    result = md.export()
    assert len(result) == 1
    assert result[0]["asset_id"] == "abc123"
    assert result[0]["best_bid"] == 0.55


def test_record_and_export_multiple():
    md = OrderBookData()
    md.record(_make_snap(timestamp=1.0))
    md.record(_make_snap(timestamp=2.0))
    md.record(_make_snap(timestamp=3.0))
    result = md.export()
    assert len(result) == 3
    assert [d["timestamp"] for d in result] == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# export clears buffer
# ---------------------------------------------------------------------------

def test_export_clears_buffer():
    md = OrderBookData()
    md.record(_make_snap())
    md.record(_make_snap())
    first = md.export()
    second = md.export()
    assert len(first) == 2
    assert len(second) == 0


def test_export_clears_then_new_records():
    md = OrderBookData()
    md.record(_make_snap(timestamp=1.0))
    md.record(_make_snap(timestamp=2.0))
    first = md.export()
    md.record(_make_snap(timestamp=3.0))
    second = md.export()
    assert len(first) == 2
    assert len(second) == 1
    assert second[0]["timestamp"] == 3.0


# ---------------------------------------------------------------------------
# export format
# ---------------------------------------------------------------------------

def test_export_returns_dicts_not_snapshots():
    md = OrderBookData()
    md.record(_make_snap())
    result = md.export()
    assert isinstance(result[0], dict)
    assert not isinstance(result[0], OrderBookMarketData)


def test_export_dict_contains_bids_asks():
    md = OrderBookData()
    md.record(_make_snap(bids=[(0.5, 10.0)], asks=[(0.6, 20.0)]))
    result = md.export()
    assert result[0]["bids"] == [[0.5, 10.0]]
    assert result[0]["asks"] == [[0.6, 20.0]]


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------

def test_thread_safety_concurrent_record_and_export():
    md = OrderBookData()
    num_threads = 4
    snaps_per_thread = 100
    all_exports = []
    export_lock = threading.Lock()

    def recorder():
        for i in range(snaps_per_thread):
            md.record(_make_snap(timestamp=float(i)))

    def exporter():
        for _ in range(10):
            batch = md.export()
            with export_lock:
                all_exports.extend(batch)

    threads = []
    for _ in range(num_threads):
        threads.append(threading.Thread(target=recorder))
    threads.append(threading.Thread(target=exporter))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Drain any remaining snapshots
    remaining = md.export()
    all_exports.extend(remaining)

    total_recorded = num_threads * snaps_per_thread
    assert len(all_exports) == total_recorded
