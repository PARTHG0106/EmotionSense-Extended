"""Engine and schema bootstrap.

SQLAlchemy Core is used rather than the ORM. The schema in ``sql/schema.sql`` uses
partitioned tables, array columns, JSONB and CHECK constraints that encode real safety
rules (an event cannot exist without evidence; an alert cannot exist without all six
explanation fields). Mirroring that in ORM models would duplicate those rules in a second
place where they could silently drift, so SQL stays the single source of truth and this
module only maps rows to contracts.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL_ENV = "WELLBEING_DB_URL"

#: Applied in order. Additive migrations only; a destructive change needs a reviewed plan
#: because event history is the audit record for alerts that were already acted on.
MIGRATIONS = ("schema.sql", "migrations/002_trend_and_profile.sql")


def create_engine_from_url(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an engine from an explicit URL or ``WELLBEING_DB_URL``.

    ``pool_pre_ping`` is on deliberately: the perception process holds connections open
    across long idle stretches overnight, and a stale connection surfacing as a failed alert
    write is exactly the failure this system cannot afford.
    """
    resolved = url or os.environ.get(DEFAULT_URL_ENV)
    if not resolved:
        raise RuntimeError(
            f"no database URL provided and {DEFAULT_URL_ENV} is unset; "
            "pass url= explicitly or use the in-memory Repository for tests"
        )
    return create_engine(resolved, echo=echo, pool_pre_ping=True, future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def bootstrap(engine: Engine, sql_dir: str | Path = "sql") -> list[str]:
    """Apply the schema and additive migrations. Idempotent.

    Intended for local development, tests and container start-up. In production the same
    files should be applied by a reviewed migration step, not by application code.
    """
    root = Path(sql_dir)
    applied: list[str] = []
    with engine.begin() as connection:
        for name in MIGRATIONS:
            path = root / name
            if not path.exists():
                continue
            statement = path.read_text(encoding="utf-8")
            try:
                connection.exec_driver_sql(statement)
                applied.append(name)
            except Exception as error:  # noqa: BLE001
                # schema.sql is not written with IF NOT EXISTS on every object, so a repeat
                # run raises. That is not a failure worth aborting start-up for.
                if "already exists" not in str(error).lower():
                    raise
    return applied
