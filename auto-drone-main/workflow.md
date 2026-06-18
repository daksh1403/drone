# 🎨 Autonomous Drone Painting System — Complete Workflow

**VIT Chennai | Multi-Disciplinary Project**

---

## 1. What the System Does (Big Picture)

The system autonomously detects unpainted areas on a wall using a camera, divides
the wall into a grid, and sends a spray mechanism (mounted on a drone or cardboard)
to paint each unpainted cell automatically — without a human manually controlling
where to spray.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GROUND (Laptop)                          │
│                                                                 │
│   Browser (Web App)  ◄──►  Flask Backend (app.py)              │
│        │                          │                             │
│        │                    PaintDetector                       │
│        │                  (detection code)                      │
└────────┼──────────────────────────┼────────────────────────────┘
         │ WiFi (PaintDrone)         │ WiFi (PaintDrone)
         │                          │
┌────────▼──────────────────────────▼────────────────────────────┐
│                     ESP32-CAM (On Drone)                       │
│                                                                 │
│   Port 81: /stream  (live MJPEG video)                         │
│   Port 80: /ping    (health check)                             │
│            /capture_frame  (single photo)                       │
│            /spray   (fire pump for Xms)                        │
│            /spray_start  (continuous ON)                        │
│            /spray_stop   (continuous OFF)                       │
│                                                                 │
│   GPIO 13 ──► Relay ──► 12V Pump ──► Spray Nozzle             │
└─────────────────────────────────────────────────────────────────┘
         │
         │ MAVLink (USB / ETH / 433MHz radio)
         │
┌────────▼────────────────────────────────────────────────────────┐
│                  Pixhawk V6X (Flight Controller)               │
│                  Firmware: ArduCopter                          │
│                  GPS: HERE3 NEO 3m                             │
│                  Mode: GUIDED (programmatic waypoints)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Hardware Components — What Each One Does

### ESP32-CAM (AI Thinker)
- The brain of the spray payload
- Creates the "PaintDrone" WiFi hotspot (IP: 192.168.4.1)
- Streams live video from its OV2640 camera (640×480 @ ~20fps)
- Receives spray commands from Flask via HTTP
- Fires GPIO 13 HIGH/LOW to trigger the relay
- Runs two simultaneous HTTP servers (port 80 + port 81) so
  the stream never blocks the spray signal

### ESP32-S3 (used only for flashing)
- Acts as a USB-to-Serial bridge
- Lets you upload code to the ESP32-CAM using a USB-C cable
- Not used at all once the ESP32-CAM is flashed
- Connects: ESP32-S3 GPIO17(TX) → ESP32-CAM U0R(RX)
            ESP32-S3 GPIO18(RX) → ESP32-CAM U0T(TX)

### Relay Module (Active HIGH)
- An electronically controlled switch
- When ESP32-CAM GPIO 13 goes HIGH → relay coil energises → switch closes
- When GPIO 13 goes LOW → switch opens → pump stops
- Needs 5V on its VCC pin (not 3.3V) to physically click

### 12V Water Pump
- Sprays paint/water when relay switch is closed
- Powered from drone battery (11.1V 3S LiPo) via buck converter
- Buck converter steps down 11.1V → 5V for ESP32-CAM
            and 11.1V → 12V kept as-is for pump

### Pixhawk V6X (Flight Controller)
- Controls all 6 motors of the hexacopter
- Runs ArduCopter firmware
- In GUIDED mode: accepts GPS waypoints from DroneKit (Python)
- Has USB, Ethernet, and 433MHz telemetry radio for laptop connection
- Connected to HERE3 NEO 3m GPS for precision positioning

### HERE3 NEO 3m GPS
- High-precision GPS/GNSS module
- Gives the drone its real-world GPS coordinates
- Required for GUIDED mode autonomous flight

### 433MHz SiK Telemetry Radio
- Long range radio link (up to 1-2km)
- Connects laptop to Pixhawk wirelessly outdoors
- Laptop has ground radio (USB) → drone has air radio
- Carries MAVLink protocol messages

### Hexacopter Frame + ESCs + Motors
- 6-arm drone frame with 6 brushless motors
- Rubicon ESCs control each motor speed
- Provides the flight platform and carries the spray payload

---

## 4. Software Components — What Each File Does

