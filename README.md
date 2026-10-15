# MeshTracker

Web-App (Docker), die einen **MeshCore**-GPS-Tracker auf einer Karte verfolgt.
Sie verbindet sich als Companion-Client mit deinem MeshCore-Node – entweder über den
**Virtual Node von MeshMonitor** oder direkt (WiFi/USB) – und fragt die Telemetrie des
Trackers regelmäßig ab. Die **GPS-Position aus der Telemetrie (Cayenne LPP)** landet als Spur
auf der Karte, dazu Akku, Temperatur & Co.

- Abfrage-Intervall pro Tracker einstellbar (Standard 10 Min), „Jetzt abfragen“ per Knopf
- **Pfad → Flood automatisch:** Antwortet der gespeicherte Pfad nicht, wird er sofort verworfen
  und per Flood wiederholt (bis zu 2×). Optional „Immer Flood“ für bewegte Tracker
- Zusätzlich werden Positionen aus Adverts übernommen
- Spur-Zeitraum wählbar, GPX-Export, Abfrage-Protokoll (welcher Weg, wie lange, warum Fehler)
- SQLite im Volume `/data`, optionaler Passwortschutz

## Schnellstart

```bash
git clone <dieses-repo> && cd meshtracker
# docker-compose.yml: MT_HOST / MT_PORT eintragen
docker compose up -d --build
# → http://<server>:8282
```

Ohne Funkhardware ausprobieren: `MT_TRANSPORT=sim docker compose up --build` – ein simulierter
Tracker, dessen Pfad regelmäßig „stirbt“, damit man den Flood-Fallback sieht.

## Anbindung an MeshMonitor

Ein MeshCore-Companion lässt nur **einen** Client zu – und den belegt MeshMonitor. MeshMonitor
bietet dafür den **MeshCore Virtual Node** an (ein TCP-Server, über den weitere Companion-Clients
mitreden). MeshTracker verbindet sich dort wie eine normale Companion-App:

1. In MeshMonitor beim MeshCore-Source den Virtual Node aktivieren und den Port notieren.
2. `MT_TRANSPORT=tcp`, `MT_HOST=<MeshMonitor-Host>`, `MT_PORT=<Virtual-Node-Port>`.
3. In MeshMonitor **„Admin-Befehle erlauben“** (`allowAdminCommands`) für den Virtual Node
   einschalten. Ohne das lässt MeshMonitor den Befehl *Pfad zurücksetzen* nicht zum Node durch –
   Telemetrie-Anfragen gehen trotzdem, aber der Wechsel auf Flood klappt dann nicht
   (MeshTracker meldet das im Abfrage-Protokoll: „Pfad-Reset fehlgeschlagen“).
4. Den Tracker über „+ Tracker hinzufügen“ aus den Kontakten des Nodes wählen.

Tipp: Schalte in MeshMonitor die eigene periodische Telemetrie-Abfrage für den Tracker ab,
sonst belegt ihr die Funkzeit doppelt.

Ohne MeshMonitor geht es genauso direkt: WiFi-Companion-Firmware (Port 5000) oder
`MT_TRANSPORT=serial` mit `MT_SERIAL_PORT=/dev/ttyACM0` (Gerät in der Compose-Datei durchreichen).
BLE wird nicht unterstützt.

## Voraussetzungen am Tracker

Telemetrie-Anfragen beantwortet der Tracker nur, wenn er das erlaubt:

- Telemetrie-Modus **Location** (und für Sensorwerte **Environment/Base**) am Tracker auf
  „erlaubt“ bzw. „immer“ stellen; bei „erlaubt“ muss der Node, der anfragt, beim Tracker als
  Kontakt mit Telemetrie-Berechtigung geführt sein.
- Der Tracker braucht einen GPS-Fix. Ohne Fix antwortet er u. U. ohne Position – MeshTracker
  zeigt dann „Antwort ohne GPS“ statt einen falschen Punkt zu setzen.
- Der Tracker muss auf dem Node als Kontakt bekannt sein (Advert empfangen).

## Einstellungen (Umgebungsvariablen)

| Variable | Standard | Bedeutung |
|---|---|---|
| `MT_TRANSPORT` | `tcp` | `tcp`, `serial` oder `sim` |
| `MT_HOST` / `MT_PORT` | `127.0.0.1` / `5000` | Ziel bei `tcp` |
| `MT_SERIAL_PORT` / `MT_SERIAL_BAUD` | `/dev/ttyACM0` / `115200` | bei `serial` |
| `MT_AUTH_USER` / `MT_AUTH_PASSWORD` | – | HTTP-Basic-Schutz (beide setzen) |
| `MT_FLOOD_RETRIES` | `2` | Flood-Wiederholungen nach totem Pfad |
| `MT_PATH_TIMEOUT` / `MT_FLOOD_TIMEOUT` | `10` / `25` | Mindest-Wartezeit je Versuch (s); die Firmware schlägt je nach Hops ggf. mehr vor |
| `MT_MIN_SPACING` | `10` | Mindestabstand zwischen zwei Funk-Anfragen (s) |
| `MT_FAIL_RETRY` | `180` | Nach Fehlschlag früher erneut versuchen (s) |

Ein Intervall unter 5 Minuten belastet das Mesh (Duty-Cycle) – nur zum Testen empfehlenswert.

## Entwicklung

```bash
pip install -r requirements-dev.txt
pytest                      # Logik, API und Ende-zu-Ende gegen einen Fake-Companion
MT_TRANSPORT=sim MT_DB_PATH=./dev.db uvicorn app.main:app_factory --factory --reload
```

## Stand der Verifikation

- Getestet: Abfragelogik inkl. Pfad→Flood, API, Oberfläche (Browser) und die echte
  `meshcore`-Bibliothek gegen einen Fake-Companion (TCP-Framing, Kontakte, Telemetrie, Pfad-Reset).
- **Nicht getestet:** echte Hardware, eine laufende MeshMonitor-Instanz und der `docker build`
  selbst (in der Entwicklungsumgebung gab es keinen Docker-Daemon; der Startbefehl wurde in einem
  frischen venv nur mit `requirements.txt` nachgestellt). Das Verhalten des
  Virtual Node (insbesondere `allowAdminCommands` für Pfad-Reset) stammt aus dem MeshMonitor-Quelltext,
  nicht aus einem Live-Test. Bitte beim ersten Einsatz das Abfrage-Protokoll im UI beobachten.
