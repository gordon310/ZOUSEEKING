"""Execute SQL files in one transaction for disposable-database checks."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg


async def run(files: list[str], database_url: str, rollback_after: bool) -> None:
    connection = await asyncpg.connect(database_url)
    transaction = connection.transaction()
    await transaction.start()
    try:
        for filename in files:
            await connection.execute(Path(filename).read_text(encoding="utf-8"))
        if rollback_after:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        await transaction.rollback()
        raise
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--database-url-env", default="TEST_DATABASE_URL")
    parser.add_argument("--rollback-after", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get(args.database_url_env, "")
    if not database_url:
        raise SystemExit(f"missing environment variable: {args.database_url_env}")
    asyncio.run(run(args.files, database_url, args.rollback_after))


if __name__ == "__main__":
    main()
