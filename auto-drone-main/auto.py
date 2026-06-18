"""
auto.py
Autonomous painting simulation for ArduPilot SITL.
Connects to SITL, takes off, visits every grid cell, sprays, returns home.
"""

# Monkey-patch collections for dronekit compatibility with Python 3.10+
import collections
import collections.abc
for attr in ("MutableMapping", "MutableSequence", "MutableSet",
             "Mapping", "Sequence", "Set", "Iterable", "Iterator",
             "Callable", "Hashable", "Sized"):
    if not hasattr(collections, attr):
        setattr(collections, attr, getattr(collections.abc, attr))

from dronekit import connect, VehicleMode, LocationGlobalRelative
import time
import math

CONN_STRING = 'tcp:127.0.0.1:5762'
ALTITUDE = 10.0
WAYPOINT_REACH_DIST = 2.0    # metres — close enough to call "arrived"
TIMEOUT = 120                # seconds — max wait for any phase


def distance_metres(loc1, loc2):
    """Approximate ground distance in metres between two GPS locations."""
    dlat = (loc2.lat - loc1.lat) * 1.113195e5
    dlon = (loc2.lon - loc1.lon) * 1.113195e5 * math.cos(math.radians(loc1.lat))
    return math.sqrt(dlat**2 + dlon**2)


def goto_and_wait(vehicle, lat, lon, alt, label="target"):
    """Fly to a waypoint and block until arrival or timeout. Re-sends command periodically."""
    target = LocationGlobalRelative(lat, lon, alt)
    last_send = 0
    RESEND_INTERVAL = 5  # re-send goto every 5 seconds
    prev_dist = None
    stale_count = 0

    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        # Re-send simple_goto periodically to survive transient connection issues
        if elapsed - last_send >= RESEND_INTERVAL:
            vehicle.simple_goto(target, groundspeed=3.0)
            last_send = elapsed

        current = vehicle.location.global_relative_frame
        dist = distance_metres(current, target)
        print(f"  -> {label}: dist={dist:.1f}m  alt={current.alt:.1f}m")

        if dist < WAYPOINT_REACH_DIST:
            break

        # Detect stale position (drone not moving)
        if prev_dist is not None and abs(dist - prev_dist) < 0.01:
            stale_count += 1
        else:
            stale_count = 0
        prev_dist = dist

        if stale_count >= 15:
            print(f"  [!] Position stale for 15s at {label}, re-sending goto...")
            vehicle.simple_goto(target, groundspeed=3.0)
            stale_count = 0

        if elapsed > TIMEOUT:
            print(f"  [!] Timeout reaching {label}, continuing...")
            break
        time.sleep(1)


def main():
    # ── Connect (retry until SITL is reachable) ──
    vehicle = None
    while vehicle is None:
        try:
            print(f"Connecting to SITL on {CONN_STRING} ...")
            vehicle = connect(CONN_STRING, wait_ready=True, heartbeat_timeout=15)
        except Exception as e:
            print(f"  Connection failed ({e}). Retrying in 5s...")
            time.sleep(5)
    print(f"Connected! Mode: {vehicle.mode.name}")

    # Wait for a valid GPS position (non-zero lat/lon)
    print("Waiting for valid GPS position...")
    t0 = time.time()
    while True:
        home = vehicle.location.global_relative_frame
        if home.lat != 0 and home.lon != 0:
            break
        if time.time() - t0 > TIMEOUT:
            print("ERROR: No valid GPS position received. Exiting.")
            vehicle.close()
            return
        time.sleep(1)
    HOME_LAT = home.lat
    HOME_LON = home.lon
    print(f"Home position: {HOME_LAT:.6f}, {HOME_LON:.6f}")

    # ── Pre-arm checks ──
    print("Waiting for vehicle to be armable...")
    t0 = time.time()
    while not vehicle.is_armable:
        if time.time() - t0 > TIMEOUT:
            print("ERROR: Vehicle never became armable. Exiting.")
            vehicle.close()
            return
        time.sleep(1)

    # ── GUIDED + Arm ──
    vehicle.mode = VehicleMode("GUIDED")
    time.sleep(2)

    vehicle.armed = True
    t0 = time.time()
    while not vehicle.armed:
        if time.time() - t0 > TIMEOUT:
            print("ERROR: Vehicle failed to arm. Exiting.")
            vehicle.close()
            return
        print("Waiting to arm...")
        time.sleep(1)

    # ── Takeoff ──
    print(f"Armed! Taking off to {ALTITUDE}m ...")
    vehicle.simple_takeoff(ALTITUDE)

    t0 = time.time()
    while vehicle.location.global_relative_frame.alt < ALTITUDE * 0.9:
        if time.time() - t0 > TIMEOUT:
            print("[!] Takeoff timeout, proceeding anyway...")
            break
        print(f"  Altitude: {vehicle.location.global_relative_frame.alt:.1f}m")
        time.sleep(1)

    print("Reached altitude! Starting paint mission...")

    # ── Paint grid — 50m square with 4 corners ──
    OFFSET = 0.00045  # ~50 metres
    paint_positions = [
        (HOME_LAT + OFFSET, HOME_LON),            # North
        (HOME_LAT + OFFSET, HOME_LON + OFFSET),   # North-East
        (HOME_LAT,          HOME_LON + OFFSET),   # East
        (HOME_LAT,          HOME_LON),             # Back to start
    ]

    for i, (lat, lon) in enumerate(paint_positions):
        cell = f"Corner {i+1}"
        print(f"\nFlying to {cell}...")
        goto_and_wait(vehicle, lat, lon, ALTITUDE, label=cell)

        print(f"{cell} -- SPRAYING")
        time.sleep(2)
        print(f"{cell} done")

    # ── RTL ──
    print("\nAll corners painted! Returning home...")
    vehicle.mode = VehicleMode("RTL")
    time.sleep(15)

    vehicle.close()
    print("Simulation complete!")


if __name__ == "__main__":
    main()