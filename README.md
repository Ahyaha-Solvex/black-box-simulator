# SolveX Blackbox Telemetry & Crash Response Controller

High-rate vehicle blackbox telemetry pipeline with scenario injection, MQTT ingestion, 3-second MongoDB persistence, bidirectional WebSocket relay to the remote SolveX crash response server (`ws://10.24.211.68:8000/ws/telemetry`), and live AI crash prediction display (Model M2).

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

## 2. Remote Server Protocol & Buffer Requirements

According to [`solvex-crash-response`](https://github.com/AbderrahimZineddineEsi/solvex-crash-response):
1. **Trigger Condition**: Remote server monitors horizontal acceleration $\sqrt{a_x^2 + a_y^2} > 1.0\text{ g}$.
2. **Sliding Buffer**: Remote server requires **8 seconds before** the trigger and collects **8 seconds after** the trigger.
3. **Lead-In Normal Driving**: To ensure the remote buffer is primed, the controller automatically prepends 10 seconds of normal driving before event scenarios (`crash.json`, `trigger_no_crash.json`).
4. **M2 Ensemble Model**: Evaluates the 16-second window with LightGBM + 1D-CNN and replies with:
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

## 3. Telemetry Message Schema

Every 1-second batch follows this exact format:

```json
{
  "type": "telemetry",
  "device_id": "blackbox-01",
  "seq": 42,
  "recorded_at": "2026-10-30T11:05:00+01:00",
  "location": {
    "lat": 36.3741,
    "lon": 3.9012
  },
  "acc": [
    // 100 rows of [x, y, z] in g
    [-0.0012, 0.0025, 0.9851]
  ],
  "gyro": [
    // 100 rows of [x, y, z] in deg/s
    [0.15, -0.22, 0.04]
  ],
  "gps_speed_kmh": 74.0
}
```

---

## 4. Available Scenarios (`scenarios/`)

- **`crash.json`**: 16-second severe deceleration impact collision (peak $5.69\text{ g}$). Triggers M2 crash classifier ($P(\text{crash}) \approx 99.9\%$).
- **`trigger_no_crash.json`**: 16-second hard jolt/pothole (peak $1.57\text{ g} > 1\text{ g}$). Evaluated by M2 as safe non-crash ($P(\text{crash}) \approx 0.3\%$).
- **`normal.json`**: 16-second baseline nominal driving (peak $1.10\text{ g}$).
- **`normal_driving.json`**: 16-second baseline nominal driving.

---

## 5. Modular Codebase Architecture

The codebase is organized into cleanly partitioned subsystems and FastAPI routers:

```text
Solvex3/
├── app.py                     # Thin FastAPI entrypoint (~80 lines), lifespan & CORS configuration
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
├── scenarios/                 # Pre-recorded driving and crash scenarios (JSON)
├── templates/
│   └── index.html             # High-performance dashboard with oscilloscopes and control deck
└── server.py                  # Standalone CLI 100 Hz MQTT telemetry simulator
```

---

## 6. How to Run

### 1. Launch the Backend Server
```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Open **`http://localhost:8000/`** in your browser.

### 2. (Optional) Run the Standalone CLI Simulator
```bash
# Synthetic dynamics:
python3 server.py --device-id blackbox-01 --speed 74.0

# Replay scenario:
python3 server.py --scenario scenarios/crash.json
```

---

## 7. API Endpoints

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

## 8. Multi-Tier Emergency Uplink Ladder

Based on Section S6 of the SolveX Crash Response Plan:

| Tier | Technology | Bandwidth / Payload | Purpose | Trigger Condition |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **4G LTE / WebSocket** | Full 100 Hz IMU batches (~15 kB/s) | Primary live telematics & M2 ML inference | Nominal mobile internet available |
| **Tier 2** | **GSM 2G SMS Gateway** | 160-char SMS (`SOS\|lat,lon\|time\|SPD:x\|G:y...`) | eCall Minimum Set of Data (MSD) | 4G / Mobile Data lost (weak 2G coverage) |
| **Tier 3** | **LoRaWAN 868 MHz** | 18-byte packed binary frame (`>BHiibHI`) | Ultra long-range LPWAN emergency relay | Complete cellular outage / rural dead zone |
