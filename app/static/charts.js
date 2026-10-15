"use strict";

/* Verlaufsdiagramme: eine kleine Kurve pro Messwert (Small Multiples).
   Die Messwerte haben verschiedene Einheiten, darum gibt es bewusst keine
   gemeinsame oder zweite Achse. Farben kommen aus CSS (--c), Text bleibt in
   Textfarben. Reines SVG, keine Abhängigkeiten. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const H = 150;
  const M = { l: 48, r: 14, t: 10, b: 22 };

  const METRICS = {
    voltage: { label: "Akku-Spannung", unit: "V", dec: 2, order: 1 },
    percentage: { label: "Akku", unit: "%", dec: 0, order: 2 },
    temperature: { label: "Temperatur", unit: "°C", dec: 1, order: 3 },
    illuminance: { label: "Licht", unit: "lx", dec: 0, order: 4 },
    humidity: { label: "Luftfeuchte", unit: "%", dec: 0, order: 5 },
    barometer: { label: "Luftdruck", unit: "hPa", dec: 1, order: 6 },
    gps_altitude: { label: "Höhe (GPS)", unit: "m", dec: 0, order: 7 },
    altitude: { label: "Höhe", unit: "m", dec: 0, order: 8 },
    current: { label: "Strom", unit: "A", dec: 3, order: 9 },
    power: { label: "Leistung", unit: "W", dec: 2, order: 10 },
    concentration: { label: "Konzentration", unit: "ppm", dec: 0, order: 11 },
  };

  /** Anzeigename/Einheit zu einem Messwert-Typ ("temperature_2" → zweite Temperatur). */
  function info(type) {
    const m = /^(.+?)_(\d+)$/.exec(type);
    const base = m ? m[1] : type;
    const known = METRICS[base.split(".")[0]];
    const extra = m ? ` ${m[2]}` : "";
    if (!known) return { label: type, unit: "", dec: 2, order: 99 };
    const sub = base.includes(".") ? ` ${base.split(".")[1]}` : "";
    return { ...known, label: known.label + sub + extra };
  }

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const svg = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
  };

  const fmt = (v, dec) => v.toLocaleString("de-CH", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleString("de-CH", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });

  /** Runde Achsenwerte; flache Kurven bekommen etwas Luft. */
  function niceScale(min, max, n = 4) {
    if (!(max > min)) {
      const pad = Math.abs(min) * 0.05 || 1;
      min -= pad;
      max += pad;
    }
    const step0 = (max - min) / n;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const norm = step0 / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const digits = Math.max(0, -Math.floor(Math.log10(step)));
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(digits + 1)));
    return { lo, hi, ticks, digits };
  }

  function nearest(points, ts) {
    let a = 0, b = points.length - 1;
    while (b - a > 1) {
      const mid = (a + b) >> 1;
      if (points[mid][0] < ts) a = mid; else b = mid;
    }
    return Math.abs(points[a][0] - ts) <= Math.abs(points[b][0] - ts) ? a : b;
  }

  function titleOf(s, all) {
    const base = info(s.type).label;
    const same = all.filter((o) => o.type === s.type).length;
    return same > 1 ? `${base} (K${s.channel})` : base;
  }

  function drawCard(card, s, title, ctx) {
    const body = card.querySelector(".chart-body");
    const W = Math.max(240, body.clientWidth);
    const meta = info(s.type);
    const pts = s.points;
    const iw = W - M.l - M.r, ih = H - M.t - M.b;
    const x0 = ctx.x0, x1 = ctx.x1 > ctx.x0 ? ctx.x1 : ctx.x0 + 1;
    const vals = pts.map((p) => p[1]);
    const sc = niceScale(Math.min(...vals), Math.max(...vals));
    const x = (ts) => M.l + ((ts - x0) / (x1 - x0)) * iw;
    const y = (v) => M.t + (1 - (v - sc.lo) / (sc.hi - sc.lo)) * ih;

    const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, tabindex: 0, role: "img" });
    const last = pts[pts.length - 1];
    root.setAttribute("aria-label",
      `${title}: aktuell ${fmt(last[1], meta.dec)} ${meta.unit}, ${pts.length} Messwerte`);

    for (const t of sc.ticks) {
      root.append(svg("line", { class: "grid", x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }));
      const lab = svg("text", { class: "tick", x: M.l - 8, y: y(t), "text-anchor": "end", "dominant-baseline": "middle" });
      lab.textContent = fmt(t, Math.min(sc.digits, 3));
      root.append(lab);
    }
    const spanH = (x1 - x0) / 3600;
    for (let i = 0; i <= 3; i++) {
      const ts = x0 + ((x1 - x0) * i) / 3;
      const d = new Date(ts * 1000);
      const lab = svg("text", {
        class: "tick", x: x(ts), y: H - 5,
        "text-anchor": i === 0 ? "start" : i === 3 ? "end" : "middle",
      });
      lab.textContent = spanH <= 36
        ? d.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString("de-CH", { day: "2-digit", month: "2-digit" });
      root.append(lab);
    }

    // Linie in Abschnitte teilen, wo lange keine Messwerte kamen (kein Erfinden von Verläufen).
    const segs = [];
    let cur = [];
    for (const p of pts) {
      if (cur.length && p[0] - cur[cur.length - 1][0] > ctx.gapSec) { segs.push(cur); cur = []; }
      cur.push(p);
    }
    segs.push(cur);
    const base = M.t + ih;
    const pt = (p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`;
    const lines = segs.filter((g) => g.length > 1);
    if (lines.length) {
      root.append(svg("path", {
        class: "area",
        d: lines.map((g) => `M${x(g[0][0]).toFixed(1)},${base}L${g.map(pt).join("L")}L${x(g[g.length - 1][0]).toFixed(1)},${base}Z`).join(""),
      }));
      root.append(svg("path", { class: "line", d: lines.map((g) => `M${g.map(pt).join("L")}`).join("") }));
    }
    for (const g of segs.filter((g) => g.length === 1)) {
      root.append(svg("circle", { class: "dot small", cx: x(g[0][0]), cy: y(g[0][1]), r: 4 }));
    }
    root.append(svg("circle", { class: "dot", cx: x(last[0]), cy: y(last[1]), r: 4 }));

    // Hover/Fokus: Fadenkreuz rastet auf den nächsten Messwert ein.
    const cross = svg("line", { class: "cross", y1: M.t, y2: base, visibility: "hidden" });
    const hot = svg("circle", { class: "dot", r: 5, visibility: "hidden" });
    const hit = svg("rect", { x: M.l, y: M.t, width: iw, height: ih, fill: "transparent" });
    root.append(cross, hot, hit);
    const tip = el("div", "chart-tip");
    tip.hidden = true;

    let idx = pts.length - 1;
    const show = (i) => {
      idx = Math.max(0, Math.min(pts.length - 1, i));
      const p = pts[idx];
      cross.setAttribute("x1", x(p[0])); cross.setAttribute("x2", x(p[0]));
      hot.setAttribute("cx", x(p[0])); hot.setAttribute("cy", y(p[1]));
      cross.setAttribute("visibility", "visible"); hot.setAttribute("visibility", "visible");
      tip.replaceChildren(el("b", "", `${fmt(p[1], meta.dec)}${meta.unit ? " " + meta.unit : ""}`), el("span", "", fmtTime(p[0])));
      tip.hidden = false;
      const px = x(p[0]);
      const w = tip.offsetWidth || 120;
      tip.style.left = `${px + 12 + w > W ? px - 12 - w : px + 12}px`;
      tip.style.top = `${Math.max(0, y(p[1]) - 40)}px`;
    };
    const hide = () => {
      cross.setAttribute("visibility", "hidden"); hot.setAttribute("visibility", "hidden"); tip.hidden = true;
    };
    hit.addEventListener("pointermove", (e) => {
      const r = root.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * W;
      show(nearest(pts, x0 + ((px - M.l) / iw) * (x1 - x0)));
    });
    hit.addEventListener("pointerleave", hide);
    root.addEventListener("focus", () => show(pts.length - 1));
    root.addEventListener("blur", hide);
    root.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { show(idx - 1); e.preventDefault(); }
      if (e.key === "ArrowRight") { show(idx + 1); e.preventDefault(); }
    });

    body.replaceChildren(root, tip);
  }

  function sorted(series) {
    return [...series].sort((a, b) => info(a.type).order - info(b.type).order || a.key.localeCompare(b.key));
  }

  /** Kurven je Messwert in `container` zeichnen. ctx: {x0, x1, gapSec}. */
  function render(container, series, ctx) {
    container._data = { series, ctx };
    const all = sorted(series);
    container.replaceChildren();
    for (const s of all) {
      const meta = info(s.type);
      const last = s.points[s.points.length - 1];
      const card = el("div", "chart-card");
      const head = el("div", "chart-head");
      head.append(el("span", "chart-title", titleOf(s, all)),
        el("span", "chart-value", `${fmt(last[1], meta.dec)}${meta.unit ? " " + meta.unit : ""}`));
      card.append(head, el("div", "chart-body"));
      container.append(card);
    }
    const cards = container.querySelectorAll(".chart-card");
    all.forEach((s, i) => drawCard(cards[i], s, titleOf(s, all), ctx));
    if (!container._ro && "ResizeObserver" in window) {
      let width = container.clientWidth;
      container._ro = new ResizeObserver(() => {
        if (container.clientWidth !== width && container._data) {
          width = container.clientWidth;
          render(container, container._data.series, container._data.ctx);
        }
      });
      container._ro.observe(container);
    }
  }

  /** Dieselben Werte als Tabelle (jüngste zuerst) – ohne Maus erreichbar. */
  function renderTable(container, series, limit = 200) {
    const all = sorted(series);
    const rows = new Map();
    all.forEach((s, col) => {
      for (const [ts, v] of s.points) {
        if (!rows.has(ts)) rows.set(ts, []);
        rows.get(ts)[col] = v;
      }
    });
    const times = [...rows.keys()].sort((a, b) => b - a).slice(0, limit);
    const table = el("table", "data-table");
    const head = el("tr");
    head.append(el("th", "", "Zeit"));
    all.forEach((s) => {
      const m = info(s.type);
      head.append(el("th", "", `${titleOf(s, all)}${m.unit ? " (" + m.unit + ")" : ""}`));
    });
    const thead = el("thead");
    thead.append(head);
    table.append(thead);
    const tb = el("tbody");
    for (const ts of times) {
      const tr = el("tr");
      tr.append(el("td", "", fmtTime(ts)));
      all.forEach((s, col) => {
        const v = rows.get(ts)[col];
        tr.append(el("td", "num", v == null ? "–" : fmt(v, info(s.type).dec)));
      });
      tb.append(tr);
    }
    table.append(tb);
    container.replaceChildren(table);
  }

  window.MeshCharts = { render, renderTable, info };
})();
