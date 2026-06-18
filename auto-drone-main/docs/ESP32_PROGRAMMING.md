# ESP32-CAM Programming Guide — Drone Painting System

The ESP32-CAM (AI Thinker board) is the drone's onboard vision and spray-control module. It runs a dual-port HTTP server:

| Port | Role | Endpoint examples |
|------|------|-------------------|
| **80** | Control server | `/ping`, `/capture_frame`, `/spray` |
| **81** | MJPEG stream server | `/stream` |

Port 80 handles low-latency command/response traffic. Port 81 delivers a continuous MJPEG video feed. They run on separate `WiFiServer` instances so the long-lived stream connection never blocks spray commands.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Arduino IDE | 2.x | Or PlatformIO (see note below) |
| ESP32 board package | Espressif Systems v2.x | Installed via Board Manager |
| USB cable | Micro-USB or USB-C | For the ESP32-S3 bridge board |

> **PlatformIO alternative:** If you prefer PlatformIO, set `board = esp32cam` in `platformio.ini` and use the `arduino` framework. The sketch code is identical.

---

## Board Setup in Arduino IDE

### 1. Add the ESP32 Board URL

**File → Preferences → Additional Board Manager URLs**, paste:

```
https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```

### 2. Install the Board Package

**Tools → Board → Board Manager** → search `esp32` → install **Espressif Systems v2.x**.

### 3. Select the Board

**Tools → Board → ESP32 Arduino → AI Thinker ESP32-CAM**

### 4. Partition Scheme

**Tools → Partition Scheme → Huge APP (3MB No OTA/1MB SPIFFS)**

The camera firmware is large. The default partition scheme will not fit — you **must** use the Huge APP scheme.

### 5. Flash Frequency

**Tools → Flash Frequency → 80 MHz**

---

## Flashing via ESP32-S3 (USB-to-Serial Bridge)

The ESP32-CAM has **no USB port**. You need an external USB-to-Serial adapter. Here we use an ESP32-S3 dev board as a bridge, but any 3.3 V FTDI/CP2102 adapter works identically.

### Step 1 — Flash the Bridge Sketch onto ESP32-S3

Upload the following sketch to your ESP32-S3 first (using its own USB port):

```cpp
// esp32s3_bridge.ino
// Turns the ESP32-S3 into a transparent USB ↔ UART bridge.
// GPIO17 = TX out to ESP32-CAM RX
// GPIO18 = RX in from ESP32-CAM TX

void setup() {
  Serial.begin(115200);                          // USB ↔ laptop
  Serial1.begin(115200, SERIAL_8N1, 18, 17);    // RX=GPIO18, TX=GPIO17 → ESP32-CAM
}

void loop() {
  while (Serial.available()) Serial1.write(Serial.read());
  while (Serial1.available()) Serial.write(Serial1.read());
}
```

### Step 2 — Wire ESP32-S3 to ESP32-CAM

```
ESP32-S3 GPIO17 (TX)  ──────►  ESP32-CAM U0R (RX)
ESP32-S3 GPIO18 (RX)  ◄──────  ESP32-CAM U0T (TX)
ESP32-S3 GND          ────────  ESP32-CAM GND
ESP32-S3 5V           ────────  ESP32-CAM 5V

ESP32-CAM IO0         ────────  GND   ◄── BOOT MODE JUMPER
```

> **CRITICAL:** The `IO0 → GND` jumper puts the ESP32-CAM into **flash/boot mode**. It must be connected **before** you power the board. Remove it **after** flashing.

### Step 3 — Flash the ESP32-CAM Firmware

1. Connect the ESP32-S3 to your laptop via USB.
2. In Arduino IDE, select the **ESP32-S3's COM port** (e.g., COM5).
3. Select the board **AI Thinker ESP32-CAM** (this tells the IDE which chip the compiled binary targets — the S3 is just a passthrough).
4. Click **Upload** to flash `esp32cam.ino` (full sketch below).
5. Wait for `Hard resetting via RTS pin...` in the console.
6. **Remove the IO0 → GND jumper.**
7. Press the **RST** button on the ESP32-CAM.
8. Open Serial Monitor at 115200 baud — you should see `WiFi AP started: PaintDrone`.
9. Disconnect the ESP32-S3. It is no longer needed; the ESP32-CAM runs standalone.

---

## ESP32-CAM Firmware — `esp32cam.ino`

This is the **complete** sketch. Copy it into a new Arduino project named `esp32cam`.

