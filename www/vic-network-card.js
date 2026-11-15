/*
 * vic-network-card  v1.0.0
 * The official Victorian train network map with live trains moving over it and a status for every line
 * (Metro Trains and V/Line). Tap a line to highlight it and zoom in; drag to pan, scroll or pinch to zoom.
 *
 * Needs: the vline_trains and metro_network AppDaemon apps (sensor.vline_network, sensor.metro_network),
 * and these files in Home Assistant's www folder: vic_network_map.png, vic_network_anchors.json.
 *
 * type: custom:vic-network-card
 * title: Victorian train network                 # optional
 * map_image: /local/vic_network_map.png          # optional
 * anchors_url: /local/vic_network_anchors.json   # optional
 * sources:                                       # optional (these are the defaults)
 *   - { entity: sensor.vline_network, geometry_url: /local/vline_network.json, group: Regional }
 *   - { entity: sensor.metro_network, geometry_url: /local/vic_metro_network.json, group: Metro }
 */
const VIC_VERSION = "1.0.0";
console.info("%c vic-network-card %c v" + VIC_VERSION + " ", "background:#222;color:#fff", "background:#8b1f9a;color:#fff");

const SVG_NS = "http://www.w3.org/2000/svg";
const LEVEL_GLYPH = { ok: "\u2713", minor: "!", major: "\u2715", unknown: "?" };
const LEVEL_RANK = { unknown: -1, ok: 0, minor: 1, major: 2 };
// Line colours as drawn on the official map (matched on the line's name); anything else uses its timetable colour.
const MAP_COLOURS = [
  [/alamein|belgrave|lilydale|glen waverley/i, "#0c4a9b"],
  [/mernda|hurstbridge/i, "#c8102e"],
  [/craigieburn|upfield|flemington|showgrounds/i, "#f2b705"],
  [/cranbourne|pakenham|sunbury/i, "#00a0df"],
  [/frankston|stony point/i, "#0f9d3a"],
  [/werribee|williamstown|sandringham/i, "#f489b6"],
];
const REGIONAL_COLOUR = "#8b1f9a";

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const truthy = (v) => v === true || ["true", "1", "on", "yes"].includes(String(v).toLowerCase());
const num = (v, d = null) => { const n = Number(v); return v === null || v === undefined || v === "" || Number.isNaN(n) ? d : n; };
const svgEl = (name, attrs = {}) => {
  const e = document.createElementNS(SVG_NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
};
// "Flinders Street Railway Station", "Heidelberg (Heidelberg)" -> "flindersstreet", "heidelberg"
const nkey = (s) => String(s || "").toLowerCase().replace(/\(.*?\)/g, "").replace(/railway station|\bstation\b/g, "")
  .replace(/\bmt\b/g, "mount").replace(/\bsaint\b/g, "st").replace(/[^a-z0-9]/g, "");

const STYLE = `
:host { display: block; }
ha-card { display: block; overflow: hidden; container-type: inline-size; }
.head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 12px; padding: 14px 16px 6px; }
.sign { display: inline-block; clip-path: polygon(0 0, 100% 0, calc(100% - 14px) 100%, 0 100%); }
.sign .t { display: block; background: var(--primary-text-color); color: var(--card-background-color); padding: 10px 30px 9px 16px;
  font: 800 1.05rem/1 "Gill Sans", "Gill Sans MT", Futura, "Century Gothic", "Trebuchet MS", sans-serif; letter-spacing: .12em; text-transform: uppercase; white-space: nowrap; }
.sign .bars { display: flex; height: 6px; }
.sign .bars i { flex: 1; }
.sub { font-size: .78rem; color: var(--secondary-text-color); margin-top: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: .8rem; font-weight: 600; white-space: nowrap;
  color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); border: 1px solid color-mix(in srgb, var(--c) 45%, transparent); }
.ok { --c: var(--success-color, #2e8b57); }
.minor { --c: var(--warning-color, #c77700); }
.major { --c: var(--error-color, #d1342f); }
.unknown { --c: var(--secondary-text-color, #7a7f87); }
.mapwrap { position: relative; margin: 0 8px; border-radius: 10px; overflow: hidden; background: #fff; }
svg.map { width: 100%; height: auto; display: block; touch-action: none; cursor: grab; user-select: none; -webkit-user-select: none; }
svg.map.drag { cursor: grabbing; }
.reset { position: absolute; top: 8px; right: 8px; border: 1px solid #222; background: #fff; color: #222; border-radius: 999px;
  padding: 4px 10px; font-size: .78rem; cursor: pointer; display: none; }
.reset.on { display: block; }
.fade { fill: #fff; opacity: 0; transition: opacity .25s; pointer-events: none; }
.fade.on { opacity: .62; }
.hl path { fill: none; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.hl .halo { stroke: #fff; stroke-width: 11px; }
.hl .core { stroke-width: 7px; }
.hl circle { fill: #fff; stroke: #222; stroke-width: 2px; vector-effect: non-scaling-stroke; }
.u { transform: scale(var(--u, 1)); }
.tr { transition: transform 1s linear; cursor: pointer; }
.zooming .tr, .drag .tr { transition: none; }
.tr .body { stroke: #fff; stroke-width: 2px; vector-effect: non-scaling-stroke; fill: var(--c); }
.tr.dim { opacity: .3; }
.tr .ring { display: none; fill: none; stroke: #222; stroke-width: 1.5px; vector-effect: non-scaling-stroke; }
.tr.picked .ring { display: block; }
text.dly { font-size: 10px; font-weight: 700; fill: var(--c); paint-order: stroke; stroke: #fff; stroke-width: 3px; pointer-events: none; }
.note { margin: 0 16px 6px; padding: 8px 10px; border-radius: 8px; font-size: .82rem; color: var(--primary-text-color);
  background: color-mix(in srgb, var(--c) 12%, transparent); border: 1px solid color-mix(in srgb, var(--c) 40%, transparent); }
.grp { padding: 8px 16px 0; font-size: .72rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--secondary-text-color); }
.rows { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; padding: 6px 12px 4px; }
@container (min-width: 640px) { .rows { grid-template-columns: repeat(var(--cols, 7), minmax(0, 1fr)); } }
.row { display: block; width: 100%; box-sizing: border-box; text-align: left; background: none; color: inherit; font: inherit; min-width: 0;
  padding: 7px 9px 8px; border-radius: 9px; cursor: pointer; border: 1px solid var(--divider-color); border-top: 4px solid var(--lc); }
.row.sel { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); border-color: var(--lc); }
.row:focus-visible { outline: 2px solid var(--primary-color); }
.nm { display: block; font-weight: 600; font-size: .86rem; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pill { display: block; color: var(--c); font-size: .74rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }
.pill .g { display: inline-block; width: 1.1em; text-align: center; }
.more { grid-column: 1 / -1; padding: 6px 8px 4px; font-size: .84rem; color: var(--primary-text-color); }
.more a { color: var(--primary-color); }
.more ul { margin: 4px 0 0; padding-left: 16px; }
.more li { margin: 3px 0; color: var(--secondary-text-color); }
.more li b { color: var(--primary-text-color); font-weight: 600; }
.foot { display: flex; justify-content: space-between; gap: 8px; padding: 6px 16px 12px; font-size: .74rem; color: var(--secondary-text-color); }
.empty { padding: 24px 16px; color: var(--secondary-text-color); font-size: .9rem; }
`;

class VicNetworkCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._anchors = null;
    this._srcs = [];          // [{cfg, geo, geoVersion, loading, attrs}]
    this._lines = [];         // flattened, in display order
    this._sel = null;
    this._pick = null;
    this._markers = new Map();
    this._vb = null;
    this._anchor = performance.now();
    this._built = false;
    this._pxw = 800;
    this._err = null;
    this._rowSig = "";
  }

  setConfig(config) {
    const c = Object.assign({
      title: "Victorian train network",
      map_image: "/local/vic_network_map.png",
      anchors_url: "/local/vic_network_anchors.json",
      sources: [
        { entity: "sensor.vline_network", geometry_url: "/local/vline_network.json", group: "Regional" },
        { entity: "sensor.metro_network", geometry_url: "/local/vic_metro_network.json", group: "Metro" },
      ],
    }, config || {});
    this._config = c;
    this._srcs = c.sources.map((cfg) => ({ cfg, geo: null, geoVersion: null, loading: false, attrs: null, state: null }));
    this._render();
    this._loadAnchors();
  }

  getCardSize() { return 9; }
  static getStubConfig() { return {}; }

  set hass(hass) {
    this._hass = hass;
    let changed = false;
    this._srcs.forEach((s) => {
      const st = hass.states[s.cfg.entity];
      s.state = st || null;
      s.attrs = st ? st.attributes || {} : null;
      if (st) {
        const upd = s.attrs.updated || st.last_updated;
        if (upd !== s.lastUpdated) { s.lastUpdated = upd; changed = true; }
        const ver = String(s.attrs.geometry_version || "0");
        if (ver !== s.geoVersion && !s.loading) this._loadGeometry(s, ver);
      }
    });
    if (changed) this._anchor = performance.now();
    this._update();
  }

  connectedCallback() {
    this._tick = setInterval(() => this._frame(), 1000);
    this._vis = () => { if (!document.hidden) { this._anchor = performance.now(); this._frame(); } };
    document.addEventListener("visibilitychange", this._vis);
    if (window.ResizeObserver) { this._ro = new ResizeObserver(() => this._measure()); this._ro.observe(this); }
  }
  disconnectedCallback() {
    clearInterval(this._tick);
    document.removeEventListener("visibilitychange", this._vis);
    if (this._ro) this._ro.disconnect();
  }

  // ------------------------------------------------------------- loading
  async _loadAnchors() {
    try {
      const r = await fetch(`${this._config.anchors_url}?v=${VIC_VERSION}`, { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const a = await r.json();
      if (!a.stations || !a.w) throw new Error("not an anchors file");
      this._anchors = a;
      this._err = null;
    } catch (e) {
      this._err = `Could not load ${this._config.anchors_url} (${e && e.message || e})`;
      setTimeout(() => { if (!this._anchors) this._loadAnchors(); }, 15000);
    }
    this._built = false;
    this._update();
  }

  async _loadGeometry(s, ver) {
    s.loading = true;
    try {
      const r = await fetch(`${s.cfg.geometry_url}?v=${encodeURIComponent(ver)}`, { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const g = await r.json();
      if (!g.lines || !g.lines.length) throw new Error("no lines in file");
      s.geo = g; s.geoVersion = ver; s.geoErr = null;
      this._built = false;
    } catch (e) {
      s.geoErr = String(e && e.message || e);
      setTimeout(() => { s.loading = false; if (!s.geo) this._loadGeometry(s, ver); }, 15000);
      this._update();
      return;
    }
    s.loading = false;
    this._update();
  }

  // ----------------------------------------------------------- geometry
  _prepare() {
    const A = this._anchors;
    const lines = [];
    let la = 0, n = 0;
    this._srcs.forEach((s) => s.geo && s.geo.lines.forEach((l) => l.stations.forEach((st) => { la += st[1]; n++; })));
    const cos0 = Math.cos(((n ? la / n : -37.8) * Math.PI) / 180);
    this._kxy = (lat, lon) => [lon * cos0 * 111.32, lat * 110.57];
    this._srcs.forEach((s, si) => {
      if (!s.geo) return;
      s.geo.lines.forEach((ln) => {
        const L = { id: ln.id, src: si, group: s.cfg.group || "", name: ln.name, raw: ln };
        const m = MAP_COLOURS.find((c) => c[0].test(ln.name));
        L.color = (s.cfg.group || "").toLowerCase().startsWith("reg") ? REGIONAL_COLOUR : (m ? m[1] : (ln.gtfs_color || ln.color || "#555"));
        L._rp = ln.path.map((q) => this._kxy(q[0], q[1]));
        L._cum = [0];
        for (let i = 1; i < L._rp.length; i++) L._cum.push(L._cum[i - 1] + Math.hypot(L._rp[i][0] - L._rp[i - 1][0], L._rp[i][1] - L._rp[i - 1][1]));
        let prev = -1;
        const anch = [];
        ln.stations.forEach((st) => {
          const p = A.stations[nkey(st[0])];
          if (!p) return;
          const pr = this._project(L, this._kxy(st[1], st[2]));
          prev = Math.max(prev, pr.s);
          if (anch.length && Math.abs(anch[anch.length - 1].s - prev) < 1e-6 && anch[anch.length - 1].p[0] === p[0] && anch[anch.length - 1].p[1] === p[1]) return;
          anch.push({ s: prev, p: [p[0], p[1]] });
        });
        L._anch = anch;
        L.matched = anch.length; L.total = ln.stations.length;
        lines.push(L);
      });
    });
    // groups in the order given; within a group, alphabetical
    const gOrder = this._srcs.map((s) => s.cfg.group || "");
    lines.sort((a, b) => gOrder.indexOf(b.group) - gOrder.indexOf(a.group) || a.name.localeCompare(b.name));
    this._lines = lines;
    this._lineById = new Map(lines.map((l) => [l.src + "|" + l.id, l]));
  }

  _project(L, p) {
    let best = { d: 1e18, s: 0 };
    for (let i = 1; i < L._rp.length; i++) {
      const a = L._rp[i - 1], b = L._rp[i];
      const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
      const t = L2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) : 0;
      const d = Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
      if (d < best.d) best = { d, s: L._cum[i - 1] + t * Math.sqrt(L2) };
    }
    return best;
  }

  _at(L, s) {
    const A = L._anch;
    if (!A || A.length < 2) return null;
    s = Math.max(A[0].s, Math.min(A[A.length - 1].s, s));
    let j = 0;
    while (j < A.length - 2 && A[j + 1].s < s) j++;
    const a = A[j], b = A[j + 1];
    const t = b.s > a.s ? (s - a.s) / (b.s - a.s) : 0;
    const dx = b.p[0] - a.p[0], dy = b.p[1] - a.p[1];
    return { x: a.p[0] + dx * t, y: a.p[1] + dy * t, ang: (Math.atan2(dx, -dy) * 180) / Math.PI };
  }

  // --------------------------------------------------------------- build
  _render() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div id="root"></div></ha-card>`;
    this._built = false;
    this._rowSig = "";
    this._update();
  }
  _root() { return this.shadowRoot.getElementById("root"); }

  _buildMap() {
    this._prepare();
    this._rowSig = "";
    this._sel = null;
    const A = this._anchors, root = this._root();
    root.innerHTML = `
      <div class="head"><div><div class="sign"><span class="t">${esc(this._config.title)}</span><span class="bars"><i style="background:#0c4a9b"></i><i style="background:#c8102e"></i><i style="background:#f2b705"></i><i style="background:#00a0df"></i><i style="background:#0f9d3a"></i><i style="background:#f489b6"></i><i style="background:#8b1f9a"></i></span></div><div class="sub" id="sub"></div></div><span class="chip" id="chip"></span></div>
      <div id="banner"></div>
      <div class="mapwrap"><svg class="map" id="svg" viewBox="0 0 ${A.w} ${A.h}" role="img" aria-label="Map of Victorian trains and lines">
        <image href="${esc(this._config.map_image)}" x="0" y="0" width="${A.w}" height="${A.h}" preserveAspectRatio="none"/></svg>
        <button class="reset" id="reset" type="button">All lines</button></div>
      <div id="rows"></div>
      <div class="foot"><span id="f1"></span><span id="f2"></span></div>`;
    this._full = { x: 0, y: 0, w: A.w, h: A.h };
    this._vb = { ...this._full };
    const svg = root.querySelector("#svg");
    this._svg = svg;
    this._fade = svgEl("rect", { class: "fade", x: 0, y: 0, width: A.w, height: A.h });
    this._hl = svgEl("g", { class: "hl" });
    this._gt = svgEl("g", { id: "trains" });
    svg.append(this._fade, this._hl, this._gt);
    this._markers.clear();
    root.querySelector("#reset").addEventListener("click", () => this._select(null));
    this._wireGestures(svg);
    this._built = true;
    this._measure();
  }

  _measure() {
    if (!this._svg) return;
    const r = this._svg.getBoundingClientRect();
    if (r.width > 10) this._pxw = r.width;
    this._applyU();
  }
  _applyU() { if (this._svg && this._vb) this._svg.style.setProperty("--u", (this._vb.w / this._pxw).toFixed(4)); }
  _setVB(vb) {
    const f = this._full;
    vb.w = Math.min(f.w, Math.max(f.w / 12, vb.w));
    vb.h = vb.w * (f.h / f.w);
    vb.x = Math.max(0, Math.min(f.w - vb.w, vb.x));
    vb.y = Math.max(0, Math.min(f.h - vb.h, vb.y));
    this._vb = vb;
    this._svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    this._applyU();
    const zoomed = vb.w < f.w * 0.98;
    this.shadowRoot.getElementById("reset").classList.toggle("on", zoomed || !!this._sel);
  }

  _wireGestures(svg) {
    const pts = new Map();
    let last = null;
    const toMap = (cx, cy) => {
      const r = svg.getBoundingClientRect();
      return [this._vb.x + ((cx - r.left) / r.width) * this._vb.w, this._vb.y + ((cy - r.top) / r.height) * this._vb.h];
    };
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      cancelAnimationFrame(this._anim);
      const [mx, my] = toMap(e.clientX, e.clientY);
      const k = Math.exp(e.deltaY * 0.0015);
      const w = this._vb.w * k;
      const f = w / this._vb.w;
      this._setVB({ x: mx - (mx - this._vb.x) * f, y: my - (my - this._vb.y) * f, w, h: 0 });
    }, { passive: false });
    svg.addEventListener("pointerdown", (e) => {
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      this._moved = 0;
      last = null;
    });
    svg.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId);
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      const r = svg.getBoundingClientRect();
      if (pts.size === 1) {
        const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
        this._moved += Math.abs(dx) + Math.abs(dy);
        if (this._moved < 6) return;
        cancelAnimationFrame(this._anim);
        svg.classList.add("drag");
        this._setVB({ x: this._vb.x - (dx / r.width) * this._vb.w, y: this._vb.y - (dy / r.height) * this._vb.h, w: this._vb.w, h: 0 });
      } else if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (last) {
          const [mx, my] = toMap((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
          const f = last / d;
          this._moved = 99;
          this._setVB({ x: mx - (mx - this._vb.x) * f, y: my - (my - this._vb.y) * f, w: this._vb.w * f, h: 0 });
        }
        last = d;
      }
    });
    const up = (e) => { pts.delete(e.pointerId); last = null; if (!pts.size) svg.classList.remove("drag"); };
    svg.addEventListener("pointerup", up);
    svg.addEventListener("pointercancel", up);
    svg.addEventListener("click", (e) => {
      if (this._moved > 6 || e.target.closest && e.target.closest(".tr")) return;
      // tap on empty map: pick the nearest line anchor, if close enough
      const [mx, my] = toMap(e.clientX, e.clientY);
      let best = null;
      this._lines.forEach((L) => (L._anch || []).forEach((a) => {
        const d = Math.hypot(a.p[0] - mx, a.p[1] - my);
        if (d < this._vb.w * 0.02 && (!best || d < best[0])) best = [d, L];
      }));
      if (best) this._select(best[1].src + "|" + best[1].id);
    });
  }

  // ---------------------------------------------------------- selection
  _select(key) {
    this._sel = key && key !== this._sel ? key : null;
    this._pick = null;
    this._drawHighlight();
    this._zoomTo(this._targetBox());
    this._rowSig = "";
    this._update();
  }

  _drawHighlight() {
    this._hl.textContent = "";
    const L = this._sel && this._lineById.get(this._sel);
    this._fade.classList.toggle("on", !!L);
    if (!L || L._anch.length < 2) return;
    const d = "M" + L._anch.map((a) => `${a.p[0].toFixed(1)} ${a.p[1].toFixed(1)}`).join(" L");
    this._hl.append(svgEl("path", { class: "halo", d }), svgEl("path", { class: "core", d, stroke: L.color }));
    L._anch.forEach((a) => {
      const g = svgEl("g", { transform: `translate(${a.p[0].toFixed(1)} ${a.p[1].toFixed(1)})` });
      const u = svgEl("g", { class: "u" });
      u.append(svgEl("circle", { r: 4 }));
      g.append(u);
      this._hl.append(g);
    });
  }

  _targetBox() {
    const f = this._full;
    const L = this._sel && this._lineById.get(this._sel);
    if (!L || !L._anch.length) return { ...f };
    let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
    L._anch.forEach(({ p }) => { minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]); miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]); });
    const asp = f.w / f.h;
    let w = Math.max(maxx - minx, 300) * 1.3 + 160, h = Math.max(maxy - miny, 200) * 1.3 + 120;
    if (w / h < asp) w = h * asp; else h = w / asp;
    return { x: (minx + maxx) / 2 - w / 2, y: (miny + maxy) / 2 - h / 2, w, h };
  }

  _zoomTo(t) {
    cancelAnimationFrame(this._anim);
    const from = { ...this._vb };
    const t0 = performance.now(), dur = 450;
    const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    this._svg.classList.add("zooming");
    const step = (now) => {
      const k = reduce ? 1 : Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      this._setVB({ x: from.x + (t.x - from.x) * e, y: from.y + (t.y - from.y) * e, w: from.w + (t.w - from.w) * e, h: 0 });
      if (k < 1) this._anim = requestAnimationFrame(step);
      else { this._svg.classList.remove("zooming"); this._frame(); }
    };
    this._anim = requestAnimationFrame(step);
  }

  // -------------------------------------------------------------- update
  _update() {
    const root = this._root();
    if (!root || !this._config) return;
    if (this._err && !this._anchors) { root.innerHTML = `<div class="empty">${esc(this._err)}. Copy vic_network_map.png and vic_network_anchors.json into Home Assistant's www folder.</div>`; this._built = false; return; }
    if (!this._anchors) { root.innerHTML = '<div class="empty">Loading map\u2026</div>'; this._built = false; return; }
    const have = this._srcs.filter((s) => s.geo);
    if (!have.length) {
      const miss = this._srcs.filter((s) => !s.state).map((s) => s.cfg.entity);
      root.innerHTML = `<div class="empty">${miss.length === this._srcs.length
        ? `Entities not found: ${esc(miss.join(", "))}. Check the AppDaemon apps are running.`
        : "Loading line shapes\u2026"}</div>`;
      this._built = false;
      return;
    }
    if (!this._built) this._buildMap();

    const lines = [];
    this._vehicles = [];
    this._status = {};
    let worst = "ok", affected = 0, total = 0, anyStale = false, unknownAll = true;
    const banners = [];
    this._srcs.forEach((s, si) => {
      if (!s.attrs) { banners.push(["unknown", `${esc(s.cfg.group || s.cfg.entity)} data not available (${esc(s.cfg.entity)} not found).`]); return; }
      const a = s.attrs;
      (Array.isArray(a.lines) ? a.lines : []).forEach((st) => {
        this._status[si + "|" + st.id] = st;
        total++;
        if (st.level !== "unknown") unknownAll = false;
        if (st.level !== "ok" && st.level !== "unknown") affected++;
        if (LEVEL_RANK[st.level] > LEVEL_RANK[worst]) worst = st.level;
      });
      (Array.isArray(a.vehicles) ? a.vehicles : []).forEach((v) => this._vehicles.push(Object.assign({}, v, { _src: si })));
      if (truthy(a.stale)) { anyStale = true; banners.push(["unknown", `${esc(s.cfg.group || "")} live data is out of date, so statuses may be wrong.`]); }
      if (truthy(a.ptv_enabled) && !truthy(a.ptv_ok)) banners.push(["unknown", `${esc(s.cfg.group || "")} PTV notices unavailable${a.ptv_error ? " (" + esc(a.ptv_error) + ")" : ""}; status uses live data only.`]);
    });
    const chip = this.shadowRoot.getElementById("chip");
    const lvl = unknownAll ? "unknown" : worst;
    chip.className = `chip ${lvl}`;
    chip.innerHTML = `<span aria-hidden="true">${LEVEL_GLYPH[lvl]}</span>${unknownAll ? "Live data unavailable" : affected ? `${affected} of ${total} lines affected` : "All lines normal"}`;
    this.shadowRoot.getElementById("sub").textContent = `${this._vehicles.length} train${this._vehicles.length === 1 ? "" : "s"} running`;
    this.shadowRoot.getElementById("banner").innerHTML = banners.map(([c, t]) => `<div class="note ${c}">${t}</div>`).join("");
    this._placeTrains();
    this._renderRows();
    this._frame();
  }

  _renderRows() {
    const sig = JSON.stringify([this._status, this._sel, (this._vehicles || []).map((v) => [v.id, v.delay_min])]);
    if (sig === this._rowSig) return;
    this._rowSig = sig;
    const rows = this.shadowRoot.getElementById("rows");
    const out = [];
    let group = null, cols = 7;
    const groups = [];
    this._lines.forEach((L) => { if (!groups.includes(L.group)) groups.push(L.group); });
    cols = Math.max(2, Math.ceil(Math.max(...groups.map((g) => this._lines.filter((l) => l.group === g).length)) / 2));
    const vehByLine = {};
    this._vehicles.forEach((v) => { (vehByLine[v._src + "|" + v.line] = vehByLine[v._src + "|" + v.line] || []).push(v); });
    groups.forEach((g) => {
      out.push(`<div class="grp">${esc(g)}</div><div class="rows" style="--cols:${cols}">`);
      this._lines.filter((l) => l.group === g).forEach((L) => {
        const key = L.src + "|" + L.id;
        const s = this._status[key] || { level: "unknown", label: "No status" };
        const lv = LEVEL_RANK[s.level] === undefined ? "unknown" : s.level;
        const sel = this._sel === key;
        const sub = [];
        if (num(s.running, 0)) sub.push(`${s.running} running`);
        (s.detail || []).forEach((d) => sub.push(esc(d)));
        out.push(`<button class="row ${sel ? "sel" : ""}" data-key="${esc(key)}" type="button" aria-pressed="${sel}" style="--lc:${esc(L.color)}" title="${esc(L.name)}: ${esc(s.label)}${sub.length ? " (" + sub.join(", ") + ")" : ""}">
          <span class="nm">${esc(L.name)}</span><span class="pill ${lv}"><span class="g" aria-hidden="true">${LEVEL_GLYPH[lv]}</span>${esc(s.label)}</span></button>`);
        if (sel) {
          const items = [];
          (s.notices || []).forEach((n) => items.push(`<li><b>${esc(n.title)}</b>${n.url ? ` &middot; <a href="${esc(n.url)}" target="_blank" rel="noopener">Details</a>` : ""}</li>`));
          const tr = (vehByLine[key] || []).slice().sort((a, b) => (b.delay_min || 0) - (a.delay_min || 0)).map((v) => {
            const d = v.delay_min;
            const dl = d === null || d === undefined ? "" : d >= 1 ? ` &middot; ${d} min late` : d <= -1 ? ` &middot; ${-d} min early` : " &middot; on time";
            return `<li>${v.to ? "To " + esc(v.to) : "Train"}${dl}${v.state ? " &middot; " + esc(v.state) : ""}</li>`;
          });
          const miss = L.matched < 2 ? `<div style="color:var(--secondary-text-color)">Only ${L.matched} of this line's ${L.total} stations were found on the map, so its trains cannot be drawn.</div>` : "";
          out.push(`<div class="more">${esc(L.name)}: ${esc(s.label)}${items.length ? `<ul>${items.join("")}</ul>` : ""}${tr.length ? `<div style="margin-top:6px;color:var(--secondary-text-color)">Trains now</div><ul>${tr.join("")}</ul>` : "<div>No trains running on this line right now.</div>"}${miss}</div>`);
        }
      });
      out.push("</div>");
    });
    rows.innerHTML = out.join("");
    rows.querySelectorAll(".row").forEach((b) => b.addEventListener("click", () => this._select(b.dataset.key)));
  }

  // -------------------------------------------------------------- trains
  _levelOf(v) {
    const d = v.delay_min;
    if (d === null || d === undefined) return "unknown";
    return d >= 15 ? "major" : d >= 5 ? "minor" : "ok";
  }

  _placeTrains() {
    if (!this._gt) return;
    const seen = new Set();
    this._vehicles.forEach((v) => {
      const key = v._src + "|" + v.id;
      const lat = num(v.lat), lon = num(v.lon);
      const L = this._lineById.get(v._src + "|" + v.line);
      if (lat === null || lon === null || !L || !L._anch || L._anch.length < 2) return;
      seen.add(key);
      let m = this._markers.get(key);
      if (!m) {
        const g = svgEl("g", { class: "tr" });
        const inner = svgEl("g", { class: "u" });
        const body = svgEl("path", { class: "body", d: "M0,-9 L6.5,7 L0,3.5 L-6.5,7 Z" });
        const dot = svgEl("circle", { class: "body", r: 5 });
        const ring = svgEl("circle", { class: "ring", r: 10 });
        const t = svgEl("text", { class: "dly", x: 9, y: 4 });
        inner.append(ring, body, dot, t);
        g.append(inner);
        g.addEventListener("click", (e) => {
          e.stopPropagation();
          const was = this._pick === key;
          const lk = m.v._src + "|" + m.v.line;
          if (this._sel !== lk) this._select(lk);
          this._pick = was ? null : key;
          this._rowSig = "";
          this._update();
        });
        this._gt.append(g);
        m = { g, body, dot, t };
        this._markers.set(key, m);
      }
      m.v = v;
      const lvl = this._levelOf(v);
      m.g.setAttribute("class", `tr ${lvl}${this._sel && this._sel !== v._src + "|" + v.line ? " dim" : ""}${this._pick === key ? " picked" : ""}`);
      const brg = num(v.brg);
      m.body.style.display = brg === null ? "none" : "";
      m.dot.style.display = brg === null ? "" : "none";
      const d = v.delay_min;
      m.t.textContent = d !== null && d !== undefined && d >= 5 ? `+${d}` : "";
      m.g.setAttribute("aria-label", `Train${v.to ? " to " + v.to : ""}, ${L.name} line`);
      // schematic position follows the real position along the line; direction from the bearing
      const km = this._kxy(lat, lon);
      const pr = this._project(L, km);
      let i = 1;
      while (i < L._rp.length - 1 && L._cum[i] < pr.s) i++;
      const a = L._rp[i - 1], b = L._rp[i];
      const tx = b[0] - a[0], ty = b[1] - a[1], tl = Math.hypot(tx, ty) || 1;
      const sign = brg === null ? 0 : (Math.sin((brg * Math.PI) / 180) * tx / tl + Math.cos((brg * Math.PI) / 180) * ty / tl) >= 0 ? 1 : -1;
      m.base = { L, s: pr.s, sign, spd: num(v.spd, 0), state: v.state };
    });
    for (const [k, m] of this._markers) if (!seen.has(k)) { m.g.remove(); this._markers.delete(k); }
    this._frame();
  }

  _frame() {
    if (!this._markers || !this._built) return;
    const dt = Math.min(45, Math.max(0, (performance.now() - this._anchor) / 1000));
    for (const m of this._markers.values()) {
      const b = m.base;
      if (!b) continue;
      let s = b.s;
      if (b.sign && b.spd > 0 && !/at stop/i.test(b.state || "")) s += b.sign * ((b.spd * dt) / 3600);
      const at = this._at(b.L, s);
      if (!at) continue;
      m.g.style.transform = `translate(${at.x.toFixed(1)}px, ${at.y.toFixed(1)}px)`;
      if (b.sign) m.body.setAttribute("transform", `rotate(${(at.ang + (b.sign < 0 ? 180 : 0)).toFixed(0)})`);
    }
    const f1 = this.shadowRoot.getElementById("f1");
    if (f1) {
      const ts = this._srcs.map((s) => Date.parse((s.attrs && s.attrs.updated) || "")).filter((t) => !Number.isNaN(t));
      const age = ts.length ? Math.max(0, Math.round((Date.now() - Math.max(...ts)) / 1000)) : null;
      f1.textContent = age === null ? "" : age < 90 ? `Updated ${age}s ago` : `Updated ${Math.round(age / 60)} min ago`;
      const f2 = this.shadowRoot.getElementById("f2");
      if (f2) f2.textContent = "Map: Transport Victoria";
    }
  }
}

if (!customElements.get("vic-network-card")) customElements.define("vic-network-card", VicNetworkCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "vic-network-card")) {
  window.customCards.push({ type: "vic-network-card", name: "Victorian train network map",
    description: "Official network map with live Metro and V/Line trains and a status for every line (v" + VIC_VERSION + ")" });
}
