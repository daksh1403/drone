"""
============================================================
 drone_controller.py  —  Autonomous Drone Paint Controller
============================================================

Connects to Pixhawk V6X via:
  - ETH cable  : 'udp:192.168.1.1:14550'  (indoor testing)
  - 433MHz radio: '/dev/ttyUSB0'           (outdoor use)
  - USB direct : '/dev/ttyACM0'            (bench testing)

Uses DroneKit to:
  1. Arm the drone
  2. Take off to painting altitude
  3. Fly to each grid cell position
  4. Signal ESP32-CAM to spray
  5. Support continuous painting mode
  6. Return home after completion

Install: pip install dronekit
============================================================
"""

import time
import math
import requests
from dronekit import connect, VehicleMode, LocationGlobalRelative

# ── ESP32-CAM address ────────────────────────────────────────
ESP32_CONTROL = "http://192.168.4.1"

# ── Painting parameters — TUNE THESE FOR YOUR SETUP ─────────
PAINTING_ALTITUDE  = 3.0     # meters above ground (1st floor ~3m)
WALL_DISTANCE      = 0.5     # meters from wall to hover
CELL_WIDTH_M       = 0.3     # real-world width of one grid cell (meters)
CELL_HEIGHT_M      = 0.3     # real-world height of one grid cell (meters)
SPRAY_DURATION_MS  = 800     # ms per cell in precision mode
CONTINUOUS_SPEED   = 0.3     # m/s when doing continuous painting
GRID_COLS          = 12
GRID_ROWS          = 8

# ── Connection string — CHANGE THIS based on connection type ─
# ETH cable (indoor):   'udp:192.168.1.1:14550'
# 433MHz radio:         'COM5' on Windows, '/dev/ttyUSB0' on Linux
# USB direct:           'COM3' on Windows, '/dev/ttyACM0' on Linux
CONNECTION_STRING = 'udp:192.168.1.1:14550'


