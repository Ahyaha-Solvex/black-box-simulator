#!/usr/bin/env python3
"""
FastAPI Telemetry Hub & Blackbox Scenario Controller
Modular application entrypoint.
"""

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from core.config import TEMPLATES_DIR
from core.database import db
from core.mqtt_service import start_mqtt, stop_mqtt
from core.player import player
from core.remote_ws import remote_ws_forwarder_task
from core.state import state
from routers.fallback_router import router as fallback_router
from routers.health_router import router as health_router
from routers.player_router import router as player_router
from routers.telemetry_router import router as telemetry_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.main_event_loop = asyncio.get_running_loop()
    state.ws_outbox_queue = asyncio.Queue(maxsize=1000)

    # 1. Connect to MongoDB
    db.connect()

    # 2. Start MQTT background consumer
    start_mqtt()

    # 3. Start background outgoing WebSocket forwarder & receiver
    ws_task = asyncio.create_task(remote_ws_forwarder_task())

    yield

    # Shutdown
    print("[Shutdown] Cleaning up...")
    ws_task.cancel()
    player.stop()
    stop_mqtt()
    db.close()
    print("[Shutdown] Completed.")


app = FastAPI(
    title="Blackbox Telemetry Hub & Controller",
    description="Scenario Injector, MQTT Ingestion, Remote WebSocket Forwarder & MongoDB Storage",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    """Serves the Blackbox Scenario Controller Web Dashboard."""
    template_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Blackbox Controller: templates/index.html not found</h1>"


# Include Modular Subsystem Routers
app.include_router(health_router)
app.include_router(player_router)
app.include_router(telemetry_router)
app.include_router(fallback_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