```cpp
// esp32cam.ino — PaintDrone ESP32-CAM Firmware
// Dual-port HTTP server: control on :80, MJPEG stream on :81
// Board: AI Thinker ESP32-CAM | Partition: Huge APP (3MB)

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

// ---------------------------------------------------------------------------
// Pin definitions — AI Thinker ESP32-CAM
// ---------------------------------------------------------------------------
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ---------------------------------------------------------------------------
// Relay / spray hardware
// ---------------------------------------------------------------------------
#define RELAY_PIN         13

// ---------------------------------------------------------------------------
// WiFi Access Point
// ---------------------------------------------------------------------------
const char* AP_SSID = "PaintDrone";
const char* AP_PASS = "";            // open network, no password

// ---------------------------------------------------------------------------
// Servers
// ---------------------------------------------------------------------------
WebServer controlServer(80);
WiFiServer streamServer(81);

// ---------------------------------------------------------------------------
// Spray state (non-blocking)
// ---------------------------------------------------------------------------
volatile bool     relayOn        = false;
volatile bool     continuousMode = false;
unsigned long     sprayEndTime   = 0;

// ---------------------------------------------------------------------------
// Forward declarations
// ---------------------------------------------------------------------------
void initCamera();
void setupControlRoutes();
void handleStream(WiFiClient client);

// ============================= setup() =====================================
void setup() {
  Serial.begin(115200);
  Serial.println();

  // Relay pin
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  // Camera
  initCamera();

  // WiFi AP
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("WiFi AP started: ");
  Serial.println(AP_SSID);
  Serial.print("IP address: ");
  Serial.println(WiFi.softAPIP());   // 192.168.4.1

  // Control server (port 80)
  setupControlRoutes();
  controlServer.begin();
  Serial.println("Control server started on port 80");

  // Stream server (port 81)
  streamServer.begin();
  Serial.println("Stream server started on port 81");
}

// ============================= loop() ======================================
void loop() {
  // --- Handle control HTTP requests ---
  controlServer.handleClient();

  // --- Non-blocking relay timer ---
  if (relayOn && !continuousMode && millis() >= sprayEndTime) {
    digitalWrite(RELAY_PIN, LOW);
    relayOn = false;
    Serial.println("Spray finished (timed)");
  }

  // --- Accept stream clients on port 81 ---
  WiFiClient streamClient = streamServer.available();
  if (streamClient) {
    Serial.println("Stream client connected");
    handleStream(streamClient);
    Serial.println("Stream client disconnected");
  }
}

// ============================= Camera Init =================================
void initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Use VGA (640x480) with 2 frame buffers for smooth streaming
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = 10;           // 0-63, lower = better quality
  config.fb_count     = 2;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init FAILED: 0x%x\n", err);
    // Halt — camera is essential
    while (true) { delay(1000); }
  }
  Serial.println("Camera initialized");
}

// ============================= Control Routes (Port 80) ====================
void setupControlRoutes() {

  // ---------- GET /ping ----------
  controlServer.on("/ping", HTTP_GET, []() {
    controlServer.send(200, "application/json", "{\"status\":\"ok\"}");
  });

  // ---------- GET /status ----------
  controlServer.on("/status", HTTP_GET, []() {
    String json = "{\"relay\":";
    json += relayOn ? "true" : "false";
    json += ",\"continuous\":";
    json += continuousMode ? "true" : "false";
    json += "}";
    controlServer.send(200, "application/json", json);
  });

  // ---------- GET /capture_frame ----------
  controlServer.on("/capture_frame", HTTP_GET, []() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
      controlServer.send(500, "application/json", "{\"error\":\"capture failed\"}");
      return;
    }
    controlServer.sendHeader("Content-Disposition", "inline; filename=frame.jpg");
    controlServer.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
  });

  // ---------- POST /spray ----------
  controlServer.on("/spray", HTTP_POST, []() {
    // Reject if already spraying
    if (relayOn) {
      controlServer.send(409, "application/json",
        "{\"error\":\"already spraying\"}");
      return;
    }

    // Parse duration_ms from POST body (default 500 ms)
    unsigned long duration = 500;
    if (controlServer.hasArg("duration_ms")) {
      duration = controlServer.arg("duration_ms").toInt();
    }
    // Clamp to sane range
    if (duration < 50)   duration = 50;
    if (duration > 5000) duration = 5000;

    // Fire relay (non-blocking)
    continuousMode = false;
    relayOn        = true;
    sprayEndTime   = millis() + duration;
    digitalWrite(RELAY_PIN, HIGH);

    Serial.printf("Spray: %lu ms\n", duration);

    String json = "{\"spray\":true,\"duration_ms\":";
    json += String(duration);
    json += "}";
    controlServer.send(200, "application/json", json);
  });

  // ---------- POST /spray_start ----------
  controlServer.on("/spray_start", HTTP_POST, []() {
    continuousMode = true;
    relayOn        = true;
    digitalWrite(RELAY_PIN, HIGH);
    Serial.println("Spray: continuous ON");
    controlServer.send(200, "application/json",
      "{\"spray\":true,\"continuous\":true}");
  });

  // ---------- POST /spray_stop ----------
  controlServer.on("/spray_stop", HTTP_POST, []() {
    continuousMode = false;
    relayOn        = false;
    digitalWrite(RELAY_PIN, LOW);
    Serial.println("Spray: OFF");
    controlServer.send(200, "application/json",
      "{\"spray\":false,\"continuous\":false}");
  });

  // ---------- 404 fallback ----------
  controlServer.onNotFound([]() {
    controlServer.send(404, "application/json",
      "{\"error\":\"not found\"}");
  });
}

// ============================= MJPEG Stream (Port 81) ======================
// The stream uses raw WiFiClient writes (not WebServer) because WebServer
// can only handle one request at a time and we need the control server free.

static const char* STREAM_CONTENT_TYPE =
  "multipart/x-mixed-replace; boundary=frame";
static const char* STREAM_BOUNDARY =
  "\r\n--frame\r\n";
static const char* STREAM_PART_HEADER =
  "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

void handleStream(WiFiClient client) {
  // Read and discard the HTTP request line & headers
  String request = client.readStringUntil('\r');
  // Only serve /stream
  if (request.indexOf("GET /stream") == -1) {
    client.println("HTTP/1.1 404 Not Found\r\n\r\n");
    client.stop();
    return;
  }
  // Consume remaining headers
  while (client.available()) { client.read(); }

  // Send HTTP response header
  client.println("HTTP/1.1 200 OK");
  client.printf("Content-Type: %s\r\n", STREAM_CONTENT_TYPE);
  client.println("Access-Control-Allow-Origin: *");
  client.println("Connection: keep-alive");
  client.println();

  // Stream frames until client disconnects
  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Stream: frame capture failed");
      continue;
    }

    // Boundary
    client.print(STREAM_BOUNDARY);

    // Part header with content length
    char partHeader[64];
    snprintf(partHeader, sizeof(partHeader), STREAM_PART_HEADER, fb->len);
    client.print(partHeader);

    // JPEG data
    client.write(fb->buf, fb->len);

    esp_camera_fb_return(fb);

    // Yield to let the control server handle requests
    delay(1);

    // Check if client is still there
    if (!client.connected()) break;
  }

  client.stop();
}
```

