import threading

import pytest

from dataFeed.struct.Tick import Tick
from dataFeed.struct.TickMarketData import TickMarketData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(price: float = 68500.0, source: str = "test") -> Tick:
    return Tick(timestamp=1700000000.0, price=price, source=source)


# ---------------------------------------------------------------------------
# export — empty
# ---------------------------------------------------------------------------

def test_export_empty():
    md = TickMarketData()
    result = md.export()
    assert result == []


# ---------------------------------------------------------------------------
# record + export
# ---------------------------------------------------------------------------

def test_record_and_export_single():
    md = TickMarketData()
    tick = _make_tick(price=100.0)
    md.record(tick)
    result = md.export()
    assert len(result) == 1
    assert result[0]["price"] == 100.0


def test_record_and_export_multiple():
    md = TickMarketData()
    md.record(_make_tick(price=100.0))
    md.record(_make_tick(price=200.0))
    md.record(_make_tick(price=300.0))
    result = md.export()
    assert len(result) == 3
    assert [d["price"] for d in result] == [100.0, 200.0, 300.0]


# ---------------------------------------------------------------------------
# export clears buffer
# ---------------------------------------------------------------------------

def test_export_clears_buffer():
    md = TickMarketData()
    md.record(_make_tick())
    md.record(_make_tick())
    first = md.export()
    second = md.export()
    assert len(first) == 2
    assert len(second) == 0


def test_export_clears_then_new_records():
    md = TickMarketData()
    md.record(_make_tick(price=1.0))
    md.record(_make_tick(price=2.0))
    first = md.export()
    md.record(_make_tick(price=3.0))
    second = md.export()
    assert len(first) == 2
    assert len(second) == 1
    assert second[0]["price"] == 3.0


# ---------------------------------------------------------------------------
# export format
# ---------------------------------------------------------------------------

def test_record_tick_with_optional_fields():
    md = TickMarketData()
    tick = Tick(timestamp=1.0, price=100.0, source="coinbase", size=0.5, side="BUY")
    md.record(tick)
    result = md.export()
    assert result[0]["size"] == 0.5
    assert result[0]["side"] == "BUY"


def test_record_tick_without_optional_fields():
    md = TickMarketData()
    tick = Tick(timestamp=1.0, price=100.0, source="binance")
    md.record(tick)
    result = md.export()
    assert result[0]["size"] is None
    assert result[0]["side"] is None


def test_export_returns_dicts_not_ticks():
    md = TickMarketData()
    md.record(_make_tick())
    result = md.export()
    assert isinstance(result[0], dict)
    assert not isinstance(result[0], Tick)


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------

def test_thread_safety_concurrent_record_and_export():
    md = TickMarketData()
    num_threads = 4
    ticks_per_thread = 100
    all_exports = []
    export_lock = threading.Lock()

    def recorder():
        for i in range(ticks_per_thread):
            md.record(_make_tick(price=float(i)))

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

    # Drain any remaining ticks
    remaining = md.export()
    all_exports.extend(remaining)

    total_recorded = num_threads * ticks_per_thread
    assert len(all_exports) == total_recorded
