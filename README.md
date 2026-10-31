# SolveX Blackbox Telemetry & Crash Response Controller

[![GitHub Organization](https://img.shields.io/badge/Org-Ahyaha--Solvex-blue.svg)](https://github.com/Ahyaha-Solvex)
[![Repository](https://img.shields.io/badge/GitHub-black--box--simulator-black?logo=github)](https://github.com/Ahyaha-Solvex/black-box-simulator)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python)](https://python.org)
[![ESP32](https://img.shields.io/badge/ESP32-PlatformIO%20%7C%20Arduino-E7352C.svg?logo=espressif)](https://espressif.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

High-rate vehicle blackbox telemetry pipeline, hardware firmware, and scenario injection engine for the **SolveX** crash response platform. Features 100 Hz IMU sampling, MQTT ingestion, 3-second MongoDB persistence, bidirectional WebSocket relay to the remote SolveX crash response server (`ws://10.24.211.68:8000/ws/telemetry`), live AI crash prediction display (Model M2), and a multi-tier emergency uplink ladder (GSM 2G SMS + LoRaWAN 868 MHz).

---

## Table of Contents

- [1. System Pipeline Architecture](#1-system-pipeline-architecture)
- [2. Multi-Tier Emergency Uplink Ladder](#2-multi-tier-emergency-uplink-ladder)
- [3. Remote Server Protocol & Buffer Requirements](#3-remote-server-protocol--buffer-requirements)
- [4. Telemetry Message Schema](#4-telemetry-message-schema)
- [5. Scenarios Library](#5-scenarios-library)
- [6. ESP32 Physical Blackbox Firmware](#6-esp32-physical-blackbox-firmware)
  - [Hardware Wiring & Pinout](#hardware-wiring--pinout)
  - [Flashing Firmware](#flashing-firmware)
- [7. Modular Codebase Architecture](#7-modular-codebase-architecture)
- [8. Installation & Quick Start](#8-installation--quick-start)
  - [Prerequisites](#prerequisites)
  - [Setup Backend](#setup-backend)
  - [Running the Web Dashboard](#running-the-web-dashboard)
  - [Running the Standalone CLI Simulator](#running-the-standalone-cli-simulator)
- [9. Configuration & Environment Variables](#9-configuration--environment-variables)
- [10. API Reference](#10-api-reference)

---

## 1. System Pipeline Architecture

```
                       [ Web Dashboard (http://localhost:8000/) ]
                                      │
                 (1) Select scenario & click Send / Step
                                      ▼
                           [ Scenario Player Engine ]
                                      │
                                      │ (100 Hz IMU batched every 1 second)
                                      ▼
                        [ MQTT Topic: vehicle/telemetry ]
                                      │
                                      ▼
                         [ FastAPI Backend (app.py) ]
                          │           │            │
                          │ (2)       │ (3)        │ (4)
                          ▼           ▼            ▼
             [ MongoDB (telemetry) ]  [ ws://10.24.211.68:8000/ws/telemetry ]  [ Local Browser WS ]
               Saved every 3s          Remote SolveX Crash Service               Dual 60fps Oscilloscopes
                                              │                                  JSON Wire Inspector
                                              │ (5) Model M2 Prediction
                                              ▼
                                   [ Crash Alert in UI & DB ]
```

---

## 2. Multi-Tier Emergency Uplink Ladder

In critical collision scenarios, primary internet connectivity (4G/LTE) is often damaged or unavailable in remote areas. The blackbox implements the **SolveX 3-Tier Uplink Ladder**:

```text
               [ 100 Hz IMU Sampler (ESP32 / Simulator) ]
                                   │
                         1-sec buffer aggregated
                                   ▼
                      [ Uplink Decision Engine ]
                                   │
           ┌───────────────────────┼────────────────────────┐
           │ (Nominal)             │ (Network Down)         │ (Impact > 3g)
           ▼                       ▼                        ▼
     [ Tier 1: MQTT ]     [ Tier 2: GSM 2G SMS ]    [ Tier 3: LoRa 868 MHz ]
     Wi-Fi / 4G Data      AT+CMGS 160-char MSD     18-Byte Binary Frame
     Topic: vehicle/telemetry  Protection Civile (+213)   EU868 SF7 / 125 kHz
```

| Tier | Technology | Bandwidth / Payload | Purpose | Trigger Condition |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **4G LTE / WebSocket** | Full 100 Hz IMU batches (~15 kB/s) | Primary live telematics & M2 ML inference | Nominal mobile internet available |
| **Tier 2** | **GSM 2G SMS Gateway** | 160-char SMS (`SOS\|lat,lon\|time\|SPD:x\|G:y...`) | eCall Minimum Set of Data (MSD) | 4G / Mobile Data lost (weak 2G coverage) |
| **Tier 3** | **LoRaWAN 868 MHz** | 18-byte packed big-endian binary (`>BHiibHI`) | Ultra long-range LPWAN emergency relay | Complete cellular outage / rural dead zone |

### Binary LoRaWAN Frame Layout (18 Bytes)

```
Offset  Size  Type       Field
+0      1 B   uint8      Type (0xFF = Crash Alert)
+1      2 B   uint16     Sequence Number
+3      4 B   int32      Latitude  (lat * 1,000,000)
+7      4 B   int32      Longitude (lon * 1,000,000)
+11     1 B   uint8      Speed (km/h)
+12     2 B   int16      Peak Acceleration (g * 100)
+14     4 B   uint32     Unix Epoch Timestamp
```

---

## 3. Remote Server Protocol & Buffer Requirements

According to the SolveX Crash Response protocol specifications:
1. **Trigger Condition**: Remote service monitors horizontal acceleration:
   $$\sqrt{a_x^2 + a_y^2} > 1.0\text{ g}$$
2. **Sliding Buffer**: Remote server requires **8 seconds before** the trigger and collects **8 seconds after** the trigger (16-second analysis window = 1,600 IMU rows).
3. **Lead-In Normal Driving**: To ensure the remote buffer is primed, the scenario player automatically synthesizes 10 seconds of nominal driving before event scenarios (`crash.json`, `trigger_no_crash.json`).
4. **M2 Ensemble Model**: Evaluates the 16-second window with LightGBM + 1D-CNN and replies over the WebSocket with:
   ```json
   {
     "type": "prediction",
     "device_id": "blackbox-01",
     "model": "m2",
     "level": "crash",
     "p_crash": 0.9989,
     "latency_ms": 28.6
   }
   ```

---

## 4. Telemetry Message Schema

Every 1-second batch follows this standard JSON schema:

```json
{
  "type": "telemetry",
  "device_id": "blackbox-01",
  "seq": 42,
  "recorded_at": "2026-10-31T10:00:00+01:00",
  "location": {
    "lat": 36.3741,
    "lon": 3.9012
  },
  "acc": [
    [-0.0012, 0.0025, 0.9851]
  ],
  "gyro": [
    [0.15, -0.22, 0.04]
  ],
  "gps_speed_kmh": 74.0
}
```
*Note: `acc` and `gyro` contain exactly 100 rows per batch (100 Hz strict sampling).*

---

## 5. Scenarios Library

Pre-recorded vehicle telemetry scenarios located in `scenarios/`:

- **`crash.json`**: 16-second severe deceleration impact collision (peak $5.69\text{ g}$). Triggers M2 crash classifier ($P(\text{crash}) \approx 99.9\%$).
- **`trigger_no_crash.json`**: 16-second hard jolt/pothole (peak $1.57\text{ g} > 1\text{ g}$). Evaluated by M2 as safe non-crash ($P(\text{crash}) \approx 0.3\%$).
- **`normal.json`**: 16-second baseline nominal driving (peak $1.10\text{ g}$).
- **`normal_driving.json`**: Extended baseline nominal driving scenario.

---

## 6. ESP32 Physical Blackbox Firmware

The repository includes ready-to-flash embedded C++ firmware in `esp32/` for the physical telemetry unit.

### Hardware Wiring & Pinout

ESP32 DevKit V1 (30/38 pin) configuration:

| Peripheral | Module | ESP32 Pin | Details |
| :--- | :--- | :--- | :--- |
| **IMU (I2C)** | MPU-6050 / BMI088 | **GPIO 21** (`SDA`), **GPIO 22** (`SCL`) | 100 Hz strict 10 ms periodic sampling |
| **GNSS / GPS (UART2)** | NEO-6M / NEO-M8N | **GPIO 16** (`RX2`), **GPIO 17** (`TX2`) | 9600 baud, NMEA sentences parsing |
| **Cellular Modem (UART1)** | SIM800L / SIM7600 | **GPIO 4** (`RX1`), **GPIO 2** (`TX1`) | AT commands, 2G SMS eCall MSD |
| **LoRa Radio (SPI)** | SX1276 / SX1278 (Ra-02) | **GPIO 18** (`SCK`), **GPIO 19** (`MISO`), **GPIO 23** (`MOSI`), **GPIO 5** (`NSS`), **GPIO 14** (`RST`), **GPIO 26** (`DIO0`) | 868 MHz / 433 MHz LPWAN binary frame |
| **Status Indicator** | Built-in Blue LED | **GPIO 2** | Toggles during batch transmission |

> [!TIP]
> **No physical sensors connected yet?** The firmware auto-detects the absence of an MPU-6050 at boot and falls back to an internal realistic vehicle dynamics generator. You can flash a bare ESP32 board and immediately receive live 100 Hz telemetry!

### Flashing Firmware

#### Using PlatformIO (Recommended)
```bash
cd esp32
pio run -t upload
pio device monitor -b 115200
```

#### Using Arduino IDE
1. Open `esp32/esp32_blackbox/esp32_blackbox.ino`.
2. Board: **ESP32 Dev Module**.
3. Install libraries: `PubSubClient`, `TinyGPSPlus`, `LoRa`.
4. Update `config.h` with your Wi-Fi credentials and MQTT broker IP.
5. Click **Upload** and monitor at **115200 baud**.

---

## 7. Modular Codebase Architecture

```text
black-box-simulator/
├── app.py                     # FastAPI entrypoint, lifespan lifecycle & CORS setup
├── requirements.txt           # Python package dependencies
├── server.py                  # Standalone CLI 100 Hz MQTT telemetry simulator
├── core/
│   ├── config.py              # Centralized environment variables, DB constants, and paths
│   ├── state.py               # Singleton state (caches, queues, flags, fallback statistics)
│   ├── database.py            # MongoDB connection pool & collection handles
│   ├── models.py              # Pydantic request models
│   ├── player.py              # Scenario player engine & multi-phase normal driving synthesizer
│   ├── fallback.py            # GSM 2G SMS and LoRaWAN 868 MHz binary codec & dispatchers
│   ├── hardware.py            # Hardware health diagnostics (CPU thermals, RAM, IMU, GPS, Power)
│   ├── mqtt_service.py        # MQTT ingestion client and 3-second database persistence
│   └── remote_ws.py           # Remote WebSocket forwarder to M2 service & local browser broadcaster
├── routers/
│   ├── health_router.py       # /api/status, /box/health diagnostics routes
│   ├── player_router.py       # /api/scenarios and /api/player/* playback control routes
│   ├── telemetry_router.py    # /api/telemetry/*, /api/predictions/*, and /ws/telemetry stream
│   └── fallback_router.py     # /api/fallback/* outage simulation and inbound webhook routes
├── esp32/
│   ├── platformio.ini         # PlatformIO build definition
│   ├── main.cpp               # PlatformIO C++ firmware entrypoint
│   ├── config.h               # Hardware pinouts, baud rates, and Wi-Fi credentials
│   ├── README.md              # Detailed embedded setup & wiring manual
│   └── esp32_blackbox/
│       ├── esp32_blackbox.ino # Arduino IDE compatible sketch
│       └── config.h           # Arduino sketch configuration
├── scenarios/                 # Pre-recorded driving and crash scenarios (JSON)
└── templates/
    └── index.html             # High-performance dashboard with oscilloscopes and control deck
```

---

## 8. Installation & Quick Start

### Prerequisites
- Python 3.10 or newer
- Mosquitto MQTT Broker (`sudo apt install mosquitto mosquitto-clients`)
- MongoDB (`mongodb-org` running locally on port 27017, optional for persistence)

### Setup Backend

```bash
# 1. Clone repository
git clone https://github.com/Ahyaha-Solvex/black-box-simulator.git
cd black-box-simulator

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Running the Web Dashboard

```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at **`http://localhost:8000/`** to view:
- 60 FPS dual-axis real-time oscilloscopes (Accelerometer $g$ & Gyroscope $^\circ/\text{s}$).
- Scenario playback controls (Play, Pause, Step, Loop, Speed).
- Real-time SolveX Model M2 AI crash prediction confidence meter.
- Emergency Uplink Outage Simulator (4G/LTE, 2G SMS, and LoRaWAN fallback).
- Hardware diagnostics and sensor health monitors.

### Running the Standalone CLI Simulator

```bash
# Continuous realistic synthetic driving:
python3 server.py --device-id blackbox-01 --speed 74.0

# Replay a specific scenario file directly via MQTT:
python3 server.py --scenario scenarios/crash.json
```

---

## 9. Configuration & Environment Variables

All settings can be configured via environment variables or [.env](file:///home/mnwr/Desktop/black_box_simulator/core/config.py):

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `MQTT_HOST` | `localhost` | MQTT Broker hostname or IP |
| `MQTT_PORT` | `1883` | MQTT Broker port |
| `MQTT_TOPIC` | `vehicle/telemetry` | Telemetry topic for ingestion |
| `REMOTE_WS_URL` | `ws://10.24.211.68:8000/ws/telemetry` | SolveX remote crash classification endpoint |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection URI |
| `MONGO_DB` | `telemetry_db` | MongoDB database name |
| `SCENARIOS_DIR` | `scenarios` | Directory containing scenario JSON files |

---

## 10. API Reference

### Core Dashboard & Scenario Control
- `GET /` — Web Dashboard (Oscilloscopes, Scenario Selector, AI Prediction Panel, Fallback Simulation Deck)
- `GET /box/health` (or `/box-health`, `/api/box/health`) — **Blackbox Hardware Health & Diagnostics** (CPU, temp, RAM, IMU 100 Hz, GPS lock, 12V bus & LiPo backup battery, 4G modem & 2G SMS fallback, eMMC circular buffer, uplink ladder)
- `GET /api/status` — Status of MQTT, Remote WS (`10.24.211.68`), and MongoDB
- `GET /api/scenarios` — Available scenario files and peak-g / speed metadata
- `POST /api/player/start` — Start scenario playback (`scenario`, `speed_multiplier`, `loop`, `device_id`, `lead_in_normal`)
- `POST /api/player/pause` — Pause playback
- `POST /api/player/resume` — Resume playback
- `POST /api/player/stop` — Stop and reset playback
- `POST /api/player/step` — Advance scenario by 1 second
- `GET /api/player/status` — Current playback state, phase, and progress
- `GET /api/predictions/latest` — Latest AI predictions returned by remote M2 model
- `GET /api/predictions/history` — Historical predictions stored in MongoDB
- `GET /api/telemetry/latest` — Latest telemetry batch
- `GET /api/telemetry/history` — Historical 3-second batches stored in MongoDB
- `WS /ws/telemetry` — Local WebSocket streaming 100 Hz waveforms, M2 alerts, and fallback events

### Emergency Uplink & Fallback Simulation (GSM SMS & LoRaWAN)
- `GET /api/fallback/status` — Current active uplink tier, network simulation state, and transmission statistics
- `POST /api/fallback/simulate` — Configure simulated channel states (`internet_enabled`, `gsm_enabled`, `lorawan_enabled`)
- `POST /api/fallback/sms/send` — Manually dispatch a simulated GSM 2G SMS emergency packet
- `POST /api/fallback/sms/inbound` — Webhook for incoming SMS messages (compatible with Android SMS Gateway & Termux)
- `POST /api/fallback/lorawan/send` — Manually dispatch a simulated 18-byte LoRaWAN binary packet
- `POST /api/fallback/lorawan/uplink` — Webhook for LoRaWAN Network Server uplinks (ChirpStack / TTN / RSU gateway)
- `GET /api/fallback/history` — Historical log of all fallback transmissions and received messages

---

<p align="center">
  Part of the <b>SolveX Crash Response Ecosystem</b> &bull; Maintained by <a href="https://github.com/Ahyaha-Solvex">Ahyaha-Solvex</a>
</p>
