import collections
import collections.abc
for attr in ("MutableMapping", "MutableSequence", "MutableSet",
             "Mapping", "Sequence", "Set", "Iterable", "Iterator",
             "Callable", "Hashable", "Sized"):
    if not hasattr(collections, attr):
        setattr(collections, attr, getattr(collections.abc, attr))

import time
import math
from dronekit import connect as dk_connect, VehicleMode, LocationGlobalRelative, Command
from pymavlink import mavutil


def distance_metres(lat1, lon1, lat2, lon2):
    """Haversine-like flat-earth distance in metres between two GPS points."""
    dlat = (lat2 - lat1) * 111319.5
    dlon = (lon2 - lon1) * 111319.5 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.sqrt(dlat * dlat + dlon * dlon)


class DroneController:
    def __init__(self):
        self.vehicle = None
        self.connected = False

    def connect(self, conn_string, timeout=30):
        """Connect to vehicle via DroneKit. Retry-safe."""
        if self.vehicle is not None:
            try:
                self.disconnect()
            except Exception:
                pass

        print("[DroneController] Connecting to %s ..." % conn_string)
        try:
            self.vehicle = dk_connect(conn_string, wait_ready=True, heartbeat_timeout=timeout)
            self.connected = True
            print("[DroneController] Connected. Firmware: %s" % self.vehicle.version)
            return True
        except Exception as e:
            self.vehicle = None
            self.connected = False
            print("[DroneController] Connection failed: %s" % e)
            return False

    def disconnect(self):
        """Close vehicle connection."""
        if self.vehicle is not None:
            try:
                self.vehicle.close()
                print("[DroneController] Disconnected.")
            except Exception as e:
                print("[DroneController] Error during disconnect: %s" % e)
            finally:
                self.vehicle = None
                self.connected = False

    def arm_and_takeoff(self, altitude=3.0, timeout=60):
        """Wait for armable, switch to GUIDED, arm, takeoff, wait for altitude."""
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        print("[DroneController] Waiting for vehicle to become armable ...")
        deadline = time.time() + timeout
        while not self.vehicle.is_armable:
            if time.time() > deadline:
                print("[DroneController] Timeout waiting for armable state.")
                return False
            time.sleep(1)

        print("[DroneController] Setting GUIDED mode ...")
        self.vehicle.mode = VehicleMode("GUIDED")
        deadline = time.time() + timeout
        while self.vehicle.mode.name != "GUIDED":
            if time.time() > deadline:
                print("[DroneController] Timeout waiting for GUIDED mode.")
                return False
            time.sleep(0.5)

        print("[DroneController] Arming motors ...")
        self.vehicle.armed = True
        deadline = time.time() + timeout
        while not self.vehicle.armed:
            if time.time() > deadline:
                print("[DroneController] Timeout waiting for arming.")
                return False
            time.sleep(0.5)

        # Disable auto-yaw so drone won't turn to face waypoints (crab-walk)
        try:
            self.vehicle.parameters['WP_YAW_BEHAVIOR'] = 0
            print("[DroneController] WP_YAW_BEHAVIOR set to 0 (never change yaw)")
        except Exception as e:
            print("[DroneController] Warning: could not set WP_YAW_BEHAVIOR: %s" % e)

        print("[DroneController] Taking off to %.1f m ..." % altitude)
        self.vehicle.simple_takeoff(altitude)

        deadline = time.time() + timeout
        while True:
            current_alt = self.vehicle.location.global_relative_frame.alt or 0.0
            print("[DroneController]   Altitude: %.1f m" % current_alt)
            if current_alt >= altitude * 0.95:
                print("[DroneController] Reached target altitude.")
                return True
            if time.time() > deadline:
                print("[DroneController] Timeout waiting for target altitude.")
                return False
            time.sleep(1)

    def goto_global(self, lat, lon, alt, groundspeed=2.0):
        """Send vehicle to GPS position using SET_POSITION_TARGET_GLOBAL_INT.
        Explicitly sets yaw=0 (north) so drone strafes without turning."""
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        self.vehicle.groundspeed = groundspeed

        # Use SET_POSITION_TARGET_GLOBAL_INT for yaw control
        # type_mask bits (1=ignore): 
        #   0-2: position (000 = use lat/lon/alt)
        #   3-5: velocity (111 = ignore)
        #   6-8: accel    (111 = ignore)
        #   9:   force    (0)
        #   10:  yaw      (0 = USE yaw)
        #   11:  yaw_rate (1 = ignore)
        # = 0b0000_1001_1111_1000 = 0x09F8
        msg = self.vehicle.message_factory.set_position_target_global_int_encode(
            0,       # time_boot_ms
            0, 0,    # target system, component
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000100111111000,  # type_mask: use pos + yaw, ignore vel/accel/yaw_rate
            int(lat * 1e7),     # lat_int
            int(lon * 1e7),     # lon_int
            alt,                # alt (relative)
            0, 0, 0,            # vx, vy, vz (ignored)
            0, 0, 0,            # afx, afy, afz (ignored)
            0,                  # yaw = 0 radians (north)
            0                   # yaw_rate (ignored)
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()
        print("[DroneController] Heading to (%.7f, %.7f, %.1f) at %.1f m/s, yaw=NORTH" % (lat, lon, alt, groundspeed))
        return True

    def _send_yaw_north(self):
        """Send MAV_CMD_CONDITION_YAW to lock heading north (0 deg)."""
        if self.vehicle is None:
            return
        msg = self.vehicle.message_factory.command_long_encode(
            0, 0,
            mavutil.mavlink.MAV_CMD_CONDITION_YAW,
            0,
            0,     # heading 0 = north
            0,     # yaw speed 0 = instant
            1,     # direction CW
            0,     # absolute
            0, 0, 0
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()

    def set_yaw(self, heading_deg, relative=False):
        """Lock drone yaw to a specific heading (degrees, 0=North, 90=East).
        relative=True means rotate BY heading_deg from current heading.
        """
        if self.vehicle is None:
            return
        is_relative = 1 if relative else 0
        msg = self.vehicle.message_factory.command_long_encode(
            0, 0,
            mavutil.mavlink.MAV_CMD_CONDITION_YAW,
            0,
            heading_deg,   # target angle
            10,            # yaw speed deg/s
            1,             # direction: 1=CW, -1=CCW (only for relative)
            is_relative,   # 0=absolute, 1=relative
            0, 0, 0
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()
        print("[DroneController] Yaw set to %d deg (%s)" % (heading_deg, "relative" if relative else "absolute"))

    def upload_mission(self, waypoints, speed=0.5):
        """Upload a list of (lat, lon, alt) waypoints as an AUTO mission.
        Inserts DO_SET_ROI at start to lock yaw north, and
        sets WP_YAW_BEHAVIOR=0 to prevent auto-yaw.
        """
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        cmds = self.vehicle.commands
        cmds.clear()

        # Set speed for the mission
        cmds.add(Command(
            0, 0, 0,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
            0, 0,
            0,      # speed type: 0=airspeed, 1=groundspeed
            speed,  # speed in m/s
            -1,     # throttle (-1 = no change)
            0, 0, 0, 0
        ))

        # Set ROI to a point far north to lock yaw facing wall
        first_lat, first_lon, first_alt = waypoints[0]
        # ROI 100m north of first waypoint
        roi_lat, roi_lon = DroneController.offset_to_gps(first_lat, first_lon, 0, 100.0)
        cmds.add(Command(
            0, 0, 0,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_DO_SET_ROI,
            0, 0,
            0, 0, 0, 0,
            roi_lat, roi_lon, first_alt
        ))

        # Add all waypoints
        for lat, lon, alt in waypoints:
            cmds.add(Command(
                0, 0, 0,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                0, 0,
                0,   # hold time (0 = fly through)
                1.0, # acceptance radius metres
                0,   # pass through (0 = go to waypoint)
                0,   # yaw (0 = unused when ROI is set)
                lat, lon, alt
            ))

        # End with RTL
        cmds.add(Command(
            0, 0, 0,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
            0, 0,
            0, 0, 0, 0, 0, 0, 0
        ))

        print("[DroneController] Uploading mission with %d waypoints..." % len(waypoints))
        cmds.upload()
        print("[DroneController] Mission uploaded.")

        # Set WP_YAW_BEHAVIOR = 0 (never change yaw in AUTO)
        try:
            self.vehicle.parameters['WP_YAW_BEHAVIOR'] = 0
            print("[DroneController] WP_YAW_BEHAVIOR = 0 (never change yaw)")
        except Exception as e:
            print("[DroneController] Warning: could not set WP_YAW_BEHAVIOR: %s" % e)

        return True

    def start_mission(self):
        """Switch to AUTO mode to start uploaded mission."""
        if self.vehicle is None:
            return False
        self.vehicle.commands.next = 0
        self.vehicle.mode = VehicleMode("AUTO")
        deadline = time.time() + 10
        while self.vehicle.mode.name != "AUTO":
            if time.time() > deadline:
                print("[DroneController] Timeout switching to AUTO.")
                return False
            time.sleep(0.5)
        print("[DroneController] AUTO mode active, mission started.")
        return True

    def get_mission_progress(self):
        """Return current mission waypoint index (0-based)."""
        if self.vehicle is None:
            return -1
        return self.vehicle.commands.next

    def wait_for_waypoint(self, wp_index, timeout=120):
        """Block until the vehicle reaches or passes waypoint wp_index.
        wp_index is the mission command index (0-based)."""
        if self.vehicle is None:
            return False
        deadline = time.time() + timeout
        while True:
            current = self.vehicle.commands.next
            if current > wp_index:
                return True
            if time.time() > deadline:
                print("[DroneController] Timeout waiting for waypoint %d (at %d)." % (wp_index, current))
                return False
            time.sleep(0.5)

    def wait_until_reached(self, lat, lon, alt, threshold=2.0, timeout=120):
        """Block until vehicle reaches position. Re-sends position command
        every 3s with yaw=north so drone crab-walks without turning."""
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        deadline = time.time() + timeout
        last_resend = 0
        while True:
            loc = self.vehicle.location.global_relative_frame
            current_lat = loc.lat or 0.0
            current_lon = loc.lon or 0.0
            current_alt = loc.alt or 0.0

            horiz_dist = distance_metres(current_lat, current_lon, lat, lon)
            vert_dist = abs(current_alt - alt)
            total_dist = math.sqrt(horiz_dist ** 2 + vert_dist ** 2)

            if total_dist <= threshold:
                print("[DroneController] Reached target (dist=%.2f m)." % total_dist)
                return True
            if time.time() > deadline:
                print("[DroneController] Timeout reaching target (dist=%.2f m)." % total_dist)
                return False

            # Re-send position+yaw command every 3 seconds
            now = time.time()
            if now - last_resend > 3:
                self.goto_global(lat, lon, alt, self.vehicle.groundspeed or 0.5)
                last_resend = now

            time.sleep(1)

    def return_to_launch(self):
        """Switch to RTL mode."""
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        print("[DroneController] Switching to RTL ...")
        self.vehicle.mode = VehicleMode("RTL")
        deadline = time.time() + 10
        while self.vehicle.mode.name != "RTL":
            if time.time() > deadline:
                print("[DroneController] Timeout switching to RTL.")
                return False
            time.sleep(0.5)
        print("[DroneController] RTL mode active.")
        return True

    def land(self):
        """Switch to LAND mode."""
        if self.vehicle is None:
            print("[DroneController] Not connected.")
            return False

        print("[DroneController] Switching to LAND ...")
        self.vehicle.mode = VehicleMode("LAND")
        deadline = time.time() + 10
        while self.vehicle.mode.name != "LAND":
            if time.time() > deadline:
                print("[DroneController] Timeout switching to LAND.")
                return False
            time.sleep(0.5)
        print("[DroneController] LAND mode active.")
        return True

    def get_status(self):
        """Return dict with vehicle telemetry."""
        if self.vehicle is None:
            return {
                "armed": False,
                "mode": "N/A",
                "altitude": 0.0,
                "lat": 0.0,
                "lon": 0.0,
                "battery": None,
                "groundspeed": 0.0,
                "gps_fix": 0,
                "is_armable": False,
            }

        loc = self.vehicle.location.global_relative_frame
        batt = self.vehicle.battery
        gps = self.vehicle.gps_0

        return {
            "armed": self.vehicle.armed,
            "mode": self.vehicle.mode.name,
            "altitude": loc.alt if loc.alt is not None else 0.0,
            "lat": loc.lat if loc.lat is not None else 0.0,
            "lon": loc.lon if loc.lon is not None else 0.0,
            "heading": self.vehicle.heading or 0,
            "battery": batt.level if batt else None,
            "groundspeed": self.vehicle.groundspeed or 0.0,
            "gps_fix": gps.fix_type if gps else 0,
            "is_armable": self.vehicle.is_armable,
        }

    @staticmethod
    def offset_to_gps(origin_lat, origin_lon, east_m, north_m):
        """Convert metre offsets from origin to GPS coordinates.
        Returns (lat, lon).
        """
        lat = origin_lat + (north_m / 111319.5)
        lon = origin_lon + (east_m / (111319.5 * math.cos(math.radians(origin_lat))))
        return (lat, lon)

    @staticmethod
    def cells_to_waypoints(cells, origin_lat, origin_lon, top_alt, cell_width=1.0):
        """Convert grid cells [(row,col),...] to GPS waypoints [(lat,lon,alt),...].
        Row 0 = top of wall (highest altitude), row N = bottom (lowest altitude).
        Each column = cell_width east offset from origin.
        Each row = cell_width altitude drop from top_alt.
        """
        waypoints = []
        for row, col in cells:
            east_m = col * cell_width
            alt = top_alt - row * cell_width  # Row 0 = top, rows go down
            alt = max(alt, 1.0)  # Don't go below 1m
            lat, lon = DroneController.offset_to_gps(origin_lat, origin_lon, east_m, 0.0)
            waypoints.append((lat, lon, alt))
        return waypoints

    @staticmethod
    def group_cells_by_row(cells):
        """Group cells by row number. Returns dict {row: [col1, col2, ...]} sorted."""
        groups = {}
        for row, col in cells:
            groups.setdefault(row, []).append(col)
        for row in groups:
            groups[row].sort()
        return dict(sorted(groups.items()))
