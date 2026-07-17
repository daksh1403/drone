# 🛸 Autonomous Drone Painting System

> A VIT Chennai Multi-Disciplinary Project — an autonomous drone that detects unpainted areas on a wall and sprays them, no human piloting required.

This repository is the **project hub** for the autonomous wall-painting drone: it bundles the drone application, the main control implementation, and the full TRL (Technology Readiness Level) documentation.

> 🔧 For the flight-control stack, see the related [`auto-drone`](https://github.com/daksh1403/auto-drone) repo (Pixhawk + DroneKit + ESP32-CAM).

## Repository structure

| Path | Description |
|------|-------------|
| `auto-drone-app/` | Drone application (control surface / UI) |
| `auto-drone-main/` | Main implementation |
| `TRL_1_2_3_Documentation.md` | Technology Readiness Level 1–3 documentation |

## Tech stack

- **Flight controller** — Pixhawk V6X running ArduCopter
- **Control layer** — DroneKit-Python
- **Vision & actuation** — ESP32-CAM
- **Backend** — Flask + real-time web UI

## Related repositories

- **[auto-drone](https://github.com/daksh1403/auto-drone)** — Auto-Drone Wall Painter
- **[mdp](https://github.com/daksh1403/mdp)** — ESP32-CAM vision + ESP32-S3 spray control

## Documentation

Full project documentation (TRL 1–3, hardware, flight ops) lives in [`TRL_1_2_3_Documentation.md`](TRL_1_2_3_Documentation.md).

## License

[MIT](LICENSE) — © 2026 Daksh Agarwal
