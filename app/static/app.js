"use strict";

const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#db2777", "#4d7c0f"];
const SENSOR_LABELS = {
  voltage: ["Spannung", "V"], temperature: ["Temperatur", "°C"], humidity: ["Feuchte", "%"],
  barometer: ["Luftdruck", "hPa"], altitude: ["Höhe", "m"], percentage: ["Akku", "%"],
  illuminance: ["Licht", "lx"], current: ["Strom", "A"], power: ["Leistung", "W"],
};

const map = L.map("map").setView([47.37, 8.54], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap-Mitwirkende",
}).addTo(map);

const state = { trackers: [], selected: null, layers: new Map(), fitted: false, lastTrackKey: new Map() };
const $ = (id) => document.getElementById(id);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.error || (Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail) || msg;
    } catch (_) { /* kein JSON */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}
const send = (method, path, body) => api(path, {
  method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
});

function ago(ts, now) {
  if (!ts) return "–";
  const s = Math.max(0, now - ts);
  if (s < 90) return `vor ${s} s`;
  if (s < 5400) return `vor ${Math.round(s / 60)} Min`;
  if (s < 172800) return `vor ${Math.round(s / 3600)} Std`;
  return `vor ${Math.round(s / 86400)} Tagen`;
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString("de-CH");
const colorOf = (t) => COLORS[(t.id - 1) % COLORS.length];

function routeText(f) {
  if (!f || !f.route) return f && f.source === "advert" ? "Advert" : "";
  if (f.route === "flood") return "Flood";
  return f.hops == null ? "Pfad" : `Pfad (${f.hops} Hop${f.hops === 1 ? "" : "s"})`;
}

function sensorNode(s) {
  const base = s.type.split(".")[0];
  const [label, unit] = SENSOR_LABELS[base] || [s.type, ""];
  const val = Number.isInteger(s.value) ? s.value : Math.round(s.value * 100) / 100;
  return h("span", {}, `${label} `, h("b", {}, `${val}${unit ? " " + unit : ""}`));
}

function card(t, now) {
  const f = t.fix;
  const stale = f && now - f.ts > t.interval_min * 60 * 3;
  const lp = t.last_poll;
  const polling = t.polling;

  let pollInfo;
  if (polling) pollInfo = h("span", { class: "warn" }, "Abfrage läuft …");
  else if (lp && !lp.ok) pollInfo = h("span", { class: "bad" }, `Letzte Abfrage fehlgeschlagen ${ago(lp.ts, now)}`);
  else if (lp && !lp.has_gps) pollInfo = h("span", { class: "warn" }, `Antwort ohne GPS ${ago(lp.ts, now)}`);
  else if (lp) pollInfo = h("span", { class: "ok" }, `Letzte Abfrage ok ${ago(lp.ts, now)}`);
  else pollInfo = "Noch keine Abfrage";

  const next = !t.enabled ? "pausiert"
    : t.next_poll_ts ? (t.next_poll_ts <= now ? "gleich" : `in ${Math.max(1, Math.round((t.next_poll_ts - now) / 60))} Min`) : "";

  const routePill = t.route_now
    ? h("span", { class: `pill ${t.route_now}` },
        t.route_now === "flood" ? "Flood" : `Pfad${t.hops_now != null ? ` · ${t.hops_now} Hops` : ""}`)
    : h("span", { class: "pill bad" }, "nicht auf Node");

  const details = h("details", { class: "log" }, h("summary", {}, "Abfrage-Protokoll"), h("ul", { id: `log-${t.id}` }));
  details.addEventListener("toggle", () => details.open && loadLog(t.id));

  return h("div", { class: `card${state.selected === t.id ? " sel" : ""}`, style: `--c:${colorOf(t)}` },
    h("h3", { onclick: () => select(t.id, true) }, t.name,
      h("span", { class: "age", title: f ? fmtTime(f.ts) : "" }, f ? ago(f.ts, now) : "keine Position")),
    f && h("div", { class: "row" },
      `${f.lat.toFixed(5)}, ${f.lon.toFixed(5)}`, f.alt != null ? ` · ${Math.round(f.alt)} m` : "",
      stale ? h("span", { class: "warn" }, " · veraltet") : "",
      f.source ? ` · ${f.source === "advert" ? "Advert" : routeText(f)}` : ""),
    t.sensors.length > 0 && h("div", { class: "sensors row" }, t.sensors.map(sensorNode)),
    h("div", { class: "row" }, routePill, " ", pollInfo, " · nächste: ", next),
    lp && lp.error && h("div", { class: `row ${lp.ok ? "warn" : "bad"}` }, lp.error),
    h("div", { class: "actions" },
      h("button", { class: "primary", disabled: polling, onclick: () => act(t.id, "poll") }, "Jetzt abfragen"),
      h("button", { title: "Gespeicherten Pfad verwerfen – nächste Abfrage per Flood", onclick: () => act(t.id, "reset-path") }, "Pfad zurücksetzen"),
      h("button", { onclick: () => openDialog(t) }, "Bearbeiten"),
      h("a", { href: `/api/trackers/${t.id}/export.gpx?since=${sinceTs()}`, download: "" }, h("button", {}, "GPX")),
      h("button", { onclick: () => remove(t) }, "Löschen")),
    details);
}

const sinceTs = () => {
  const r = Number($("range").value);
  return r ? Math.floor(Date.now() / 1000) - r : 0;
};

async function loadLog(id) {
  const ul = $(`log-${id}`);
  if (!ul) return;
  const polls = await api(`/api/trackers/${id}/polls?limit=12`);
  ul.replaceChildren(...polls.map((p) => h("li", { class: p.ok ? (p.has_gps ? "" : "warn") : "bad" },
    `${fmtTime(p.ts)} · ${p.ok ? "ok" : "Fehler"} · ${(p.attempts || "").split(",").join(" → ") || "–"} · ${(p.duration_ms / 1000).toFixed(1)} s`,
    p.error ? ` · ${p.error}` : "")));
}

async function act(id, what) {
  try {
    await send("POST", `/api/trackers/${id}/${what}`);
    if (what === "reset-path") alert("Pfad zurückgesetzt – die nächste Abfrage geht per Flood.");
  } catch (e) {
    alert(`Fehlgeschlagen: ${e.message}`);
  }
  refresh();
}

async function remove(t) {
  if (!confirm(`Tracker „${t.name}“ samt gespeicherter Spur löschen?`)) return;
  await send("DELETE", `/api/trackers/${t.id}`);
  refresh();
}

// --- Karte -------------------------------------------------------------------

function select(id, zoom) {
  state.selected = id;
  const layer = state.layers.get(id);
  if (zoom && layer && layer.marker) map.setView(layer.marker.getLatLng(), Math.max(map.getZoom(), 15));
  render();
}

async function drawTrack(t) {
  const key = `${t.fix ? t.fix.ts : 0}|${$("range").value}|${t.id}`;
  if (state.lastTrackKey.get(t.id) === key && state.layers.has(t.id)) {
    updateMarker(t);
    return;
  }
  state.lastTrackKey.set(t.id, key);
  const fixes = await api(`/api/trackers/${t.id}/track?since=${sinceTs()}`);
  let layer = state.layers.get(t.id);
  if (layer) layer.group.remove();
  const color = colorOf(t);
  const group = L.layerGroup().addTo(map);
  layer = { group, marker: null };
  state.layers.set(t.id, layer);
  if (fixes.length > 1) {
    L.polyline(fixes.map((f) => [f.lat, f.lon]), { color, weight: 3, opacity: 0.7 }).addTo(group);
  }
  for (const f of fixes) {
    L.circleMarker([f.lat, f.lon], {
      radius: f.source === "advert" ? 3 : 4, color, weight: 1, fillColor: color,
      fillOpacity: f.source === "advert" ? 0.3 : 0.8,
    }).bindPopup(`${t.name}<br>${fmtTime(f.ts)}<br>${routeText(f) || f.source}`).addTo(group);
  }
  updateMarker(t);
}

function updateMarker(t) {
  const layer = state.layers.get(t.id);
  if (!layer || !t.fix) return;
  const color = colorOf(t);
  if (layer.marker) layer.marker.remove();
  layer.marker = L.circleMarker([t.fix.lat, t.fix.lon], {
    radius: 9, color: "#fff", weight: 3, fillColor: color, fillOpacity: 1,
  }).bindTooltip(t.name, { permanent: true, direction: "top", offset: [0, -8] }).addTo(layer.group);
}

function fitAll() {
  const pts = state.trackers.filter((t) => t.fix).map((t) => [t.fix.lat, t.fix.lon]);
  if (!pts.length) return;
  map.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 16 });
  state.fitted = true;
}

