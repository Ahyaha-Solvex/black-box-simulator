"""
Centralized Configuration and Environment Settings
"""

import os

# --- MongoDB Configuration ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "telemetry_db")
MONGO_TELEMETRY_COLLECTION = os.getenv("MONGO_COLLECTION", "telemetry")
MONGO_PREDICTIONS_COLLECTION = "predictions"
MONGO_FALLBACK_COLLECTION = "fallback_events"
MONGO_SMS_INBOX_COLLECTION = "sms_inbox"
MONGO_LORAWAN_INBOX_COLLECTION = "lorawan_inbox"

# --- MQTT Broker Configuration ---
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "vehicle/telemetry")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fastapi_telemetry_hub")

# --- Remote ML WebSocket Forwarder ---
REMOTE_WS_URL = os.getenv("REMOTE_WS_URL", "ws://10.24.211.68:8000/ws/telemetry")

# --- Telemetry & System Parameters ---
DB_SAVE_INTERVAL_SEC = 3.0
SCENARIOS_DIR = os.getenv("SCENARIOS_DIR", "scenarios")
TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "templates")