class DroneController:
    """Manages autonomous drone movement for painting."""

    def __init__(self, connection_string=CONNECTION_STRING):
        self.connection_string = connection_string
        self.vehicle = None
        self.home_location = None
        self.connected = False

    def connect(self):
        """Connect to Pixhawk via DroneKit."""
        print(f"[Drone] Connecting to {self.connection_string}...")
        try:
            self.vehicle = connect(
                self.connection_string,
                wait_ready=True,
                timeout=30
            )
            self.connected = True
            print(f"[Drone] Connected!")
            print(f"[Drone] Firmware: {self.vehicle.version}")
            print(f"[Drone] GPS: {self.vehicle.gps_0}")
            print(f"[Drone] Battery: {self.vehicle.battery}")
            print(f"[Drone] Mode: {self.vehicle.mode.name}")
            print(f"[Drone] Armed: {self.vehicle.armed}")
            return True
        except Exception as e:
            print(f"[Drone] Connection FAILED: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Safely disconnect from drone."""
        if self.vehicle:
            self.vehicle.close()
            self.connected = False
            print("[Drone] Disconnected")

    def get_status(self):
        """Return current drone status as dict."""
        if not self.connected or not self.vehicle:
            return {"connected": False}
        return {
            "connected":  True,
            "mode":       self.vehicle.mode.name,
            "armed":      self.vehicle.armed,
            "altitude":   self.vehicle.location.global_relative_frame.alt,
            "lat":        self.vehicle.location.global_frame.lat,
            "lon":        self.vehicle.location.global_frame.lon,
            "battery":    self.vehicle.battery.level,
            "gps_fix":    self.vehicle.gps_0.fix_type,
            "groundspeed": self.vehicle.groundspeed,
        }

    def is_ready_to_fly(self):
        """Check all pre-flight conditions."""
        if not self.connected:
            return False, "Not connected to drone"
        if self.vehicle.gps_0.fix_type < 3:
            return False, "GPS fix not ready (need fix_type >= 3)"
        if self.vehicle.battery.level < 20:
            return False, f"Battery too low: {self.vehicle.battery.level}%"
        return True, "Ready"

    def arm_and_takeoff(self, target_altitude):
        """
        Arm the drone and take off to target_altitude (meters).
        Switches to GUIDED mode first.
        """
        print(f"[Drone] Arming and taking off to {target_altitude}m...")

        # Switch to GUIDED mode — required for programmatic control
        self.vehicle.mode = VehicleMode("GUIDED")
        time.sleep(2)

        # Arm the drone
        self.vehicle.armed = True
        timeout = 10
        while not self.vehicle.armed and timeout > 0:
            print("[Drone] Waiting for arm...")
            time.sleep(1)
            timeout -= 1

        if not self.vehicle.armed:
            raise Exception("Drone failed to arm — check pre-arm conditions")

        print("[Drone] Armed! Taking off...")

        # Issue takeoff command
        self.vehicle.simple_takeoff(target_altitude)

        # Store home location for relative positioning
        self.home_location = self.vehicle.location.global_frame

        # Wait until target altitude is reached
        while True:
            alt = self.vehicle.location.global_relative_frame.alt
            print(f"[Drone] Altitude: {alt:.1f}m / {target_altitude}m")
            if alt >= target_altitude * 0.95:
                print("[Drone] Target altitude reached!")
                break
            time.sleep(1)

    def goto_position_ned(self, north_m, east_m, down_m=0):
        """
        Move drone by offset in meters from current position.
        North = forward, East = right, Down = descend.
        Uses NED (North-East-Down) coordinate frame.
        """
        from dronekit import LocationGlobalRelative
        from pymavlink import mavutil

        msg = self.vehicle.message_factory.set_position_target_local_ned_encode(
            0,          # time_boot_ms
            0, 0,       # target system, component
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            0b0000111111111000,   # position only (ignore velocity/accel)
            north_m, east_m, down_m,
            0, 0, 0,   # velocity
            0, 0, 0,   # acceleration
            0, 0       # yaw, yaw_rate
        )
        self.vehicle.send_mavlink(msg)

    def goto_global(self, lat, lon, alt):
        """Fly to a specific GPS coordinate."""
        target = LocationGlobalRelative(lat, lon, alt)
        self.vehicle.simple_goto(target, groundspeed=1.0)
        print(f"[Drone] Flying to lat={lat:.6f} lon={lon:.6f} alt={alt}m")

    def wait_until_reached(self, target_lat, target_lon,
                            tolerance_m=0.5, timeout=30):
        """Wait until drone reaches target GPS position."""
        start = time.time()
        while time.time() - start < timeout:
            current = self.vehicle.location.global_frame
            dist = self._distance_m(
                current.lat, current.lon,
                target_lat, target_lon
            )
            if dist <= tolerance_m:
                print(f"[Drone] Reached target (dist={dist:.2f}m)")
                return True
            time.sleep(0.5)
        print(f"[Drone] Timeout reaching target")
        return False

    def hover(self, duration_s):
        """Hold current position for duration_s seconds."""
        print(f"[Drone] Hovering for {duration_s}s...")
        time.sleep(duration_s)

    def return_to_launch(self):
        """Switch to RTL mode — drone returns home automatically."""
        print("[Drone] Returning to launch...")
        self.vehicle.mode = VehicleMode("RTL")

    def land(self):
        """Land at current position."""
        print("[Drone] Landing...")
        self.vehicle.mode = VehicleMode("LAND")

    def _distance_m(self, lat1, lon1, lat2, lon2):
        """Calculate distance in meters between two GPS coordinates."""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = (math.sin(dphi/2)**2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(dlam/2)**2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def offset_to_gps(self, origin_lat, origin_lon,
                       north_m, east_m):
        """
        Convert a meter offset from origin GPS to a new GPS coordinate.
        Used to convert grid cell positions to GPS waypoints.
        """
        # Earth radius
        R = 6371000
        new_lat = origin_lat  + (north_m / R) * (180 / math.pi)
        new_lon = origin_lon  + (east_m  / R) * (180 / math.pi) / math.cos(
                                 math.radians(origin_lat))
        return new_lat, new_lon


def cells_to_waypoints(cells, origin_lat, origin_lon,
                        cell_w=CELL_WIDTH_M, cell_h=CELL_HEIGHT_M):
    """
    Convert grid cell (row, col) list to GPS waypoints.

    The wall is assumed to be NORTH of the drone's home position.
    Each column maps to an East offset.
    Each row maps to an altitude offset (higher row = higher altitude).

    Returns list of dicts: {row, col, lat, lon, alt}
    """
    drone = DroneController()
    waypoints = []

    for row, col in cells:
        # Column → East offset (left to right along wall)
        east_m  = col * cell_w

        # Row → altitude (row 0 = top of grid = highest)
        # Invert row so row 0 is highest altitude
        alt = PAINTING_ALTITUDE + ((GRID_ROWS - 1 - row) * cell_h)

        # Convert to GPS
        lat, lon = drone.offset_to_gps(
            origin_lat, origin_lon, 0, east_m
        )

        waypoints.append({
            "row": row, "col": col,
            "lat": lat, "lon": lon,
            "alt": alt
        })

    return waypoints


def group_cells_by_row(cells):
    """
    Group cells by row for continuous painting.
    Returns dict: {row_number: [col1, col2, ...]}
    Sorted so we paint top-to-bottom, left-to-right.
    """
    rows = {}
    for row, col in cells:
        if row not in rows:
            rows[row] = []
        rows[row].append(col)
    # Sort columns within each row
    for r in rows:
        rows[r].sort()
    return dict(sorted(rows.items()))


# ── Singleton instance used by Flask app ─────────────────────
drone = DroneController()
