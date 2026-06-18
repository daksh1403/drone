"""
app.py
Flask backend for the autonomous drone painting system.
Connects to an ESP32-CAM (or simulates it) and controls a drone
via drone_controller.py.
"""

# ── Python 3.14 compatibility monkey-patch (must be before dronekit) ──
import collections
import collections.abc
for attr in ("MutableMapping", "MutableSequence", "MutableSet",
             "Mapping", "Sequence", "Set", "Iterable", "Iterator",
             "Callable", "Hashable", "Sized"):
    if not hasattr(collections, attr):
        setattr(collections, attr, getattr(collections.abc, attr))

import base64
import json
import math
import time
import threading

import cv2
import numpy as np
import requests
from flask import Flask, Response, jsonify, render_template, request

from drone_controller import DroneController

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SIMULATION_MODE = True          # Set False when real ESP32-CAM is connected
ESP32_IP = "192.168.4.1"
SPRAY_DURATION_MS = 200         # 0.2s spray per cell (fast demo)
GRID_ROWS = 10                  # 10 rows (altitude levels)
GRID_COLS = 10                  # 10 columns (horizontal passes)
CELL_WIDTH_M = 1.0              # 1m per cell → 10x10m wall
PAINTING_ALTITUDE = 10.0        # Top of wall altitude (start high)
ROW_HEIGHT_M = 1.0              # 1m drop per row
WALL_WIDTH_M = 10.0             # Total wall width
CONTINUOUS_SPEED = 1.0          # Speed during continuous spray

# ---------------------------------------------------------------------------
# Global drone controller instance (thread-safe via DroneController internals)
# ---------------------------------------------------------------------------
drone_controller = DroneController()

# ---------------------------------------------------------------------------
# PaintDetector
# ---------------------------------------------------------------------------