### esp32cam.ino (Arduino — runs on ESP32-CAM)
```
What it does:
  1. Creates WiFi hotspot "PaintDrone" at 192.168.4.1
  2. Initialises OV2640 camera at 640×480 JPEG
  3. Runs control server on port 80:
       GET  /ping          → returns {"status":"ok"}
       GET  /status        → returns relay state
       GET  /capture_frame → sends one JPEG photo
       POST /spray         → fires relay for duration_ms
       POST /spray_start   → relay ON continuously
       POST /spray_stop    → relay OFF immediately
  4. Runs stream server on port 81:
       GET  /stream        → continuous MJPEG video

Why two ports?
  The MJPEG stream holds a connection open permanently.
  If everything ran on one port, /spray would never get
  a response while streaming. Port 81 isolates the stream.

Relay logic:
  /spray      → non-blocking timer using millis()
              → GPIO13 HIGH → wait duration_ms → GPIO13 LOW
  /spray_start → GPIO13 HIGH, flag continuousMode=true
              → loop() never auto-shutoff in continuous mode
  /spray_stop  → GPIO13 LOW, continuousMode=false
```

### esp32s3.ino (Arduino — runs on ESP32-S3, used once)
```
What it does:
  Bridges USB serial from laptop to ESP32-CAM's UART
  Every byte from USB → Serial1 (TX→ESP32-CAM RX)
  Every byte from ESP32-CAM → USB → Arduino IDE

Why needed?
  ESP32-CAM has no USB port. The ESP32-S3 acts as a
  USB-to-Serial adapter (same as an FTDI module) to
  allow Arduino IDE to flash code onto the ESP32-CAM.

After flashing: ESP32-S3 is completely disconnected.
```

### app.py (Python Flask — runs on laptop)
```
What it does:
  Serves the web UI and acts as the middle layer between
  the browser and the ESP32-CAM / Pixhawk.

Routes:
  GET  /
    → Serves index.html to the browser

  GET  /video_feed
    → Proxies MJPEG stream from http://192.168.4.1:81/stream
    → Browser can't talk to ESP32-CAM directly (CORS issues)
    → Flask fetches and forwards the stream bytes

  POST /capture
    → Calls http://192.168.4.1/capture_frame
    → Gets one JPEG from ESP32-CAM
    → Runs PaintDetector on it
    → Builds 8×12 boolean grid of unpainted cells
    → Returns base64 image + grid + cell count to browser

  POST /spray_sequence  (precision mode)
    → Receives list of cells [[row,col],[row,col]...]
    → For each cell:
        Sends SSE event "moving" → browser shows countdown
        Waits 3 seconds (manual) OR flies drone to position
        Sends SSE event "spraying"
        POSTs to http://192.168.4.1/spray with duration_ms
        Waits for spray to finish
        Sends SSE event "done"
    → Sends SSE event "complete" when all done

  POST /spray_sequence_continuous  (continuous mode)
    → Groups cells by row
    → For each row:
        Flies drone to start of row
        POSTs /spray_start to ESP32-CAM (pump ON)
        Drone flies slowly across entire row
        POSTs /spray_stop to ESP32-CAM (pump OFF)
    → RTL when done

  POST /drone/connect
    → Connects to Pixhawk via DroneKit
    → Accepts USB / ETH / 433MHz connection string

  GET  /drone/status
    → Returns telemetry: altitude, lat, lon, battery, mode

  POST /drone/arm_takeoff
    → Arms drone, switches to GUIDED, takes off

  POST /drone/land / /drone/rtl
    → Land or Return to Launch
```

### drone_controller.py (Python — imported by app.py)
```
What it does:
  Wraps DroneKit library to control Pixhawk V6X

Key functions:
  connect()         → connect to Pixhawk via DroneKit
  arm_and_takeoff() → arm, switch GUIDED, takeoff to altitude
  goto_global()     → fly to GPS lat/lon/alt waypoint
  wait_until_reached() → block until drone arrives at position
  return_to_launch() → RTL mode
  offset_to_gps()   → converts meter offsets to GPS coordinates
  cells_to_waypoints() → converts grid (row,col) to GPS positions
  group_cells_by_row() → groups cells for continuous painting

GPS math:
  The wall's starting corner GPS coordinate is the "origin".
  Each grid column = 30cm east offset from origin.
  Each grid row = 30cm altitude offset above painting altitude.
  This converts pixel grid positions to real GPS waypoints.
```

