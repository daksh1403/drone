# 🤖 Auto-Drone Wall Painter

> Autonomous drone system that detects unpainted areas on a wall and sprays them — no human piloting required.

Built as a **VIT Chennai Multi-Disciplinary Project**, this system combines a Pixhawk V6X flight controller running ArduCopter, a DroneKit-Python control layer, an ESP32-CAM for vision and spray actuation, and a Flask web backend with a real-time UI.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start (Simulation)](#quick-start-simulation)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Key Technical Decisions](#key-technical-decisions)
- [Documentation](#documentation)
- [License](#license)
- [Credits](#credits)

---

## Project Overview

The drone autonomously:

1. **Detects** unpainted (white) areas on a 10 × 10 m wall using computer vision.
2. **Plans** a serpentine flight path covering every unpainted cell.
3. **Flies** the mission in AUTO mode, crab-walking (strafing sideways) while always facing the wall.
4. **Sprays** paint at each unpainted cell via an ESP32-controlled pump.
5. **Streams** progress to a real-time web dashboard over Server-Sent Events (SSE).

### Wall Grid

The wall is divided into a **10 × 10 grid** of 1 m² cells. Each cell is classified as *painted* or *unpainted*. The drone traverses the grid in a serpentine pattern — even rows left-to-right, odd rows right-to-left — to minimise travel distance.

```
Col  0   1   2   3   4   5   6   7   8   9
Row ┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
 0  │ → │ → │ → │ → │ → │ → │ → │ → │ → │ → │  ← top (10 m)
    ├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
 1  │ ← │ ← │ ← │ ← │ ← │ ← │ ← │ ← │ ← │ ← │
    ├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
    │   ...serpentine continues...            │
    ├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
 9  │ → │ → │ → │ → │ → │ → │ → │ → │ → │ → │  ← bottom (1 m)
    └───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘
```

---

## Architecture

```
┌──────────────────┐         ┌─────────────────────────────┐
│  Browser (Web UI)│◄──SSE──►│  Flask Backend  (app.py)    │
│  index.html      │  HTTP   │  • Routes & API             │
└──────────────────┘         │  • PaintDetector            │
                             │  • Demo orchestrator        │
                             └────────────┬────────────────┘
                                          │
                                          ▼
                             ┌─────────────────────────────┐
                             │ DroneController              │
                             │ (drone_controller.py)        │
                             └────────────┬────────────────┘
                                          │ MAVLink (TCP :5762)
                                          ▼
                             ┌─────────────────────────────┐
                             │ Pixhawk V6X                 │
                             │ ArduCopter Firmware          │
                             └─────────────────────────────┘

Flask Backend ──── HTTP ────► ESP32-CAM (192.168.4.1)
                              • Camera capture
                              • Spray pump relay
```

| Connection               | Protocol        | Default Port / Address |
|--------------------------|-----------------|------------------------|
| Browser ↔ Flask          | HTTP + SSE      | `http://127.0.0.1:5000` |
| Flask → DroneController  | In-process call | —                      |
| DroneController → SITL   | MAVLink TCP     | `127.0.0.1:5762`       |
| Mission Planner → SITL   | MAVLink TCP     | `127.0.0.1:5760`       |
| Flask → ESP32-CAM        | HTTP            | `192.168.4.1`          |

---

## Features

| Category | Feature |
|----------|---------|
| **Simulation** | Full sim mode — no hardware needed. SITL provides a virtual Pixhawk. |
| **One-Click Demo** | Press *Run Demo* in the web UI to detect, plan, fly, and spray automatically. |
| **Paint Detection** | 6-method weighted vote: adaptive threshold, brightness, saturation, Otsu, LAB lightness, blurred threshold. |
| **Flight Path** | Serpentine pattern across the grid; skips already-painted cells. |
| **Crab-Walking** | AUTO mission mode + `WP_YAW_BEHAVIOR=0` + `DO_SET_ROI` keeps the drone facing the wall while strafing. |
| **Telemetry Mapping** | Real-time GPS → grid-cell conversion displayed on the web UI. |
| **KML Overlay** | `generate_kml.py` produces a KML/KMZ for Mission Planner's map view. |
| **SSE Streaming** | Server-Sent Events push `moving`, `done`, and `complete` messages to the browser in real time. |

---

## Quick Start (Simulation)

### Prerequisites

- **Python 3.10+** (tested on 3.14)
- **ArduPilot SITL** ([install guide](https://ardupilot.org/dev/docs/setting-up-sitl-on-linux.html))

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/auto-drone.git
cd auto-drone

# 2. Install Python dependencies
pip install flask dronekit future opencv-python numpy requests pymavlink

# 3. Start ArduPilot SITL (in a separate terminal)
sim_vehicle.py -v ArduCopter --map --console -j4

# 4. Launch the Flask backend
python app.py
#    → Flask runs on http://127.0.0.1:5000
#    → Connects to SITL on port 5762

# 5. Open the web UI
#    Navigate to http://127.0.0.1:5000 in your browser

# 6. Click "Run Demo"
#    The drone will arm, take off, detect unpainted cells, and begin spraying.

# 7. (Optional) Connect Mission Planner on port 5760 to watch the flight live.
```

> **Python 3.14 Note:** `collections.MutableMapping` was removed in 3.14. The code monkey-patches it from `collections.abc` before importing DroneKit.

---

## Project Structure

```
auto-drone/
├── app.py                   # Flask backend: routes, PaintDetector, demo SSE endpoint
├── drone_controller.py      # DroneKit wrapper: connect, arm, mission upload, GPS math
├── auto.py                  # Standalone test-flight script (manual / dev use)
├── generate_kml.py          # KML/KMZ overlay generator for Mission Planner
├── templates/
│   └── index.html           # Web UI — single-page app with SSE grid
├── docs/
│   ├── HARDWARE_SETUP.md    # Wiring, bill of materials, assembly
│   ├── ESP32_PROGRAMMING.md # Flashing the ESP32-CAM firmware
│   ├── PIXHAWK_CONFIG.md    # ArduCopter parameter reference
│   ├── FLIGHT_OPERATIONS.md # Pre-flight checklist & safety procedures
│   └── API_REFERENCE.md     # All HTTP endpoints documented
├── workflow.md              # Original project specification
├── demo_wall.png            # Sample wall image for testing detection
├── wall_overlay.kml         # Pre-generated KML overlay
├── wall_overlay.kmz         # Pre-generated KMZ overlay
├── wall_overlay.png         # Overlay image asset
└── README.md                # ← You are here
```

---

## Configuration

All tuneable parameters live at the top of **`app.py`**:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SIMULATION_MODE` | `True` | `True` = skip real ESP32 calls; `False` = talk to real hardware |
| `ESP32_IP` | `192.168.4.1` | IP address of the ESP32-CAM WiFi access point |
| `SPRAY_DURATION_MS` | `200` | How long the spray pump fires per cell (milliseconds) |
| `GRID_ROWS` | `10` | Number of altitude levels (vertical divisions) |
| `GRID_COLS` | `10` | Number of horizontal passes (horizontal divisions) |
| `CELL_WIDTH_M` | `1.0` | Width and height of each grid cell (metres) |
| `PAINTING_ALTITUDE` | `10.0` | Altitude of the top row (metres AGL) |

To switch from simulation to real hardware, set `SIMULATION_MODE = False` and ensure the ESP32-CAM is reachable at `ESP32_IP`.

---

## How It Works

### 1. Detection

The ESP32-CAM (or a test image in sim mode) captures a photo of the wall. **`PaintDetector`** in `app.py` runs **six independent methods** to determine which cells are unpainted:

| # | Method | What It Looks For |
|---|--------|-------------------|
| 1 | Adaptive Threshold | Local contrast — bright patches vs. surroundings |
| 2 | Brightness Check | High V-channel in HSV → white/unpainted |
| 3 | Saturation Check | Low S-channel in HSV → colourless (white) |
| 4 | Otsu Threshold | Global optimal threshold on greyscale |
| 5 | LAB Lightness | High L-channel in CIELAB colour space |
| 6 | Blurred Threshold | Gaussian blur + binary threshold to reduce noise |

Each method casts a weighted vote per cell. The final decision is **majority vote** → binary grid of painted / unpainted.

### 2. Path Planning

Unpainted cells are ordered in a **serpentine** (boustrophedon) pattern:

- **Even rows (0, 2, 4, …):** left → right (columns 0 → 9)
- **Odd rows (1, 3, 5, …):** right → left (columns 9 → 0)

Only unpainted cells are included; painted cells are skipped.

### 3. Mission Upload

For each target cell, `DroneController` builds a MAVLink mission:

```
MAV_CMD_DO_SET_ROI          → Lock yaw toward the wall centre
MAV_CMD_NAV_WAYPOINT  (0)   → Cell (0,0) GPS position
MAV_CMD_NAV_WAYPOINT  (1)   → Cell (0,1) GPS position
...
MAV_CMD_NAV_WAYPOINT  (N)   → Last unpainted cell
MAV_CMD_NAV_RETURN_TO_LAUNCH
```

The parameter `WP_YAW_BEHAVIOR` is set to **0** (Never change yaw), and `DO_SET_ROI` points the nose at the wall's centre. This combination enables **crab-walking** — the drone strafes horizontally without rotating.

### 4. Flight Execution

The flight controller is switched to **AUTO** mode. The drone follows each waypoint sequentially. Progress is tracked via `vehicle.commands.next`, which indicates the current waypoint index.

### 5. Spray Actuation

When the drone arrives at a cell waypoint, the backend sends an HTTP request to the ESP32-CAM:

```
GET http://<ESP32_IP>/spray?duration=200
```

The ESP32 fires the relay-controlled spray pump for the configured duration.

### 6. Real-Time UI

The browser subscribes to an SSE stream at `/demo-stream`. Events:

| Event | Payload | Meaning |
|-------|---------|---------|
| `moving` | `{ row, col }` | Drone is heading toward cell (row, col) |
| `done` | `{ row, col }` | Cell (row, col) has been sprayed |
| `complete` | `{}` | Mission finished, drone returning to launch |

The web UI updates the 10 × 10 grid in real time — cells turn yellow while in-progress and green when done.

---

## Key Technical Decisions

### AUTO Mode over GUIDED Mode

**Problem:** In GUIDED mode, ArduCopter auto-rotates the drone's yaw to point toward each new waypoint. This makes crab-walking (strafing while facing the wall) impossible.

**Solution:** Use **AUTO** mission mode with:
- `WP_YAW_BEHAVIOR = 0` — never change yaw automatically
- `MAV_CMD_DO_SET_ROI` — lock the nose toward the wall's centre point

This lets the drone strafe left/right and up/down while always facing the wall.

### SET_POSITION_TARGET_GLOBAL_INT type_mask

During GUIDED-mode experiments, a bug was discovered in the `type_mask` bitfield:

- **Bit 10** controls yaw (0 = use yaw field, 1 = ignore)
- **Bit 11** controls yaw rate

The bits were initially swapped, causing unexpected yaw behaviour. This was one of the reasons the project migrated to AUTO mode with ROI.

### Python 3.14 Compatibility

DroneKit internally uses `collections.MutableMapping`, which was removed in Python 3.12+. The codebase applies a **monkey-patch** before importing DroneKit:

```python
import collections
import collections.abc
collections.MutableMapping = collections.abc.MutableMapping
```

---

## Documentation

Detailed guides are available in the [`docs/`](docs/) directory:

| Document | Description |
|----------|-------------|
| [`HARDWARE_SETUP.md`](docs/HARDWARE_SETUP.md) | Bill of materials, wiring diagrams, physical assembly |
| [`ESP32_PROGRAMMING.md`](docs/ESP32_PROGRAMMING.md) | Flashing firmware to the ESP32-CAM module |
| [`PIXHAWK_CONFIG.md`](docs/PIXHAWK_CONFIG.md) | ArduCopter parameter list and tuning notes |
| [`FLIGHT_OPERATIONS.md`](docs/FLIGHT_OPERATIONS.md) | Pre-flight checklist and safety procedures |
| [`API_REFERENCE.md`](docs/API_REFERENCE.md) | Complete HTTP API endpoint reference |

> **Note:** Some documentation files are still being written. See [`workflow.md`](workflow.md) for the original project specification.

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Credits

**VIT Chennai — Multi-Disciplinary Project**

Built with [ArduPilot](https://ardupilot.org/), [DroneKit-Python](https://dronekit-python.readthedocs.io/), [Flask](https://flask.palletsprojects.com/), and [OpenCV](https://opencv.org/).
