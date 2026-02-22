from __future__ import annotations

import json
import logging
import time
import httpx

logger = logging.getLogger("market_discovery")

GAMMA_API = "https://gamma-api.polymarket.com"


def _fetch_market(slug_prefix: str, window_seconds: int) -> dict | None:
    """Shared logic: find an active BTC market by slug prefix and window size.

    Args:
        slug_prefix: e.g. "btc-updown-5m" or "btc-updown-15m"
        window_seconds: 300 for 5m, 900 for 15m
    """
    now = int(time.time())
    current_window = now - (now % window_seconds)

    for offset in [0, window_seconds]:
        ts = current_window + offset
        slug = f"{slug_prefix}-{ts}"
        logger.debug("Querying Gamma API — slug=%s", slug)
        try:
            resp = httpx.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10.0)
            resp.raise_for_status()
            events = resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning("Gamma API request failed — slug=%s, error=%s", slug, e)
            continue
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Gamma API returned invalid JSON — slug=%s, error=%s", slug, e)
            continue

        if not events or not isinstance(events, list):
            logger.debug("No events returned for slug=%s", slug)
            continue

        event = events[0]
        markets = event.get("markets", [])
        if not markets or not markets[0].get("acceptingOrders"):
            logger.info(
                "Market not accepting orders — slug=%s, markets_count=%d",
                slug,
                len(markets),
            )
            continue

        market = markets[0]
        try:
            token_ids = json.loads(market.get("clobTokenIds", "[]"))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse clobTokenIds — slug=%s, error=%s", slug, e)
            continue

        try:
            outcomes = json.loads(market.get("outcomes", "[]"))
        except (json.JSONDecodeError, TypeError):
            outcomes = []

        url = f"https://polymarket.com/event/{event['slug']}"
        description = market.get("description", "")
        logger.info(
            "Discovered market — title=%s, slug=%s, market_id=%s, "
            "outcomes=%s, tokens=%d, start=%s, end=%s",
            event.get("title", "?"),
            event["slug"],
            market.get("id"),
            outcomes,
            len(token_ids),
            event.get("startTime"),
            event.get("endDate"),
        )
        return {
            "url": url,
            "title": event["title"],
            "slug": event["slug"],
            "market_id": market.get("id"),
            "condition_id": market.get("conditionId"),
            "question_id": market.get("questionID"),
            "token_ids": token_ids,
            "outcomes": outcomes,
            "description": description,
            "event_start_time": event.get("startTime"),
            "end_date": event.get("endDate"),
        }

    logger.warning(
        "No active BTC market found — prefix=%s, window=%ds, checked_window=%d",
        slug_prefix,
        window_seconds,
        current_window,
    )
    return None


def get_current_btc_5m_market():
    """Find the currently active BTC up/down 5-minute market."""
    return _fetch_market("btc-updown-5m", 300)


def get_current_btc_15m_market():
    """Find the currently active BTC up/down 15-minute market."""
    return _fetch_market("btc-updown-15m", 900)


def get_current_btc_4h_market():
    """Find the currently active BTC up/down 4-hour market."""
    return _fetch_market("btc-updown-4h", 14400)


def find_events(slug_contains, closed=False, limit=10):
    """General-purpose event search via the Gamma API."""
    try:
        resp = httpx.get(
            f"{GAMMA_API}/events",
            params={
                "slug_contains": slug_contains,
                "closed": str(closed).lower(),
                "limit": limit,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.error("Gamma API search failed: %s", e)
        return []
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Gamma API returned invalid JSON: %s", e)
        return []


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    market = get_current_btc_5m_market()
    if market:
        print(f"\n{market['title']}")
        print(f"  slug:             {market['slug']}")
        print(f"  condition_id:     {market['condition_id']}")
        print(f"  event_start_time: {market['event_start_time']}")
        print(f"  end_date:         {market['end_date']}")
        print(f"  outcomes:         {market['outcomes']}")
        print(f"  token_ids:")
        for tid in market["token_ids"]:
            print(f"    {tid}")
