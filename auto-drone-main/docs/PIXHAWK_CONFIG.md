# Pixhawk V6X / ArduCopter Configuration Guide

> **Wall-Painting Drone** — Comprehensive setup for crab-walking, low-speed precision flight near walls.

---

## Table of Contents

1. [Firmware Installation](#firmware-installation)
2. [Frame Type](#frame-type)
3. [Critical Parameters for Wall Painting](#critical-parameters-for-wall-painting)
4. [Calibration Checklist](#calibration-checklist)
5. [SITL Simulation Setup](#sitl-simulation-setup)
6. [Mission Planner Integration](#mission-planner-integration)
7. [Mission Structure (What Our Code Uploads)](#mission-structure-what-our-code-uploads)
8. [Troubleshooting](#troubleshooting)

---

## Firmware Installation

1. Download **ArduCopter stable** from [firmware.ardupilot.org](https://firmware.ardupilot.org).
2. Open **Mission Planner → Initial Setup → Install Firmware** → select **Pixhawk V6X** → **ArduCopter**.
3. After flash: connect via USB and run the **Initial Setup wizard**.

> **Note:** Always use the latest stable release. Beta/dev builds may introduce regressions
> in waypoint navigation or yaw control that affect painting accuracy.

---

## Frame Type

- **Hexacopter X** configuration (6 motors for redundancy and payload capacity).
- Mission Planner → **Initial Setup → Frame Type → Hexa X**.

Why Hexa X:
- Motor redundancy — can survive a single motor failure and still land safely.
- Higher payload capacity for paint mechanism and fluid reservoir.
- Better stability in the turbulent airflow near walls.

---

## Critical Parameters for Wall Painting

All parameters below can be set via **Mission Planner → Config → Full Parameter List**, or
programmatically through DroneKit (`vehicle.parameters['PARAM_NAME'] = value`).

### Yaw Control (MOST IMPORTANT)

```
WP_YAW_BEHAVIOR = 0      # Never change yaw during AUTO missions
                          # This is THE key parameter for crab-walking
                          # 0 = Never change yaw
                          # 1 = Face next waypoint
                          # 2 = Face next waypoint except RTL
```

**Why this matters:** During wall painting, the drone must keep its paint nozzle pointed at the
wall at all times, even while traversing horizontal passes. The default behavior (face next
waypoint) would rotate the drone away from the wall on every lateral move. Setting this to `0`
enables true crab-walking — the drone translates left/right while maintaining a fixed heading
toward the wall.

Our code (`app.py`) also sets this programmatically via `MAV_CMD_DO_SET_ROI`, but the parameter
acts as a safety net in case the ROI command is missed.

### Speed and Navigation

```
WPNAV_SPEED     = 50      # Waypoint horizontal speed in cm/s (0.5 m/s — slow for painting)
WPNAV_SPEED_DN  = 50      # Descent speed in cm/s
WPNAV_SPEED_UP  = 50      # Ascent speed in cm/s
WPNAV_RADIUS    = 100     # Waypoint acceptance radius in cm (1 m)
WPNAV_ACCEL     = 50      # Horizontal acceleration in cm/s/s (gentle acceleration)
```

**Rationale:**
- 0.5 m/s ensures consistent paint coverage without gaps or drips.
- Large acceptance radius (1 m) prevents the drone from overshooting and oscillating
  around waypoints, which would create uneven paint lines.
- Low acceleration avoids sudden jerks that could smear paint or disturb the spray pattern.

### Position Hold Precision

```
LOIT_SPEED      = 250     # Loiter max speed in cm/s
LOIT_ACC_MAX    = 250     # Loiter max acceleration in cm/s/s
LOIT_BRK_ACCEL  = 125     # Braking acceleration in cm/s/s
LOIT_BRK_DELAY  = 1.0     # Braking delay in seconds
```

These parameters govern behavior in LOITER mode, which the drone uses while waiting at
waypoints or during manual override. Tighter loiter settings keep the drone more stable
when hovering near the wall.

### GPS Settings

```
GPS_TYPE        = 2       # uBlox protocol (for HERE3 GPS module)
GPS_GNSS_MODE   = 0       # Auto — let the receiver pick the best constellation
GPS_AUTO_CONFIG = 1       # Auto-configure GPS module on boot
```

> **Tip:** The HERE3 GPS should be mounted as far as possible from the paint mechanism
> electronics to minimize EMI interference. Use a GPS mast if needed.

### Battery and Failsafe

```
BATT_MONITOR    = 4       # Analog voltage + current sensing
BATT_CAPACITY   = [your battery mAh]  # Set to your actual battery capacity
BATT_LOW_VOLT   = 10.5    # Low voltage warning threshold (3S LiPo)
BATT_CRT_VOLT   = 10.2    # Critical voltage — triggers failsafe
BATT_FS_LOW_ACT = 2       # Action on low battery: RTL (Return to Launch)
BATT_FS_CRT_ACT = 1       # Action on critical battery: Land immediately
```

**Battery voltage thresholds by cell count:**

| Cells | Nominal | BATT_LOW_VOLT | BATT_CRT_VOLT |
|-------|---------|---------------|---------------|
| 3S    | 11.1 V  | 10.5 V        | 10.2 V        |
| 4S    | 14.8 V  | 14.0 V        | 13.6 V        |
| 6S    | 22.2 V  | 21.0 V        | 20.4 V        |

Adjust these values based on your actual battery configuration.

### GeoFence (SAFETY!)

```
FENCE_ENABLE    = 1       # Enable geofence
FENCE_TYPE      = 7       # Altitude + circle + polygon (bitmask: 1+2+4)
FENCE_ALT_MAX   = 15      # Maximum altitude 15 m (wall height is ~10 m)
FENCE_RADIUS    = 50      # Maximum distance from home point: 50 m
FENCE_ACTION    = 1       # Action on breach: RTL
```

**⚠️ WARNING:** Always enable the geofence when operating near structures. The fence prevents
flyaways and keeps the drone within the safe operating envelope around the wall.

### Telemetry (SiK Radio)

```
SERIAL1_PROTOCOL = 2      # MAVLink2 on TELEM1 port
SERIAL1_BAUD     = 57     # 57600 baud rate
```

This configures the SiK telemetry radio for real-time monitoring in Mission Planner
during autonomous painting operations.

### DroneKit / Mission Planner Connection

```
SERIAL2_PROTOCOL = 2      # MAVLink2 on TELEM2 / USB port
SERIAL2_BAUD     = 921    # 921600 baud for USB connection
```

This is the port our `app.py` connects to via DroneKit. The high baud rate is appropriate
for direct USB connections to the companion computer (e.g., Raspberry Pi).

---

## Calibration Checklist

Complete these calibrations **in order** before the first flight:

### 1. Accelerometer Calibration

- Mission Planner → **Initial Setup → Accel Calibration**
- Follow the 6-position calibration process:
  1. Level
  2. Left side
  3. Right side
  4. Nose down
  5. Nose up
  6. Upside down
- Click "Calibrate Accel" and follow on-screen prompts for each position.

### 2. Compass Calibration

- **Initial Setup → Compass → Start** calibration.
- Rotate the drone slowly through all axes (pitch, roll, yaw).
- Aim for offsets below 200 on each axis.
- If using an external compass (HERE3), ensure it is set as primary.

### 3. Radio Calibration

- **Initial Setup → Radio Calibration** → click "Calibrate Radio".
- Move all transmitter sticks and switches to their full extents.
- Verify channel mappings: Roll (CH1), Pitch (CH2), Throttle (CH3), Yaw (CH4).

### 4. ESC Calibration

- **Initial Setup → ESC Calibration** → use the "all-at-once" method.
- Follow safety warnings — **remove propellers** before ESC calibration.
- This ensures all ESCs respond identically to throttle commands.

### 5. Motor Test

- **Optional Config → Motor Test** → test each motor individually.
- Verify:
  - Correct motor order (matches Hexa X motor layout).
  - Correct spin direction (CW/CCW per motor position).
  - No vibrations or unusual noises.

### 6. PID Tuning

- Use **Autotune** mode for initial PID values:
  1. Take off in AltHold mode.
  2. Switch to Autotune.
  3. Wait for the drone to complete oscillation tests on each axis.
  4. Land and disarm to save the tuned PIDs.
- Fine-tune manually if needed for smoother wall-painting flight.

---

## SITL Simulation Setup

For testing the painting mission without real hardware:

### Installation

1. Install ArduPilot SITL by following the official guide:
   [Setting up SITL on Windows](https://ardupilot.org/dev/docs/setting-up-sitl-on-windows.html)

2. Alternatively, use WSL2 with Ubuntu for a more reliable SITL experience.

### Starting SITL

```bash
sim_vehicle.py -v ArduCopter --map --console -j4
```

### SITL Ports

| Port | Purpose                        |
|------|--------------------------------|
| 5760 | Mission Planner connection     |
| 5762 | DroneKit / `app.py` connection |
| 5763 | Spare (additional GCS)         |

### SITL Configuration

**Parameters still apply in SITL** — set `WP_YAW_BEHAVIOR = 0` in simulation too.
This ensures your simulated test matches real-world behavior.

To connect `app.py` to SITL, use:
```python
vehicle = connect('tcp:127.0.0.1:5762', wait_ready=True)
```

---

## Mission Planner Integration

### Connecting to SITL
- **Connection type:** TCP
- **Host:** `127.0.0.1`
- **Port:** `5760`

### Connecting to Real Drone
- **Connection type:** COM port (via SiK radio USB dongle)
- **Baud rate:** 57600

### KML Wall Overlay
- Flight Plan tab → right-click the map → **Overlay → Load** → select `wall_overlay.kmz`.
- This displays the wall outline on the map so you can visually verify the mission
  waypoints align with the painting surface.

### Monitoring
- Use the **Flight Data** tab to monitor AUTO mission progress in real-time.
- Watch the HUD for heading (should remain constant during crab-walking).
- Check battery voltage and current draw throughout the mission.

---

## Mission Structure (What Our Code Uploads)

The `app.py` script generates and uploads the following mission structure:

```
Command   0: MAV_CMD_DO_CHANGE_SPEED  — Set speed to 0.5 m/s
Command   1: MAV_CMD_DO_SET_ROI       — Lock yaw toward wall (100 m north)
Commands  2–101: MAV_CMD_NAV_WAYPOINT — 100 cells in serpentine pattern
Command 102: MAV_CMD_NAV_RETURN_TO_LAUNCH
```

### Serpentine Pattern

```
Start ──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ (Row 1: left to right)
                                                  │
          ←── ←── ←── ←── ←── ←── ←── ←── ←── ←──┘ (Row 2: right to left)
          │
          └──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ ──→ (Row 3: left to right)
          ...
```

The serpentine pattern minimizes repositioning time between rows. Each waypoint represents
one paint cell on the wall surface. The `DO_SET_ROI` command ensures the drone always
faces the wall regardless of travel direction.

---

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| Drone turns during flight | `WP_YAW_BEHAVIOR` ≠ 0 | Set `WP_YAW_BEHAVIOR = 0` and verify `DO_SET_ROI` is in the mission |
| Won't arm | Pre-arm check failure | Check: GPS fix (need 3D fix, HDOP < 2.0), battery voltage, safety switch pressed |
| Drifts in loiter | Compass or GPS issues | Re-calibrate compass; move GPS away from electronics / paint motor EMI |
| Altitude oscillation | PID tuning or speed too high | Tune `ALT_HOLD_P`; reduce `WPNAV_SPEED_DN` |
| Loses connection | Telemetry radio issue | Check wiring on TELEM1; ensure antenna orientation (vertical); reduce baud if noisy |
| Inconsistent paint coverage | Speed too high or wind | Reduce `WPNAV_SPEED`; check weather conditions (max 10 km/h wind) |
| Mission doesn't start | Mode not set to AUTO | Ensure vehicle is in AUTO mode after uploading mission; check mission item count |
| GPS HDOP too high | Multipath near wall | Use RTK GPS or move home point to open area; wait for more satellites |

### Pre-Flight Safety Checklist

- [ ] Propellers secure and correct orientation
- [ ] Battery fully charged and voltage confirmed
- [ ] GPS fix acquired (3D fix, HDOP < 2.0)
- [ ] Geofence enabled and parameters verified
- [ ] `WP_YAW_BEHAVIOR = 0` confirmed
- [ ] Telemetry link active and Mission Planner connected
- [ ] Paint mechanism tested and loaded
- [ ] Area cleared of personnel (minimum safe distance)
- [ ] Emergency stop (kill switch) tested on transmitter
- [ ] Wind speed checked (< 10 km/h recommended)
