# Flight Operations & Safety Guide — Wall-Painting Drone

> **Read this entire document before your first flight.**
> This guide covers pre-flight checks, flight procedures, emergency protocols, and post-flight steps for the autonomous wall-painting drone system.

---

## Pre-Flight Checklist

### Hardware Checks (before every flight)

- [ ] Battery fully charged (3S: 12.6V = full, 10.5V = low)
- [ ] All propellers secure, no cracks, correct rotation direction
- [ ] Frame tight, no loose screws or vibrations
- [ ] GPS mast secure, unobstructed view of sky
- [ ] ESP32-CAM mounted securely, camera facing wall direction
- [ ] Spray pump loaded with paint/water, nozzle clear
- [ ] Relay wiring secure, no exposed connections
- [ ] Telemetry radio connected and paired
- [ ] Safety switch accessible
- [ ] Kill switch / manual RC override available and tested
- [ ] No propeller damage or debris

### Software Checks

- [ ] ArduPilot SITL or real Pixhawk running
- [ ] Mission Planner connected and showing telemetry
- [ ] Flask app running (`python app.py`)
- [ ] `SIMULATION_MODE` set correctly (`True` for sim, `False` for real)
- [ ] ESP32-CAM WiFi AP visible ("PaintDrone")
- [ ] Browser can reach <http://localhost:5000>
- [ ] GPS fix acquired (3D fix, HDOP < 2.0)
- [ ] Battery level above 80% for full painting run
- [ ] `WP_YAW_BEHAVIOR` confirmed as `0`
- [ ] Geofence configured and enabled

### Environment Checks

- [ ] Wind speed < 10 km/h (ideally < 5 km/h for painting)
- [ ] No rain or excessive moisture
- [ ] Wall surface identified and accessible
- [ ] Clear area around flight zone (min 10m buffer on all sides)
- [ ] No overhead obstacles (wires, branches, roofs)
- [ ] No people in the flight zone
- [ ] Ground station operator has clear line of sight

---

## Flight Procedure

### Step 1: Setup

1. Position drone 5–10m in front of wall, centered.
2. Power on drone, wait for GPS lock.
3. Connect Mission Planner (verify all green in HUD).
4. Connect laptop to **PaintDrone** WiFi.
5. Start Flask app: `python app.py`
6. Open browser: <http://localhost:5000>

### Step 2: Capture and Detection

1. Click **"Capture & Detect"** or use the **"Run Demo"** button.
2. Review detected grid — green = unpainted cells.
3. Manually toggle cells if detection missed any areas.
4. Verify the cell count matches expectations.

### Step 3: Demo Flight (Automated)

1. Click **"Run Demo"**.
2. System will:
   - Connect to drone on port `5762`
   - Arm motors (check: hear motors spin up)
   - Takeoff to 10m (top of wall)
   - Upload 100 waypoints (serpentine pattern)
   - Set ROI 100m north (lock yaw toward wall)
   - Switch to AUTO mode
   - Fly serpentine, marking each cell as complete
   - RTL when done
3. Monitor progress on grid display.
4. Watch drone heading — should stay constant (crab-walking).

### Step 4: Manual Override

At **ANY** time:

- **Mission Planner:** switch to LOITER or RTL
- **RC transmitter:** flip to manual mode
- **Flask app:** click **"Abort"** button
- **Physical:** hit the safety/kill switch

---

## Emergency Procedures

### Drone Not Responding

1. Switch to **STABILIZE** mode via RC transmitter.
2. If no RC: use Mission Planner to set **RTL**.
3. If no telemetry: wait for failsafe (auto-land after 30s no heartbeat).
4. Last resort: cut power via kill switch.

### Flyaway

1. **Do NOT chase the drone.**
2. Switch to **RTL** via any available method.
3. If RTL fails, switch to **LAND**.
4. Note last known GPS coordinates from Mission Planner.
5. Report to local authorities if drone is lost.

### Battery Emergency

- **Low battery alarm:** drone auto-RTLs (configured in parameters).
- **Critical battery:** drone auto-lands at current position.
- **NEVER** continue a mission with low battery warning.

### Spray System Malfunction

- **Pump won't stop:** Flask sends `/spray_stop` → ESP32-CAM GPIO 13 LOW.
- **ESP32-CAM unresponsive:** pump stops when drone powers off (relay de-energizes).
- **Pump leaks:** abort mission, land immediately.

---

## Safety Rules

1. **NEVER** fly over people.
2. Always have a spotter watching the drone.
3. Keep minimum 10m distance from the drone during flight.
4. Always have RC transmitter as manual backup.
5. Test spray system on ground before flight.
6. First flights: use water only, not paint.
7. Maximum wind speed for painting: 5 km/h.
8. Never operate near airports or restricted airspace.
9. Follow local drone regulations (weight class, registration, pilot license).
10. Have a fire extinguisher nearby (LiPo batteries).

---

## Flight Modes Used

| Mode | When | Notes |
|------|------|-------|
| GUIDED | Arm & takeoff | Initial takeoff only |
| AUTO | Wall painting | Main painting mode, follows uploaded mission |
| RTL | After painting / emergency | Returns to launch point |
| LOITER | Manual override | Holds position |
| STABILIZE | Emergency | Full manual control |
| LAND | Emergency | Lands at current position |

---

## Performance Expectations

- **10×10 wall (100 cells) at 0.5 m/s:** approximately 15–25 minutes.
- **Battery consumption:** ~40–60% for full wall (depends on conditions).
- **GPS accuracy:** ±1–3m horizontal (affects cell targeting).
- **Painting accuracy:** ±0.5m (limited by GPS, wind).
- **Best results:** calm conditions, good GPS fix, wall < 15m away.

---

## Post-Flight

1. Land drone, disarm motors.
2. Disconnect battery immediately.
3. Inspect propellers for damage.
4. Check spray system for leaks.
5. Download flight logs from Mission Planner (**Ctrl+F → Dataflash Logs**).
6. Review flight log for any anomalies.
7. Clean spray nozzle if using paint.
8. Store battery at storage voltage (11.1V for 3S).