// --- Render / Refresh ----------------------------------------------------------

let status = { now: Math.floor(Date.now() / 1000) };

function render() {
  const now = status.now;
  $("trackers").replaceChildren(...state.trackers.map((t) => card(t, now)));
  $("empty-hint").hidden = state.trackers.length > 0;
}

async function refresh() {
  try {
    [status, state.trackers] = await Promise.all([api("/api/status"), api("/api/trackers")]);
  } catch (e) {
    $("link-badge").textContent = "Server nicht erreichbar";
    $("link-badge").className = "badge off";
    return;
  }
  const b = $("link-badge");
  b.className = `badge ${status.connected ? "on" : "off"}`;
  b.textContent = status.connected
    ? `Node verbunden${status.node_name ? ": " + status.node_name : ""}`
    : "Node nicht verbunden";
  b.title = status.connected ? `${status.transport} · ${status.target}` : (status.error || status.target);

  const open = new Set([...document.querySelectorAll("details.log[open]")].map((d) => d.querySelector("ul").id));
  render();
  for (const id of open) {
    const d = $(id)?.closest("details");
    if (d) { d.open = true; }
  }
  for (const t of state.trackers) await drawTrack(t);
  for (const id of [...state.layers.keys()]) {
    if (!state.trackers.some((t) => t.id === id)) {
      state.layers.get(id).group.remove();
      state.layers.delete(id);
      state.lastTrackKey.delete(id);
    }
  }
  if (!state.fitted) fitAll();
}

