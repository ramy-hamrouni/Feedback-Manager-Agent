from typing import Annotated, Any, Iterator

import logging

from fastapi import Depends, Request

from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

from core.edge_errors import EdgeHandledError
from core.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class MongoRepositoryError(EdgeHandledError):
    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            status_code=502,
            code="MONGO_REPOSITORY_ERROR",
            message=message,
            details=details,
        )


class InvalidIdError(EdgeHandledError):
    """Raised when a caller-supplied id is not a valid ObjectId (client error, not a Mongo failure)."""

    def __init__(self, doc_id: str, collection: str, details: dict | None = None) -> None:
        super().__init__(
            status_code=400,
            code="INVALID_ID",
            message=f"Invalid id {doc_id!r} for '{collection}': it must be a 12-byte input or a 24-character hex string",
            details=details or {"id": doc_id, "collection": collection},
        )


class MongoRepository:
    """Generic MongoDB access for the `scores` / `competencies` / `projects` collections.

    Reads and writes both go to the single cluster selected by MANAGER_AGENT_MONGO_REGION
    (UAE | KSA | DEV). Competency/project lookups are best-effort: callers fall back on a
    miss (None)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._region = settings.mongo_region
        self._uri = settings.mongo_uri()
        self._client: MongoClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._uri)

    @property
    def region(self) -> str:
        return self._region

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _db(self) -> Database:
        if not self.enabled:
            raise MongoRepositoryError(
                f"Mongo is not configured for region {self._region} "
                "(set MANAGER_AGENT_MONGO_USERNAME / MANAGER_AGENT_MONGO_PASSWORD, "
                "or MANAGER_AGENT_MONGO_DEV_URI for DEV)."
            )
        if self._client is None:
            self._client = MongoClient(
                self._uri,
                serverSelectionTimeoutMS=self._settings.mongo_server_selection_timeout_ms,
            )
        return self._client[self._settings.mongo_database]

    def _find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        db = self._db()
        try:
            logger.info("Executing Mongo query in region %s for collection '%s': %s", self._region, collection, query)
            doc = db[collection].find_one(query)
        except Exception as exc:
            logger.error("Mongo query failed in region %s for '%s': %s", self._region, collection, exc)
            raise MongoRepositoryError(
                f"Could not query '{collection}' in region {self._region}.",
                details={"error": f"{type(exc).__name__}: {exc}"},
            ) from exc
        if doc is None:
            logger.debug("Mongo '%s' query returned no document: %s", collection, query)
        return doc

    def find_by_id(self, collection: str, id: str) -> dict[str, Any] | None:
        try:
            oid = ObjectId(id)
        except Exception as exc:
            raise InvalidIdError(id, collection, details={"error": str(exc)}) from exc

        return self._find_one(collection, {"_id": oid})

    def find_by_attributes(self, collection: str, attributes: dict[str, Any]) -> dict[str, Any] | None:
        """Look up a single document matching all given field/value pairs (exact match, ANDed)."""
        if not attributes:
            raise ValueError("attributes must not be empty")
        return self._find_one(collection, dict(attributes))

    def update_by_attributes(
        self,
        collection: str,
        query: dict[str, Any],
        update: dict[str, Any],
        array_filters: list[dict[str, Any]] | None = None,
    ) -> bool:
        
        if not query:
            raise ValueError("query must not be empty")
        if not update:
            raise ValueError("update must not be empty")
        db = self._db()
        try:
            result = db[collection].update_one(query, {"$set": update}, array_filters=array_filters)
        except Exception as exc:
            logger.error("Mongo update failed in region %s for '%s': %s", self._region, collection, exc)
            raise MongoRepositoryError(
                f"Could not update '{collection}' in region {self._region}.",
                details={"error": f"{type(exc).__name__}: {exc}"},
            ) from exc
        if not result.matched_count:
            logger.debug("Mongo '%s' update matched no document: %s", collection, query)
            return False
        return True


def get_mongo_repository(request: Request) -> Iterator[MongoRepository]:
    """The process-wide repository built in lifespan.

    Not constructed here: MongoClient owns a connection pool and is meant to live for
    the process, and a per-request close() also cut the pool out from under background
    tasks, which run after dependency teardown.
    """
    yield request.app.state.mongo