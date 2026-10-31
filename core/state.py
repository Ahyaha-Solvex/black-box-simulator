"""
Global Application State, In-Memory Caches, and Event Loops
"""

import asyncio
from typing import Any, Optional
from fastapi import WebSocket


class AppState:
    """Encapsulates in-memory caches, connection states, and synchronization handles."""

    def __init__(self):
        # Local browser WebSocket subscribers
        self.connected_local_clients: set[WebSocket] = set()

        # Telemetry & Prediction Caches
        self.latest_telemetry_cache: dict[str, dict[str, Any]] = {}
        self.latest_predictions_cache: list[dict[str, Any]] = []

        # Connection health
        self.mqtt_connected: bool = False
        self.remote_ws_connected: bool = False
        self.last_db_save_time: float = 0.0

        # Multi-tier Emergency Uplink Fallback Configuration & Counters
        self.fallback_state: dict[str, Any] = {
            "internet_enabled": True,       # Tier 1: 4G LTE Mobile Data / Remote WS
            "gsm_enabled": True,            # Tier 2: GSM 2G SMS eCall MSD
            "lorawan_enabled": True,        # Tier 3: LoRaWAN 868 MHz LPWAN
            "auto_fallback": True,          # Auto-fallback when higher tiers are offline
            "emergency_recipient": "+213-555-PROTECTION-CIVILE",
            "device_msisdn": "+213-555-BLACKBOX-01",
            "lorawan_dev_eui": "SX1262-BB-01-ALGERIA",
            "lorawan_gateway_eui": "AA555A000001FFFE",
        }

        self.fallback_stats: dict[str, int] = {
            "primary_packets": 0,
            "sms_sent": 0,
            "lorawan_sent": 0,
            "sms_received": 0,
            "lorawan_received": 0,
        }

        self.latest_fallback_events: list[dict[str, Any]] = []

        # Async coordination handles
        self.main_event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws_outbox_queue: Optional[asyncio.Queue] = None
        self.mqtt_client: Optional[Any] = None


# Global state singleton
state = AppState()
