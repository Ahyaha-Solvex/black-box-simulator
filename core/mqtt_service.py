"""
MQTT Broker Ingestion Service & Telemetry Dispatcher
Handles high-rate (100 Hz) MQTT ingestion, database batch storage (every 3 seconds),
and dynamic routing according to the emergency uplink ladder.
"""

import asyncio
from datetime import datetime, timezone
import json
import math
from typing import Optional
import paho.mqtt.client as mqtt

from core.config import (
    DB_SAVE_INTERVAL_SEC,
    MQTT_CLIENT_ID,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TOPIC,
)
from core.database import db
from core.fallback import (
    dispatch_gsm_sms,
    dispatch_lorawan_frame,
    get_active_uplink_tier,
)
from core.remote_ws import broadcast_to_local_clients
from core.state import state


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        state.mqtt_connected = True
        print(f"[MQTT] Connected to broker at {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC, qos=1)
        print(f"[MQTT] Subscribed to topic: {MQTT_TOPIC}")
    else:
        state.mqtt_connected = False
        print(f"[MQTT] Connection failed with code {rc}")


def on_mqtt_disconnect(client, userdata, flags, rc, properties=None):
    state.mqtt_connected = False
    print("[MQTT] Disconnected from broker.")


def on_mqtt_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)

        device_id = data.get("device_id", "unknown_device")
        seq = data.get("seq", 0)
        speed = data.get("gps_speed_kmh", 0)
        now_ts = datetime.now(timezone.utc).timestamp()

        # Update in-memory latest cache
        state.latest_telemetry_cache[device_id] = data

        # Strip internal UI metadata before forwarding to the strict remote server
        remote_payload = {
            "type": "telemetry",
            "device_id": data.get("device_id"),
            "seq": data.get("seq"),
            "recorded_at": data.get("recorded_at"),
            "location": data.get("location"),
            "acc": data.get("acc"),
            "gyro": data.get("gyro"),
            "gps_speed_kmh": data.get("gps_speed_kmh"),
        }
        remote_payload_str = json.dumps(remote_payload)

        # 1. Route based on active emergency uplink tier
        active_tier = get_active_uplink_tier()

        if active_tier == "TIER_1_INTERNET":
            state.fallback_stats["primary_packets"] += 1
            if state.main_event_loop is not None and state.ws_outbox_queue is not None:
                state.main_event_loop.call_soon_threadsafe(state.ws_outbox_queue.put_nowait, remote_payload_str)
        elif active_tier == "TIER_2_GSM_SMS":
            # Primary Internet is DOWN! Route via GSM 2G SMS eCall MSD
            acc = data.get("acc", [])
            max_g = max([math.sqrt(x * x + y * y + z * z) for x, y, z in acc]) if acc else 1.0
            # Dispatch on impact/trigger (>1.0g) or periodic heartbeat (every 3 seq)
            if max_g > 1.0 or (seq % 3 == 0):
                if state.main_event_loop is not None:
                    asyncio.run_coroutine_threadsafe(dispatch_gsm_sms(data), state.main_event_loop)
        elif active_tier == "TIER_3_LORAWAN":
            # Cellular is DOWN! Route via LoRaWAN 868 MHz packed binary frame
            acc = data.get("acc", [])
            max_g = max([math.sqrt(x * x + y * y + z * z) for x, y, z in acc]) if acc else 1.0
            # Dispatch on impact/trigger (>1.0g) or periodic heartbeat (every 3 seq)
            if max_g > 1.0 or (seq % 3 == 0):
                if state.main_event_loop is not None:
                    asyncio.run_coroutine_threadsafe(dispatch_lorawan_frame(data), state.main_event_loop)
        else:
            print(f"[OFFLINE] No uplink available for telemetry seq={seq}")

        # 2. Forward to local WebSocket clients (with UI metadata)
        if state.main_event_loop is not None and state.connected_local_clients:
            asyncio.run_coroutine_threadsafe(broadcast_to_local_clients(payload_str), state.main_event_loop)

        # 3. Store in MongoDB every 3 seconds
        time_since_last_save = now_ts - state.last_db_save_time
        if time_since_last_save >= DB_SAVE_INTERVAL_SEC or (seq > 0 and seq % 3 == 0):
            state.last_db_save_time = now_ts
            if db.telemetry is not None:
                doc_to_save = dict(remote_payload)
                doc_to_save["received_at"] = datetime.now(timezone.utc).isoformat()
                db.telemetry.insert_one(doc_to_save)
                print(f"[DB Save (3s)] Stored in MongoDB: dev={device_id} | seq={seq} | speed={speed} km/h")
        else:
            print(f"[Relayed] dev={device_id} | seq={seq} | speed={speed} km/h -> Forwarded to WS")

    except Exception as e:
        print(f"[Ingest Error] Failed to process message: {e}")


def start_mqtt() -> Optional[mqtt.Client]:
    """Initialize and start the background MQTT client loop."""
    print(f"[MQTT] Starting client for {MQTT_HOST}:{MQTT_PORT}...")
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        client.on_connect = on_mqtt_connect
        client.on_disconnect = on_mqtt_disconnect
        client.on_message = on_mqtt_message
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        state.mqtt_client = client
        return client
    except Exception as e:
        print(f"[MQTT Warning] Setup failed: {e}")
        state.mqtt_client = None
        return None


def stop_mqtt():
    """Disconnect and clean up MQTT client."""
    if state.mqtt_client:
        try:
            state.mqtt_client.loop_stop()
            state.mqtt_client.disconnect()
            print("[MQTT] Client disconnected.")
        except Exception:
            pass
        state.mqtt_client = None
