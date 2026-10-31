"""
Telemetry & Prediction Data Endpoints
Provides real-time caching, historical database lookups, and browser WebSocket streaming.
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
import pymongo

from core.database import db, serialize_doc
from core.state import state

router = APIRouter()


@router.get("/api/predictions/latest", tags=["Predictions"])
def get_latest_predictions(limit: int = Query(5, ge=1, le=50)):
    """Get the most recent AI predictions received from the remote server."""
    return state.latest_predictions_cache[:limit]


@router.get("/api/predictions/history", tags=["Predictions"])
def get_predictions_history(
    device_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Get stored predictions from MongoDB."""
    if db.predictions is None:
        return state.latest_predictions_cache[:limit]

    query = {"device_id": device_id} if device_id else {}
    cursor = db.predictions.find(query).sort("received_at", pymongo.DESCENDING).limit(limit)
    return [serialize_doc(doc) for doc in cursor]


@router.get("/api/telemetry/latest", tags=["Telemetry"])
def get_latest_telemetry(device_id: Optional[str] = Query(None)):
    """Get the latest telemetry reading."""
    if device_id and device_id in state.latest_telemetry_cache:
        return serialize_doc(state.latest_telemetry_cache[device_id])

    if db.telemetry is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    query = {"device_id": device_id} if device_id else {}
    doc = db.telemetry.find_one(query, sort=[("recorded_at", pymongo.DESCENDING)])
    if not doc:
        raise HTTPException(status_code=404, detail="No telemetry records found")
    return serialize_doc(doc)


@router.get("/api/telemetry/history", tags=["Telemetry"])
def get_telemetry_history(
    device_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Retrieve historical 3-second batches stored in MongoDB."""
    if db.telemetry is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    query: dict[str, Any] = {}
    if device_id:
        query["device_id"] = device_id

    cursor = (
        db.telemetry.find(query)
        .sort("recorded_at", pymongo.DESCENDING)
        .skip(skip)
        .limit(limit)
    )
    records = [serialize_doc(doc) for doc in cursor]
    total = db.telemetry.count_documents(query)

    return {
        "total": total,
        "count": len(records),
        "skip": skip,
        "limit": limit,
        "records": records,
    }


@router.websocket("/ws/telemetry")
async def local_websocket_endpoint(websocket: WebSocket):
    """Local WebSocket stream for dashboard telemetry gauges, map, and predictions."""
    await websocket.accept()
    state.connected_local_clients.add(websocket)
    try:
        while True:
            # Keep alive and receive any ping/commands from frontend
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.connected_local_clients.discard(websocket)
    except Exception:
        state.connected_local_clients.discard(websocket)