### PaintDetector class (Python — inside app.py)
```
What it does:
  Takes a camera frame (BGR image) and finds white/unpainted areas.

How it works (6 methods combined):
  1. Adaptive threshold  → finds locally bright areas
  2. Relative brightness → compares to average frame brightness
  3. Saturation mask     → white = low colour saturation
  4. Otsu threshold      → automatic global threshold
  5. LAB colour space    → analyses luminance channel
  6. Blurred threshold   → reduces noise before thresholding

  All 6 masks are weighted and combined:
    adaptive×0.30 + relative×0.20 + saturation×0.25
    + otsu×0.10 + lab×0.10 + blur×0.05

  Morphological cleanup removes noise (open + close operations)
  Contours are extracted and scored by confidence
  Returns binary mask + list of detected regions

Build grid from mask:
  Divides mask into 8 rows × 12 columns
  Each cell: if ≥40% pixels are white → cell is "unpainted"
  Returns 8×12 boolean grid
```

### index.html (Browser — served by Flask)
```
What it does:
  Single-page web app with 4 modes:

  LIVE MODE:
    Shows /video_feed stream from Flask
    Green dot = ESP32-CAM reachable (pings every 3 seconds)
    "Capture & Detect" button

  GRID MODE (after capture):
    Shows frozen captured image
    8×12 grid overlay drawn on HTML canvas
    Green cells = auto-detected unpainted areas
    Yellow cells = manually toggled by user
    Click any cell to toggle ON/OFF
    "Start Auto Spray" button

  SPRAYING MODE (after clicking spray):
    Current cell blinks orange
    Large countdown: 3...2...1
    "SPRAYING 💦" appears when pump fires
    Completed cells turn blue
    Progress bar shows overall completion
    Uses EventSource (SSE) to receive real-time updates from Flask

  COMPLETE MODE:
    Shows total cells painted
    "Start New Session" resets everything
```

---

## 5. Complete Step-by-Step Workflow

### Phase 1 — Setup (done once)
```
1. Flash ESP32-S3 with programmer sketch
2. Wire ESP32-S3 to ESP32-CAM (TX→RX, RX→TX, GND, 5V, IO0→GND)
3. Flash ESP32-CAM with esp32cam.ino
4. Disconnect ESP32-S3 (not needed anymore)
5. Wire relay to ESP32-CAM GPIO 13
6. Wire pump to relay COM/NO
7. Connect buck converter: battery → 5V for ESP32-CAM + relay
8. Install Python packages: pip install -r requirements.txt
9. Run Flask: python app.py
```

### Phase 2 — Ground Test (cardboard prototype)
```
1. Power on ESP32-CAM → PaintDrone WiFi hotspot appears
2. Connect laptop to PaintDrone WiFi
3. Open browser → http://localhost:5000
4. Live camera feed visible → green dot = online
5. Point camera at white wall section
6. Click "Capture & Detect"
   → Flask grabs frame → PaintDetector runs → grid appears
   → Green cells = unpainted areas detected
7. Adjust grid cells if needed (click to toggle)
8. Click "Start Auto Spray"
   → Cell 1 blinks orange
   → 3-second countdown (move cardboard to position)
   → Pump fires 800ms
   → Cell turns blue, move to next cell
   → Repeat until all cells done
```

### Phase 3 — Drone Integration
```
1. Mount ESP32-CAM + relay + pump on drone
2. Power from drone battery via buck converter
3. Connect laptop to Pixhawk:
   Indoor testing → USB cable or Ethernet
   Outdoor flight → 433MHz telemetry radio
4. Open browser → http://localhost:5000
5. Click "Connect Drone" → enter connection string
   (e.g. COM5 for radio, udp:192.168.1.1:14550 for ETH)
6. Flask calls drone_controller.py → DroneKit connects to Pixhawk
7. Verify green drone status (altitude, GPS, battery shown)
8. Point ESP32-CAM at wall → Capture & Detect
9. Select spray mode:
   PRECISION: drone flies to each cell, hovers, sprays, moves on
   CONTINUOUS: drone flies along each row with pump ON the whole time
10. Click "Start Auto Spray" with use_drone=true
    → Flask sends GPS waypoints to Pixhawk via DroneKit
    → Drone flies to position
    → Flask sends /spray to ESP32-CAM
    → Pump fires
    → Drone moves to next cell
    → Repeat
11. All cells done → drone RTL (Return to Launch)
```

---

## 6. Communication Flow Diagram

