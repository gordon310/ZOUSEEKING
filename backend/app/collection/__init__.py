"""Collection worker executor package.

``worker.py`` advances ``public.collection_runs`` rows (queued -> running ->
succeeded/failed) by claiming queued runs atomically and executing a
source_key-scoped runner.  Real data-source runners (jphouse 23ku / Osaka /
Yokohama, wired to ``configs/jphouse_*``) arrive in a later unit; this batch
ships the executor plus a deterministic in-process ``fixture`` runner used by
the test suite.
"""
