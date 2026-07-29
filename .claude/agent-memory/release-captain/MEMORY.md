# Memory Index

- [Release state](release-state.md) — read tag/version LIVE from their owners (`git tag`, `pyproject.toml`), never from memory; the cached "v3.30.0 + PR #293 pending" went stale and wrong. Only durable fact: schema `cisco_toolkit.__version__` 3.23.0 is frozen — never bump
