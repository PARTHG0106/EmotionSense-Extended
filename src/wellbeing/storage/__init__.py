"""Persistence layer.

``SqlRepository`` implements the same query surface as
:class:`wellbeing.api.repository.Repository`, so the API can be pointed at Postgres or at
the in-memory store without changing a line of route code.
"""

from wellbeing.storage.engine import bootstrap, create_engine_from_url, session_factory
from wellbeing.storage.repository import SqlRepository

__all__ = ["SqlRepository", "bootstrap", "create_engine_from_url", "session_factory"]