---

## Why Two Ports?

The MJPEG stream holds a TCP connection open **permanently** — the server writes frame after frame in an infinite loop until the client disconnects. If the control routes (`/spray`, `/capture_frame`, `/ping`) shared the same `WebServer` instance on port 80, they would be **blocked** for the entire duration of the stream because `WebServer` is single-threaded.

By running the stream on a separate `WiFiServer` on port 81:

- **Port 80** stays responsive. Spray commands get sub-millisecond handling.
- **Port 81** can saturate its connection with video data without starving control traffic.
- The two servers share the same `loop()`, but `WiFiServer.available()` is non-blocking — it only does work when a stream client actually connects.

```
┌──────────────┐         ┌──────────────────────┐
│  Laptop /    │ :80     │  WebServer           │
│  Raspberry   │────────►│  /ping /spray etc.   │
│  Pi          │         └──────────────────────┘
│              │ :81     ┌──────────────────────┐
│              │────────►│  WiFiServer          │
│              │         │  /stream (MJPEG)     │
└──────────────┘         └──────────────────────┘
       WiFi "PaintDrone"        ESP32-CAM
```

---

## Testing the ESP32-CAM

After flashing, removing the IO0 jumper, and pressing RST:

### 1. Connect to the WiFi AP

Look for **PaintDrone** in your WiFi list (phone or laptop). Connect — there is no password.

### 2. Ping the Board

```bash
curl http://192.168.4.1/ping
# Expected: {"status":"ok"}
```

### 3. Check Camera Status

```bash
curl http://192.168.4.1/status
# Expected: {"relay":false,"continuous":false}
```

### 4. Capture a Single Frame

```bash
curl -o frame.jpg http://192.168.4.1/capture_frame
# Opens as a 640×480 JPEG
```

### 5. Watch Live Video

Open in any browser:

```
http://192.168.4.1:81/stream
```

You should see a live MJPEG feed from the OV2640 camera.

### 6. Test the Spray Relay

