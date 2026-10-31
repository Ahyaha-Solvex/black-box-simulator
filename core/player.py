"""
Blackbox Scenario Playback Engine
Loads, normalizes, and replays pre-recorded vehicle dynamics scenarios over MQTT.
"""

import asyncio
from datetime import datetime, timezone
import json
import math
import os
from typing import Optional

from core.config import MQTT_TOPIC, SCENARIOS_DIR
from core.state import state


def load_scenario_chunks(filepath: str) -> list[dict]:
    """
    Loads any scenario file and normalizes it into a list of 1-second chunks.
    Handles both:
    1. A list of 16 message dicts (from solvex-crash-response examples).
    2. A flat dict with 1600 rows (e.g. normal_driving.json).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks = []
    if isinstance(data, list):
        for item in data:
            chunks.append({
                "acc": item.get("acc", []),
                "gyro": item.get("gyro", []),
                "gps_speed_kmh": item.get("gps_speed_kmh"),
                "location": item.get("location"),
                "type": item.get("type", "telemetry"),
            })
    elif isinstance(data, dict):
        acc = data.get("acc", [])
        gyro = data.get("gyro", [])
        speeds = data.get("gps_speed_kmh", [])
        total_s = max(len(speeds), len(acc) // 100, 1)
        for s in range(total_s):
            chunks.append({
                "acc": acc[s * 100 : (s + 1) * 100],
                "gyro": gyro[s * 100 : (s + 1) * 100],
                "gps_speed_kmh": speeds[s] if s < len(speeds) else 0.0,
                "location": None,
                "type": "telemetry",
            })
    return chunks


class ScenarioPlayer:
    """
    Controls scenario playback with support for:
    - Prepending 10s lead-in normal driving (essential for M2 8s pre-crash window)
    - Post-event normal driving for non-crash triggers (so the after-window finishes)
    - Speed multiplier control (0.5x, 1.0x, 2.0x, fast)
    - Stepping 1s at a time
    - Publishing directly to MQTT broker
    """

    EARTH_RADIUS = 6371000.0

    def __init__(self):
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.current_scenario: str = ""
        self.playlist: list[dict] = []
        self.current_index: int = 0
        self.seq: int = 0
        self.loop: bool = False
        self.lead_in_normal: bool = True
        self.speed_multiplier: float = 1.0
        self.device_id: str = "blackbox-01"
        self.lat: float = 36.3741
        self.lon: float = 3.9012
        self._task: Optional[asyncio.Task] = None

    def build_playlist(self, filename: str, lead_in: bool = True) -> list[dict]:
        filepath = os.path.join(SCENARIOS_DIR, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Scenario file '{filename}' not found")

        scenario_chunks = load_scenario_chunks(filepath)
        playlist = []

        is_event_scenario = ("crash" in filename or "trigger" in filename)

        # 1. Prepend 10 seconds of normal driving if requested
        if lead_in and is_event_scenario:
            normal_path = os.path.join(SCENARIOS_DIR, "normal.json")
            if not os.path.exists(normal_path):
                normal_path = os.path.join(SCENARIOS_DIR, "normal_driving.json")

            if os.path.exists(normal_path):
                normal_chunks = load_scenario_chunks(normal_path)
                for i in range(10):
                    idx = i % len(normal_chunks)
                    chunk = dict(normal_chunks[idx])
                    chunk["phase"] = "leadin"
                    chunk["phase_index"] = i + 1
                    chunk["phase_total"] = 10
                    playlist.append(chunk)

        # 2. Add event chunks
        for i, chunk in enumerate(scenario_chunks):
            ch = dict(chunk)
            ch["phase"] = "event"
            ch["phase_index"] = i + 1
            ch["phase_total"] = len(scenario_chunks)
            playlist.append(ch)

        # 3. If trigger_no_crash, append post-event driving so 8s post window finishes
        if "trigger_no_crash" in filename:
            normal_path = os.path.join(SCENARIOS_DIR, "normal.json")
            if os.path.exists(normal_path):
                normal_chunks = load_scenario_chunks(normal_path)
                for i in range(15):
                    idx = i % len(normal_chunks)
                    chunk = dict(normal_chunks[idx])
                    chunk["phase"] = "postevent"
                    chunk["phase_index"] = i + 1
                    chunk["phase_total"] = 15
                    playlist.append(chunk)

        return playlist

    def load_scenario(self, filename: str, lead_in: bool = True):
        self.playlist = self.build_playlist(filename, lead_in=lead_in)
        self.current_scenario = filename
        self.lead_in_normal = lead_in
        self.current_index = 0

    def send_step(self) -> Optional[dict]:
        """Send a single 1-second batch (100 acc, 100 gyro) to MQTT."""
        if not self.playlist:
            return None

        if self.current_index >= len(self.playlist):
            if self.loop:
                self.current_index = 0
            else:
                self.is_playing = False
                return None

        chunk = self.playlist[self.current_index]
        self.seq += 1

        acc_rows = chunk.get("acc", [])
        gyro_rows = chunk.get("gyro", [])
        speed_val = chunk.get("gps_speed_kmh")
        if speed_val is None:
            speed_val = 0.0

        # Advance location along heading ~80 deg if location not explicitly in chunk
        if chunk.get("location") and chunk["location"].get("lat"):
            self.lat = chunk["location"]["lat"]
            self.lon = chunk["location"]["lon"]
        else:
            v_ms = (speed_val or 0.0) / 3.6
            d_lat = (v_ms * 0.17 / self.EARTH_RADIUS) * (180.0 / math.pi)
            d_lon = (v_ms * 0.98 / (self.EARTH_RADIUS * math.cos(math.radians(self.lat)))) * (180.0 / math.pi)
            self.lat += d_lat
            self.lon += d_lon

        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        message = {
            "type": "telemetry",
            "device_id": self.device_id,
            "seq": self.seq,
            "recorded_at": now_iso,
            "location": {
                "lat": round(self.lat, 6),
                "lon": round(self.lon, 6),
            },
            "acc": acc_rows,
            "gyro": gyro_rows,
            "gps_speed_kmh": round(speed_val, 1) if speed_val is not None else None,
            # Metadata for browser UI HUD
            "_phase": chunk.get("phase", "event"),
            "_phase_index": chunk.get("phase_index", self.current_index + 1),
            "_phase_total": chunk.get("phase_total", len(self.playlist)),
            "_scenario": self.current_scenario,
        }

        # Transmit to MQTT broker
        if state.mqtt_client:
            payload_str = json.dumps(message)
            state.mqtt_client.publish(MQTT_TOPIC, payload_str, qos=1)

        self.current_index += 1
        return message

    async def _playback_loop(self):
        try:
            while self.is_playing:
                if self.is_paused:
                    await asyncio.sleep(0.1)
                    continue

                msg = self.send_step()
                if msg is None:
                    break

                delay = max(0.02, 1.0 / self.speed_multiplier)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        finally:
            self.is_playing = False

    def start(
        self,
        filename: str,
        loop: bool = False,
        speed_multiplier: float = 1.0,
        device_id: str = "blackbox-01",
        lead_in: bool = True,
    ):
        if self._task and not self._task.done():
            self._task.cancel()

        if self.current_scenario != filename or self.current_index >= len(self.playlist) or self.lead_in_normal != lead_in:
            self.load_scenario(filename, lead_in=lead_in)

        self.loop = loop
        self.speed_multiplier = speed_multiplier
        self.device_id = device_id
        self.is_playing = True
        self.is_paused = False
        ev_loop = state.main_event_loop or asyncio.get_running_loop()
        self._task = ev_loop.create_task(self._playback_loop())

    def pause(self):
        if self.is_playing:
            self.is_paused = True

    def resume(self):
        if self.is_playing:
            self.is_paused = False

    def stop(self):
        self.is_playing = False
        self.is_paused = False
        if self._task and not self._task.done():
            self._task.cancel()
        self.current_index = 0

    def status(self) -> dict:
        current_chunk = self.playlist[self.current_index - 1] if 0 < self.current_index <= len(self.playlist) else None
        return {
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "current_scenario": self.current_scenario,
            "current_index": self.current_index,
            "total_steps": len(self.playlist),
            "phase": current_chunk.get("phase", "idle") if current_chunk else "idle",
            "phase_index": current_chunk.get("phase_index", 0) if current_chunk else 0,
            "phase_total": current_chunk.get("phase_total", len(self.playlist)) if current_chunk else len(self.playlist),
            "seq": self.seq,
            "loop": self.loop,
            "speed_multiplier": self.speed_multiplier,
            "device_id": self.device_id,
            "lead_in_normal": self.lead_in_normal,
        }


# Global player singleton
player = ScenarioPlayer()
