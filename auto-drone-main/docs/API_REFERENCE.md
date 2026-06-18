# API Reference — Wall-Painting Drone System

> Complete reference for every HTTP endpoint and programmatic API in the
> auto-drone project.

---

## Table of Contents

- [Flask Backend API (localhost:5000)](#flask-backend-api-localhost5000)
  - [Pages](#pages)
  - [ESP32-CAM Proxy](#esp32-cam-proxy)
  - [Detection](#detection)
  - [Drone Control](#drone-control)
  - [Spray Control](#spray-control)
  - [Demo](#demo)
- [ESP32-CAM API (192.168.4.1)](#esp32-cam-api-19216841)
  - [Port 80 — Control Server](#port-80--control-server)
  - [Port 81 — Stream Server](#port-81--stream-server)
- [SSE Event Reference](#sse-event-reference)
- [DroneController Class API](#dronecontroller-class-api-drone_controllerpy)

---

## Flask Backend API (localhost:5000)

The Flask backend runs on the operator's laptop and acts as the central
coordinator.  It proxies ESP32-CAM traffic, drives paint detection, and
orchestrates drone missions.

### Pages

#### `GET /`

Serves the main web UI (`index.html`).

| Detail   | Value            |
|----------|------------------|
| Response | `text/html`      |
| Auth     | None             |

---

### ESP32-CAM Proxy

#### `GET /video_feed`

Proxies the MJPEG video stream from the ESP32-CAM (port 81) so the browser
can display a live camera feed without a direct connection to the drone.

| Detail        | Value                                        |
|---------------|----------------------------------------------|
| Content-Type  | `multipart/x-mixed-replace; boundary=frame`  |
| Auth          | None                                         |

---

#### `GET /esp32/status`

Returns the current connectivity and relay state of the ESP32-CAM.

**Response** `200 OK` — `application/json`

```json
{
  "reachable": true,
  "relay_active": false,
  "continuous_mode": false
}
```

| Field             | Type    | Description                                      |
|-------------------|---------|--------------------------------------------------|
| `reachable`       | boolean | `true` if the ESP32-CAM responded to a health check |
| `relay_active`    | boolean | `true` if the spray relay is currently energised |
| `continuous_mode` | boolean | `true` if the pump is in continuous-spray mode   |

> **Simulation mode:** When the system is running without a real ESP32-CAM,
> this endpoint always returns `reachable: true` with `relay_active: false`.

---

### Detection

#### `POST /capture`

Alias: **`POST /capture_and_detect`**

Captures a single frame from the ESP32-CAM and runs the paint-detection
algorithm to produce a 10×10 boolean grid indicating unpainted cells.

**Request body** — `application/json` *(optional)*

```json
{
  "sensitivity": 50
}
```

| Field         | Type | Default | Description                        |
|---------------|------|---------|------------------------------------|
| `sensitivity` | int  | `50`    | Detection threshold (0–100)        |

**Response** `200 OK` — `application/json`

```json
{
  "success": true,
  "image_url": "data:image/jpeg;base64,...",
  "grid": [[true, false, "..."], "..."],
  "cell_count": 42,
  "grid_rows": 10,
  "grid_cols": 10
}
```

| Field        | Type       | Description                                              |
|--------------|------------|----------------------------------------------------------|
| `success`    | boolean    | `true` if capture + detection succeeded                  |
| `image_url`  | string     | Base-64 encoded JPEG of the captured frame               |
| `grid`       | bool[][]   | 10×10 grid — `true` means the cell is **unpainted**      |
| `cell_count` | int        | Total number of unpainted cells detected                 |
| `grid_rows`  | int        | Number of rows in the grid (always `10`)                 |
| `grid_cols`  | int        | Number of columns in the grid (always `10`)              |

---

### Drone Control

#### `POST /drone/connect`

Connects to the drone autopilot via DroneKit (MAVLink).

**Request body** — `application/json`

```json
{
  "connection_string": "127.0.0.1:5762"
}
```

| Field               | Type   | Description                              |
|---------------------|--------|------------------------------------------|
| `connection_string` | string | MAVLink connection string (e.g. serial port, TCP address) |

**Response** `200 OK`

```json
{
  "success": true,
  "message": "Connected to vehicle"
}
```

---

#### `GET /drone/status`

Returns current drone telemetry.

**Response** `200 OK` — `application/json`

```json
{
  "armed": true,
  "mode": "AUTO",
  "altitude": 8.5,
  "lat": -35.3632610,
  "lon": 149.1652370,
  "heading": 0,
  "battery": 98,
  "groundspeed": 0.45,
  "gps_fix": 3,
  "is_armable": true
}
```

| Field         | Type    | Description                                |
|---------------|---------|--------------------------------------------|
| `armed`       | boolean | Whether the motors are armed               |
| `mode`        | string  | Current flight mode (`GUIDED`, `AUTO`, `LAND`, etc.) |
| `altitude`    | float   | Altitude in metres (relative to home)      |
| `lat`         | float   | Latitude in decimal degrees                |
| `lon`         | float   | Longitude in decimal degrees               |
| `heading`     | int     | Compass heading 0–359°                     |
| `battery`     | int     | Battery level (percentage)                 |
| `groundspeed` | float   | Ground speed in m/s                        |
| `gps_fix`     | int     | GPS fix type (0 = none, 2 = 2D, 3 = 3D)   |
| `is_armable`  | boolean | Whether pre-arm checks pass                |

---

#### `POST /drone/arm_takeoff`

Arms the drone and takes off to the specified altitude.

**Request body** — `application/json`

```json
{
  "altitude": 10.0
}
```

| Field      | Type  | Description                          |
|------------|-------|--------------------------------------|
| `altitude` | float | Target altitude in metres            |

**Response** `200 OK`

```json
{
  "success": true,
  "message": "Airborne at 10.0m"
}
```

---

#### `POST /drone/land`

Switches the drone to **LAND** mode.

**Response** `200 OK`

```json
{
  "success": true
}
```

---

#### `POST /drone/rtl`

Switches the drone to **RTL** (Return to Launch) mode.

**Response** `200 OK`

```json
{
  "success": true
}
```

---

### Spray Control

#### `POST /spray_sequence`

Starts a **precision spray** sequence: the drone flies to each specified cell
individually, sprays, then moves to the next cell.

**Request body** — `application/json`

```json
{
  "cells": [[0, 0], [0, 1], [1, 1], [1, 0]],
  "use_drone": true,
  "origin_lat": -35.3632610,
  "origin_lon": 149.1652370
}
```

| Field        | Type       | Description                                         |
|--------------|------------|-----------------------------------------------------|
| `cells`      | int[][]    | List of `[row, col]` pairs identifying cells to spray |
| `use_drone`  | boolean    | `true` to physically fly the drone; `false` for simulation |
| `origin_lat` | float      | Latitude of the wall's top-left corner (GPS origin) |
| `origin_lon` | float      | Longitude of the wall's top-left corner             |

**Response** — `text/event-stream` (Server-Sent Events)

Events are emitted in real time as the drone progresses:

| Event      | Data Fields      | Description                        |
|------------|------------------|------------------------------------|
| `moving`   | `row`, `col`     | Drone is navigating to cell        |
| `spraying` | `row`, `col`     | Drone is spraying cell             |
| `done`     | `row`, `col`     | Cell spray complete                |
| `complete` | `total`          | All cells sprayed                  |
| `error`    | `message`        | An error occurred                  |

Example SSE output:

```
event: moving
data: {"row": 0, "col": 0}

event: spraying
data: {"row": 0, "col": 0}

event: done
data: {"row": 0, "col": 0}

event: complete
data: {"total": 4}
```

---

#### `POST /spray_sequence_continuous`

Starts a **continuous spray** sequence: the drone flies along each row with
the pump turned ON, covering cells in a sweeping motion.

Request and response format are identical to
[`POST /spray_sequence`](#post-spray_sequence).

---

#### `POST /spray_abort`

Aborts an in-progress spray sequence immediately.

**Response** `200 OK`

```json
{
  "success": true
}
```

---

### Demo

#### `GET /demo`

One-click automated demo. Connects to SITL, arms, takes off, detects
unpainted cells, uploads a waypoint mission, flies a serpentine pattern, and
tracks progress — all streamed back to the browser as SSE events.

**Response** — `text/event-stream` (Server-Sent Events)

Events are emitted in chronological order:

| #  | Event      | Data Fields                                  | Description                          |
|----|------------|----------------------------------------------|--------------------------------------|
| 1  | `status`   | `message`                                    | `"Connecting to SITL..."`            |
| 2  | `status`   | `message`                                    | `"Arming and taking off to 10.0m..."` |
| 3  | `detected` | `cell_count`, `grid`                         | Detection results (10×10 grid)       |
| 4  | `status`   | `message`                                    | `"Uploading 100 waypoints..."`       |
| 5  | `origin`   | `lat`, `lon`, `cell_width_m`, `top_alt`      | GPS origin for telemetry mapping     |
| 6  | `moving`   | `row`, `col`                                 | Repeated for each cell               |
| 7  | `done`     | `row`, `col`                                 | Repeated for each cell               |
| 8  | `status`   | `message`                                    | `"Mission complete! RTL..."`         |
| 9  | `complete` | `total`                                      | Total cells sprayed                  |

---

## ESP32-CAM API (192.168.4.1)

The ESP32-CAM runs directly on the drone and exposes two HTTP servers on
different ports.

### Port 80 — Control Server

#### `GET /ping`

Health-check endpoint.

**Response** `200 OK` — `application/json`

```json
{
  "status": "ok"
}
```

---

#### `GET /status`

Returns current relay and spray-mode state.

**Response** `200 OK` — `application/json`

```json
{
  "relay": false,
  "continuous": false
}
```

| Field        | Type    | Description                          |
|--------------|---------|--------------------------------------|
| `relay`      | boolean | `true` if the relay is energised     |
| `continuous` | boolean | `true` if continuous spray is active |

---

#### `GET /capture_frame`

Captures a single JPEG frame from the on-board camera.

| Detail       | Value          |
|--------------|----------------|
| Content-Type | `image/jpeg`   |
| Response     | Binary JPEG data |

---

#### `POST /spray`

Fires the relay for a specified duration (one-shot spray).

**Request body** — `application/x-www-form-urlencoded`

| Field         | Type | Default | Description                       |
|---------------|------|---------|-----------------------------------|
| `duration_ms` | int  | —       | Spray duration in milliseconds    |

Example: `duration_ms=800`

**Response** `200 OK` — `application/json`

```json
{
  "sprayed": true,
  "duration_ms": 800
}
```

**Error** `409 Conflict` — if a spray is already in progress:

```json
{
  "error": "spray in progress"
}
```

---

#### `POST /spray_start`

Turns the relay ON continuously (pump stays on until explicitly stopped).

**Response** `200 OK` — `application/json`

```json
{
  "continuous": true
}
```

---

#### `POST /spray_stop`

Turns the relay OFF immediately.

**Response** `200 OK` — `application/json`

```json
{
  "continuous": false
}
```

---

### Port 81 — Stream Server

#### `GET /stream`

Continuous MJPEG video stream. Each frame is a JPEG image separated by
multipart boundary markers.

| Detail       | Value                                             |
|--------------|---------------------------------------------------|
| Content-Type | `multipart/x-mixed-replace; boundary=frame`       |
| Response     | Continuous binary stream (never-ending response)   |

Frame format (repeating):

```
--frame\r\n
Content-Type: image/jpeg\r\n
\r\n
<JPEG binary data>\r\n
```

---

## SSE Event Reference

Summary of all Server-Sent Events consumed by the frontend
(`static/index.html`).

| Event      | Fields                              | Frontend Action                         |
|------------|-------------------------------------|-----------------------------------------|
| `status`   | `message`                           | Display status text                     |
| `error`    | `message`                           | Display error, stop demo                |
| `detected` | `cell_count`, `grid`                | Switch to grid view, draw cells         |
| `origin`   | `lat`, `lon`, `cell_width_m`, `top_alt` | Store GPS origin for telemetry mapping |
| `moving`   | `row`, `col`                        | Highlight cell as "in progress"         |
| `spraying` | `row`, `col`                        | Show spray animation on cell            |
| `done`     | `row`, `col`                        | Mark cell as completed (blue)           |
| `complete` | `total`                             | Switch to complete mode                 |

---

## DroneController Class API (`drone_controller.py`)

The `DroneController` class wraps DroneKit to provide a high-level interface
for mission planning and drone control.

### Constructor

```python
controller = DroneController()
```

Creates a new controller instance. No connection is established until
`connect()` is called.

---

### Instance Methods

#### `connect(conn_string, timeout=30) → bool`

Connects to a vehicle via MAVLink.

| Parameter     | Type   | Default | Description                                 |
|---------------|--------|---------|---------------------------------------------|
| `conn_string` | str    | —       | MAVLink connection string (e.g. `"127.0.0.1:5762"`, `"/dev/ttyUSB0"`) |
| `timeout`     | int    | `30`    | Connection timeout in seconds               |

**Returns:** `True` on successful connection, `False` on failure.

---

#### `disconnect()`

Closes the MAVLink connection and releases resources.

---

#### `arm_and_takeoff(altitude=3.0, timeout=60) → bool`

Arms the motors and takes off to the specified altitude. Blocks until the
target altitude is reached (within a tolerance) or the timeout expires.

| Parameter  | Type  | Default | Description                       |
|------------|-------|---------|-----------------------------------|
| `altitude` | float | `3.0`   | Target altitude in metres         |
| `timeout`  | int   | `60`    | Maximum time to wait (seconds)    |

**Returns:** `True` if target altitude reached, `False` on timeout.

---

#### `goto_global(lat, lon, alt, groundspeed=2.0) → bool`

Commands the drone to fly to a global GPS coordinate.

| Parameter     | Type  | Default | Description                    |
|---------------|-------|---------|--------------------------------|
| `lat`         | float | —       | Target latitude                |
| `lon`         | float | —       | Target longitude               |
| `alt`         | float | —       | Target altitude (metres)       |
| `groundspeed` | float | `2.0`   | Ground speed in m/s            |

**Returns:** `True` when the position is reached.

---

#### `set_yaw(heading_deg, relative=False)`

Rotates the drone to a specified compass heading.

| Parameter     | Type  | Default | Description                               |
|---------------|-------|---------|-------------------------------------------|
| `heading_deg` | float | —       | Target heading in degrees (0–360)         |
| `relative`    | bool  | `False` | If `True`, heading is relative to current |

---

#### `upload_mission(waypoints, speed=0.5) → bool`

Uploads a list of waypoints as an autonomous mission.

| Parameter   | Type              | Default | Description                          |
|-------------|-------------------|---------|--------------------------------------|
| `waypoints` | list[tuple]       | —       | List of `(lat, lon, alt)` tuples     |
| `speed`     | float             | `0.5`   | Mission speed in m/s                 |

**Returns:** `True` if the mission was uploaded successfully.

---

#### `start_mission() → bool`

Switches to AUTO mode and begins the uploaded mission.

**Returns:** `True` if mode switch succeeded.

---

#### `get_mission_progress() → int`

Returns the index of the current waypoint being targeted.

**Returns:** Current waypoint index (int).

---

#### `wait_for_waypoint(wp_index, timeout=120) → bool`

Blocks until the drone reaches the specified waypoint index.

| Parameter  | Type | Default | Description                         |
|------------|------|---------|-------------------------------------|
| `wp_index` | int  | —       | Target waypoint index               |
| `timeout`  | int  | `120`   | Maximum time to wait (seconds)      |

**Returns:** `True` if waypoint reached, `False` on timeout.

---

#### `wait_until_reached(lat, lon, alt, threshold=2.0, timeout=120) → bool`

Blocks until the drone is within `threshold` metres of the target position.

| Parameter   | Type  | Default | Description                         |
|-------------|-------|---------|-------------------------------------|
| `lat`       | float | —       | Target latitude                     |
| `lon`       | float | —       | Target longitude                    |
| `alt`       | float | —       | Target altitude (metres)            |
| `threshold` | float | `2.0`   | Acceptance radius in metres         |
| `timeout`   | int   | `120`   | Maximum time to wait (seconds)      |

**Returns:** `True` if position reached, `False` on timeout.

---

#### `return_to_launch() → bool`

Switches to RTL mode.

**Returns:** `True` if mode switch succeeded.

---

#### `land() → bool`

Switches to LAND mode.

**Returns:** `True` if mode switch succeeded.

---

#### `get_status() → dict`

Returns a dictionary of current telemetry values (same schema as the
[`GET /drone/status`](#get-dronestatus) endpoint).

---

### Static Methods

#### `offset_to_gps(origin_lat, origin_lon, east_m, north_m) → (lat, lon)`

Converts a local east/north metre offset from a GPS origin into decimal
degree coordinates.

| Parameter    | Type  | Description                     |
|--------------|-------|---------------------------------|
| `origin_lat` | float | Reference latitude              |
| `origin_lon` | float | Reference longitude             |
| `east_m`     | float | Eastward offset in metres       |
| `north_m`    | float | Northward offset in metres      |

**Returns:** `(lat, lon)` tuple in decimal degrees.

---

#### `cells_to_waypoints(cells, origin_lat, origin_lon, top_alt, cell_width=1.0) → [(lat, lon, alt)]`

Converts a list of grid cells into GPS waypoints suitable for
`upload_mission()`.

| Parameter    | Type        | Default | Description                        |
|--------------|-------------|---------|------------------------------------|
| `cells`      | list[tuple] | —       | List of `(row, col)` pairs         |
| `origin_lat` | float       | —       | GPS latitude of grid origin        |
| `origin_lon` | float       | —       | GPS longitude of grid origin       |
| `top_alt`    | float       | —       | Flight altitude in metres          |
| `cell_width` | float       | `1.0`   | Width of each grid cell in metres  |

**Returns:** List of `(lat, lon, alt)` tuples.

---

#### `group_cells_by_row(cells) → dict`

Groups a list of cells by their row index, useful for planning row-by-row
sweeps.

| Parameter | Type        | Description                  |
|-----------|-------------|------------------------------|
| `cells`   | list[tuple] | List of `(row, col)` pairs   |

**Returns:** `dict` mapping `row_index → [col_indices]`.

Example:

```python
>>> DroneController.group_cells_by_row([(0,0), (0,1), (1,2)])
{0: [0, 1], 1: [2]}
```