```bash
# Timed spray (500 ms)
curl -X POST http://192.168.4.1/spray -d "duration_ms=500"
# Expected: {"spray":true,"duration_ms":500}
# The relay should click ON then OFF after 500 ms.

# Continuous spray
curl -X POST http://192.168.4.1/spray_start
# Expected: {"spray":true,"continuous":true}

curl -X POST http://192.168.4.1/spray_stop
# Expected: {"spray":false,"continuous":false}
```

### 7. Verify Dual-Port Independence

Open the stream in a browser (`http://192.168.4.1:81/stream`), then in a separate terminal:

```bash
curl http://192.168.4.1/ping
```

If you get `{"status":"ok"}` while the stream is running, dual-port isolation is working correctly.

---

## Troubleshooting

### No "PaintDrone" WiFi Network

| Check | Fix |
|-------|-----|
| IO0 still grounded | Remove the IO0→GND jumper and press RST |
| No power | Ensure 5V on the 5V pin (LED should blink on boot) |
| Wrong firmware | Re-flash; verify you selected AI Thinker ESP32-CAM board |

### Camera Init Failed (0x20001 / 0x105)

| Check | Fix |
|-------|-----|
| Wrong board selected | Must be **AI Thinker ESP32-CAM** — other ESP32 boards have different pin mappings |
| Dirty ribbon cable | Re-seat the OV2640 camera ribbon cable on the connector |
| Damaged camera module | Try a replacement OV2640 |

### Brownout / Constant Reboots

The ESP32-CAM draws up to **310 mA** during WiFi TX bursts and camera capture. Common power issues:

- **USB power through the S3 bridge** — often insufficient. Use a dedicated 5V/1A supply.
- **Long jumper wires** — cause voltage drop. Keep wires short (< 10 cm).
- **Add a 100 µF capacitor** across 5V and GND near the ESP32-CAM.

### Stream Freezes or Lags

| Setting | Current | Try |
|---------|---------|-----|
| `frame_size` | `FRAMESIZE_VGA` (640×480) | `FRAMESIZE_QVGA` (320×240) |
| `jpeg_quality` | `10` | `15` or `20` (higher = smaller files) |
| `fb_count` | `2` | `1` (saves RAM but may stutter) |

### Relay Doesn't Click

| Check | Fix |
|-------|-----|
| Relay VCC on 3.3V | Move to **5V** — most relay modules need 5V |
| Wrong GPIO | Confirm relay signal wire is on **GPIO 13** |
| GPIO 13 conflict | GPIO 13 is also the onboard LED on some boards — verify your module |
| Relay module type | Active-low modules need `LOW` to trigger — invert the logic if needed |

### Serial Monitor Shows Garbage

Baud rate mismatch. Set Serial Monitor to **115200 baud**.

---

## API Reference (Quick Summary)

### Control Server — Port 80

| Method | Path | Body | Response |
|--------|------|------|----------|
| `GET` | `/ping` | — | `{"status":"ok"}` |
| `GET` | `/status` | — | `{"relay":bool,"continuous":bool}` |
| `GET` | `/capture_frame` | — | JPEG image (`image/jpeg`) |
| `POST` | `/spray` | `duration_ms=N` | `{"spray":true,"duration_ms":N}` or `409` if busy |
| `POST` | `/spray_start` | — | `{"spray":true,"continuous":true}` |
| `POST` | `/spray_stop` | — | `{"spray":false,"continuous":false}` |

### Stream Server — Port 81

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/stream` | `multipart/x-mixed-replace` MJPEG stream |

---

## Hardware Reference

### AI Thinker ESP32-CAM Pinout (used in this firmware)

```
GPIO  0 — XCLK (also BOOT mode when grounded)
GPIO  5 — D0 (camera data)
GPIO 13 — Relay output
GPIO 18 — D1
GPIO 19 — D2
GPIO 21 — D3
GPIO 22 — PCLK
GPIO 23 — HREF
GPIO 25 — VSYNC
GPIO 26 — SDA (SCCB / I²C)
GPIO 27 — SCL (SCCB / I²C)
GPIO 32 — PWDN (camera power down)
GPIO 34 — D6
GPIO 35 — D7
GPIO 36 — D4
GPIO 39 — D5
```

### Relay Wiring

```
ESP32-CAM GPIO 13  ──────►  Relay IN
ESP32-CAM 5V       ──────►  Relay VCC
ESP32-CAM GND      ──────►  Relay GND
                             Relay COM  ──── Spray solenoid +
                             Relay NO   ──── Power supply +
```

The relay is wired **Normally Open (NO)** so the spray solenoid is off by default.
