# Changelog

## 0.1.0

First public release.

- Map track from MeshCore GPS telemetry (and adverts), GPX export
- Polling per tracker with automatic path → flood fallback, or always-flood mode
- Connection through MeshMonitor's Virtual Node (current and older telemetry commands), WiFi/TCP or USB
- History charts for all sensor values (battery, temperature, light, altitude, …) and a table view
- Poll log with failure reasons, optional password protection, configurable map tiles
- Docker Compose setup with `.env`, simulator mode, automated tests incl. an emulated companion
