"""Collection worker executor package.

``worker.py`` advances ``public.collection_runs`` rows (queued -> running ->
succeeded/failed) by claiming queued runs atomically and executing a
source_key-scoped runner.  It ships a deterministic in-process ``fixture``
runner for tests/self-checks plus the real config-family runners registered
from ``jphouse_runners.py`` (jphouse 23ku / Osaka / Yokohama, wired to
``configs/jphouse_*``).  Live third-party fetching/parsing for those families
is not yet enabled; their runners currently perform a deterministic local data
read-in from the already collected snapshots under ``data/collected/``.
"""
