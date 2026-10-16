"use strict";

/* History charts: one small chart per measurement (small multiples).
   The measurements have different units, so there is deliberately no shared or
   second axis. Colors come from CSS (--c), text stays in text colors.
   Plain SVG, no dependencies. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const H = 150;
  const M = { l: 48, r: 14, t: 10, b: 22 };

  const METRICS = {
    voltage: { label: "Battery voltage", unit: "V", dec: 2, order: 1, nonNegative: true },
    percentage: { label: "Battery", unit: "%", dec: 0, order: 2, nonNegative: true },
    temperature: { label: "Temperature", unit: "°C", dec: 1, order: 3 },
    illuminance: { label: "Light", unit: "lx", dec: 0, order: 4, nonNegative: true },
    humidity: { label: "Humidity", unit: "%", dec: 0, order: 5, nonNegative: true },
    barometer: { label: "Pressure", unit: "hPa", dec: 1, order: 6, nonNegative: true },
    gps_altitude: { label: "Altitude (GPS)", unit: "m", dec: 0, order: 7 },
    altitude: { label: "Altitude", unit: "m", dec: 0, order: 8 },
    current: { label: "Current", unit: "A", dec: 3, order: 9 },
    power: { label: "Power", unit: "W", dec: 2, order: 10 },
    concentration: { label: "Concentration", unit: "ppm", dec: 0, order: 11 },
  };

  /** Display name/unit for a measurement type ("temperature_2" → second temperature). */
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

  const fmt = (v, dec) => v.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleString(undefined, {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });

  /** Round axis values. Flat series get some padding, quantities like light or
   *  voltage never go below 0, integer measurements get whole-number ticks. */
  function niceScale(min, max, { n = 3, integer = false, nonNegative = false } = {}) {
    if (!(max > min)) {
      let pad = Math.abs(min) * 0.05;
      if (integer) pad = Math.max(pad, 1);
      if (!pad) pad = 1;
      min -= pad;
      max += pad;
    }
    if (nonNegative && min < 0) min = 0;
    const step0 = (max - min) / n;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const norm = step0 / mag;
    let step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    if (integer) step = Math.max(1, step);
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
    const iw = W - M.l - M.r;
    const x0 = ctx.x0, x1 = ctx.x1 > ctx.x0 ? ctx.x1 : ctx.x0 + 1;
    const spanH = (x1 - x0) / 3600;
    // 20–48 h: two-line labels (time, then date below); otherwise one line.
    const twoLine = spanH > 20 && spanH <= 48;
    const ih = H - M.t - (twoLine ? 36 : M.b);
    const vals = pts.map((p) => p[1]);
    const sc = niceScale(Math.min(...vals), Math.max(...vals), {
      integer: meta.dec === 0, nonNegative: !!meta.nonNegative,
    });
    const x = (ts) => M.l + ((ts - x0) / (x1 - x0)) * iw;
    const y = (v) => M.t + (1 - (v - sc.lo) / (sc.hi - sc.lo)) * ih;

    const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, tabindex: 0, role: "img" });
    const last = pts[pts.length - 1];
    root.setAttribute("aria-label",
      `${title}: currently ${fmt(last[1], meta.dec)} ${meta.unit}, ${pts.length} readings`);

    for (const t of sc.ticks) {
      root.append(svg("line", { class: "grid", x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }));
      const lab = svg("text", { class: "tick", x: M.l - 8, y: y(t), "text-anchor": "end", "dominant-baseline": "middle" });
      lab.textContent = fmt(t, Math.min(sc.digits, 3));
      root.append(lab);
    }
    // Number of x labels from the room we have (labels must not overlap, whatever the locale).
    const labelW = spanH > 48 ? 46 : 66;
    const nTicks = Math.max(2, Math.min(5, Math.floor(iw / (1.5 * labelW)) + 1));
    for (let i = 0; i < nTicks; i++) {
      const ts = x0 + ((x1 - x0) * i) / (nTicks - 1);
      const d = new Date(ts * 1000);
      const anchor = i === 0 ? "start" : i === nTicks - 1 ? "end" : "middle";
      const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
      const date = d.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit" });
      const lab = svg("text", { class: "tick", x: x(ts), y: twoLine ? H - 17 : H - 5, "text-anchor": anchor });
      if (twoLine) {
        lab.append(svg("tspan", { x: x(ts) }), svg("tspan", { x: x(ts), dy: 12 }));
        lab.firstChild.textContent = time;
        lab.lastChild.textContent = date;
      } else {
        lab.textContent = spanH <= 20 ? time : date;
      }
      root.append(lab);
    }

    // Split the line where no readings arrived for a long time (do not invent a course).
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

    // Hover/focus: the crosshair snaps to the nearest reading.
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
      const left = px + 12 + w > W ? px - 12 - w : px + 12;
      tip.style.left = `${Math.max(0, left)}px`;
      tip.style.top = `${Math.max(0, Math.min(y(p[1]) - 40, H - 44))}px`;
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

  /** Draw one chart per measurement into `container`. ctx: {x0, x1, gapSec}. */
  function render(container, series, ctx) {
    container._data = { series, ctx };
    const scroller = container.closest(".charts");
    const scrollTop = scroller ? scroller.scrollTop : 0;
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
    if (scroller) scroller.scrollTop = scrollTop;
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

  /** The same values as a table (newest first) – reachable without a mouse. */
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
    head.append(el("th", "", "Time"));
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
