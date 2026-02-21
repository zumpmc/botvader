# CLAUDE.md — botvader

## Project Overview

**botvader** is a trading data infrastructure library providing abstract interfaces and models for market data feeds, health monitoring, and publishing.

**Tech stack:** Python 3 using only the standard library (`abc`, `dataclasses`, `enum`, `typing`, `json`). No third-party dependencies at this time.

## Repository Structure

```
botvader/
├── dataFeed/
│   ├── __init__.py          # Public exports for the dataFeed package
│   ├── DataFeed.py          # Abstract base class defining the feed interface
│   ├── FeedHealth.py        # FeedHealth dataclass + FeedStatus enum
│   └── impl/                # Concrete DataFeed implementations go here
├── publisher/
│   └── Publisher.py         # Publisher module
├── tests/                   # All test files live here
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

## Best Practices

- **Keep modules focused and small.** A single file should do one thing well.
- **Prefer composition over inheritance** — except for ABC interface hierarchies.
- **All data models must support serialization** with `to_dict`, `to_json`, and `from_dict`.
- **All feed implementations must report health** via a `health()` method returning `FeedHealth`.
- **Document public APIs** with docstrings describing purpose, parameters, and return values.
- **No code without tests.** If it's worth writing, it's worth testing.
