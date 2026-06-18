# Hardware Setup Guide — Autonomous Drone Wall-Painting System

This guide covers the complete hardware assembly for the autonomous wall-painting drone. The system uses a hexacopter platform with a Pixhawk V6X flight controller, ESP32-CAM for vision and spray control, and a relay-driven pump for paint delivery.

> **⚠️ Safety Warning:** This project involves high-current LiPo batteries, spinning propellers, and pressurized fluid. Always follow safe practices — never arm the drone with people nearby, use a kill switch, and test on the bench before flight.

---

## Bill of Materials (BOM)

### Flight Platform (Essential)

| Component | Description | Approx. Price | Notes |
|---|---|---|---|
| Hexacopter Frame | 550–650mm hex frame kit | $60–$120 | Must support 6 motors; aluminum/carbon fiber |
| Brushless Motors (6x) | 2212–2216 class, ~920KV | $12–$20 each | Match to frame size and prop diameter |
| Rubicon ESCs (6x) | 30A–40A ESC | $15–$25 each | Must support the motor current draw |
| Propellers (6x + spares) | 10"–13" props (3 CW, 3 CCW) | $10–$20/set | Always carry spares; check motor thread direction |
| 3S LiPo Battery | 11.1V, 5000–8000mAh, 25C+ | $40–$70 | Higher capacity = longer flight, but heavier |
| LiPo Battery Charger | Balance charger (e.g., ISDT, SkyRC) | $30–$50 | **Never charge unattended** |
| Power Distribution Board | Included with most frames | $0–$15 | Must support 6 ESC outputs |

### Flight Controller & Navigation (Essential)

| Component | Description | Approx. Price | Notes |
|---|---|---|---|
| Pixhawk V6X | Flight controller (runs ArduCopter) | $200–$300 | Holybro recommended; includes PM02 power module |
| HERE3 GPS Module | GNSS with compass (CAN bus) | $80–$120 | Mounts on a mast away from interference |
| GPS Mast | Foldable or fixed mast | $5–$15 | Raises GPS above frame for clean signal |
| 433MHz SiK Telemetry Radio | Air + ground pair | $30–$50 | For Mission Planner / QGroundControl link |
| Power Module (PM02 or PM07) | Voltage/current sensor for Pixhawk | Included w/ Pixhawk | Connects LiPo → Pixhawk POWER1 port |

### Spray System (Essential)

| Component | Description | Approx. Price | Notes |
|---|---|---|---|
| ESP32-CAM (AI Thinker) | Camera + WiFi + GPIO control | $8–$12 | Creates WiFi AP; controls relay via GPIO 13 |
| Relay Module (1-channel) | Active HIGH, 5V coil | $3–$5 | **Must be 5V relay — 3.3V will NOT work** |
| 12V Water Pump | DC diaphragm or peristaltic pump | $10–$20 | Self-priming preferred; check flow rate |
| Spray Nozzle | Adjustable flat-fan or cone nozzle | $3–$8 | Controls spray pattern and width |
| Silicone Tubing | 6mm ID, ~1m length | $3–$5 | Food-grade silicone resists paint |
| Paint Reservoir | Small container, 200–500mL | $5–$10 | Must be leak-proof; mount securely |
| Buck Converter (12V → 5V) | DC-DC step-down, 3A+ output | $3–$8 | Powers ESP32-CAM and relay from LiPo |

### Programming & Setup (Essential for initial setup)

| Component | Description | Approx. Price | Notes |
|---|---|---|---|
| ESP32-S3 Dev Board | Used as USB-to-serial programmer | $8–$15 | Only needed for flashing ESP32-CAM |
| Jumper Wires | Male-to-female, assorted | $3–$5 | For ESP32-S3 ↔ ESP32-CAM connections |
| Micro-USB / USB-C Cables | For Pixhawk and ESP32 programming | $5–$10 | Check connector type for your boards |

### Optional but Recommended

| Component | Description | Approx. Price | Notes |
|---|---|---|---|
| FPV Camera + VTX | Real-time video feed to goggles/monitor | $30–$60 | Helpful for manual flight and aiming |
| Buzzer / LED Strip | For status indication | $3–$5 | ArduCopter supports buzzer on Pixhawk |
| Landing Gear (tall) | Extended legs for ground clearance | $10–$20 | Needed to clear the pump/nozzle underneath |
| Vibration Dampening Mount | For Pixhawk | $5–$10 | Reduces IMU noise from motors |
| Safety Kill Switch | External arming switch | $5–$10 | **Highly recommended** — physical arm/disarm |
| LiPo Voltage Alarm | Plugs into balance lead | $3–$5 | Beeps when battery is low |
| Zip Ties & Mounting Tape | Assorted | $5 | For cable management and securing components |

