#pragma once

#include <Arduino.h>

// ==============================================================================
// 1. VEHICLE & DEVICE IDENTIFICATION
// ==============================================================================
#define DEVICE_ID               "blackbox-01"
#define TELEMETRY_TYPE          "telemetry"

// ==============================================================================
// 2. SENSOR SAMPLING SPECIFICATIONS
// ==============================================================================
#define IMU_SAMPLE_RATE_HZ      100       // 100 Hz strict 10ms sampling
#define SAMPLES_PER_SECOND      100       // Exactly 100 [x,y,z] rows per message
#define IMU_SAMPLE_INTERVAL_MS  (1000 / IMU_SAMPLE_RATE_HZ)

// ==============================================================================
// 3. NETWORK: WI-FI & MQTT BROKER CONFIGURATION
// ==============================================================================
#define WIFI_SSID               "SolveX_AP"
#define WIFI_PASSWORD           "solve_crash_2026"

// IP address or hostname of the machine running Mosquitto / FastAPI backend
#define MQTT_BROKER_HOST        "10.24.211.68"  // Update with your backend server IP
#define MQTT_BROKER_PORT        1883
#define MQTT_TELEMETRY_TOPIC    "vehicle/telemetry"
#define MQTT_BUFFER_SIZE        8192            // Crucial: 100 samples JSON is ~4.5 KB

// ==============================================================================
// 4. HARDWARE PIN DEFINITIONS (ESP32 DevKit V1)
// ==============================================================================
// --- I2C: 6-DoF IMU (MPU-6050 / BMI088) ---
#define I2C_SDA_PIN             21
#define I2C_SCL_PIN             22
#define MPU6050_I2C_ADDR        0x68

// --- UART2: GNSS / GPS Module (NEO-6M / NEO-M8N) ---
#define GPS_RX_PIN              16    // ESP32 RX2 connects to GPS TX
#define GPS_TX_PIN              17    // ESP32 TX2 connects to GPS RX
#define GPS_BAUD_RATE           9600

// --- UART1: GSM 2G / 4G Cellular Modem (SIM800L / SIM7600) ---
#define GSM_RX_PIN              4     // ESP32 RX1 connects to Modem TX
#define GSM_TX_PIN              2     // ESP32 TX1 connects to Modem RX
#define GSM_BAUD_RATE           9600
#define EMERGENCY_SMS_RECIPIENT "+213555123456" // Protection Civile / Emergency Dispatch

// --- SPI: LoRa Radio (SX1276 / SX1278 / SX1262) ---
#define LORA_SCK_PIN            18
#define LORA_MISO_PIN           19
#define LORA_MOSI_PIN           23
#define LORA_CS_PIN             5
#define LORA_RST_PIN            14
#define LORA_DIO0_PIN           26
#define LORA_BAND_HZ            868E6 // EU868 (or 915E6 for US915 / 433E6)

// --- On-board Diagnostics & Indicators ---
#define STATUS_LED_PIN          2     // Built-in blue LED on ESP32 DevKit
#define BUZZER_PIN              15    // Optional crash acoustic beacon

// ==============================================================================
// 5. CRASH DETECTION ACCELERATION THRESHOLDS (in g)
// ==============================================================================
#define G_CRASH_THRESHOLD       3.0f  // Triggers immediate Tier 2 / Tier 3 eCall alert
#define G_JOLT_THRESHOLD        1.0f  // Triggers M2 Remote Sliding Window Classifier
