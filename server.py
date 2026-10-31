#!/usr/bin/env python3
"""
Vehicle Telemetry Simulator (MQTT)
Simulates high-rate (100 Hz) vehicle sensor readings (accelerometer in g, gyroscope in deg/s)
and GPS telemetry, packaging 1-second batches (100 rows each) into the exact JSON schema
expected by the backend and external WebSocket services.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
import random
import sys
import time
import paho.mqtt.client as mqtt

try:
    from core.player import load_scenario_chunks
except ImportError:
    def load_scenario_chunks(filepath: str) -> list[dict]:
        """Loads any scenario file and normalizes it into a list of 1-second chunks."""
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


class VehicleDynamics:
    """Simulates realistic vehicle motion, road vibration, and GPS positioning."""

    EARTH_RADIUS = 6371000.0  # meters

    def __init__(
        self,
        start_lat: float = 36.3741,
        start_lon: float = 3.9012,
        initial_speed_kmh: float = 74.0,
        heading_deg: float = 80.0,
    ):
        self.lat = start_lat
        self.lon = start_lon
        self.speed_kmh = initial_speed_kmh
        self.target_speed_kmh = initial_speed_kmh
        self.heading = heading_deg
        self.time = 0.0

    def step(self, dt: float = 0.01) -> tuple[list[float], list[float]]:
        """Advance simulation by 0.01s (100 Hz) and return (acc_sample_g, gyro_sample_deg_s)."""
        self.time += dt

        # 1. Gentle speed random walk (e.g. 40 to 110 km/h)
        self.target_speed_kmh += random.gauss(0.0, 0.08)
        self.target_speed_kmh = max(20.0, min(120.0, self.target_speed_kmh))
        accel_rate = (self.target_speed_kmh - self.speed_kmh) * 0.1
        self.speed_kmh += accel_rate * dt
        self.speed_kmh = max(0.0, self.speed_kmh)

        # 2. Road curvature (yaw rate in deg/s)
        heading_rate = 1.2 * math.sin(self.time * 0.25)
        self.heading = (self.heading + heading_rate * dt) % 360.0

        # 3. Position update on Earth
        speed_ms = self.speed_kmh / 3.6
        heading_rad = math.radians(self.heading)
        d_north = speed_ms * math.cos(heading_rad) * dt
        d_east = speed_ms * math.sin(heading_rad) * dt

        d_lat = (d_north / self.EARTH_RADIUS) * (180.0 / math.pi)
        d_lon = (d_east / (self.EARTH_RADIUS * math.cos(math.radians(self.lat)))) * (180.0 / math.pi)
        self.lat += d_lat
        self.lon += d_lon

        # 4. Accelerometer simulation (specific force in m/s^2, then converted to g)
        vib_level = 0.04 + 0.12 * (self.speed_kmh / 100.0)
        forward_accel = accel_rate / 3.6  # m/s^2
        lateral_accel = speed_ms * math.radians(heading_rate)  # m/s^2

        ax_ms2 = forward_accel + random.gauss(0.0, vib_level)
        ay_ms2 = lateral_accel + random.gauss(0.0, vib_level)
        az_ms2 = 9.81 + random.gauss(0.0, vib_level * 1.5)  # gravity is +9.81 at rest

        # Convert to g (1 g = 9.81 m/s^2)
        ax_g = ax_ms2 / 9.81
        ay_g = ay_ms2 / 9.81
        az_g = az_ms2 / 9.81

        # 5. Gyroscope simulation (deg/s)
        gx = random.gauss(0.0, 0.4)
        gy = random.gauss(0.0, 0.4) - (forward_accel * 0.3)
        gz = heading_rate + random.gauss(0.0, 0.4)

        acc_sample = [round(ax_g, 4), round(ay_g, 4), round(az_g, 4)]
        gyro_sample = [round(gx, 2), round(gy, 2), round(gz, 2)]

        return acc_sample, gyro_sample


def main():
    parser = argparse.ArgumentParser(description="Simulate vehicle blackbox telemetry (100 Hz batch per second).")
    parser.add_argument("--host", default="localhost", help="MQTT broker host (default: localhost)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("--topic", default="vehicle/telemetry", help="MQTT topic (default: vehicle/telemetry)")
    parser.add_argument("--device-id", default="blackbox-01", help="Device identifier (default: blackbox-01)")
    parser.add_argument("--speed", type=float, default=74.0, help="Initial speed in km/h (default: 74.0)")
    parser.add_argument("--scenario", default=None, help="Scenario file to replay (e.g. crash.json, normal.json)")
    parser.add_argument("--loop", action="store_true", help="Loop scenario continuously")
    args = parser.parse_args()

    print("==================================================")
    print("      Blackbox 100 Hz Telemetry Simulator         ")
    print("==================================================")
    print(f" Broker    : {args.host}:{args.port}")
    print(f" Topic     : {args.topic}")
    print(f" Device ID : {args.device_id}")
    print(f" Initial   : Speed {args.speed:.1f} km/h")
    print(" Output    : 1-sec message with 100 rows acc/gyro")
    print("==================================================")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim_{args.device_id}")

    connected = False

    def on_connect(cl, userdata, flags, rc, properties=None):
        nonlocal connected
        if rc == 0:
            connected = True
            print(f"[MQTT] Connected successfully to {args.host}:{args.port}")
        else:
            print(f"[MQTT] Connection failed with code: {rc}")

    def on_disconnect(cl, userdata, flags, rc, properties=None):
        nonlocal connected
        connected = False
        print("[MQTT] Disconnected from broker.")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(args.host, args.port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[ERROR] Failed to connect to MQTT broker: {e}")
        print("Please ensure your MQTT broker (e.g. mosquitto) is running.")
        sys.exit(1)

    print("[MQTT] Waiting for broker handshake...")
    wait_start = time.time()
    while not connected and (time.time() - wait_start < 5.0):
        time.sleep(0.05)

    scenario_chunks = []
    if args.scenario:
        sc_path = args.scenario if os.path.exists(args.scenario) else os.path.join("scenarios", args.scenario)
        if not os.path.exists(sc_path):
            print(f"[ERROR] Scenario file not found: {sc_path}")
            sys.exit(1)
        scenario_chunks = load_scenario_chunks(sc_path)
        print(f"[Scenario Loaded] {sc_path} ({len(scenario_chunks)} seconds)")

    sim = VehicleDynamics(initial_speed_kmh=args.speed)
    seq = 0
    sec_idx = 0

    print("\nStarting transmission (1 batch / second). Press Ctrl+C to stop...\n")

    try:
        while True:
            t_start = time.time()
            seq += 1

            if scenario_chunks:
                if sec_idx >= len(scenario_chunks):
                    if args.loop:
                        sec_idx = 0
                    else:
                        print("\n[Scenario Finished] Completed all seconds.")
                        break

                chunk = scenario_chunks[sec_idx]
                acc_batch = chunk.get("acc", [])
                gyro_batch = chunk.get("gyro", [])
                gps_speed = chunk.get("gps_speed_kmh", 0.0)

                if chunk.get("location") and chunk["location"].get("lat"):
                    sim.lat = chunk["location"]["lat"]
                    sim.lon = chunk["location"]["lon"]
                else:
                    v_ms = (gps_speed or 0.0) / 3.6
                    d_lat = (v_ms * 0.17 / sim.EARTH_RADIUS) * (180.0 / math.pi)
                    d_lon = (v_ms * 0.98 / (sim.EARTH_RADIUS * math.cos(math.radians(sim.lat)))) * (180.0 / math.pi)
                    sim.lat += d_lat
                    sim.lon += d_lon

                sec_idx += 1
            else:
                # Synthetic dynamics
                acc_batch = []
                gyro_batch = []
                for _ in range(100):
                    a_row, g_row = sim.step(dt=0.01)
                    acc_batch.append(a_row)
                    gyro_batch.append(g_row)
                gps_speed = round(sim.speed_kmh, 1) if sim.speed_kmh >= 0.0 else None

            # Construct exact message payload
            now_iso = datetime.now(timezone.utc).astimezone().isoformat()
            message = {
                "type": "telemetry",
                "device_id": args.device_id,
                "seq": seq,
                "recorded_at": now_iso,
                "location": {
                    "lat": round(sim.lat, 6),
                    "lon": round(sim.lon, 6),
                },
                "acc": acc_batch,
                "gyro": gyro_batch,
                "gps_speed_kmh": round(gps_speed, 1) if gps_speed is not None else None,
            }

            payload_str = json.dumps(message)
            client.publish(args.topic, payload_str, qos=1)

            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"seq={seq:<5} | "
                f"Speed: {gps_speed if gps_speed is not None else 0.0:5.1f} km/h | "
                f"GPS: ({sim.lat:.4f}, {sim.lon:.4f}) | "
                f"acc: {len(acc_batch)} rows | "
                f"gyro: {len(gyro_batch)} rows"
            )

            # Sleep to maintain 1.0 second per message
            elapsed = time.time() - t_start
            sleep_time = max(0.0, 1.0 - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopping simulator...")
    finally:
        client.loop_stop()
        client.disconnect()
        print("Simulator stopped cleanly.")


if __name__ == "__main__":
    main()
