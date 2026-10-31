"""
Health and Status Endpoints
Serves system overview and vehicle blackbox hardware telemetry diagnostics.
"""

from fastapi import APIRouter

from core.config import (
    MONGO_DB_NAME,
    MONGO_TELEMETRY_COLLECTION,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TOPIC,
    REMOTE_WS_URL,
)
from core.database import db
from core.fallback import get_active_uplink_tier
from core.hardware import get_box_health_data
from core.state import state

router = APIRouter()


@router.get("/api/status", tags=["System"])
def get_status():
    """System overview and connection health."""
    total_docs = db.telemetry.count_documents({}) if db.telemetry is not None else 0
    total_preds = db.predictions.count_documents({}) if db.predictions is not None else 0
    total_fallbacks = db.fallback.count_documents({}) if db.fallback is not None else 0
    return {
        "status": "online",
        "service": "Telemetry Hub & Forwarder",
        "mqtt": {
            "broker": f"{MQTT_HOST}:{MQTT_PORT}",
            "topic": MQTT_TOPIC,
            "connected": state.mqtt_connected,
        },
        "remote_websocket": {
            "target": REMOTE_WS_URL,
            "connected": state.remote_ws_connected and state.fallback_state["internet_enabled"],
        },
        "mongodb": {
            "database": MONGO_DB_NAME,
            "collection": MONGO_TELEMETRY_COLLECTION,
            "total_stored_batches": total_docs,
            "total_predictions": total_preds,
            "total_fallback_events": total_fallbacks,
            "save_frequency": "Every 3 seconds",
        },
        "uplink_ladder": {
            "active_tier": get_active_uplink_tier(),
            "internet_enabled": state.fallback_state["internet_enabled"],
            "gsm_enabled": state.fallback_state["gsm_enabled"],
            "lorawan_enabled": state.fallback_state["lorawan_enabled"],
            "stats": state.fallback_stats,
        },
        "latest_predictions_count": len(state.latest_predictions_cache),
    }


@router.get("/box/health", tags=["Hardware"])
@router.get("/box-health", tags=["Hardware"])
@router.get("/api/box/health", tags=["Hardware"])
@router.get("/api/box-health", tags=["Hardware"])
def get_box_health():
    """
    Returns real-time operational status and diagnostics of the vehicle blackbox hardware:
    - Compute & System: CPU load, CPU temperature, RAM usage, storage
    - IMU Sensors: 100 Hz Accelerometer & Gyroscope operational status
    - GNSS / GPS: Fix quality, 3D lock, satellites, coordinates, vehicle speed
    - Power Management: 12V vehicle bus, backup crash-proof LiPo battery
    - Modem & Telematics: 4G LTE link with 2G SMS fallback gateway status
    - Non-volatile Storage: Flash crash circular buffer write health
    - Uplinks: MQTT broker, remote crash response WebSocket, local database
    """
    return get_box_health_data()