class PaintDetector:
    """Detects white / unpainted areas in a BGR image using multiple
    thresholding strategies combined with weighted voting."""

    def detect(self, frame, sensitivity=50):
        """Return (mask, regions) where *mask* is a binary uint8 image
        (255 = unpainted / white) and *regions* is a list of contour arrays."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)

        h, w = gray.shape
        accumulator = np.zeros((h, w), dtype=np.float32)

        # 1. Adaptive threshold (weight 0.30)
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 51, -sensitivity
        )
        accumulator += (adaptive.astype(np.float32) / 255.0) * 0.30

        # 2. Relative brightness vs frame mean (weight 0.20)
        mean_val = gray.mean()
        bright_thresh = max(0, mean_val + sensitivity)
        _, bright_mask = cv2.threshold(gray, int(bright_thresh), 255, cv2.THRESH_BINARY)
        accumulator += (bright_mask.astype(np.float32) / 255.0) * 0.20

        # 3. Low saturation in HSV = white (weight 0.25)
        sat = hsv[:, :, 1]
        sat_thresh = max(0, 255 - sensitivity * 2)
        _, low_sat_mask = cv2.threshold(sat, int(sat_thresh), 255, cv2.THRESH_BINARY_INV)
        # Also require some minimum brightness
        val = hsv[:, :, 2]
        _, val_mask = cv2.threshold(val, 180, 255, cv2.THRESH_BINARY)
        white_mask = cv2.bitwise_and(low_sat_mask, val_mask)
        accumulator += (white_mask.astype(np.float32) / 255.0) * 0.25

        # 4. Otsu threshold (weight 0.10)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        accumulator += (otsu.astype(np.float32) / 255.0) * 0.10

        # 5. LAB luminance channel (weight 0.10)
        l_channel = lab[:, :, 0]
        l_thresh = max(0, 200 - sensitivity)
        _, lab_mask = cv2.threshold(l_channel, int(l_thresh), 255, cv2.THRESH_BINARY)
        accumulator += (lab_mask.astype(np.float32) / 255.0) * 0.10

        # 6. Blurred threshold (weight 0.05)
        blurred = cv2.GaussianBlur(gray, (15, 15), 0)
        blur_thresh = max(0, 200 - sensitivity)
        _, blur_mask = cv2.threshold(blurred, int(blur_thresh), 255, cv2.THRESH_BINARY)
        accumulator += (blur_mask.astype(np.float32) / 255.0) * 0.05

        # Combine: threshold the weighted sum at 0.5
        combined = (accumulator >= 0.5).astype(np.uint8) * 255

        # Morphological cleanup: open then close
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        return combined, contours

    def build_grid(self, mask, rows=GRID_ROWS, cols=GRID_COLS, threshold=0.4):
        """Divide *mask* into a grid. A cell is True (unpainted) when
        >= *threshold* fraction of its pixels are white (255)."""
        h, w = mask.shape[:2]
        cell_h = h // rows
        cell_w = w // cols
        grid = []
        for r in range(rows):
            row = []
            for c in range(cols):
                y0 = r * cell_h
                y1 = (r + 1) * cell_h if r < rows - 1 else h
                x0 = c * cell_w
                x1 = (c + 1) * cell_w if c < cols - 1 else w
                cell = mask[y0:y1, x0:x1]
                total = cell.size
                white = np.count_nonzero(cell)
                row.append(white / total >= threshold if total > 0 else False)
            grid.append(row)
        return grid


paint_detector = PaintDetector()

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def _simulation_frame():
    """Generate a realistic wall simulation: textured surface with painted
    areas (color) and unpainted patches (white/bare concrete)."""
    H, W = 480, 640
    rng = np.random.default_rng()

    # Base wall: warm concrete/plaster texture
    base_color = np.array([160, 170, 175], dtype=np.uint8)  # BGR light beige
    img = np.full((H, W, 3), base_color, dtype=np.uint8)

    # Add texture noise to simulate concrete grain
    noise = rng.integers(-15, 16, size=(H, W, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Add subtle horizontal and vertical streaks (plaster lines)
    for _ in range(8):
        y = int(rng.integers(0, H))
        thickness = int(rng.integers(1, 3))
        shade = int(rng.integers(-20, 10))
        cv2.line(img, (0, y), (W, y),
                 tuple(np.clip(base_color.astype(int) + shade, 0, 255).tolist()),
                 thickness)

    # Paint the wall with a main color (blue/green/teal) — the "painted" area
    paint_color = (180, 120, 50)  # BGR — a nice teal/blue-green
    paint_layer = np.full((H, W, 3), paint_color, dtype=np.uint8)

    # Add paint texture — slight variation
    paint_noise = rng.integers(-8, 9, size=(H, W, 3), dtype=np.int16)
    paint_layer = np.clip(paint_layer.astype(np.int16) + paint_noise, 0, 255).astype(np.uint8)

    # Apply paint over most of the wall
    img[:] = paint_layer

    # Create unpainted patches (white/bare wall showing through)
    # These are the areas the drone needs to paint
    num_patches = int(rng.integers(4, 9))
    for _ in range(num_patches):
        patch_type = int(rng.integers(0, 3))

        if patch_type == 0:
            # Rectangular unpainted area
            x1 = int(rng.integers(20, W - 100))
            y1 = int(rng.integers(20, H - 80))
            pw = int(rng.integers(40, 120))
            ph = int(rng.integers(30, 90))
            # White/light grey bare wall
            brightness = int(rng.integers(210, 250))
            patch = np.full((ph, pw, 3), brightness, dtype=np.uint8)
            patch_noise = rng.integers(-10, 11, size=(ph, pw, 3), dtype=np.int16)
            patch = np.clip(patch.astype(np.int16) + patch_noise, 0, 255).astype(np.uint8)
            y2 = min(y1 + ph, H)
            x2 = min(x1 + pw, W)
            img[y1:y2, x1:x2] = patch[:y2-y1, :x2-x1]

        elif patch_type == 1:
            # Irregular blob — circle with rough edges
            cx = int(rng.integers(50, W - 50))
            cy = int(rng.integers(50, H - 50))
            radius = int(rng.integers(20, 55))
            brightness = int(rng.integers(215, 248))
            cv2.circle(img, (cx, cy), radius, (brightness, brightness, brightness), -1)
            # Add texture to the bare spot
            mask = np.zeros((H, W), dtype=np.uint8)
            cv2.circle(mask, (cx, cy), radius, 255, -1)
            spot_noise = rng.integers(-8, 9, size=(H, W, 3), dtype=np.int16)
            img = np.where(mask[:, :, None] > 0,
                          np.clip(img.astype(np.int16) + spot_noise, 0, 255).astype(np.uint8),
                          img)

        else:
            # Paint drip / streak — thin vertical unpainted line
            x = int(rng.integers(30, W - 30))
            y1 = int(rng.integers(0, H // 2))
            y2 = y1 + int(rng.integers(60, 150))
            y2 = min(y2, H)
            w = int(rng.integers(15, 35))
            brightness = int(rng.integers(210, 245))
            cv2.rectangle(img, (x, y1), (x + w, y2),
                         (brightness, brightness, brightness), -1)

    # Add some edge wear / corners showing bare wall
    corner_size = int(rng.integers(20, 50))
    corners = [(0, 0), (W - corner_size, 0), (0, H - corner_size), (W - corner_size, H - corner_size)]
    chosen = rng.choice(len(corners), size=min(2, len(corners)), replace=False)
    for idx in chosen:
        cx, cy = corners[idx]
        brightness = int(rng.integers(200, 240))
        cv2.rectangle(img, (cx, cy), (cx + corner_size, cy + corner_size),
                     (brightness, brightness - 5, brightness - 10), -1)

    # Add a subtle grid overlay to hint at the wall structure (mortar lines)
    for y in range(0, H, H // 8):
        cv2.line(img, (0, y), (W, y), (140, 110, 45), 1, cv2.LINE_AA)
    for x in range(0, W, W // 12):
        cv2.line(img, (x, 0), (x, H), (140, 110, 45), 1, cv2.LINE_AA)

    return img


def _encode_jpeg(img, quality=85):
    """Encode a BGR numpy image to JPEG bytes."""
    ret, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ret:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def _sse_event(data_dict):
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data_dict)}\n\n"


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    if SIMULATION_MODE:
        def gen():
            while True:
                img = np.full((480, 640, 3), 128, dtype=np.uint8)
                cv2.putText(img, "SIMULATION", (140, 260),
                            cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
                frame_bytes = _encode_jpeg(img)
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" +
                       frame_bytes + b"\r\n")
                time.sleep(0.1)
        return Response(gen(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")
    else:
        # Proxy ESP32-CAM MJPEG stream
        try:
            resp = requests.get(f"http://{ESP32_IP}:81/stream", stream=True,
                                timeout=10)
            return Response(resp.iter_content(chunk_size=4096),
                            mimetype="multipart/x-mixed-replace; boundary=frame")
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502


@app.route("/capture", methods=["POST"])
@app.route("/capture_and_detect", methods=["POST"])
def capture():
    if SIMULATION_MODE:
        frame = _simulation_frame()
    else:
        try:
            resp = requests.get(f"http://{ESP32_IP}/capture_frame", timeout=10)
            resp.raise_for_status()
            arr = np.frombuffer(resp.content, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return jsonify({"success": False, "error": "Failed to decode image"}), 500
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 502

    mask, _ = paint_detector.detect(frame)
    grid = paint_detector.build_grid(mask)
    # Convert numpy bools to Python bools for JSON serialization
    grid = [[bool(cell) for cell in row] for row in grid]
    unpainted_count = sum(cell for row in grid for cell in row)

    jpeg_bytes = _encode_jpeg(frame)
    b64_image = base64.b64encode(jpeg_bytes).decode("utf-8")

    return jsonify({
        "success": True,
        "image_url": "data:image/jpeg;base64," + b64_image,
        "grid": grid,
        "unpainted_count": unpainted_count,
    })


@app.route("/spray_sequence", methods=["POST"])
def spray_sequence():
    payload = request.get_json(force=True)
    cells = payload.get("cells", [])
    use_drone = payload.get("use_drone", False)
    origin_lat = payload.get("origin_lat", 0.0)
    origin_lon = payload.get("origin_lon", 0.0)
    total = len(cells)

    if use_drone:
        waypoints = DroneController.cells_to_waypoints(
            cells, origin_lat, origin_lon, PAINTING_ALTITUDE, CELL_WIDTH_M
        )

    def generate():
        global spray_abort_flag
        spray_abort_flag = False
        for i, cell in enumerate(cells):
            if spray_abort_flag:
                yield _sse_event({"event": "complete", "total": i, "aborted": True})
                return
            row, col = cell[0], cell[1]
            yield _sse_event({
                "event": "moving",
                "row": row,
                "col": col,
                "countdown": 3,
                "index": i,
                "total": total,
            })

            if use_drone:
                lat, lon, alt = waypoints[i]
                drone_controller.goto_global(lat, lon, alt, groundspeed=1.0)
                drone_controller.wait_until_reached(lat, lon, alt,
                                                    threshold=1.0,
                                                    timeout=60)
            else:
                time.sleep(3)

            if spray_abort_flag:
                yield _sse_event({"event": "complete", "total": i, "aborted": True})
                return

            yield _sse_event({"event": "spraying", "row": row, "col": col})

            if not SIMULATION_MODE:
                try:
                    requests.post(f"http://{ESP32_IP}/spray",
                                  json={"duration": SPRAY_DURATION_MS},
                                  timeout=5)
                except Exception:
                    pass
            else:
                time.sleep(SPRAY_DURATION_MS / 1000.0)

            yield _sse_event({"event": "done", "row": row, "col": col})

        yield _sse_event({"event": "complete", "total": total})

    return Response(generate(), mimetype="text/event-stream")


@app.route("/spray_sequence_continuous", methods=["POST"])
def spray_sequence_continuous():
    payload = request.get_json(force=True)
    cells = payload.get("cells", [])
    origin_lat = payload.get("origin_lat", 0.0)
    origin_lon = payload.get("origin_lon", 0.0)

    grouped = DroneController.group_cells_by_row(cells)
    total_rows = len(grouped)

    def generate():
        row_index = 0
        for row_num in sorted(grouped.keys()):
            cols_in_row = sorted(grouped[row_num])

            # Fly to start of row
            start_cell = [row_num, cols_in_row[0]]
            end_cell = [row_num, cols_in_row[-1]]

            start_wp = DroneController.cells_to_waypoints(
                [start_cell], origin_lat, origin_lon,
                PAINTING_ALTITUDE, CELL_WIDTH_M
            )[0]
            end_wp = DroneController.cells_to_waypoints(
                [end_cell], origin_lat, origin_lon,
                PAINTING_ALTITUDE, CELL_WIDTH_M
            )[0]

            yield _sse_event({
                "event": "row_start",
                "row": row_num,
                "row_index": row_index,
                "total_rows": total_rows,
                "cols": cols_in_row,
            })

            # Move to row start
            drone_controller.goto_global(start_wp[0], start_wp[1],
                                         start_wp[2], groundspeed=2.0)
            drone_controller.wait_until_reached(start_wp[0], start_wp[1],
                                                start_wp[2],
                                                threshold=1.0, timeout=60)

            # Start spray
            if not SIMULATION_MODE:
                try:
                    requests.post(f"http://{ESP32_IP}/spray_start", timeout=5)
                except Exception:
                    pass

            yield _sse_event({
                "event": "spraying_row",
                "row": row_num,
            })

            # Fly along row slowly
            drone_controller.goto_global(end_wp[0], end_wp[1],
                                         end_wp[2],
                                         groundspeed=CONTINUOUS_SPEED)
            drone_controller.wait_until_reached(end_wp[0], end_wp[1],
                                                end_wp[2],
                                                threshold=1.0, timeout=120)

            # Stop spray
            if not SIMULATION_MODE:
                try:
                    requests.post(f"http://{ESP32_IP}/spray_stop", timeout=5)
                except Exception:
                    pass

            yield _sse_event({
                "event": "row_done",
                "row": row_num,
            })

            row_index += 1

        # Return to launch
        drone_controller.return_to_launch()

        yield _sse_event({
            "event": "complete",
            "total_rows": total_rows,
        })

    return Response(generate(), mimetype="text/event-stream")


# ── Drone control routes ──────────────────────────────────────────────────

@app.route("/drone/connect", methods=["POST"])
def drone_connect():
    payload = request.get_json(force=True)
    conn_string = payload.get("connection_string", "tcp:127.0.0.1:5762")
    try:
        drone_controller.connect(conn_string)
        return jsonify({"success": True, **drone_controller.get_status()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/drone/status", methods=["GET"])
def drone_status():
    try:
        return jsonify(drone_controller.get_status())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/drone/arm_takeoff", methods=["POST"])
def drone_arm_takeoff():
    payload = request.get_json(force=True)
    altitude = payload.get("altitude", PAINTING_ALTITUDE)
    try:
        drone_controller.arm_and_takeoff(altitude)
        return jsonify({"success": True, **drone_controller.get_status()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/drone/land", methods=["POST"])
def drone_land():
    try:
        drone_controller.land()
        return jsonify({"success": True, **drone_controller.get_status()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/drone/rtl", methods=["POST"])
def drone_rtl():
    try:
        drone_controller.return_to_launch()
        return jsonify({"success": True, **drone_controller.get_status()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── ESP32 status ──────────────────────────────────────────────────────────

@app.route("/esp32/status", methods=["GET"])
def esp32_status():
    if SIMULATION_MODE:
        return jsonify({"status": "ok", "reachable": True, "mode": "simulation"})
    try:
        resp = requests.get(f"http://{ESP32_IP}/ping", timeout=5)
        data = resp.json()
        data["reachable"] = True
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc), "reachable": False}), 200


spray_abort_flag = False


@app.route("/spray_abort", methods=["POST"])
def spray_abort():
    global spray_abort_flag
    spray_abort_flag = True
    return jsonify({"success": True})


# ── Full Demo (SSE): connect → arm → takeoff → upload mission → AUTO → track ─

@app.route("/demo", methods=["POST"])
def demo():
    payload = request.get_json(force=True)
    conn_string = payload.get("connection_string", "tcp:127.0.0.1:5762")

    def generate():
        global spray_abort_flag
        spray_abort_flag = False

        # Step 1: Connect
        yield _sse_event({"event": "status", "step": "connect", "message": "Connecting to drone..."})
        try:
            drone_controller.connect(conn_string)
            yield _sse_event({"event": "status", "step": "connect", "message": "Connected!", "success": True,
                              **drone_controller.get_status()})
        except Exception as e:
            yield _sse_event({"event": "error", "step": "connect", "message": str(e)})
            return

        # Step 2: Arm & Takeoff to top of wall
        yield _sse_event({"event": "status", "step": "arm_takeoff",
                          "message": "Arming and taking off to %.0f m (top of wall)..." % PAINTING_ALTITUDE})
        try:
            result = drone_controller.arm_and_takeoff(PAINTING_ALTITUDE)
            if not result:
                yield _sse_event({"event": "error", "step": "arm_takeoff", "message": "Arm/takeoff failed"})
                return
            yield _sse_event({"event": "status", "step": "arm_takeoff", "message": "Airborne!", "success": True,
                              **drone_controller.get_status()})
        except Exception as e:
            yield _sse_event({"event": "error", "step": "arm_takeoff", "message": str(e)})
            return

        if spray_abort_flag:
            drone_controller.return_to_launch()
            yield _sse_event({"event": "complete", "aborted": True})
            return

        # Build 10x10 grid — ALL cells unpainted (entire wall)
        grid = [[True] * GRID_COLS for _ in range(GRID_ROWS)]

        # Generate wall image for UI
        if SIMULATION_MODE:
            frame = _simulation_frame()
        else:
            frame = np.full((480, 640, 3), 240, dtype=np.uint8)
        jpeg_bytes = _encode_jpeg(frame)
        b64_image = base64.b64encode(jpeg_bytes).decode("utf-8")

        # Build serpentine cell order
        cells = []
        for row in range(GRID_ROWS):
            cols = list(range(GRID_COLS))
            if row % 2 == 1:
                cols.reverse()
            for col in cols:
                cells.append([row, col])

        total = len(cells)

        yield _sse_event({
            "event": "detected",
            "step": "capture",
            "grid": grid,
            "image_url": "data:image/jpeg;base64," + b64_image,
            "unpainted_count": total,
            "success": True,
        })

        # Use drone's current position as origin
        status = drone_controller.get_status()
        origin_lat = status.get("lat", 0.0)
        origin_lon = status.get("lon", 0.0)

        yield _sse_event({
            "event": "origin",
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "cell_width": CELL_WIDTH_M,
            "top_alt": PAINTING_ALTITUDE,
            "rows": GRID_ROWS,
            "cols": GRID_COLS,
        })

        # Convert cells to GPS waypoints
        waypoints = DroneController.cells_to_waypoints(
            cells, origin_lat, origin_lon, PAINTING_ALTITUDE, CELL_WIDTH_M
        )

        # Step 3: Upload mission (AUTO mode, no yaw changes)
        yield _sse_event({"event": "status", "step": "mission",
                          "message": "Uploading %d waypoints as AUTO mission (no yaw)..." % total})
        try:
            drone_controller.upload_mission(waypoints, speed=0.5)
        except Exception as e:
            yield _sse_event({"event": "error", "step": "mission", "message": "Mission upload failed: " + str(e)})
            drone_controller.return_to_launch()
            return

        # Face north before starting
        drone_controller.set_yaw(0)
        time.sleep(2)

        # Start AUTO mission
        yield _sse_event({"event": "status", "step": "mission", "message": "Starting AUTO mission..."})
        if not drone_controller.start_mission():
            yield _sse_event({"event": "error", "step": "mission", "message": "Failed to start AUTO mode"})
            drone_controller.return_to_launch()
            return

        # Step 4: Track mission progress — each waypoint = one cell painted
        # Mission layout: cmd 0 = speed, cmd 1 = ROI, cmds 2..N+1 = waypoints, cmd N+2 = RTL
        wp_offset = 2  # First two commands are speed + ROI

        last_wp = -1
        while True:
            if spray_abort_flag:
                drone_controller.return_to_launch()
                yield _sse_event({"event": "complete", "total": last_wp + 1, "aborted": True})
                return

            current_wp = drone_controller.get_mission_progress()

            # Check if mission complete (past all waypoints, at RTL command)
            if current_wp >= wp_offset + total:
                break

            # A new waypoint was reached
            cell_idx = current_wp - wp_offset
            if cell_idx >= 0 and cell_idx < total and cell_idx != last_wp:
                # Mark the PREVIOUS cell as done (sprayed)
                if last_wp >= 0 and last_wp < total:
                    prev_cell = cells[last_wp]
                    yield _sse_event({"event": "done", "row": prev_cell[0], "col": prev_cell[1]})

                # Show current cell as target
                cur_cell = cells[cell_idx]
                lat, lon, alt = waypoints[cell_idx]
                yield _sse_event({
                    "event": "moving",
                    "row": cur_cell[0], "col": cur_cell[1],
                    "index": cell_idx, "total": total,
                    "altitude": alt,
                })

                last_wp = cell_idx

            # Check vehicle mode — if it left AUTO, mission may be done
            mode = drone_controller.vehicle.mode.name if drone_controller.vehicle else "N/A"
            if mode == "RTL" or mode == "LAND":
                break

            time.sleep(0.5)

        # Mark last cell as done
        if last_wp >= 0 and last_wp < total:
            final_cell = cells[last_wp]
            yield _sse_event({"event": "done", "row": final_cell[0], "col": final_cell[1]})

        # Mark any remaining cells as done (mission may have progressed past our tracking)
        for i in range(last_wp + 1, total):
            c = cells[i]
            yield _sse_event({"event": "done", "row": c[0], "col": c[1]})

        yield _sse_event({"event": "status", "step": "rtl", "message": "Mission complete, returning to launch..."})
        yield _sse_event({"event": "complete", "total": total})

    return Response(generate(), mimetype="text/event-stream")


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
