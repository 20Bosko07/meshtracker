# MeshTracker

**Selbst gehostete Karte für [MeshCore](https://meshcore.co.uk)-GPS-Tracker.** MeshTracker verbindet sich
als Companion-Client mit deinem MeshCore-Node, fragt die Telemetrie deines Trackers in einem festen
Intervall ab und zeichnet die GPS-Position als Spur auf einer Karte – dazu Akku, Temperatur, Licht, Höhe
und jeden weiteren Sensorwert, den der Tracker meldet. Läuft in Docker und funktioniert entweder
**über [MeshMonitor](https://github.com/Yeraze/meshmonitor)** (dessen MeshCore Virtual Node) oder
**direkt** an einem WiFi-/USB-Companion-Node.

🇬🇧 [English version](README.md)

![Verlaufsdiagramme](docs/screenshot-charts.png)
<sub>Demodaten aus dem eingebauten Simulator.</sub>

## Wozu

Position und Sensorwerte eines MeshCore-Trackers kommen als *Telemetrie* (Cayenne LPP), wenn man sie über
das Mesh anfragt. Werkzeuge wie MeshMonitor speichern diese Werte, zeichnen die GPS-Position aus einer
Telemetrie-Antwort aber nicht auf die Karte. MeshTracker fragt den Tracker selbst ab und tut genau das.

## Funktionen

- **Spur auf der Karte** aus GPS-Telemetrie (und aus Adverts); GPX-Export
- **Abfrage-Intervall pro Tracker** (Standard 10 Min) und Knopf *Jetzt abfragen*
- **Pfad → Flood automatisch:** Antwortet der gespeicherte Pfad nicht, wird er zurückgesetzt und sofort
  per Flood wiederholt. Optional *Immer Flood* für bewegte Tracker
- **Verlaufsdiagramme** für jeden Wert, den der Tracker sendet (Akku-Spannung, Temperatur, Licht,
  Luftdruck, GPS-Höhe, …): eine kleine Kurve pro Wert, Werte per Maus/Tastatur, Tabellenansicht, Lücken
  bleiben Lücken
- **Abfrage-Protokoll**: welcher Weg, wie lange, und *warum* eine Anfrage scheiterte
- Hell/Dunkel, handytauglich, optionaler Passwortschutz, SQLite in einem Docker-Volume

## Voraussetzungen

- Ein Linux-Rechner (oder ähnlich) mit **Docker + Docker Compose**
- Ein erreichbarer **MeshCore-Companion-Node** – über MeshMonitor, WiFi (TCP) oder USB
- Ein MeshCore-**Tracker mit GPS** (entwickelt mit einem T1000-E), der Telemetrie-Anfragen erlaubt
  (siehe [Voraussetzungen am Tracker](#voraussetzungen-am-tracker))

## Schnellstart

```bash
git clone https://github.com/20Bosko07/meshtracker.git
cd meshtracker
cp .env.example .env
nano .env                     # MT_HOST und MT_PORT eintragen (siehe „Anbindung“)
docker compose up -d --build
```

Öffne **http://\<server\>:8282**. Das Feld oben links wird grün („Node verbunden“), sobald die Verbindung
steht. Dann **+ Tracker hinzufügen** klicken, den Tracker aus den Kontakten des Nodes wählen (oder seinen
64-stelligen Public Key einfügen), Intervall wählen, fertig.

Ohne Funkhardware: `MT_TRANSPORT=sim docker compose up --build` startet einen simulierten Tracker, dessen
Pfad ab und zu „stirbt“, damit man den Flood-Wechsel sieht.

## Anbindung

Ein MeshCore-Companion-Node lässt **nur einen Client gleichzeitig** zu. Such dir das passende Szenario aus:

### A) Über MeshMonitor (empfohlen, wenn du es schon betreibst)

MeshMonitor hält die Verbindung zu deinem Node und bietet einen **MeshCore Virtual Node** an: einen
TCP-Server, über den weitere Companion-Clients denselben Node mitbenutzen können. MeshTracker verbindet
sich dort wie eine normale Companion-App.

1. In MeshMonitor den **Virtual Node** für deine MeshCore-Source aktivieren und den **Port** notieren.
2. Läuft MeshMonitor in Docker, diesen **Port in MeshMonitors eigener `docker-compose.yml` freigeben**
   (`ports:` → `"7555:7555"`, mit deinem Port) und dort `docker compose up -d` ausführen.
3. In MeshMonitor **Admin-Befehle** am Virtual Node erlauben (`allowAdminCommands` im Code). Ohne das
   reicht MeshMonitor den Befehl *Pfad zurücksetzen* nicht durch; Telemetrie geht trotzdem, aber der
   Wechsel Pfad→Flood kann den Pfad nicht zurücksetzen (das Abfrage-Protokoll meldet dann
   „Pfad-Reset fehlgeschlagen“).
4. In `.env`: `MT_TRANSPORT=tcp`, `MT_HOST=<IP des MeshMonitor-Rechners>` (nicht `localhost` – die
   Verbindung wird aus dem Container heraus aufgebaut), `MT_PORT=<Port des Virtual Node>`.
5. In MeshMonitor die **eigene periodische Telemetrie-Abfrage für den Tracker ausschalten** – zwei
   Abfragende konkurrieren sonst um denselben Node und dieselbe Funkzeit.

Hinweise:
- Der **Web-Port** von MeshMonitor (z. B. 8080) ist *nicht* der Port des Virtual Node.
- Der Virtual Node hat **keine Anmeldung**. Wer den Port freigibt, macht ihn für das ganze LAN
  erreichbar. Willst du das nicht, lege MeshTracker und MeshMonitor in dasselbe Docker-Netzwerk und
  nimm den Containernamen als `MT_HOST` (vom Autor nicht getestet, normale Docker-Netzwerktechnik).
- MeshTracker versucht zuerst MeshCores aktuelle Binär-Telemetrie-Anfrage und fällt bei MeshMonitor-
  Versionen, die sie nicht kennen, automatisch auf den älteren Befehl zurück.

### B) Direkt per WiFi (TCP)

Die **WiFi-Companion**-Firmware auf den Node flashen und `MT_TRANSPORT=tcp`, `MT_HOST=<IP des Nodes>`,
`MT_PORT=5000` setzen. Währenddessen darf nichts anderes mit dem Node verbunden sein (MeshMonitor,
Handy-App, …). Bei direkter Verbindung kannst du die Wartezeiten senken: `MT_PATH_TIMEOUT=10`,
`MT_FLOOD_TIMEOUT=25`.

### C) Direkt per USB (seriell)

```bash
# .env:  MT_TRANSPORT=serial   MT_SERIAL_PORT=/dev/ttyACM0
docker compose -f docker-compose.yml -f docker-compose.serial.yml up -d --build
```

Die Zusatzdatei reicht das Gerät in den Container durch und fügt die Gruppe `dialout` hinzu. BLE wird
nicht unterstützt.

> Direkte WiFi-/USB-Verbindungen sind durch automatische Tests gegen einen nachgebauten Companion
> abgedeckt, vom Autor aber nicht an echter Hardware geprüft. Rückmeldungen sind willkommen.

## Voraussetzungen am Tracker

Ein MeshCore-Node beantwortet Telemetrie-Anfragen nur, wenn sein Besitzer es erlaubt:

- In den Einstellungen des Trackers Telemetrie für **Base** (Akku), **Location** (Standort) und
  **Environment** (Sensoren) erlauben. Die Modi sind *alle erlauben* oder *per Kontakt-Flags*; bei
  Letzterem muss der anfragende Node ein Kontakt mit den passenden Telemetrie-Rechten sein.
- Der Tracker braucht einen **GPS-Fix**. Ohne Fix antwortet er ohne Position – MeshTracker zeigt dann
  „Antwort ohne GPS“, statt einen falschen Punkt zu setzen.
- Der Tracker muss auf deinem Node als **Kontakt** bekannt sein (der Node muss seinen Advert gehört haben).

Welche Sensoren auftauchen, entscheidet der Tracker, nicht MeshTracker: Jeder Wert aus der Antwort wird
automatisch gespeichert und als Diagramm angezeigt.

## Bedienung

- **Routing** (pro Tracker, *Bearbeiten*):
  - *Auto* – zuerst der auf dem Node gespeicherte Pfad. Kommt keine Antwort rechtzeitig, wird der Pfad
    zurückgesetzt und die Anfrage per Flood wiederholt (bis zu `MT_FLOOD_RETRIES`-mal).
  - *Immer Flood* – vor jeder Abfrage den Pfad zurücksetzen. Am zuverlässigsten für einen bewegten
    Tracker, kostet etwas mehr Funkzeit.
- **Intervall:** Jede Abfrage sendet 1–3 Funk-Anfragen. Intervalle unter 5 Minuten belasten das Mesh
  (Duty-Cycle) und sind nur zum Testen gedacht.
- **Abfrage-Protokoll** (an der Tracker-Karte aufklappen): Zeit, Weg, Dauer und Grund jedes Versuchs.
- **Zeitraum** (oben rechts) gilt für Karten-Spur und Diagramme; die Tabellenansicht zeigt dieselben Werte.
  Der GPX-Export nutzt denselben Zeitraum.

## Einstellungen

In `.env` setzen (siehe [`.env.example`](.env.example)):

| Variable | Standard | Bedeutung |
|---|---|---|
| `MT_WEB_PORT` | `8282` | Port der Weboberfläche auf dem Server |
| `MT_TRANSPORT` | `tcp` | `tcp`, `serial` oder `sim` |
| `MT_HOST` / `MT_PORT` | – / `5000` | Ziel bei `tcp` (IP, nicht `localhost`) |
| `MT_SERIAL_PORT` / `MT_SERIAL_BAUD` | `/dev/ttyACM0` / `115200` | bei `serial` |
| `MT_AUTH_USER` / `MT_AUTH_PASSWORD` | – | HTTP-Basic-Schutz (beide setzen) |
| `MT_TILE_URL` / `MT_TILE_ATTRIBUTION` / `MT_TILE_MAX_ZOOM` | OpenStreetMap / `19` | Kartenkacheln, z. B. eigener Kachelserver |
| `MT_FLOOD_RETRIES` | `2` | Flood-Wiederholungen, wenn eine Anfrage unbeantwortet blieb |
| `MT_PATH_TIMEOUT` / `MT_FLOOD_TIMEOUT` | `48` / `48` | Mindest-Wartezeit je Versuch (s). 48 braucht man hinter MeshMonitors Virtual Node (der wartet intern bis 45 s); bei direkter Verbindung reichen 10 / 25 |
| `MT_FLOOD_BACKOFF` | `5` | Pause zwischen Flood-Wiederholungen (s) |
| `MT_MIN_SPACING` | `10` | Mindestabstand zwischen zwei Funk-Anfragen (s) |
| `MT_FAIL_RETRY` | `180` | Nach einer fehlgeschlagenen Runde früher erneut versuchen (s) |
| `MT_LOG_LEVEL` | `INFO` | Log-Stufe |

## Fehlersuche

| Was du siehst | Bedeutung / Lösung |
|---|---|
| Feld **Node nicht verbunden**, Log `Connect call failed … Connection refused` | Auf `MT_HOST:MT_PORT` lauscht nichts. IP/Port prüfen; bei MeshMonitor in Docker muss der Virtual-Node-Port freigegeben sein. Test auf dem Server: `nc -zv <host> <port>` |
| `Keine Antwort vom MeshCore-Node (falscher Host/Port?)` | Der Port ist offen, aber kein MeshCore-Companion-Port (z. B. MeshMonitors Web-Port) |
| `Anfrage abgelehnt (ERR_CODE_BAD_STATE)` | MeshMonitor verweigert das Senden, z. B. weil die Source im *Receive-Only*-Modus ist |
| `Anfrage abgelehnt (ERR_CODE_UNSUPPORTED_CMD)` | Node/Virtual Node kennt den Befehl nicht. MeshTracker wechselt selbst auf den älteren Befehl; bleibt es, MeshMonitor aktualisieren |
| `Keine Antwort nach 3 Versuchen (…)` | Die Anfrage ging raus, der Tracker antwortete nicht: außer Reichweite, Telemetrie nicht erlaubt oder zwei Abfragende kollidieren (MeshMonitors eigene Abfrage für diesen Tracker ausschalten) |
| `Antwort ohne GPS-Position` | Der Tracker antwortete, hat aber keinen GPS-Fix oder Standort-Telemetrie ist nicht erlaubt |
| `Tracker nicht in der Kontaktliste des Nodes` | Der Node hat den Advert des Trackers noch nicht gehört – abwarten oder den Kontakt am Node hinzufügen |
| `Pfad-Reset fehlgeschlagen` | MeshMonitors Virtual Node erlaubt keine Admin-Befehle (siehe *Anbindung → A*, Schritt 3) |
| `port is already allocated` bei `docker compose up` | Port 8282 ist belegt – in `.env` einen anderen `MT_WEB_PORT` setzen |
| Karte grau | Der Browser erreicht den Kachelserver nicht (Internetzugang oder `MT_TILE_URL`) |

`docker compose logs --tail 50` zeigt Verbindungsprobleme mit dem Präfix `meshtracker.link`.

## Sicherheit

- Die Oberfläche zeigt, **wo dein Tracker ist**. Nicht ungeschützt ins Internet stellen: `MT_AUTH_USER` /
  `MT_AUTH_PASSWORD` setzen und HTTPS davorschalten (Reverse Proxy wie Caddy oder nginx). HTTP Basic über
  unverschlüsseltes HTTP überträgt das Passwort im Klartext.
- Ein MeshMonitor Virtual Node hat keine Anmeldung (siehe oben) – im vertrauenswürdigen Netz halten.
- Die Kartenkacheln lädt dein *Browser* vom Kachelanbieter (standardmäßig OpenStreetMap). Beachte deren
  [Nutzungsrichtlinie](https://operations.osmfoundation.org/policies/tiles/) oder nimm einen eigenen Anbieter.

## Update / Backup / Entfernen

```bash
git pull && docker compose up -d --build        # aktualisieren (deine .env bleibt unberührt)
docker run --rm -v meshtracker_meshtracker-data:/data -v "$PWD":/backup alpine \
  cp /data/meshtracker.db /backup/                # Datenbank sichern
docker compose down                              # stoppen (Daten bleiben im Volume)
docker compose down -v                           # stoppen und alle Daten löschen
```

## Funktionsweise

MeshTracker ist ein MeshCore-Companion-Client auf Basis der Python-Bibliothek
[`meshcore`](https://github.com/meshcore-dev/meshcore_py). Pro Tracker sendet es eine Telemetrie-Anfrage
über deinen Node, wartet auf die Antwort, dekodiert die Cayenne-LPP-Daten (GPS + Sensoren) und speichert
sie in SQLite. Ein kleines FastAPI-Backend liefert die Leaflet-Karte und die Diagramm-Oberfläche aus.
Adverts liefern zusätzliche Positionen, und die Kontaktliste des Nodes wird vor jeder Abfrage abgeglichen,
weil ein Virtual Node Pfadänderungen nicht meldet.

HTTP-API (von der Oberfläche genutzt): `GET /api/status`, `/api/config`, `/api/contacts`, `/api/trackers`,
`POST /api/trackers`, `PATCH|DELETE /api/trackers/{id}`, `POST /api/trackers/{id}/poll`,
`POST /api/trackers/{id}/reset-path`, `GET /api/trackers/{id}/track|series|polls|export.gpx`.

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                           # Logik, API und Ende-zu-Ende gegen einen Fake-Companion
MT_TRANSPORT=sim MT_DB_PATH=./dev.db uvicorn app.main:app_factory --factory --reload
```

Siehe [CONTRIBUTING.md](CONTRIBUTING.md). Übersetzungen der (deutschen) Oberfläche sind willkommen.

## Stand und Grenzen

- Genutzt mit MeshMonitors Virtual Node und einem T1000-E-Tracker. Direkte WiFi-/USB-Verbindungen:
  nur automatische Tests (siehe oben). Kein BLE.
- Oberfläche und Meldungen sind nur auf Deutsch.
- Ein Companion-Node pro MeshTracker-Instanz.

## Lizenz und Danksagung

[MIT](LICENSE). Drittanbieter: [Leaflet](https://leafletjs.com) (BSD-2-Clause, enthalten),
[meshcore_py](https://github.com/meshcore-dev/meshcore_py) (MIT), FastAPI (MIT), Uvicorn (BSD-3-Clause),
Kartendaten © [OpenStreetMap-Mitwirkende](https://www.openstreetmap.org/copyright).
MeshTracker ist ein unabhängiges Projekt und nicht mit MeshCore oder MeshMonitor verbunden.
