"""
MongoDB Database Connection and Collection Handles
"""

from typing import Optional
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection

from core.config import (
    MONGO_DB_NAME,
    MONGO_FALLBACK_COLLECTION,
    MONGO_LORAWAN_INBOX_COLLECTION,
    MONGO_PREDICTIONS_COLLECTION,
    MONGO_SMS_INBOX_COLLECTION,
    MONGO_TELEMETRY_COLLECTION,
    MONGO_URI,
)


def serialize_doc(doc: Optional[dict]) -> Optional[dict]:
    """Convert MongoDB BSON document to clean JSON dict."""
    if not doc:
        return None
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d["_id"])
        del d["_id"]
    return d


class DatabaseManager:
    """Manages the MongoDB client connection and collection references."""

    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.telemetry: Optional[Collection] = None
        self.predictions: Optional[Collection] = None
        self.fallback: Optional[Collection] = None
        self.sms_inbox: Optional[Collection] = None
        self.lorawan_inbox: Optional[Collection] = None

    def connect(self):
        """Establish connection to MongoDB and ensure indexes."""
        print(f"[Database] Connecting to MongoDB at {MONGO_URI}...")
        try:
            self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            self.client.admin.command("ping")
            database = self.client[MONGO_DB_NAME]

            self.telemetry = database[MONGO_TELEMETRY_COLLECTION]
            self.predictions = database[MONGO_PREDICTIONS_COLLECTION]
            self.fallback = database[MONGO_FALLBACK_COLLECTION]
            self.sms_inbox = database[MONGO_SMS_INBOX_COLLECTION]
            self.lorawan_inbox = database[MONGO_LORAWAN_INBOX_COLLECTION]

            # Ensure optimal query indexes
            self.telemetry.create_index([("device_id", pymongo.ASCENDING), ("seq", pymongo.DESCENDING)])
            self.telemetry.create_index([("recorded_at", pymongo.DESCENDING)])
            self.predictions.create_index([("device_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])
            self.fallback.create_index([("timestamp", pymongo.DESCENDING)])
            self.sms_inbox.create_index([("received_at", pymongo.DESCENDING)])
            self.lorawan_inbox.create_index([("received_at", pymongo.DESCENDING)])

            print(f"[Database] Successfully connected to database '{MONGO_DB_NAME}'")
        except Exception as e:
            print(f"[Database Warning] Could not connect to MongoDB: {e}")
            self.client = None
            self.telemetry = None
            self.predictions = None
            self.fallback = None
            self.sms_inbox = None
            self.lorawan_inbox = None

    def close(self):
        """Close MongoDB connection pool."""
        if self.client:
            try:
                self.client.close()
                print("[Database] MongoDB connection closed.")
            except Exception:
                pass
            self.client = None
            self.telemetry = None
            self.predictions = None
            self.fallback = None
            self.sms_inbox = None
            self.lorawan_inbox = None


# Global database manager singleton
db = DatabaseManager()
