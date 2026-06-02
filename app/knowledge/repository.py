from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from bson.objectid import ObjectId


class KnowledgeRepository:
    def __init__(self, mongo_client: MongoClient, database_name: str) -> None:
        self.mongo_client = mongo_client
        self.database: Database = mongo_client[database_name]

    @property
    def symbols(self) -> Collection:
        return self.database["symbols"]

    @property
    def relationships(self) -> Collection:
        return self.database["relationships"]

    @property
    def evidence(self) -> Collection:
        return self.database["evidence"]

    @property
    def libraries(self) -> Collection:
        return self.database["libraries"]

    def ensure_indexes(self) -> None:
        existing = set(self.database.list_collection_names())
        for name in ("symbols", "relationships", "evidence", "libraries"):
            if name not in existing:
                self.database.create_collection(name)

        self.symbols.create_index("library")
        self.relationships.create_index([("from", 1), ("relation", 1), ("to", 1)], unique=True)
        self.relationships.create_index("from")
        self.relationships.create_index("library")
        self.evidence.create_index("relationship_id")
        self.libraries.create_index("library", unique=True)

    def lookup_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        record = self.symbols.find_one({"_id": symbol_id})
        return dict(record) if record else None

    def lookup_relationships(self, symbol_id: str) -> list[dict[str, Any]]:
        records = list(self.relationships.find({"from": symbol_id}))
        return [dict(record) for record in records]

    def insert_symbol(self, symbol_id: str, library: str) -> None:
        now = datetime.now(timezone.utc)
        self.symbols.update_one(
            {"_id": symbol_id},
            {
                "$setOnInsert": {
                    "_id": symbol_id,
                    "library": library,
                    "created_at": now,
                }
            },
            upsert=True,
        )

    def insert_relationship(self, from_sym: str, relation: str, to_sym: str, confidence: float, library: str) -> ObjectId:
        now = datetime.now(timezone.utc)
        result = self.relationships.find_one_and_update(
            {
                "from": from_sym,
                "relation": relation,
                "to": to_sym,
            },
            {
                "$setOnInsert": {
                    "from": from_sym,
                    "relation": relation,
                    "to": to_sym,
                    "confidence": confidence,
                    "status": "candidate",
                    "supporting_sources": 1,
                    "library": library,
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=True,
        )
        return result["_id"]

    def increment_supporting_sources(self, relationship_id: ObjectId) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        result = self.relationships.find_one_and_update(
            {"_id": relationship_id},
            {
                "$inc": {"supporting_sources": 1},
                "$set": {"updated_at": now}
            },
            return_document=True,
        )
        if result and result.get("supporting_sources", 1) >= 2 and result.get("status") == "candidate":
            self.promote_to_verified(relationship_id)
            result["status"] = "verified"
            result["updated_at"] = datetime.now(timezone.utc)
        return dict(result) if result else None

    def promote_to_verified(self, relationship_id: ObjectId) -> None:
        self.relationships.update_one(
            {"_id": relationship_id},
            {
                "$set": {
                    "status": "verified",
                    "updated_at": datetime.now(timezone.utc),
                }
            }
        )

    def insert_evidence(self, relationship_id: ObjectId, url: str, source_type: str, snippet: str) -> None:
        # Don't insert duplicate evidence for the same relationship
        existing = self.evidence.find_one({
            "relationship_id": relationship_id,
            "url": url,
            "snippet": snippet,
        })
        if existing:
            return

        now = datetime.now(timezone.utc)
        self.evidence.insert_one({
            "relationship_id": relationship_id,
            "url": url,
            "source_type": source_type,
            "snippet": snippet,
            "retrieved_at": now,
        })

    def lookup_evidence(self, relationship_id: ObjectId) -> list[dict[str, Any]]:
        records = list(self.evidence.find({"relationship_id": relationship_id}))
        return [dict(record) for record in records]

    def lookup_library(self, library: str) -> dict[str, Any] | None:
        record = self.libraries.find_one({"library": library})
        return dict(record) if record else None

    def upsert_library(
        self,
        library: str,
        latest_version: str | None = None,
        official_docs: str | None = None,
        github_repo: str | None = None,
        pypi_url: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        update_fields: dict[str, Any] = {"updated_at": now}
        
        if latest_version is not None:
            update_fields["latest_version"] = latest_version
        if official_docs is not None:
            update_fields["official_docs"] = official_docs
        if github_repo is not None:
            update_fields["github_repo"] = github_repo
        if pypi_url is not None:
            update_fields["pypi_url"] = pypi_url

        self.libraries.update_one(
            {"library": library},
            {
                "$set": update_fields,
                "$setOnInsert": {
                    "library": library,
                    "created_at": now,
                }
            },
            upsert=True,
        )