```
CAPTURE FLOW:
Browser → POST /capture → Flask
Flask → GET /capture_frame → ESP32-CAM port 80
ESP32-CAM takes photo → sends JPEG bytes
Flask → PaintDetector → builds 8×12 grid
Flask → returns {image, grid, cell_count} → Browser
Browser draws grid overlay on canvas

SPRAY FLOW (precision, manual):
Browser → POST /spray_sequence {cells:[...]} → Flask
Flask → SSE event "moving cell 1" → Browser (shows countdown)
Flask waits 3 seconds
Flask → SSE event "spraying" → Browser
Flask → POST /spray {duration_ms:800} → ESP32-CAM port 80
ESP32-CAM → GPIO13 HIGH → relay closes → pump ON
800ms passes → GPIO13 LOW → relay opens → pump OFF
ESP32-CAM → {"sprayed":true} → Flask
Flask → SSE event "done cell 1" → Browser (cell turns blue)
Repeat for next cell...

SPRAY FLOW (drone mode):
Browser → POST /spray_sequence {cells, use_drone:true, origin_lat, origin_lon}
Flask → drone_controller.cells_to_waypoints() → GPS coordinates
Flask → drone.goto_global(lat, lon, alt) → DroneKit
DroneKit → MAVLink waypoint → Pixhawk V6X
Pixhawk → moves drone to position
Flask → waits until drone arrives
Flask → POST /spray → ESP32-CAM → pump fires
Flask → drone moves to next cell

CONTINUOUS SPRAY FLOW:
Flask → group_cells_by_row() → rows of cells
For each row:
  Flask → drone.goto_global(row start position)
  Flask → POST /spray_start → ESP32-CAM → pump ON indefinitely
  Flask → drone.goto_global(row end position) at slow speed
  Drone flies across row while pump sprays
  Flask → POST /spray_stop → ESP32-CAM → pump OFF
  Move to next row
All rows done → drone RTL
```

---

## 7. Network Architecture

### Phase 1 (Ground / Cardboard):
```
ESP32-CAM creates WiFi AP "PaintDrone" (192.168.4.1)
Laptop connects to PaintDrone WiFi (gets IP 192.168.4.2)
Flask runs on laptop port 5000
Browser talks to Flask: http://localhost:5000
Flask talks to ESP32-CAM: http://192.168.4.1
```

### Phase 2 (Drone — Indoor ETH):
```
Laptop ──ETH cable──► Pixhawk V6X ETH port
Flask uses DroneKit: udp:192.168.1.1:14550
ESP32-CAM still on PaintDrone WiFi
Laptop still connected to PaintDrone WiFi
```

### Phase 3 (Drone — Outdoor 433MHz):
```
Laptop USB → 433MHz ground radio module
Drone 433MHz air radio → Pixhawk UART
DroneKit connection string: "COM5" or "/dev/ttyUSB0"
Range: up to 1-2km
ESP32-CAM WiFi → still PaintDrone hotspot
(for longer range ESP32-CAM WiFi: upgrade to long-range router)
```

---

## 8. Spray Modes Comparison

| Feature | Precision Mode | Continuous Mode |
|---|---|---|
| Movement | Stop at each cell | Fly along row |
| Pump | ON/OFF per cell (800ms) | ON for entire row |
| Coverage | Cell by cell | Row by row |
| Accuracy | High | Medium |
| Speed | Slower | Much faster |
| Best for | Small/scattered areas | Large continuous areas |
| Drone required | Optional (can be manual) | Required |

---

## 9. Key Parameters (Easy to Tune)

All these can be changed without re-flashing:

| Parameter | File | Variable | Default |
|---|---|---|---|
| Spray duration | app.py | SPRAY_DURATION_MS | 800ms |
| Countdown time | app.py | time.sleep(3) | 3 seconds |
| Painting altitude | drone_controller.py | PAINTING_ALTITUDE | 3.0m |
| Cell real size | drone_controller.py | CELL_WIDTH_M | 0.3m |
| Continuous speed | drone_controller.py | CONTINUOUS_SPEED | 0.3 m/s |
| Detection sensitivity | app.py | sensitivity=50 | 50 (0-100) |
| Grid size | app.py | GRID_ROWS/COLS | 8×12 |
| JPEG quality | esp32cam.ino | jpeg_quality | 10 |

---

## 10. Safety Features

- Relay auto-shutoff: in precision mode, relay always turns OFF
  after duration_ms even if Flask crashes (hardware timer in ESP32)
- Spray already-in-progress guard: /spray returns 409 if relay
  is already active, preventing double-fire
- DroneKit pre-flight check: verifies GPS fix, battery level,
  and arm status before takeoff
- RTL on completion: drone automatically returns home after all
  cells are painted
- Retry logic: Flask retries spray command 3 times before giving
  up on a cell, ensuring reliability over WiFi
