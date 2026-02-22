import json
import time
from unittest.mock import patch, MagicMock

import httpx
import pytest

from dataFeed.impl.polymarket_discovery import (
    _fetch_market,
    get_current_btc_5m_market,
    get_current_btc_15m_market,
    find_events,
    GAMMA_API,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(slug="btc-updown-5m-1700000000", accepting=True):
    """Build a minimal Gamma API event response."""
    return {
        "title": "BTC Up/Down 5m",
        "slug": slug,
        "startTime": "2023-11-14T22:13:20Z",
        "endDate": "2023-11-14T22:18:20Z",
        "markets": [
            {
                "id": "market-1",
                "conditionId": "cond-1",
                "questionID": "q-1",
                "acceptingOrders": accepting,
                "clobTokenIds": json.dumps(["token-yes", "token-no"]),
                "outcomes": json.dumps(["Up", "Down"]),
                "description": "Will BTC go up?",
            }
        ],
    }


def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# _fetch_market — success
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_first_active(mock_get):
    now = int(time.time())
    window = now - (now % 300)
    slug = f"btc-updown-5m-{window}"
    mock_get.return_value = _mock_response([_make_event(slug=slug)])

    result = _fetch_market("btc-updown-5m", 300)

    assert result is not None
    assert result["slug"] == slug
    assert result["condition_id"] == "cond-1"
    assert result["token_ids"] == ["token-yes", "token-no"]
    assert result["outcomes"] == ["Up", "Down"]
    assert result["market_id"] == "market-1"
    assert "polymarket.com" in result["url"]


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_tries_next_window(mock_get):
    now = int(time.time())
    window = now - (now % 300)
    next_slug = f"btc-updown-5m-{window + 300}"

    # First call returns empty, second returns a market.
    mock_get.side_effect = [
        _mock_response([]),
        _mock_response([_make_event(slug=next_slug)]),
    ]

    result = _fetch_market("btc-updown-5m", 300)
    assert result is not None
    assert result["slug"] == next_slug
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# _fetch_market — failure paths
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_none_on_http_error(mock_get):
    mock_get.side_effect = httpx.HTTPError("connection failed")
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_none_on_timeout(mock_get):
    mock_get.side_effect = httpx.TimeoutException("timed out")
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_none_on_invalid_json(mock_get):
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status.return_value = None
    resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    mock_get.return_value = resp
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_none_when_not_accepting(mock_get):
    now = int(time.time())
    window = now - (now % 300)
    slug = f"btc-updown-5m-{window}"
    mock_get.return_value = _mock_response([_make_event(slug=slug, accepting=False)])
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_returns_none_on_empty_events(mock_get):
    mock_get.return_value = _mock_response([])
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_fetch_market_handles_bad_clob_token_ids(mock_get):
    now = int(time.time())
    window = now - (now % 300)
    slug = f"btc-updown-5m-{window}"
    event = _make_event(slug=slug)
    event["markets"][0]["clobTokenIds"] = "not-json"
    mock_get.return_value = _mock_response([event])
    result = _fetch_market("btc-updown-5m", 300)
    assert result is None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.polymarket_discovery._fetch_market")
def test_get_current_btc_5m_market(mock_fetch):
    mock_fetch.return_value = {"slug": "btc-updown-5m-123"}
    result = get_current_btc_5m_market()
    mock_fetch.assert_called_once_with("btc-updown-5m", 300)
    assert result["slug"] == "btc-updown-5m-123"


@patch("dataFeed.impl.polymarket_discovery._fetch_market")
def test_get_current_btc_15m_market(mock_fetch):
    mock_fetch.return_value = {"slug": "btc-updown-15m-456"}
    result = get_current_btc_15m_market()
    mock_fetch.assert_called_once_with("btc-updown-15m", 900)
    assert result["slug"] == "btc-updown-15m-456"


# ---------------------------------------------------------------------------
# find_events
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_find_events_returns_results(mock_get):
    events = [{"title": "BTC event", "slug": "btc-test"}]
    mock_get.return_value = _mock_response(events)
    result = find_events("btc")
    assert result == events
    mock_get.assert_called_once()


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_find_events_returns_empty_on_error(mock_get):
    mock_get.side_effect = httpx.HTTPError("fail")
    result = find_events("btc")
    assert result == []


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_find_events_returns_empty_on_invalid_json(mock_get):
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status.return_value = None
    resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    mock_get.return_value = resp
    result = find_events("btc")
    assert result == []


@patch("dataFeed.impl.polymarket_discovery.httpx.get")
def test_find_events_passes_params(mock_get):
    mock_get.return_value = _mock_response([])
    find_events("btc-updown", closed=True, limit=5)
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["slug_contains"] == "btc-updown"
    assert kwargs["params"]["closed"] == "true"
    assert kwargs["params"]["limit"] == 5
