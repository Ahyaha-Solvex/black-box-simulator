"""
Emergency Uplink Fallback Subsystem (GSM 2G SMS & LoRaWAN 868 MHz)
Implements autonomous multi-tier transmission failover for vehicle telemetry and crash alerts.
"""

import base64
from datetime import datetime, timezone
import json
import math
import struct
import time
from typing import Any, Optional

from core.database import db
from core.player import player
from core.remote_ws import broadcast_to_local_clients
from core.state import state


def get_active_uplink_tier() -> str:
    """Evaluate active transmission tier according to the emergency ladder."""
    if state.fallback_state["internet_enabled"]:
        return "TIER_1_INTERNET"
    elif state.fallback_state["gsm_enabled"]:
        return "TIER_2_GSM_SMS"
    elif state.fallback_state["lorawan_enabled"]:
        return "TIER_3_LORAWAN"
    else:
        return "OFFLINE_NO_UPLINK"


def format_emergency_sms(
    device_id: str,
    seq: int,
    lat: float,
    lon: float,
    speed_kmh: float,
    peak_g: float,
    event_type: str = "CRASH",
    timestamp_dt: Optional[datetime] = None,
) -> str:
    """
    Format emergency SMS matching SolveX Crash Response specification (Section S6):
    Max 160 GSM 7-bit characters: SOS|<lat>,<lon>|<time>|SPD:<spd>|G:<peak_g>|SEV:<sev>|OCC:1|ID:<dev>
    """
    t_dt = timestamp_dt or datetime.now(timezone.utc).astimezone()
    t_str = t_dt.strftime("%H:%M:%S")
    sev = "CRITICAL" if peak_g > 3.0 else ("HIGH" if peak_g > 1.0 else "NOMINAL")
    spd = int(round(speed_kmh or 0))
    return f"SOS|{lat:.4f},{lon:.4f}|{t_str}|SPD:{spd}|G:{peak_g:.2f}|SEV:{sev}|OCC:1|ID:{device_id}"


def parse_emergency_sms(text: str) -> dict[str, Any]:
    """Parse SolveX emergency SMS string back into structured dictionary."""
    result: dict[str, Any] = {"raw": text, "valid_sos": False}
    if not text.startswith("SOS|"):
        return result
    parts = text.split("|")
    result["valid_sos"] = True
    if len(parts) > 1:
        coords = parts[1].split(",")
        if len(coords) == 2:
            try:
                result["lat"] = float(coords[0])
                result["lon"] = float(coords[1])
            except ValueError:
                pass
    if len(parts) > 2:
        result["time_str"] = parts[2]
    for p in parts[3:]:
        if ":" in p:
            k, v = p.split(":", 1)
            result[k.lower()] = v
    return result


def encode_lorawan_telemetry(
    msg_type: int,  # 0xFF: Crash, 0x02: Jolt, 0x01: Nominal
    seq: int,
    lat: float,
    lon: float,
    speed_kmh: float,
    peak_g: float,
    epoch: Optional[int] = None,
) -> bytes:
    """
    Encode 18-byte packed binary payload for LoRaWAN DR0-DR5 (868 MHz / 915 MHz):
    Format: >BHiibHI (18 bytes total)
    """
    lat_scaled = int(lat * 1_000_000)
    lon_scaled = int(lon * 1_000_000)
    g_scaled = int(round(peak_g * 100))
    spd_byte = min(255, max(0, int(speed_kmh or 0)))
    ep = epoch or int(time.time())
    return struct.pack(">BHiibHI", msg_type, seq % 65536, lat_scaled, lon_scaled, spd_byte, g_scaled, ep)


def decode_lorawan_telemetry(raw_bytes: bytes) -> dict[str, Any]:
    """Decode 18-byte packed binary LoRaWAN payload back into vehicle dynamics."""
    if len(raw_bytes) < 18:
        raise ValueError(f"LoRaWAN payload too short: {len(raw_bytes)} bytes, expected 18")
    msg_type, seq, lat_scaled, lon_scaled, spd_byte, g_scaled, ep = struct.unpack(">BHiibHI", raw_bytes[:18])
    event_str = "CRASH" if msg_type == 0xFF else ("JOLT" if msg_type == 0x02 else "NOMINAL")
    return {
        "event_type": event_str,
        "msg_type_code": hex(msg_type),
        "seq": seq,
        "location": {
            "lat": round(lat_scaled / 1_000_000.0, 6),
            "lon": round(lon_scaled / 1_000_000.0, 6),
        },
        "gps_speed_kmh": spd_byte,
        "peak_g": round(g_scaled / 100.0, 2),
        "epoch": ep,
        "timestamp": datetime.fromtimestamp(ep, timezone.utc).isoformat(),
    }


