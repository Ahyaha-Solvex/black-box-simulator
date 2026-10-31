# SolveX Blackbox ESP32 Firmware

Embedded C++ firmware for the SolveX vehicle telematics unit ("blackbox-01"). Samples a 6-DoF IMU at a strict 100 Hz (10 ms period), captures GPS/GNSS coordinates, aggregates 1-second batches (100 rows `[ax,ay,az]` in g, 100 rows `[gx,gy,gz]` in deg/s), and transmits to the FastAPI backend via MQTT with autonomous GSM 2G SMS and LoRaWAN fallback.

---

## 1. Hardware Pinout & Wiring Guide

### ESP32 DevKit V1 (30/38 Pin) Connections:

| Peripheral | Sensor / Module | ESP32 Pin | Function / Description |
| :--- | :--- | :--- | :--- |
| **IMU (I2C)** | MPU-6050 / BMI088 | **GPIO 21** | `SDA` (Data) |
| | | **GPIO 22** | `SCL` (Clock) |
| | | **3V3 / GND** | Power & Ground |
| **GNSS / GPS (UART2)** | NEO-6M / NEO-M8N | **GPIO 16** | `RX2` (Connects to GPS **TX**) |
| | | **GPIO 17** | `TX2` (Connects to GPS **RX**) |
| | | **VCC / GND** | 3.3V or 5V (Module dependent) |
| **Cellular Modem (UART1)** | SIM800L / SIM7600 | **GPIO 4** | `RX1` (Connects to Modem **TX**) |
| | | **GPIO 2** | `TX1` (Connects to Modem **RX**) |
| | | **VBAT / GND** | 3.8V - 4.2V external 2A peak source |
| **LoRa Radio (SPI)** | SX1276 / SX1278 (Ra-02) | **GPIO 18** | `SCK` |
| | | **GPIO 19** | `MISO` |
| | | **GPIO 23** | `MOSI` |
| | | **GPIO 5** | `NSS / CS` |
| | | **GPIO 14** | `RST` |
| | | **GPIO 26** | `DIO0` |
| | | **3V3 / GND** | 3.3V ONLY |
| **Status Indicator** | Built-in Blue LED | **GPIO 2** | Toggles HIGH during 1-sec batch transmission |

> [!NOTE]
> If physical sensors are not yet wired, the firmware **automatically detects the absence of MPU-6050** at boot and activates an internal realistic vehicle dynamics generator. You can flash the code to a bare ESP32 and see live 100 Hz telemetry arriving at your backend immediately!

---

## 2. Multi-Tier Telematics Uplink Engine

```text
               [ 100 Hz IMU Sampler (FreeRTOS Core 0) ]
                                  │
                       100 rows / sec buffer
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

### Uplink Specifications:
1. **Tier 1 (MQTT)**: Publishes the full 1-second batch (100 acc, 100 gyro, lat, lon, speed) as JSON (~4.5 KB).
2. **Tier 2 (GSM 2G SMS)**: Dispatches standard 160-char eCall MSD:
   `SOS|36.3741,3.9012|12:00:00|SPD:74|G:5.69|SEV:CRITICAL|OCC:1|ID:blackbox-01`
3. **Tier 3 (LoRaWAN 868 MHz)**: Transmits 18-byte packed big-endian binary frame (`>BHiibHI`):
   - `0xFF` (Type: Crash)
   - `uint16_t seq`
   - `int32_t lat * 1,000,000`
   - `int32_t lon * 1,000,000`
   - `uint8_t speed_kmh`
   - `int16_t peak_g * 100`
   - `uint32_t epoch`

---

## 3. How to Compile & Flash

### Option A: Using PlatformIO (Recommended)
```bash
cd esp32
pio run -t upload
pio device monitor -b 115200
```

### Option B: Using Arduino IDE
1. Open Arduino IDE.
2. Go to **File -> Open** and select `esp32/esp32_blackbox/esp32_blackbox.ino`.
3. Select board: **ESP32 Dev Module** (from ESP32 by Espressif).
4. Install required libraries from Library Manager:
   - `PubSubClient` (by Nick O'Leary)
   - `TinyGPSPlus` (by Mikal Hart) - *Optional for GPS*
   - `LoRa` (by Sandeep Mistry) - *Optional for LoRa*
5. In `config.h`, update `WIFI_SSID`, `WIFI_PASSWORD`, and `MQTT_BROKER_HOST` with your machine's IP address.
6. Click **Upload** and open Serial Monitor at **115200 baud**.
