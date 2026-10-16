# Third-party notices

MeshTracker itself is released under the [MIT license](LICENSE). It uses the following third-party
software. Only **Leaflet** is bundled in this repository (`app/static/vendor/leaflet/`, license text
included there); everything else is installed from PyPI when the Docker image is built
(`requirements.txt` and its dependencies, versions as of the last release check).

| Component | License | Use |
|---|---|---|
| [Leaflet](https://leafletjs.com) 1.9.4 | BSD-2-Clause | Map in the browser (bundled) |
| [meshcore](https://github.com/meshcore-dev/meshcore_py) | MIT | MeshCore companion protocol client |
| [FastAPI](https://fastapi.tiangolo.com) | MIT | Web backend |
| [Uvicorn](https://www.uvicorn.org) | BSD-3-Clause | Web server |
| Starlette | BSD-3-Clause | (FastAPI) |
| Pydantic, pydantic-core, annotated-types, annotated-doc, typing-inspection | MIT | (FastAPI) |
| anyio, h11, idna, click | MIT / BSD-3-Clause | (Uvicorn / Starlette) |
| typing-extensions | PSF-2.0 | (Pydantic) |
| pycayennelpp | MIT | Cayenne LPP decoding (meshcore) |
| pyserial, pyserial-asyncio-fast | BSD | USB/serial connection (meshcore) |
| bleak, dbus-fast | MIT | Bluetooth backend of meshcore (not used by MeshTracker) |
| pycryptodome | BSD-2-Clause AND Unlicense | Cryptography (meshcore) |
| opentelemetry-api | Apache-2.0 | (meshcore dependency) |

Not bundled, only interacted with over the network:

- **[MeshMonitor](https://github.com/Yeraze/meshmonitor)** (BSD-3-Clause) – MeshTracker can connect to its
  MeshCore Virtual Node. No MeshMonitor code is included.
- **[MeshCore](https://github.com/meshcore-dev/MeshCore)** firmware – protocol behaviour was studied from
  the public source; no firmware code is included.
- **OpenStreetMap** map tiles are loaded by the user's browser, © OpenStreetMap contributors
  ([ODbL](https://www.openstreetmap.org/copyright); [tile usage policy](https://operations.osmfoundation.org/policies/tiles/)).

MeshTracker is an independent project and not affiliated with MeshCore or MeshMonitor.