async def dispatch_gsm_sms(telemetry_data: dict[str, Any]) -> dict[str, Any]:
    """Simulates GSM 2G SMS dispatch via AT command interface."""
    state.fallback_stats["sms_sent"] += 1

    device_id = telemetry_data.get("device_id", "blackbox-01")
    seq = telemetry_data.get("seq", 0)
    loc = telemetry_data.get("location") or {"lat": player.lat, "lon": player.lon}
    lat = loc.get("lat", player.lat)
    lon = loc.get("lon", player.lon)
    speed = telemetry_data.get("gps_speed_kmh", 0.0) or 0.0

    acc = telemetry_data.get("acc", [])
    peak_g = 1.0
    if acc:
        peak_g = max(math.sqrt(x * x + y * y + z * z) for x, y, z in acc)

    event_type = "CRASH_IMPACT" if peak_g > 3.0 else ("HIGH_G_JOLT" if peak_g > 1.0 else "NOMINAL_DRIVING")
    now_dt = datetime.now(timezone.utc).astimezone()
    sms_text = format_emergency_sms(device_id, seq, lat, lon, speed, peak_g, event_type, now_dt)

    event = {
        "type": "fallback_event",
        "channel": "GSM_2G_SMS",
        "tier": "TIER_2",
        "timestamp": now_dt.isoformat(),
        "device_id": device_id,
        "seq": seq,
        "sender_msisdn": state.fallback_state["device_msisdn"],
        "recipient_msisdn": state.fallback_state["emergency_recipient"],
        "sms_body": sms_text,
        "character_count": len(sms_text),
        "pdu_encoding": "GSM_7BIT_ALPHABET",
        "modem_at_log": [
            "AT+CPIN?",
            "+CPIN: READY",
            "AT+CREG?",
            "+CREG: 0,1 (REGISTERED_HOME_2G)",
            "AT+CSQ",
            "+CSQ: 18,99 (-77 dBm)",
            f'AT+CMGS="{state.fallback_state["emergency_recipient"]}"',
            f"> {sms_text} <CTRL+Z>",
            "+CMGS: 142 (DELIVERED_TO_SMSC)",
        ],
        "telemetry_summary": {
            "location": {"lat": round(lat, 6), "lon": round(lon, 6)},
            "speed_kmh": round(speed, 1),
            "peak_g": round(peak_g, 2),
            "event_type": event_type,
        },
        "delivered": True,
    }

    state.latest_fallback_events.insert(0, event)
    if len(state.latest_fallback_events) > 30:
        state.latest_fallback_events.pop()

    if db.fallback is not None:
        try:
            db.fallback.insert_one(dict(event))
        except Exception:
            pass

    await broadcast_to_local_clients(json.dumps(event))
    print(f"\n[GSM 2G SMS FALLBACK DISPATCHED] -> {event['recipient_msisdn']}")
    print(f"  Body: {sms_text} ({len(sms_text)} chars)\n")
    return event


async def dispatch_lorawan_frame(telemetry_data: dict[str, Any]) -> dict[str, Any]:
    """Simulates LoRaWAN 868 MHz binary packet transmission."""
    state.fallback_stats["lorawan_sent"] += 1

    device_id = telemetry_data.get("device_id", "blackbox-01")
    seq = telemetry_data.get("seq", 0)
    loc = telemetry_data.get("location") or {"lat": player.lat, "lon": player.lon}
    lat = loc.get("lat", player.lat)
    lon = loc.get("lon", player.lon)
    speed = telemetry_data.get("gps_speed_kmh", 0.0) or 0.0

    acc = telemetry_data.get("acc", [])
    peak_g = 1.0
    if acc:
        peak_g = max(math.sqrt(x * x + y * y + z * z) for x, y, z in acc)

    msg_type = 0xFF if peak_g > 3.0 else (0x02 if peak_g > 1.0 else 0x01)
    event_type = "CRASH_IMPACT" if peak_g > 3.0 else ("HIGH_G_JOLT" if peak_g > 1.0 else "NOMINAL_DRIVING")

    raw_bin = encode_lorawan_telemetry(msg_type, seq, lat, lon, speed, peak_g)
    hex_str = raw_bin.hex()
    b64_str = base64.b64encode(raw_bin).decode("utf-8")
    now_dt = datetime.now(timezone.utc).astimezone()

    event = {
        "type": "fallback_event",
        "channel": "LORAWAN_868MHZ",
        "tier": "TIER_3",
        "timestamp": now_dt.isoformat(),
        "device_id": device_id,
        "seq": seq,
        "dev_eui": state.fallback_state["lorawan_dev_eui"],
        "gateway_eui": state.fallback_state["lorawan_gateway_eui"],
        "payload_bytes": len(raw_bin),
        "hex_payload": hex_str,
        "base64_payload": b64_str,
        "rf_params": {
            "frequency_mhz": 868.100,
            "modulation": "LORA",
            "spreading_factor": "SF7",
            "bandwidth_khz": 125,
            "coding_rate": "4/5",
            "rssi_dbm": -108,
            "snr_db": 7.8,
        },
        "telemetry_summary": {
            "location": {"lat": round(lat, 6), "lon": round(lon, 6)},
            "speed_kmh": round(speed, 1),
            "peak_g": round(peak_g, 2),
            "event_type": event_type,
        },
        "delivered": True,
    }

    state.latest_fallback_events.insert(0, event)
    if len(state.latest_fallback_events) > 30:
        state.latest_fallback_events.pop()

    if db.fallback is not None:
        try:
            db.fallback.insert_one(dict(event))
        except Exception:
            pass

    await broadcast_to_local_clients(json.dumps(event))
    print(f"\n[LoRaWAN 868 MHz FALLBACK DISPATCHED] -> GW: {event['gateway_eui']}")
    print(f"  Payload: {len(raw_bin)}B | Hex: {hex_str} | SF7/125kHz | RSSI: -108 dBm\n")
    return event
