"""
Emergency Uplink Fallback & Simulation Endpoints
Provides control switches for 4G/GSM/LoRaWAN simulated link outages,
manual SMS/LoRaWAN dispatchers, and inbound webhooks for field gateways.
"""

import base64
from datetime import datetime, timezone
import json
import math
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
import pymongo

from core.database import db, serialize_doc
from core.fallback import (
    decode_lorawan_telemetry,
    dispatch_gsm_sms,
    dispatch_lorawan_frame,
    get_active_uplink_tier,
    parse_emergency_sms,
)
from core.models import (
    FallbackSimulateRequest,
    InboundLorawanRequest,
    InboundSmsRequest,
    ManualLorawanRequest,
    ManualSmsRequest,
)
from core.player import player
from core.remote_ws import broadcast_to_local_clients
from core.state import state

router = APIRouter(prefix="/api/fallback", tags=["Fallback"])


@router.get("/status")
def get_fallback_status():
    """Returns the current state and metrics of the emergency uplink ladder."""
    active_tier = get_active_uplink_tier()
    return {
        "status": "online",
        "active_tier": active_tier,
        "config": state.fallback_state,
        "stats": state.fallback_stats,
        "latest_events": state.latest_fallback_events[:10],
    }


@router.post("/simulate")
async def configure_fallback_simulation(req: FallbackSimulateRequest):
    """
    Configure simulated uplink availability:
    - internet_enabled: True (4G LTE active) / False (Internet outage -> triggers GSM 2G SMS)
    - gsm_enabled: True (2G GSM available) / False (Cellular outage -> triggers LoRaWAN)
    - lorawan_enabled: True (LoRaWAN available) / False (Total blackout)
    """
    if req.internet_enabled is not None:
        state.fallback_state["internet_enabled"] = req.internet_enabled
    if req.gsm_enabled is not None:
        state.fallback_state["gsm_enabled"] = req.gsm_enabled
    if req.lorawan_enabled is not None:
        state.fallback_state["lorawan_enabled"] = req.lorawan_enabled
    if req.emergency_recipient is not None:
        state.fallback_state["emergency_recipient"] = req.emergency_recipient
    if req.device_msisdn is not None:
        state.fallback_state["device_msisdn"] = req.device_msisdn

    active_tier = get_active_uplink_tier()
    notification = {
        "type": "network_state_change",
        "active_tier": active_tier,
        "config": state.fallback_state,
        "stats": state.fallback_stats,
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    await broadcast_to_local_clients(json.dumps(notification))

    print(f"\n[NETWORK SIMULATION UPDATED] Active Uplink: {active_tier}")
    print(f"  Internet (4G): {state.fallback_state['internet_enabled']} | GSM (2G SMS): {state.fallback_state['gsm_enabled']} | LoRaWAN: {state.fallback_state['lorawan_enabled']}\n")

    return {
        "status": "updated",
        "active_tier": active_tier,
        "config": state.fallback_state,
        "stats": state.fallback_stats,
    }


@router.post("/sms/send")
async def trigger_manual_sms(req: ManualSmsRequest):
    """Manually dispatch a simulated or custom emergency SMS message."""
    device_id = req.device_id or player.device_id or "blackbox-01"
    lat = player.lat
    lon = player.lon
    speed = 0.0
    peak_g = 5.69 if req.body and "CRASH" in req.body.upper() else 1.0

    if device_id in state.latest_telemetry_cache:
        t = state.latest_telemetry_cache[device_id]
        if t.get("location"):
            lat = t["location"].get("lat", lat)
            lon = t["location"].get("lon", lon)
        speed = t.get("gps_speed_kmh", 0.0) or 0.0
        acc = t.get("acc", [])
        if acc:
            peak_g = max(math.sqrt(x * x + y * y + z * z) for x, y, z in acc)

    event = await dispatch_gsm_sms({
        "device_id": device_id,
        "seq": player.seq,
        "location": {"lat": lat, "lon": lon},
        "gps_speed_kmh": speed,
        "acc": [[0, 0, peak_g]] * 100,
    })
    return {"status": "dispatched", "event": event}


@router.post("/sms/inbound")
async def receive_inbound_sms(req: InboundSmsRequest):
    """
    Webhook for inbound SMS messages. Compatible with Android SMS Gateway, Termux, and cloud SMS APIs.
    """
    state.fallback_stats["sms_received"] += 1

    sender = req.sender or req.from_ or "UNKNOWN_SENDER"
    body = req.body or req.message or ""
    now_dt = datetime.now(timezone.utc).astimezone()

    parsed = parse_emergency_sms(body)

    sms_record = {
        "type": "inbound_sms",
        "channel": "GSM_2G_SMS",
        "sender": sender,
        "body": body,
        "parsed": parsed,
        "received_at": now_dt.isoformat(),
    }

    if db.sms_inbox is not None:
        try:
            db.sms_inbox.insert_one(dict(sms_record))
        except Exception:
            pass

    await broadcast_to_local_clients(json.dumps(sms_record))
    print(f"\n[INBOUND SMS RECEIVED] From: {sender} | Body: {body}\n")

    return {
        "status": "received",
        "parsed": parsed,
        "record": serialize_doc(sms_record),
    }


@router.post("/lorawan/send")
async def trigger_manual_lorawan(req: ManualLorawanRequest):
    """Manually dispatch a simulated 18-byte LoRaWAN binary packet."""
    device_id = req.device_id or player.device_id or "blackbox-01"
    lat = player.lat
    lon = player.lon
    speed = 0.0
    req_type = (req.msg_type or "CRASH").upper()
    peak_g = 5.69 if req_type == "CRASH" else (1.57 if req_type == "JOLT" else 1.0)

    if device_id in state.latest_telemetry_cache:
        t = state.latest_telemetry_cache[device_id]
        if t.get("location"):
            lat = t["location"].get("lat", lat)
            lon = t["location"].get("lon", lon)
        speed = t.get("gps_speed_kmh", 0.0) or 0.0

    event = await dispatch_lorawan_frame({
        "device_id": device_id,
        "seq": player.seq,
        "location": {"lat": lat, "lon": lon},
        "gps_speed_kmh": speed,
        "acc": [[0, 0, peak_g]] * 100,
    })
    return {"status": "dispatched", "event": event}


@router.post("/lorawan/uplink")
async def receive_lorawan_uplink(req: InboundLorawanRequest):
    """
    Webhook for LoRaWAN Network Server uplinks (ChirpStack / The Things Network / RSU gateway).
    Accepts Base64 or Hex payload, decodes 18-byte packed telemetry.
    """
    state.fallback_stats["lorawan_received"] += 1

    raw_bytes = b""
    if req.data:
        try:
            raw_bytes = base64.b64decode(req.data)
        except Exception:
            pass
    elif req.hex:
        try:
            raw_bytes = bytes.fromhex(req.hex)
        except Exception:
            pass

    if len(raw_bytes) < 18:
        raise HTTPException(status_code=400, detail="Invalid LoRaWAN payload: must be at least 18 bytes")

    decoded = decode_lorawan_telemetry(raw_bytes)
    now_dt = datetime.now(timezone.utc).astimezone()

    uplink_record = {
        "type": "inbound_lorawan",
        "channel": "LORAWAN_868MHZ",
        "dev_eui": req.devEUI or state.fallback_state["lorawan_dev_eui"],
        "rssi": req.rssi or -105.0,
        "snr": req.snr or 8.0,
        "fport": req.fPort or 1,
        "decoded": decoded,
        "raw_hex": raw_bytes.hex(),
        "received_at": now_dt.isoformat(),
    }

    if db.lorawan_inbox is not None:
        try:
            db.lorawan_inbox.insert_one(dict(uplink_record))
        except Exception:
            pass

    await broadcast_to_local_clients(json.dumps(uplink_record))
    print(f"\n[INBOUND LoRaWAN UPLINK DECODED] Event: {decoded['event_type']} | Lat: {decoded['location']['lat']}, Lon: {decoded['location']['lon']} | Peak G: {decoded['peak_g']}g\n")

    return {
        "status": "decoded",
        "uplink": serialize_doc(uplink_record),
    }


@router.get("/history")
def get_fallback_history(limit: int = Query(30, ge=1, le=100)):
    """Retrieve historical fallback events (SMS & LoRaWAN) from database."""
    if db.fallback is None:
        return state.latest_fallback_events[:limit]
    cursor = db.fallback.find({}).sort("timestamp", pymongo.DESCENDING).limit(limit)
    return [serialize_doc(doc) for doc in cursor]