**Estimated Total: $550–$950** (depending on component quality and sourcing)

---

## Wiring Diagrams

### ESP32-CAM Wiring (Spray Control)

The ESP32-CAM controls the paint pump via a relay on GPIO 13. The relay switches 12V battery power to the pump motor.

```
ESP32-CAM GPIO 13 → Relay IN
ESP32-CAM 5V      → Relay VCC (must be 5V, not 3.3V!)
ESP32-CAM GND     → Relay GND
Relay COM          → 12V battery positive
Relay NO           → Pump positive
Pump negative      → 12V battery negative (common ground)
```

**Important details:**
- The relay is **active HIGH** — GPIO 13 HIGH = relay energized = pump ON.
- Use the **NO** (Normally Open) terminal so the pump is OFF by default (fail-safe).
- The relay VCC **must** be 5V. At 3.3V the relay coil won't generate enough magnetic force to click the switch — the pump simply won't fire.
- Add a flyback diode across the pump terminals (cathode to positive) if your relay module doesn't include one. This protects against back-EMF when the pump switches off.

```
         ESP32-CAM                    Relay Module                  Pump Circuit
        ┌──────────┐                ┌─────────────┐
        │     GPIO13├───────────────┤ IN          │
        │          │                │             │           ┌──────────┐
        │       5V ├───────────────┤ VCC     COM ├───────────┤ 12V Batt+│
        │          │                │             │           └──────────┘
        │      GND ├───────────────┤ GND      NO ├───────────┤ Pump +   │
        └──────────┘                └─────────────┘           └──────────┘
                                                               Pump -
                                                                 │
                                                              12V Batt-
                                                            (common GND)
```

### ESP32-S3 to ESP32-CAM (Programming Connection)

The ESP32-S3 dev board acts as a USB-to-serial bridge for flashing firmware onto the ESP32-CAM. **This connection is only needed during programming** — the ESP32-S3 is not part of the flight hardware.

```
ESP32-S3 GPIO17 (TX) → ESP32-CAM U0R (RX)
ESP32-S3 GPIO18 (RX) → ESP32-CAM U0T (TX)
ESP32-S3 GND         → ESP32-CAM GND
ESP32-S3 5V          → ESP32-CAM 5V
ESP32-CAM IO0        → GND (boot mode for flashing)
```

**Flashing procedure:**
1. Wire the ESP32-S3 to ESP32-CAM as shown above.
2. Connect **IO0 to GND** on the ESP32-CAM to enter bootloader/flash mode.
3. Upload firmware via PlatformIO or Arduino IDE (see [ESP32_PROGRAMMING.md](ESP32_PROGRAMMING.md)).
4. After flashing is complete:
   - **Remove the IO0 ↔ GND jumper** (otherwise the ESP32-CAM stays in boot mode).
   - **Disconnect the ESP32-S3 entirely** — it is not needed during operation.
5. Power-cycle the ESP32-CAM; it should boot normally and create the "PaintDrone" WiFi AP.

> **Note:** If you have an FTDI adapter or other USB-to-serial converter, you can use that instead of the ESP32-S3. The wiring is the same: TX→RX, RX→TX, GND→GND, 5V→5V, IO0→GND for flash mode.

### Pixhawk V6X Connections

```
Pixhawk V6X Port    Connection                    Notes
─────────────────────────────────────────────────────────────
GPS1 (CAN)           HERE3 GPS module              CAN bus; set CAN_D1_PROTOCOL=1
TELEM1               SiK 433MHz radio (air unit)   57600 baud default
POWER1               PM02/PM07 power module        Voltage + current sensing
MAIN OUT 1–6         ESCs (6x)                     Motor outputs; check order
USB-C                Computer (setup/indoor)        Mission Planner / QGC
SAFETY               Safety switch (optional)       Physical arm/disarm button
BUZZER               Buzzer (optional)              Audio feedback
```

**CAN bus setup for HERE3 GPS:**
- In Mission Planner, set `CAN_D1_PROTOCOL = 1` (DroneCAN/UAVCAN).
- Set `GPS_TYPE = 9` (DroneCAN).
- The HERE3 also provides a compass — ArduCopter will auto-detect it.

### Power Distribution

```
3S LiPo Battery (11.1V, fully charged ~12.6V)
  │
  ├──► Power Module (PM02/PM07)
  │       └──► Pixhawk V6X POWER1 port
  │            (provides regulated 5V to Pixhawk + voltage/current sensing)
  │
  ├──► Power Distribution Board
  │       └──► ESCs (6x) ──► Brushless Motors (6x)
  │
  ├──► Buck Converter (12V → 5V, 3A+)
  │       ├──► ESP32-CAM 5V pin
  │       └──► Relay Module VCC (5V)
  │
  └──► Relay COM terminal (direct 12V)
          └──► Relay NO ──► Pump + (switched 12V)
                              Pump - ──► Battery GND
```

