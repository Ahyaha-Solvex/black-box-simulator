"""
Remote WebSocket Client & Local Dashboard Broadcaster
Manages real-time bidirectional telemetry streaming to the ML service and local browser HUDs.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any
import websockets

from core.config import REMOTE_WS_URL
from core.database import db
from core.state import state


async def broadcast_to_local_clients(message_str: str):
    """Broadcast JSON string to all connected local browser WebSockets."""
    for ws in list(state.connected_local_clients):
        try:
            await ws.send_text(message_str)
        except Exception:
            state.connected_local_clients.discard(ws)


async def remote_ws_forwarder_task():
    """
    Maintains persistent bidirectional connection to remote WebSocket (ws://10.24.211.68:8000/ws/telemetry).
    1. Sends outgoing telemetry batches queued from MQTT.
    2. Concurrently listens for incoming predictions and errors from Model M2.
    """
    while True:
        try:
            print(f"[Remote WS] Connecting to {REMOTE_WS_URL}...")
            async with websockets.connect(REMOTE_WS_URL, open_timeout=5, ping_interval=20) as ws:
                state.remote_ws_connected = True
                print(f"[Remote WS] Connected successfully to {REMOTE_WS_URL}")

                async def sender():
                    while True:
                        if state.ws_outbox_queue is None or not state.fallback_state.get("internet_enabled", True):
                            await asyncio.sleep(0.2)
                            continue
                        payload_str = await state.ws_outbox_queue.get()
                        await ws.send(payload_str)
                        state.ws_outbox_queue.task_done()

                async def receiver():
                    async for raw_message in ws:
                        try:
                            reply = json.loads(raw_message)
                            msg_type = reply.get("type")
                            if msg_type == "prediction":
                                level = reply.get("level", "unknown")
                                p = reply.get("p_crash", 0.0)
                                dev = reply.get("device_id")
                                lat_ms = reply.get("latency_ms", 0.0)
                                print(f"\n==================================================")
                                print(f" [REMOTE M2 PREDICTION] Dev: {dev} | LEVEL: {level.upper()} | p_crash: {p:.4f} | Latency: {lat_ms} ms")
                                print(f"==================================================\n")

                                state.latest_predictions_cache.insert(0, reply)
                                if len(state.latest_predictions_cache) > 20:
                                    state.latest_predictions_cache.pop()

                                # Store in MongoDB predictions collection
                                if db.predictions is not None:
                                    doc = dict(reply)
                                    doc["received_at"] = datetime.now(timezone.utc).isoformat()
                                    db.predictions.insert_one(doc)

                                # Broadcast to connected browser clients
                                await broadcast_to_local_clients(raw_message)

                            elif msg_type == "error":
                                print(f"[Remote WS Error] {reply.get('code')}: {reply.get('message')}")
                                await broadcast_to_local_clients(raw_message)
                            else:
                                await broadcast_to_local_clients(raw_message)

                        except Exception as e:
                            print(f"[Remote WS Receiver Error] {e}")

                sender_task = asyncio.create_task(sender())
                receiver_task = asyncio.create_task(receiver())

                done, pending = await asyncio.wait(
                    [sender_task, receiver_task],
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for t in pending:
                    t.cancel()

        except asyncio.CancelledError:
            state.remote_ws_connected = False
            break
        except Exception as e:
            state.remote_ws_connected = False
            print(f"[Remote WS Warning] Disconnected ({e}). Reconnecting in 3s...")
            await asyncio.sleep(3.0)