// --- Dialog ----------------------------------------------------------------------

let editing = null;

async function openDialog(t) {
  editing = t || null;
  $("dlg-title").textContent = t ? `Tracker bearbeiten` : "Tracker hinzufügen";
  $("pick-row").hidden = !!t;
  $("key-row").hidden = !!t;
  $("enabled-row").hidden = !t;
  $("f-key").required = !t;
  $("f-name").value = t ? t.name : "";
  $("f-key").value = t ? t.public_key : "";
  $("f-interval").value = t ? t.interval_min : 10;
  $("f-mode").value = t ? t.route_mode : "auto";
  $("f-enabled").checked = t ? t.enabled : true;
  $("form-error").hidden = true;
  if (!t) {
    const pick = $("f-pick");
    pick.replaceChildren(h("option", { value: "" }, "– manuell eingeben –"));
    try {
      for (const c of await api("/api/contacts")) {
        if (c.tracked) continue;
        pick.append(h("option", { value: c.public_key }, `${c.name} (${c.public_key.slice(0, 8)}…)`));
      }
    } catch (_) { /* Node evtl. offline */ }
  }
  $("dlg").showModal();
}

$("f-pick").addEventListener("change", (e) => {
  const key = e.target.value;
  if (!key) return;
  $("f-key").value = key;
  if (!$("f-name").value) $("f-name").value = e.target.selectedOptions[0].textContent.replace(/ \(.*$/, "");
});
$("cancel").addEventListener("click", () => $("dlg").close());
$("add-btn").addEventListener("click", () => openDialog(null));
$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = {
    name: $("f-name").value.trim(),
    interval_min: Number($("f-interval").value),
    route_mode: $("f-mode").value,
  };
  try {
    if (editing) {
      body.enabled = $("f-enabled").checked;
      await send("PATCH", `/api/trackers/${editing.id}`, body);
    } else {
      body.public_key = $("f-key").value.trim();
      await send("POST", "/api/trackers", body);
    }
    $("dlg").close();
    state.fitted = false;
    refresh();
  } catch (e) {
    $("form-error").textContent = e.message;
    $("form-error").hidden = false;
  }
});

$("range").addEventListener("change", () => { state.lastTrackKey.clear(); refresh(); });

refresh();
setInterval(refresh, 5000);
