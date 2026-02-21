# CLAUDE.md — botvader

## Project Overview

**botvader** is a trading data infrastructure library providing abstract interfaces and models for market data feeds, health monitoring, and publishing.

**Tech stack:** Python 3 using only the standard library (`abc`, `dataclasses`, `enum`, `typing`, `json`). No third-party dependencies at this time.

## Repository Structure

```
botvader/
├── dataFeed/
│   ├── __init__.py          # Public exports for the dataFeed package
│   ├── DataFeed.py          # ABC — feed interface (start, stop, fetch, health, name)
│   ├── FeedHealth.py        # FeedHealth dataclass + FeedStatus enum
│   ├── MarketData.py        # ABC — Generic[T, E] interface (record, export)
│   └── impl/                # Concrete DataFeed implementations go here
├── publisher/
│   ├── __init__.py          # Public exports (Publisher, S3Publisher)
│   ├── Publisher.py         # ABC — key/value publishing interface
│   ├── S3Publisher.py       # Concrete S3 implementation
│   └── tests/               # Publisher integration tests
├── feedManager/
│   ├── __init__.py          # Public exports (FeedManager)
│   └── FeedManager.py       # ABC — orchestrator interface (create, run)
└── CLAUDE.md
```

### Module conventions

- Each package exposes its public API through `__init__.py` using explicit `__all__` lists.
- The `impl/` directories hold concrete implementations of their parent package's abstract interfaces.

## Coding Conventions

### One class per file

Every file contains **exactly one primary class definition**. The file is named after the class it contains using PascalCase (e.g., `DataFeed.py` contains `class DataFeed`).

Small, tightly-coupled helper types (like an `Enum` used only by the class in the same file) may live alongside the primary class — see `FeedHealth.py` which also defines `FeedStatus`.

### Rich models

Data models use `@dataclass` and include built-in serialization:

- `to_dict() -> dict` — convert to a plain dictionary (serialize enums to their `.value`)
- `to_json() -> str` — convert to a JSON string via `to_dict()`
- `from_dict(cls, data: dict) -> Self` — classmethod to reconstruct from a dictionary

Use `Enum` for any field with a finite, known set of values. See `FeedHealth.py` for the canonical example of this pattern.

### Abstract base classes

Extensibility points are defined as ABCs using `abc.ABC` and `@abstractmethod`. Concrete implementations go in the corresponding `impl/` directory.

Required shape for feed interfaces:
- Lifecycle methods: `start()`, `stop()`
- Data retrieval: `fetch() -> dict`
- Observability: `health() -> FeedHealth`
- Identity: `name` property

### Type hints

All function signatures, method parameters, and return types **must** include type annotations. Use `typing` module types where needed.

### Imports

- Prefer the standard library. If a third-party dependency is introduced, document it and add it to the project's dependency file.
- Use relative imports within a package (e.g., `from .DataFeed import DataFeed`).

## Testing Requirements

**Every new piece of code must have corresponding tests.** No exceptions.

### Test structure

- Tests live in the `tests/` directory at the project root.
- Test files are named `test_<ModuleName>.py` (e.g., `test_FeedHealth.py`).
- Use **pytest** as the test runner.

### What to test

- **Models:** Instantiation, field defaults, `to_dict()` / `to_json()` / `from_dict()` round-trip serialization, edge cases, and enum value handling.
- **ABC implementations:** Verify the interface contract — `start`, `stop`, `fetch`, `health`, and `name` must all work correctly.
- **Publishers:** Message formatting, delivery behavior, and error handling.
- **General:** Happy path, edge cases, and error conditions for every public method.

### Running tests

```bash
pytest tests/
```

## Architecture — Data Flow

```
[1-n] DataFeeds  →  FeedManager  →  [1-n] Publishers
                      ↕
                   MarketData
                 (internal state)
```

### How it works

1. **DataFeeds** produce market data. Each feed implements `DataFeed` ABC (`start`, `stop`, `fetch`, `health`, `name`). Existing implementations: `BinanceDataFeed`, `KrakenDataFeed`, `PolymarketDataFeed`.

2. **MarketData** accumulates feed data between publishes. It is a generic ABC (`MarketData[T, E]`) with two methods:
   - `record(data: T)` — store incoming data from a feed
   - `export() -> E` — export accumulated data for publishing

   Subclasses bind `T` (input type) and `E` (export type) and decide storage strategy, whether to clear on export, etc.

3. **FeedManager** orchestrates the pipeline. It is an ABC with two methods:
   - `create(feeds, publishers, market_data)` — wire up all components
   - `run()` — start the feed-to-publish loop

   Subclasses decide threading model, polling vs callbacks, intervals, shutdown behavior, etc.

4. **Publishers** persist/send the exported data. Each publisher implements `Publisher` ABC (`publish`, `publish_json`, `get`, `delete`, `list_keys`). Existing implementation: `S3Publisher`.

## Best Practices

- **Keep modules focused and small.** A single file should do one thing well.
- **Prefer composition over inheritance** — except for ABC interface hierarchies.
- **All data models must support serialization** with `to_dict`, `to_json`, and `from_dict`.
- **All feed implementations must report health** via a `health()` method returning `FeedHealth`.
- **Document public APIs** with docstrings describing purpose, parameters, and return values.
- **No code without tests.** If it's worth writing, it's worth testing.

## S3 Key Convention

All data feed implementations that publish to S3 **must** use this key format:

```
{exchange}/{collector_name}/{unix_timestamp_start}-{unix_timestamp_end}
```

**Example:** `coinbase/coinbase-btc-usd/1740000000.000000-1740000300.000000`

### Rules

- **Window size:** 5 minutes (300 seconds)
- **Alignment:** Windows are aligned to clean 5-minute clock boundaries (`:00`, `:05`, `:10`, `:15`, `:20`, `:25`, `:30`, `:35`, `:40`, `:45`, `:50`, `:55`)
- **Partial first window:** When a collector starts mid-window, the first flush covers the partial period from startup to the next boundary
- **exchange:** The data source (e.g., `coinbase`, `binance`)
- **collector_name:** Matches the feed's `name` property (e.g., `coinbase-btc-usd`)
- **Timestamps:** Microsecond-precision floats (e.g., `1740000000.000000`), formatted with 6 decimal places
