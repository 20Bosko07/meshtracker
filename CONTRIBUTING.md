# Contributing

Thanks for helping! Bug reports, hardware feedback (especially direct WiFi/USB companions and other
trackers) and pull requests are welcome.

## Reporting a problem

Please include:

- how you connect (MeshMonitor Virtual Node / WiFi / USB) and the MeshMonitor / firmware versions,
- the **poll log** entry of the failed request (expand it on the tracker card),
- `docker compose logs --tail 100` (lines with `meshtracker.link` / `meshtracker.service`).

Remove your tracker's public key and coordinates if you share logs publicly.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
MT_TRANSPORT=sim MT_DB_PATH=./dev.db uvicorn app.main:app_factory --factory --reload
```

- `tests/fake_companion.py` is a tiny emulated MeshCore companion (TCP framing, contacts, telemetry,
  path reset). Extend it when you add protocol behaviour, so it is covered without hardware.
- `app/sim.py` is the simulator behind `MT_TRANSPORT=sim`.
- The frontend is plain JavaScript (no build step) in `app/static/`; Leaflet is bundled.

## Pull requests

By contributing you agree that your contribution is licensed under the project's [MIT license](LICENSE).

- Keep changes focused and add or update a test where behaviour changes.
- `pytest` must pass (CI runs it plus a Docker build).
- The interface is German. Translations / an i18n layer are a very welcome contribution.