**Power notes:**
- The buck converter input can tap off the PDB or directly from the battery via an XT30/XT60 pigtail.
- Use at least **18 AWG wire** for the pump circuit (12V side) — pumps can draw 2–5A.
- Use at least **12–14 AWG wire** for ESC power leads.
- All grounds must be **common** — battery negative, buck converter GND, ESP32-CAM GND, relay GND, and pump negative all connect to the same ground rail.

---

## Assembly Steps

Follow this order to build the system methodically. Test each subsystem before integrating.

### Step 1: Build the Hexacopter Frame
- Assemble the frame per manufacturer instructions.
- Mount all 6 brushless motors (3 CW, 3 CCW — follow the ArduCopter hex motor layout).
- Attach propeller adapters (do **not** install propellers yet).
- Route ESC signal and power wires cleanly through the arms.
- Connect ESCs to the power distribution board.

### Step 2: Mount the Pixhawk V6X
- Secure the Pixhawk to the frame center using vibration-dampening foam or a dampening mount.
- Orient the Pixhawk with the **arrow pointing forward** (direction of travel).
- Connect the power module: LiPo → PM02/PM07 → Pixhawk POWER1 port.
- Connect ESC signal wires to MAIN OUT ports 1–6 (see [ArduCopter motor order](https://ardupilot.org/copter/docs/connect-escs-and-motors.html) for hex layout).

### Step 3: Mount GPS on Mast
- Attach the GPS mast to the rear of the frame (or wherever it's furthest from ESCs/wires).
- Mount the HERE3 GPS on top of the mast with the arrow pointing forward.
- Connect the HERE3 to the Pixhawk **GPS1 (CAN)** port using the supplied cable.
- Ensure the cable is secured and won't snag on propellers.

### Step 4: Connect Telemetry Radio
- Mount the SiK air unit on the frame (use Velcro or zip tie).
- Connect to Pixhawk **TELEM1** port.
- Keep the antenna vertical and away from other electronics.
- Plug the ground unit into your laptop via USB.

### Step 5: Flash and Test ESP32-CAM Separately
- **Do this on a bench — NOT on the drone.**
- Wire the ESP32-S3 to ESP32-CAM as described in the programming section above.
- Flash the firmware (see [ESP32_PROGRAMMING.md](ESP32_PROGRAMMING.md) for detailed instructions).
- Verify the "PaintDrone" WiFi AP appears and responds to HTTP commands.
- Test the relay and pump on the bench (see [Testing Without Drone](#testing-without-drone) below).

### Step 6: Mount ESP32-CAM on Drone
- Mount the ESP32-CAM facing **forward** (camera lens unobstructed).
- Use a 3D-printed mount or secure with mounting tape + zip ties.
- **Keep the antenna (the small gold trace on the PCB) away from motors and ESCs** — EMI will degrade WiFi performance.
- Route wires cleanly and secure with zip ties.

### Step 7: Mount Spray System
- Mount the relay module on the frame in a protected location.
- Mount the pump securely (vibration can loosen connections).
- Attach the spray nozzle to the drone underside or front, aimed in the spray direction.
- Connect tubing: reservoir → pump inlet → pump outlet → nozzle.
- Ensure tubing is secured and won't contact propellers.

### Step 8: Connect Power Distribution
- Wire the buck converter: input from PDB/battery, output (5V) to ESP32-CAM and relay VCC.
- Wire the relay: COM to 12V battery, NO to pump positive, pump negative to battery negative.
- Wire the ESP32-CAM: 5V from buck converter, GND to common ground, GPIO 13 to relay IN.
- Double-check all connections against the wiring diagrams above.
- Secure all wires with zip ties; ensure nothing can contact spinning parts.

### Step 9: Pre-Flight Verification
Before the first power-on:
- [ ] **Visual inspection**: No loose wires, no exposed conductors, no pinched cables.
- [ ] **Propellers removed** (for initial power-on testing).
- [ ] **LiPo voltage**: Fully charged (12.4–12.6V for 3S).
- [ ] **ESC connections**: Correct motor order (1–6) per ArduCopter hex layout.
- [ ] **GPS mast**: Secure, arrow forward.
- [ ] **Pixhawk orientation**: Arrow forward.
- [ ] **ESP32-CAM**: Powered, WiFi AP active, relay responding to commands.
- [ ] **Pump circuit**: Relay clicks, pump runs when commanded.
- [ ] **Telemetry**: Ground station connects and shows telemetry data.
- [ ] **Safety switch**: If installed, verify it prevents accidental arming.

---

## Important Notes

### Relay Power
- The relay module VCC **must be 5V**. At 3.3V, the electromagnetic coil cannot generate enough force to actuate the switch — the relay will not click and the pump will not fire. This is the most common wiring mistake.

### WiFi Access Point
- The ESP32-CAM creates a WiFi network called **"PaintDrone"** on boot.
- Default IP address: **192.168.4.1**
- Connect from your phone or laptop to send spray commands and view the camera feed.

### EMI / Electromagnetic Interference
- Keep the ESP32-CAM antenna as far from motors and ESCs as possible.
- ESCs generate significant electrical noise that can disrupt WiFi and GPS signals.
- Use ferrite rings on ESC power wires if you experience connectivity issues.
- The GPS mast serves the same purpose — elevating the GPS away from interference sources.

### Pump Current Draw
- DC diaphragm pumps can draw **2–5A at 12V**. Use appropriate wire gauge:
  - **18 AWG minimum** for the pump circuit.
  - **16 AWG preferred** for runs longer than 15cm.
- Ensure relay contacts are rated for the pump's current draw (most relay modules handle 10A).

### Safety
- **Always use a safety switch or kill switch** — an external arming button prevents accidental motor spin-up.
- **NEVER arm the drone with people nearby.** Hexacopter propellers can cause serious injury.
- **Remove propellers** during all bench testing and initial setup.
- **LiPo safety**: Never charge unattended, never over-discharge (set low-voltage alarm at 3.3V/cell = 9.9V for 3S), store at storage voltage (~11.1V / 3.7V per cell).
- **Test the kill switch** before every flight session.

---

## Testing Without Drone

You can (and should) test the entire spray system on a bench before mounting it on the drone. This verifies the ESP32-CAM firmware, relay wiring, and pump operation without any flight risk.

### What You Need
- ESP32-CAM (flashed with PaintDrone firmware)
- 5V power supply (USB adapter or bench supply)
- Relay module
- 12V pump + nozzle + tubing
- 12V power supply or LiPo battery
- A cup of water (for testing — not paint!)
- A phone or laptop with WiFi

### Bench Test Procedure

**1. Power the ESP32-CAM**
```bash
# Via USB or 5V supply — no drone battery needed for this test
# The ESP32-CAM should boot and create the WiFi AP
```

**2. Connect to the WiFi AP**
- On your phone or laptop, connect to the **"PaintDrone"** WiFi network.
- No password required (open AP) — or enter the password if one was configured in firmware.

**3. Verify connectivity**
```bash
curl http://192.168.4.1/ping
```
Expected response: a JSON acknowledgment confirming the ESP32-CAM is running.

**4. Test the spray relay**
```bash
curl -X POST http://192.168.4.1/spray -d "duration_ms=500"
```
- You should **hear the relay click** (energize for 500ms, then de-energize).
- If the pump is connected and primed, it should spray for half a second.

**5. Verify pump operation**
- Fill a small container with water and submerge the pump inlet (or connect tubing).
- Run the spray command again with a longer duration:
```bash
curl -X POST http://192.168.4.1/spray -d "duration_ms=2000"
```
- Confirm water flows through the nozzle for ~2 seconds.

**6. Test the camera feed** (if applicable)
```bash
curl http://192.168.4.1/capture
```
- Should return a JPEG image from the ESP32-CAM.

### Troubleshooting Bench Test

| Symptom | Likely Cause | Fix |
|---|---|---|
| No WiFi AP appears | ESP32-CAM not booting / still in flash mode | Remove IO0↔GND jumper; power cycle |
| WiFi AP appears but no HTTP response | Firmware issue | Re-flash; check serial monitor for errors |
| Relay doesn't click | VCC is 3.3V instead of 5V | Wire relay VCC to 5V source |
| Relay clicks but pump doesn't run | Wiring on NO/COM terminals wrong | Check relay terminal wiring; verify 12V on COM |
| Pump runs but no water flow | Pump not primed / tubing kinked | Submerge inlet; check for kinks or air locks |
| Intermittent relay behavior | Insufficient current on GPIO 13 | Most relay modules have a transistor driver — if yours doesn't, add one |

---

## Next Steps

Once bench testing passes:
1. **Pixhawk setup**: Connect to Mission Planner, calibrate accelerometer, compass, and radio.
2. **ESC calibration**: Follow ArduCopter ESC calibration procedure.
3. **Motor test**: In Mission Planner, test each motor individually (props OFF) to verify spin direction and order.
4. **First flight**: Outdoors, open area, no people nearby. Start with a simple hover in Stabilize mode.
5. **Spray integration**: After stable hover is achieved, test spray commands during flight.

For ESP32-CAM firmware details, see [ESP32_PROGRAMMING.md](ESP32_PROGRAMMING.md).
