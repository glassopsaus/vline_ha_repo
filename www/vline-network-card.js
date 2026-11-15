/*
 * vline-network-card  v3.11.0
 * Live schematic (tube-map style: straight lines at 45-degree angles) map of the V/Line network: every line, trains as moving markers,
 * and an overall status for each line. Tap a line (map or list) to zoom to it.
 *
 * Needs the vline_trains AppDaemon app (sensor.vline_network + /local/vline_network.json).
 *
 * type: custom:vline-network-card
 * entity: sensor.vline_network            # optional
 * geometry_url: /local/vline_network.json # optional
 * title: V/Line network                   # optional
 */
const VNET_VERSION = "3.10.0";
console.info("%c vline-network-card %c v" + VNET_VERSION + " ", "background:#222;color:#fff", "background:#e0a410;color:#000");
// Roughly largest-first; used to pick which stations to show on the whole-network view.
const MAJOR_RANK = ["geelong", "ballarat", "bendigo", "traralgon", "warrnambool", "shepparton", "wangaratta", "albury", "seymour",
  "echuca", "swan hill", "sale", "bairnsdale", "maryborough", "ararat", "castlemaine", "bacchus marsh", "melton", "sunbury",
  "pakenham", "warragul", "morwell", "moe", "benalla", "kyneton", "colac", "ballan", "stawell", "wendouree", "euroa", "kilmore",
  "ballan", "wallan", "gisborne", "sunshine", "footscray", "dandenong", "broadmeadows", "lara", "winchelsea", "camperdown", "terang"];
// Direction each line leaves its junction on the official V/Line network map (0 = up, 1 = up-right ... 7 = up-left, in 45-degree steps),
// keyed by the line's terminus. `then` is a second heading after the first stretch. Lines not listed fall back to their real compass bearing.
const OFFICIAL = [
  [/^(ballarat|wendouree)/i, { o: 6 }], [/^ararat/i, { o: 6 }], [/^maryborough/i, { o: 7 }],
  [/^(bendigo|epsom)/i, { o: 7 }], [/^echuca/i, { o: 0 }], [/^swan hill/i, { o: 7 }],
  [/^seymour/i, { o: 0 }], [/^shepparton/i, { o: 0 }], [/^albury/i, { o: 1, then: 2 }],
  [/^traralgon/i, { o: 3, then: 2 }], [/^(bairnsdale|sale)/i, { o: 1 }],
  [/^(geelong|waurn ponds)/i, { o: 5 }], [/^warrnambool/i, { o: 6 }],
];
const BECK = ["#d6322b", "#1e4fa3", "#2f8a3b", "#e0a410", "#7a4a2b", "#e2751d", "#6b3f8f", "#4b5563", "#0b9aae", "#b4306a", "#8a9a1c", "#3c7f9e"];
const SVG_NS = "http://www.w3.org/2000/svg";
const BASE_W = 1000;

const LEVEL_GLYPH = { ok: "\u2713", minor: "!", major: "\u2715", unknown: "?" };
const LEVEL_RANK = { unknown: -1, ok: 0, minor: 1, major: 2 };

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const truthy = (v) => v === true || ["true", "1", "on", "yes"].includes(String(v).toLowerCase());
const num = (v, d = null) => { const n = Number(v); return v === null || v === undefined || v === "" || Number.isNaN(n) ? d : n; };
const svgEl = (name, attrs = {}) => {
  const e = document.createElementNS(SVG_NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
};

const STYLE = `
:host { display: block; }
ha-card { display: block; overflow: hidden; container-type: inline-size; }
.body { display: block; }
.head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 12px; padding: 14px 16px 6px; }
.sign { display: inline-block; clip-path: polygon(0 0, 100% 0, calc(100% - 14px) 100%, 0 100%); }
.sign .t { display: block; background: var(--primary-text-color); color: var(--card-background-color); padding: 10px 30px 9px 16px;
  font: 800 1.1rem/1 "Gill Sans", "Gill Sans MT", Futura, "Century Gothic", "Trebuchet MS", sans-serif; letter-spacing: .12em; text-transform: uppercase; white-space: nowrap; }
.sign .bars { display: flex; height: 6px; }
.sign .bars i { flex: 1; }
.sub { font-size: .78rem; color: var(--secondary-text-color); margin-top: 2px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
  font-size: .8rem; font-weight: 600; white-space: nowrap; color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--c) 45%, transparent); }
.chip .g { font-weight: 700; }
.ok { --c: var(--success-color, #2e8b57); }
.minor { --c: var(--warning-color, #c77700); }
.major { --c: var(--error-color, #d1342f); }
.unknown { --c: var(--secondary-text-color, #7a7f87); }
.mapwrap { --paper: var(--card-background-color, #fff); --ink: var(--primary-text-color, #111); position: relative; margin: 0 8px; }
svg.map { width: 100%; height: auto; max-height: 76vh; display: block; touch-action: manipulation; }
.reset { position: absolute; top: 6px; right: 14px; border: 1px solid var(--ink); background: var(--paper);
  color: var(--ink); border-radius: 999px; padding: 4px 10px; font-size: .78rem; cursor: pointer; display: none; }
.reset.on { display: block; }
.line path.p { fill: none; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; stroke-width: 5px; transition: opacity .3s; }
.line path.hit { fill: none; stroke: transparent; stroke-width: 18px; vector-effect: non-scaling-stroke; cursor: pointer; }
.line.dim path.p, .line.dim .st { opacity: .18; }
.line.sel path.p { stroke-width: 7px; }
.u { transform: scale(var(--u, 1)); }
.st circle { fill: var(--paper); stroke: var(--ink); stroke-width: 2.2px; vector-effect: non-scaling-stroke; }
.st.sm { display: none; }
.line.sel .st.sm { display: inline; }
.st line { stroke: var(--ink); stroke-width: 2px; stroke-linecap: butt; vector-effect: non-scaling-stroke; }
text.lbl { font: 600 10.5px "Gill Sans", "Gill Sans MT", Futura, "Century Gothic", "Trebuchet MS", sans-serif; letter-spacing: .06em; text-transform: uppercase; fill: var(--ink); paint-order: stroke; stroke: var(--paper); stroke-width: 3.5px; stroke-linejoin: round; pointer-events: none; }
text.lbl.mel { font-weight: 800; font-size: 12px; }
.tr { transition: transform 1s linear; cursor: pointer; }
.zooming .tr { transition: none; }
.tr .body { stroke: var(--paper); stroke-width: 2px; vector-effect: non-scaling-stroke; fill: var(--c); }
.tr .body .win { fill: var(--paper, #fff); stroke: var(--paper, #fff); stroke-width: 0; }
.tr .body path.shape { stroke: var(--paper, #fff); stroke-width: 1.5px; vector-effect: non-scaling-stroke; }
.tr .body { stroke: none; }
.tr .body .jt { fill: none; stroke: var(--paper, #fff); stroke-width: 1px; vector-effect: non-scaling-stroke; }
.tr.dim { opacity: .25; }
.tr.picked .ring { display: block; }
.tr .ring { display: none; fill: none; stroke: var(--primary-text-color); stroke-width: 1.5px; vector-effect: non-scaling-stroke; }
rect.bub { display: none; fill: var(--paper); stroke: var(--c); stroke-width: 1.5px; vector-effect: non-scaling-stroke; cursor: pointer; }
.tr.picked rect.bub { stroke-width: 2.5px; }
text.tlbl { font-size: 9px; font-weight: 600; fill: var(--ink); pointer-events: none; }
text.dly { font-size: 10px; font-weight: 700; fill: var(--c); paint-order: stroke; stroke: var(--paper); stroke-width: 3px; pointer-events: none; }
.rows { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; padding: 8px 12px 6px; }
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
.note { margin: 0 16px 6px; padding: 8px 10px; border-radius: 8px; font-size: .82rem; color: var(--primary-text-color);
  background: color-mix(in srgb, var(--c) 12%, transparent); border: 1px solid color-mix(in srgb, var(--c) 40%, transparent); }
.foot { display: flex; justify-content: space-between; gap: 8px; padding: 6px 16px 12px; font-size: .74rem; color: var(--secondary-text-color); }
.empty { padding: 24px 16px; color: var(--secondary-text-color); font-size: .9rem; }
@container (min-width: 640px) { .rows { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
`;

class VLineNetworkCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._geo = null;
    this._geoErr = null;
    this._geoVersion = null;
    this._geoLoading = false;
    this._attrs = {};
    this._anchor = performance.now();
    this._lastUpdated = null;
    this._sel = null;       // selected line id
    this._pick = null;      // selected train id
    this._markers = new Map();
    this._vb = null;
    this._anim = null;
    this._rowSig = "";
    this._built = false;
    this._pxw = 360;
  }

  setConfig(config) {
    this._config = Object.assign({
      entity: "sensor.vline_network",
      geometry_url: "/local/vline_network.json",
      title: "V/Line network",
      train_labels: "always",   // always | zoom | off  (number, origin and destination beside each train)
      headings: "official",   // official = V/Line map headings (tube-map octants); compass = exact true bearings from Melbourne
    }, config || {});
    this._official = String(this._config.headings).toLowerCase() === "official";
    this._render();
  }

  getCardSize() { return 8; }
  static getStubConfig() { return { entity: "sensor.vline_network" }; }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    if (!st) { this._attrs = null; this._state = null; this._update(); return; }
    this._state = st;
    this._attrs = st.attributes || {};
    const upd = this._attrs.updated || st.last_updated;
    if (upd !== this._lastUpdated) { this._lastUpdated = upd; this._anchor = performance.now(); }
    const ver = String(this._attrs.geometry_version || "0");
    if (ver !== this._geoVersion && !this._geoLoading) this._loadGeometry(ver);
    this._update();
  }

  connectedCallback() {
    this._tick = setInterval(() => this._frame(), 1000);
    this._vis = () => { if (!document.hidden) { this._anchor = performance.now(); this._frame(); } };
    document.addEventListener("visibilitychange", this._vis);
    if (window.ResizeObserver) {
      this._ro = new ResizeObserver(() => this._measure());
      this._ro.observe(this);
    }
  }
  disconnectedCallback() {
    clearInterval(this._tick);
    document.removeEventListener("visibilitychange", this._vis);
    if (this._ro) this._ro.disconnect();
  }

  // ------------------------------------------------------------ geometry
  async _loadGeometry(ver) {
    this._geoLoading = true;
    try {
      const url = `${this._config.geometry_url}?v=${encodeURIComponent(ver)}`;
      const r = await fetch(url, { cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const g = await r.json();
      if (!g.lines || !g.lines.length) throw new Error("no lines in file");
      this._geo = g;
      this._geoVersion = ver;
      this._geoErr = null;
      this._built = false;
      this._sel = null;
    } catch (e) {
      this._geoErr = String(e && e.message || e);
      // retry in a while, without hammering
      setTimeout(() => { this._geoLoading = false; if (!this._geo) this._loadGeometry(ver); }, 15000);
      this._update();
      return;
    }
    this._geoLoading = false;
    this._update();
  }

  // Tube-map layout: every line runs at multiples of 45 degrees out of Southern Cross,
  // station spacing is compressed real distance, branches start at the shared station.
  _layout() {
    const lines = this._geo.lines;
    let la = 0, n = 0;
    lines.forEach((l) => l.stations.forEach((st) => { la += st[1]; n++; }));
    const cos0 = Math.cos(((n ? la / n : -37.8) * Math.PI) / 180);
    const kxy = (lat, lon) => [lon * cos0 * 111.32, lat * 110.57];
    const isHub = (nm) => /southern cross|flinders street/i.test(nm);
    const key = (nm) => nm.toLowerCase();
    this._kxy = kxy;

    lines.forEach((ln) => {
      if (ln.stations.length > 1 && isHub(ln.stations[ln.stations.length - 1][0]) && !isHub(ln.stations[0][0])) {
        ln.stations = ln.stations.slice().reverse();
        ln.path = ln.path.slice().reverse();
      }
      ln._rp = ln.path.map((q) => kxy(q[0], q[1]));
      ln._cum = [0];
      for (let i = 1; i < ln._rp.length; i++) ln._cum.push(ln._cum[i - 1] + Math.hypot(ln._rp[i][0] - ln._rp[i - 1][0], ln._rp[i][1] - ln._rp[i - 1][1]));
      let prev = -1;
      ln._ss = ln.stations.map((st) => {
        const pr = this._project(ln, kxy(st[1], st[2]));
        prev = Math.max(prev, pr.s);
        return prev;
      });
      ln._km = ln.stations.map((st) => kxy(st[1], st[2]));
    });

    const vec = (o) => { const a = (o * Math.PI) / 4; return [Math.sin(a), -Math.cos(a)]; };
    const bearing = (p, q) => ((Math.atan2(q[0] - p[0], q[1] - p[1]) * 180) / Math.PI + 360) % 360;
    const adiff = (x, y) => { let d = Math.abs(x - y) % 360; return d > 180 ? 360 - d : d; };
    const step = (p, q) => Math.max(66, Math.min(104, 14 * Math.sqrt(Math.hypot(q[0] - p[0], q[1] - p[1])) + 30));
    // 'Inner' stations (within ~25 km of the hub) never start a branch; measured in real distance so it does not depend on drawing scale.
    const farKm = (ln, j) => Math.hypot(ln._km[j][0] - ln._km[0][0], ln._km[j][1] - ln._km[0][1]) >= 25;
    const order = lines.slice().sort((x, y) => x.stations.length - y.stations.length);

    // Place every line; lines that leave the hub on their own ray take their octant from `forced`
    // (line -> octant), or get the nearest free one on the first pass, which records them in `rays`.
    let placed, hubDirs, rays, bdirs;
    const run = (forced) => {
      placed = new Map(); hubDirs = new Set(); rays = []; bdirs = new Map();
      order.forEach((ln) => {
        const names = ln.stations.map((st) => st[0]);
        // Branch from the furthest station this line shares with lines already drawn (not necessarily a contiguous run:
        // different services skip different stops), as long as it is well away from the hub.
        let k = -1;
        for (let j = names.length - 1; j >= 0; j--) {
          const q = placed.get(key(names[j]));
          if (q && (j === 0 || farKm(ln, j))) { k = j; break; }
        }
        if (k < 0) { placed.set(key(names[0]), { x: 0, y: 0, dir: null, ln }); k = 0; }
        // A line that carries on past another line's terminus continues from that terminus
        // (Albury continues from the end of the Seymour line) rather than starting a fresh branch further on.
        for (let j = k; j > 0; j--) {
          const q = placed.get(key(names[j]));
          if (q && farKm(ln, j) && lines.some((o2) => o2 !== ln && o2._k0 !== undefined && o2.stations.length > 1 && key(o2.stations[o2.stations.length - 1][0]) === key(names[j]) && placed.has(key(o2.stations[o2.stations.length - 1][0])))) { k = j; break; }
        }
        const o = placed.get(key(names[k]));
        const rem = names.length - 1 - k;
        ln._k0 = rem > 0 ? k : 0;
        const own = o.ln && o.ln !== ln ? o.ln : null;   // the trunk line that placed the branch station: follow its route, not another line's
        // Stations before the branch point follow the trunk line's route; any this line has but the trunk lacks are spaced in between.
        const pre = names.slice(0, k + 1).map((nm) => {
          const ti = own ? own.stations.findIndex((t) => key(t[0]) === key(nm)) : -1;
          if (ti >= 0 && own._sx[ti]) return [own._sx[ti][0], own._sx[ti][1]];
          const q = placed.get(key(nm)); return q ? [q.x, q.y] : null;
        });
        pre[0] = pre[0] || [0, 0];
        for (let j = 1; j <= k; j++) {
          if (pre[j]) continue;
          let lo = j - 1, hi = j + 1;
          while (hi <= k && !pre[hi]) hi++;
          const t = (ln._ss[j] - ln._ss[lo]) / Math.max(1e-6, ln._ss[hi] - ln._ss[lo]);
          pre[j] = [pre[lo][0] + (pre[hi][0] - pre[lo][0]) * t, pre[lo][1] + (pre[hi][1] - pre[lo][1]) * t];
        }
        ln._sx = pre;
        if (rem > 0) {
          const tb = bearing(ln._km[k], ln._km[names.length - 1]);
          let d1 = Math.round(tb / 45) % 8;
          const atHub = (isHub(names[k]) && o.dir === null) || (o.x === 0 && o.y === 0);
          const ov = this._official ? (OFFICIAL.find((r) => r[0].test(names[names.length - 1])) || [])[1] : undefined;   // default: true compass bearings
          if (atHub) {
            if (ov) d1 = ov.o;
            else if (forced && forced.has(ln)) d1 = forced.get(ln);
            else {
              let best = null;
              for (let c = 0; c < 8; c++) {
                const sc = adiff(tb, c * 45) + (hubDirs.has(c) ? 1000 : 0);
                if (best === null || sc < best[0]) best = [sc, c];
              }
              d1 = best[1];
            }
            hubDirs.add(d1);
            if (!ov) rays.push({ ln, tb });
          }
          else if (o.dir !== null && o.dir !== undefined) {
            // A branch must visibly leave the station: never reuse the direction the trunk arrived on, or another branch's.
            const bk = key(names[k]);
            if (!bdirs.has(bk)) bdirs.set(bk, new Set([o.dir]));
            const used = bdirs.get(bk);
            let best = null;
            for (let c = 0; c < 8; c++) {
              if (used.has(c)) continue;
              const sc = adiff(tb, c * 45);
              if (best === null || sc < best[0]) best = [sc, c];
            }
            if (ov) { d1 = ov.o; used.add(d1); }
            else if (best) { d1 = best[1]; used.add(d1); }
          }
          const off = ((tb - d1 * 45 + 540) % 360) - 180;
          let d2 = d1, bend = names.length;
          if (ov) { if (ov.then !== undefined && rem > 1) { d2 = ov.then; bend = k + Math.max(1, Math.floor(rem * 0.4)); } }
          else if (Math.abs(off) > 15 && rem > 2) { d2 = (d1 + (off > 0 ? 1 : 7)) % 8; bend = k + 1 + Math.max(1, Math.floor(rem * 0.45)); }
          let pos = [o.x, o.y];
          let hm = null;   // previous main station along the current horizontal run
          const isMaj = (nm, idx) => idx === 0 || idx === names.length - 1 || MAJOR_RANK.some((r) => String(nm).toLowerCase().startsWith(r));
          for (let j = k + 1; j < names.length; j++) {
            const dir = j <= bend ? d1 : d2;
            // Compass mode: a straight ray at the exact true bearing, stations spaced by real distance (no octant snapping, no squashing).
            const v = this._official ? vec(dir) : [Math.sin((tb * Math.PI) / 180), -Math.cos((tb * Math.PI) / 180)];
            let d = this._official ? step(ln._km[j - 1], ln._km[j]) : Math.max(6, 3 * (ln._ss[j] - ln._ss[j - 1]));
            if (this._official && Math.abs(v[1]) < 1e-6) {
              // Horizontal run: main station names sit just below-right of their markers, always in the same place,
              // so stretch the run until each main name fits clear of the next main name along the line.
              const U0 = this._U || 2.2, wOf = (nm) => (8 + nm.length * 7.4 + 12) * U0;
              if (!isMaj(names[j], j)) d = Math.min(d, 14 * U0);   // stations with no name shown take almost no room
              if (!hm && isMaj(names[j - 1], j - 1)) hm = { x: pos[0], nm: names[j - 1] };
              if (hm && isMaj(names[j], j)) {
                d = v[0] > 0 ? Math.max(d, hm.x + wOf(hm.nm) - pos[0]) : Math.max(d, wOf(names[j]) - (hm.x - pos[0]));
              }
            } else hm = null;
            pos = [pos[0] + v[0] * d, pos[1] + v[1] * d];
            if (this._official && Math.abs(v[1]) < 1e-6 && isMaj(names[j], j)) hm = { x: pos[0], nm: names[j] };
            if (!placed.has(key(names[j]))) placed.set(key(names[j]), { x: pos[0], y: pos[1], dir, ln });
            ln._sx.push([pos[0], pos[1]]);
          }
        }
      });
    };
    run(null);
    // Re-assign the hub rays together so each line gets the compass octant that best matches
    // its true bearing from Melbourne (best overall fit, not first come first served).
    if (rays.length > 1 && rays.length <= 8) {
      const n = rays.length;
      let bestCost = 1e18, bestAsg = null;
      const used = new Array(8).fill(false), cur = [];
      const rec = (i, cost) => {
        if (cost >= bestCost) return;
        if (i === n) { bestCost = cost; bestAsg = cur.slice(); return; }
        for (let c = 0; c < 8; c++) {
          if (used[c]) continue;
          used[c] = true; cur[i] = c;
          const d = adiff(rays[i].tb, c * 45);
          rec(i + 1, cost + d * d);
          used[c] = false;
        }
      };
      rec(0, 0);
      if (bestAsg) {
        const forced = new Map();
        rays.forEach((r, i) => forced.set(r.ln, bestAsg[i]));
        run(forced);
      }
    }

    // Interchange rings only where a line genuinely branches off another (not every shared station name).
    const branch = new Set(lines.filter((l) => l._k0 > 0).map((l) => key(l.stations[l._k0][0])));
    let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
    lines.forEach((ln) => {
      ln._sp = [];
      ln._sx.slice(ln._k0).forEach((q) => { const l = ln._sp[ln._sp.length - 1]; if (!l || l[0] !== q[0] || l[1] !== q[1]) ln._sp.push(q); });
      ln._st = ln.stations.map((st, i) => ({
        name: st[0], x: ln._sx[i][0], y: ln._sx[i][1],
        offs: (() => {
          const a = ln._sx[Math.max(0, i - 1)], b = ln._sx[Math.min(ln._sx.length - 1, i === 0 ? 1 : i)];
          const dx = b[0] - a[0], dy = b[1] - a[1];
          if (Math.abs(dx) > Math.abs(dy) + 1) return [16, -16];   // runs sideways: label just below, else above
          if (Math.abs(dx) < 1) return [0];                         // runs up/down: label straight to the right
          return dx * dy > 0 ? [-9, 0, 12] : [9, 0, -12];           // diagonal: keep the text clear of the line
        })(),
        tick: (() => { const a = ln._sx[Math.max(0, i - 1)], b = ln._sx[Math.min(ln._sx.length - 1, i + 1)]; return (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI + 90; })(),
        end: i === 0 || i === ln.stations.length - 1, ix: branch.has(key(st[0])) || isHub(st[0]),
      }));
      ln._anch = ln.stations.map((st, i) => ({ s: ln._ss[i], p: ln._sx[i] }));
      // which stations appear on the whole-network view: terminus, interchanges, then the biggest few
      const cand = ln._st.filter((q) => !/southern cross/i.test(q.name));
      cand.forEach((q) => { q.major = q.end || q.ix || /^ballan$/i.test(q.name); q.far = Math.hypot(q.x, q.y) > 240; });
      const rank = (q) => MAJOR_RANK.findIndex((r) => q.name.toLowerCase().startsWith(r));
      cand.filter((q) => !q.major && q.far && rank(q) >= 0).sort((a, b) => rank(a) - rank(b)).slice(0, 2).forEach((q) => { q.major = true; });
      let have = cand.filter((q) => q.major).length;
      const rest = cand.filter((q) => !q.major && q.far);
      for (let k = 0; have < 3 && rest.length && k < 3; k++) {
        const pick = rest.splice(Math.floor(rest.length / (3 - have + 1)), 1)[0];
        if (pick) { pick.major = true; have++; }
      }
      ln._st.forEach((q) => { if (q.end) maxx = Math.max(maxx, q.x + 30 + q.name.length * 7.4 * 2.4 - 220); });
      ln._sx.forEach((q) => { minx = Math.min(minx, q[0]); maxx = Math.max(maxx, q[0]); miny = Math.min(miny, q[1]); maxy = Math.max(maxy, q[1]); });
    });
    const padX = 220, padY = 90;
    this._full = { x: minx - padX, y: miny - padY, w: Math.max(maxx - minx + 2 * padX, 300), h: Math.max(maxy - miny + 2 * padY, 200) };
    this._hubDirs = hubDirs;
    this._mel = null;
    // Label widths depend on the drawing scale, which depends on the layout: lay out once, measure the scale, and redo it once.
    if (!this._relaid) {
      this._relaid = true;
      const wpx = Math.max(300, (this.clientWidth || 800) - 16), hpx = Math.max(300, 0.76 * (window.innerHeight || 900));
      const u = Math.max(this._full.w / wpx, this._full.h / hpx);
      if (!this._U || Math.abs(u - this._U) / this._U > 0.08) { this._U = u; this._layout(); }
    }
  }

  // nearest point of a line's real path: {s: km along the path, tx, ty: tangent}
  _project(ln, p) {
    let best = { d: 1e18, s: 0, tx: 0, ty: 1 };
    for (let i = 1; i < ln._rp.length; i++) {
      const a = ln._rp[i - 1], b = ln._rp[i];
      const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
      const t = L2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2)) : 0;
      const d = Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
      if (d < best.d) { const L = Math.sqrt(L2) || 1; best = { d, s: ln._cum[i - 1] + t * Math.sqrt(L2), tx: dx / L, ty: dy / L }; }
    }
    return best;
  }

  // position and heading (screen angle of increasing s) on the schematic for distance s
  _at(ln, s) {
    const A = ln._anch;
    if (A.length < 2) return { x: A[0].p[0], y: A[0].p[1], ang: 0, s };
    s = Math.max(A[0].s, Math.min(A[A.length - 1].s, s));
    let j = 0;
    while (j < A.length - 2 && A[j + 1].s < s) j++;
    // skip zero-length segments
    const a = A[j], b = A[j + 1];
    const t = b.s > a.s ? (s - a.s) / (b.s - a.s) : 0;
    const dx = b.p[0] - a.p[0], dy = b.p[1] - a.p[1];
    return { x: a.p[0] + dx * t, y: a.p[1] + dy * t, ang: (Math.atan2(dx, -dy) * 180) / Math.PI, s };
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
    this._relaid = false;
    this._layout();
    const root = this._root();
    const f = this._full;
    root.innerHTML = `
      <div class="head"><div><div class="sign"><span class="t">${esc(this._config.title)}</span><span class="bars">${BECK.slice(0, 7).map((c) => `<i style="background:${c}"></i>`).join("")}</span></div><div class="sub" id="sub" style="margin-top:6px"></div></div><span class="chip" id="chip"></span></div>
      <div id="banner"></div>
      <div class="body"><div class="mapwrap"><svg class="map" id="svg" viewBox="${f.x} ${f.y} ${f.w} ${f.h}" role="img" aria-label="Map of V/Line trains and lines"></svg>
        <button class="reset" id="reset" type="button">All lines</button></div>
      <div class="rows" id="rows"></div></div>
      <div class="foot"><span id="f1"></span><span id="f2"></span></div>`;
    this._vb = { ...f };
    const svg = root.querySelector("#svg");
    this._svg = svg;
    svg.addEventListener("click", () => { if (this._pick) { this._pick = null; this._rowSig = ""; this._update(); } });   // click empty map: close the train bubble
    const gl = svgEl("g", { id: "lines" });
    const gs = svgEl("g", { id: "labels" });
    const gt = svgEl("g", { id: "trains" });
    svg.append(gl, gs, gt);
    this._gl = gl; this._gs = gs; this._gt = gt;
    this._markers.clear();

    this._geo.lines.forEach((ln, li) => {
      ln.color = BECK[li % BECK.length];
      const g = svgEl("g", { class: "line", "data-id": ln.id });
      g.style.setProperty("--lc", ln.color);
      const d = this._roundPath(ln._sp, 16);
      const p = svgEl("path", { class: "p", d, stroke: ln.color });
      const hit = svgEl("path", { class: "hit", d });
      g.append(p, hit);
      ln._st.slice(ln._k0).forEach((st) => {
        const sg = svgEl("g", { class: "st" + (st.ix ? " ix" : "") + (st.major || st.ix ? "" : " sm"), transform: `translate(${st.x.toFixed(1)} ${st.y.toFixed(1)})` });
        const u = svgEl("g", { class: "u" });
        if (st.ix) u.append(svgEl("circle", { r: /southern cross/i.test(st.name) ? 7.5 : 5.5 }));
        else u.append(svgEl("line", { x1: -6.5, x2: 6.5, y1: 0, y2: 0, transform: `rotate(${st.tick.toFixed(0)})` }));
        sg.append(u);
        g.append(sg);
      });
      g.addEventListener("click", () => this._select(ln.id));
      gl.append(g);
    });
    root.querySelector("#reset").addEventListener("click", () => this._select(null));
    this._built = true;
    this._measure();
    this._layoutLabels();
  }

  _roundPath(pts, r) {
    if (pts.length < 2) return "";
    let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i - 1], b = pts[i], c = pts[i + 1];
      const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, l2 = Math.hypot(c[0] - b[0], c[1] - b[1]) || 1;
      const d1 = Math.min(r, l1 / 2), d2 = Math.min(r, l2 / 2);
      const p1 = [b[0] - ((b[0] - a[0]) / l1) * d1, b[1] - ((b[1] - a[1]) / l1) * d1];
      const p2 = [b[0] + ((c[0] - b[0]) / l2) * d2, b[1] + ((c[1] - b[1]) / l2) * d2];
      d += ` L${p1[0].toFixed(1)} ${p1[1].toFixed(1)} Q${b[0].toFixed(1)} ${b[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    const e = pts[pts.length - 1];
    return d + ` L${e[0].toFixed(1)} ${e[1].toFixed(1)}`;
  }

  _measure() {
    if (!this._svg) return;
    const r = this._svg.getBoundingClientRect();
    if (r.width > 10) { this._pxw = r.width; this._pxh = r.height; }
    this._applyU();
    this._layoutLabels();
  }

  _unit() {
    const sc = Math.min(this._pxw / this._vb.w, (this._pxh || 1e9) / this._vb.h);
    return 1 / sc;
  }

  _applyU() {
    if (!this._svg) return;
    const u = this._unit();
    this._svg.style.setProperty("--u", u.toFixed(4));
  }

  // ------------------------------------------------------------- labels
  _layoutLabels() {
    if (!this._gs || !this._geo) return;
    const u = this._unit();
    const gs = this._gs;
    gs.textContent = "";
    const boxes = [];
    const hit = (b) => boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
    const view = this._vb;
    const inView = (x, y) => x > view.x - 5 && x < view.x + view.w + 5 && y > view.y && y < view.y + view.h;
    const mel = this._melbourne();
    // Labels always sit to the right of the station (never flipped to the left); offs = vertical offsets to try (px).
    // Sample every drawn line so a label is never laid over a line (its own or another's).
    const pts = [];
    this._geo.lines.forEach((l) => {
      const sp = l._sp || [];
      for (let i = 1; i < sp.length; i++) {
        const a = sp[i - 1], b = sp[i], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (4 * u)));
        for (let j = 0; j <= n; j++) pts.push([a[0] + ((b[0] - a[0]) * j) / n, a[1] + ((b[1] - a[1]) * j) / n]);
      }
    });
    const onLine = (b) => pts.some((q) => q[0] > b.x - 2 * u && q[0] < b.x + b.w + 2 * u && q[1] > b.y - 2 * u && q[1] < b.y + b.h + 2 * u);
    const done = new Set();
    const place = (name, x, y, cls, offs, isEnd) => {
      if (!inView(x, y)) return;
      const dk = name + Math.round(x) + "," + Math.round(y);
      if (done.has(dk)) return;
      done.add(dk);
      const w = name.length * 7.4 * u, h = 14 * u;
      // Stay on one side of the line: the side of the first preferred offset, never flipping to the other.
      const pref = offs || [0];
      const side = Math.sign(pref[0]);
      const vo = side === 0 ? [0] : (side > 0 ? [16, 14, 26, 40] : [-16, -14, -26, -40]).filter((v) => true);
      const cand = side === 0 ? [0] : pref.filter((v) => Math.sign(v) === side || v === 0).concat(vo.filter((v) => !pref.includes(v)));
      const flat = pref.length === 2 && pref[0] === 16 && pref[1] === -16;   // horizontal run: one fixed slot, just below-right
      for (const strict of [true, false]) for (const dx of (flat ? [0] : [0, 10, 22])) for (const off of (flat ? [16] : cand)) {
        if (!strict && !isEnd) continue;
        const box = { x: x + (8 + dx) * u, y: y + off * u - h / 2, w, h };
        if (box.x + box.w > view.x + view.w - 2 * u || hit(box) || (strict && onLine(box))) continue;
        boxes.push(box);
        const g = svgEl("g", { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` });
        const t = svgEl("text", { class: "lbl u " + (cls || ""), x: 8 + dx, y: off + 4, "text-anchor": "start" });
        t.textContent = name;
        g.append(t);
        gs.append(g);
        return;
      }
      if (isEnd) {   // every end-of-line station is named, even if it has to overlap something
        const off = cand[0];
        const g = svgEl("g", { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` });
        const t = svgEl("text", { class: "lbl u", x: 8, y: off + 4, "text-anchor": "start" });
        t.textContent = name;
        g.append(t); gs.append(g);
        boxes.push({ x: x + 8 * u, y: y + off * u - h / 2, w, h });
      }
    };
    place("Southern Cross", mel.x, mel.y, "mel", [18, -18, 34]);
    const lines = this._geo.lines;
    const zoomed = this._sel ? lines.find((l) => l.id === this._sel) : null;
    if (zoomed) {
      zoomed._st.filter((s) => s.end && !/southern cross/i.test(s.name)).forEach((s) => place(s.name, s.x, s.y, "", s.offs, true));
      zoomed._st.filter((s) => !s.end && !/southern cross/i.test(s.name)).forEach((s) => place(s.name, s.x, s.y, "", s.offs));
    } else {
      lines.forEach((l) => l._st.filter((s) => s.end && !/southern cross/i.test(s.name)).forEach((s) => place(s.name, s.x, s.y, "", s.offs, true)));
      lines.forEach((l) => l._st.filter((s) => s.major && !s.end && !/southern cross/i.test(s.name)).forEach((s) => place(s.name, s.x, s.y, "", s.offs)));
    }
  }

  _melbourne() {
    if (this._mel) return this._mel;
    for (const l of this._geo.lines) {
      const st = l._st.find((x) => /southern cross/i.test(x.name));
      if (st) { this._mel = st; return st; }
    }
    this._mel = { x: 0, y: 0 };
    return this._mel;
  }

  // ---------------------------------------------------------- selection
  _select(id) {
    this._sel = id && id !== this._sel ? id : null;
    this._pick = null;
    const target = this._targetBox();
    this._zoomTo(target);
    this._rowSig = "";
    this._update();
  }

  _targetBox() {
    const f = this._full;
    if (!this._sel) return { ...f };
    const ln = this._geo.lines.find((l) => l.id === this._sel);
    if (!ln) return { ...f };
    let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
    ln._sx.forEach(([x, y]) => { minx = Math.min(minx, x); maxx = Math.max(maxx, x); miny = Math.min(miny, y); maxy = Math.max(maxy, y); });
    const aspect = f.w / f.h;
    let w = Math.max(maxx - minx, 60) * 1.35 + 120, h = Math.max(maxy - miny, 60) * 1.35 + 80;
    if (w / h < aspect) w = h * aspect; else h = w / aspect;
    const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
    return { x: cx - w / 2, y: cy - h / 2, w, h };
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
      const vb = {};
      for (const key of ["x", "y", "w", "h"]) vb[key] = from[key] + (t[key] - from[key]) * e;
      this._vb = vb;
      this._svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      this._applyU();
      if (k < 1) this._anim = requestAnimationFrame(step);
      else {
        this._svg.classList.remove("zooming");
        this._layoutLabels();
        this._placeTrains(true);
      }
    };
    this._anim = requestAnimationFrame(step);
    this._layoutLabels();
  }

  // -------------------------------------------------------------- update
  _theme() {
    const root = this.shadowRoot;
    if (!this._probe) {
      this._probe = document.createElement("div");
      this._probe.style.cssText = "position:absolute;width:0;height:0;visibility:hidden;background:var(--card-background-color, #fff)";
      root.appendChild(this._probe);
    }
    const m = /rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(getComputedStyle(this._probe).backgroundColor || "");
    return m ? (0.299 * m[1] + 0.587 * m[2] + 0.114 * m[3]) / 255 < 0.45 : false;
  }

  _update() {
    const root = this._root();
    if (!root) return;
    if (!this._config) return;
    if (this._attrs === null) {
      root.innerHTML = `<div class="empty">Entity <b>${esc(this._config.entity)}</b> not found. Check the V/Line AppDaemon app is running and has restarted since you added the map.</div>`;
      this._built = false;
      return;
    }
    if (!this._geo) {
      root.innerHTML = `<div class="empty">${this._geoErr
        ? `Could not load the map shape (${esc(this._geoErr)}). It is created by the AppDaemon app in /config/www/vline_network.json &mdash; restart the add-on and check its log for "Network map ready".`
        : "Loading map…"}</div>`;
      this._built = false;
      return;
    }
    if (!this._built) this._buildMap();

    const a = this._attrs;
    const lines = Array.isArray(a.lines) ? a.lines : [];
    const byId = {};
    lines.forEach((s) => { byId[s.id] = s; });
    this._status = byId;
    const stale = truthy(a.stale), vstale = truthy(a.vehicles_stale);

    // header chip
    const affected = lines.filter((s) => s.level !== "ok" && s.level !== "unknown");
    const unknown = lines.length && lines.every((s) => s.level === "unknown");
    const worst = unknown ? "unknown" : (a.worst_level || "ok");
    const chip = this.shadowRoot.getElementById("chip");
    chip.className = `chip ${worst}`;
    chip.innerHTML = `<span class="g">${LEVEL_GLYPH[worst] || "?"}</span>${unknown ? "Live data unavailable"
      : affected.length ? `${affected.length} of ${lines.length} lines affected` : "All lines normal"}`;
    const veh = Array.isArray(a.vehicles) ? a.vehicles : [];
    this.shadowRoot.getElementById("sub").textContent = vstale ? "Train positions unavailable" : `${veh.length} train${veh.length === 1 ? "" : "s"} running`;

    // banner
    const bn = [];
    if (stale) bn.push(["unknown", "Live data is out of date, so the statuses below may be wrong."]);
    if (truthy(a.ptv_enabled) && !truthy(a.ptv_ok)) bn.push(["unknown", `PTV notices unavailable${a.ptv_error ? " (" + esc(a.ptv_error) + ")" : ""}; status uses live data only.`]);
    this.shadowRoot.getElementById("banner").innerHTML = bn.map(([c, t]) => `<div class="note ${c}">${t}</div>`).join("");

    const mw = this.shadowRoot.querySelector(".mapwrap");
    if (mw) mw.classList.toggle("dk", this._theme());
    this._vehicles = veh;
    this._placeTrains(false);
    this._renderRows(lines);
    this._frame();
  }

  _renderRows(lines) {
    const sig = JSON.stringify([lines, this._sel, this._pick, (this._vehicles || []).map((v) => [v.id, v.delay_min])]);
    if (sig === this._rowSig) return;
    this._rowSig = sig;
    const rows = this.shadowRoot.getElementById("rows");
    const vehByLine = {};
    (this._vehicles || []).forEach((v) => { (vehByLine[v.line] = vehByLine[v.line] || []).push(v); });
    const out = [];
    let moreHtml = "";
    this._geo.lines.forEach((ln) => {
      const s = (this._status || {})[ln.id] || { level: "unknown", label: "No status" };
      const lvl = LEVEL_RANK[s.level] === undefined ? "unknown" : s.level;
      const tr = vehByLine[ln.id] || [];
      const sub = [];
      if (num(s.running, 0)) sub.push(`${s.running} running`);
      (s.detail || []).forEach((d) => sub.push(esc(d)));
      const sel = this._sel === ln.id;
      let more = "";
      if (sel) {
        const items = [];
        (s.notices || []).forEach((n) => items.push(`<li><b>${esc(n.title)}</b>${n.url ? ` &middot; <a href="${esc(n.url)}" target="_blank" rel="noopener">Details</a>` : ""}</li>`));
        const list = tr.slice().sort((a, b) => (b.delay_min || 0) - (a.delay_min || 0)).map((v) => {
          const d = v.delay_min;
          const dl = d === null || d === undefined ? "" : d >= 1 ? ` &middot; ${d} min late` : d <= -1 ? ` &middot; ${-d} min early` : " &middot; on time";
          return `<li data-train="${esc(v.id)}">To ${esc(v.to || "?")}${dl}${v.state ? " &middot; " + esc(v.state) : ""}</li>`;
        });
        more = `<div class="more">${items.length ? `<ul>${items.join("")}</ul>` : ""}${list.length ? `<div style="margin-top:6px;color:var(--secondary-text-color)">Trains now</div><ul>${list.join("")}</ul>` : (items.length ? "" : "No trains running on this line right now.")}</div>`;
      }
      out.push(`<button class="row ${sel ? "sel" : ""}" data-id="${esc(ln.id)}" type="button" aria-pressed="${sel}" style="--lc:${esc(ln.color)}" title="${esc(ln.name)}: ${esc(s.label)}${sub.length ? " (" + sub.join(", ") + ")" : ""}">
        <span class="nm">${esc(ln.name)}</span><span class="pill ${lvl}"><span class="g" aria-hidden="true">${LEVEL_GLYPH[lvl]}</span>${esc(s.label)}</span></button>`);
      if (more) moreHtml = more;
    });
    if (moreHtml) out.push(moreHtml);
    rows.style.setProperty("--cols2", Math.max(2, Math.ceil(this._geo.lines.length / 2)));
    rows.innerHTML = out.join("");
    rows.querySelectorAll(".row").forEach((b) => b.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      this._select(b.dataset.id);
    }));
    this.shadowRoot.getElementById("reset").classList.toggle("on", !!this._sel);
    this._gl.querySelectorAll(".line").forEach((g) => {
      g.classList.toggle("sel", g.dataset.id === this._sel);
      g.classList.toggle("dim", !!this._sel && g.dataset.id !== this._sel);
    });
  }

  // -------------------------------------------------------------- trains
  _levelOf(v) {
    const d = v.delay_min;
    if (d === null || d === undefined) return "unknown";
    return d >= 15 ? "major" : d >= 5 ? "minor" : "ok";
  }

  _placeTrains(force) {
    if (!this._gt || !this._geo) return;
    const seen = new Set();
    (this._vehicles || []).forEach((v) => {
      const lat = num(v.lat), lon = num(v.lon);
      if (lat === null || lon === null) return;
      seen.add(v.id);
      let m = this._markers.get(v.id);
      if (!m) {
        const g = svgEl("g", { class: "tr" });
        const inner = svgEl("g", { class: "u" });
        const body = svgEl("g", { class: "body" });   // small top-down train: rounded nose, windscreen, two car joints
        body.append(svgEl("path", { class: "shape", d: "M-5.3,12 V-6.8 Q-5.3,-12.8 0,-12.8 Q5.3,-12.8 5.3,-6.8 V12 Z" }),
          svgEl("path", { class: "win", d: "M-3.6,-6.9 Q-3.6,-9.9 0,-9.9 Q3.6,-9.9 3.6,-6.9 Z" }),
          svgEl("path", { class: "jt", d: "M-5.3,2 H5.3 M-5.3,7 H5.3" }));
        const dot = svgEl("circle", { class: "body", r: 5 });
        const ring = svgEl("circle", { class: "ring", r: 10 });
        const t = svgEl("text", { class: "dly", x: 9, y: 4 });
        const tl = svgEl("text", { class: "tlbl", x: -14, y: -9, "text-anchor": "end" });
        const bub = svgEl("rect", { class: "bub", rx: 8, ry: 8 });
        inner.append(ring, body, dot, t, bub, tl);
        g.append(inner);
        g.addEventListener("click", (e) => {
          e.stopPropagation();
          const was = this._pick === v.id;
          this._pick = was ? null : v.id;
          this._pick = was ? null : v.id;
          this._rowSig = "";
          this._update();
        });
        this._gt.append(g);
        m = { g, inner, body, dot, t, tl, bub };
        this._markers.set(v.id, m);
      }
      m.v = v;
      const lvl = this._levelOf(v);
      m.g.setAttribute("class", `tr ${lvl}${this._sel && v.line !== this._sel ? " dim" : ""}${this._pick === v.id ? " picked" : ""}`);
      const brg = num(v.brg);
      m.body.style.display = brg === null ? "none" : "";
      m.dot.style.display = brg === null ? "" : "none";
      // Train icon only; click a train to open its bubble: service, origin -> destination, scheduled arrival, live difference.
      const picked = this._pick === v.id;
      if (picked && this._gt.lastChild !== m.g) this._gt.append(m.g);   // keep the open bubble on top
      m.tl.textContent = "";
      if (picked && String(this._config.train_labels || "click").toLowerCase() !== "off") {
        const dm = v.delay_min;
        const diff = dm === null || dm === undefined ? "" : dm >= 1 ? `${dm} min late` : dm <= -1 ? `${-dm} min early` : "on time";
        const rows = [
          [(v.no ? v.no + " \u00B7 " : "") + (v.from && v.to ? `${v.from} \u2192 ${v.to}` : v.to ? "to " + v.to : ""), true],
          [[v.arr ? "Arrives " + v.arr : "", diff].filter(Boolean).join("  \u00B7  "), false],
        ].filter((r) => r[0]);
        const y0 = -9 - (rows.length - 1) * 12;
        m.tl.setAttribute("y", y0);
        rows.forEach((r, k) => {
          const a = svgEl("tspan", { x: -14, style: r[1] ? "font-weight:700" : "" });
          if (k) a.setAttribute("dy", "1.3em");
          a.textContent = r[0]; m.tl.append(a);
        });
        const w = Math.max(...rows.map((r) => r[0].length)) * 5.4 + 12, h = rows.length * 12 + 6;
        m.bub.setAttribute("x", -14 - w + 6); m.bub.setAttribute("y", y0 - 11);
        m.bub.setAttribute("width", w); m.bub.setAttribute("height", h); m.bub.style.display = "block";
      } else m.bub.style.display = "none";
      const d = v.delay_min;
      m.t.textContent = d !== null && d !== undefined && d >= 5 ? `+${d}` : "";
      const ln = this._geo.lines.find((l) => l.id === v.line);
      m.g.setAttribute("aria-label", `Train to ${v.to || "unknown"}, ${ln ? ln.name + " line" : ""}`);
      let base = null;
      if (ln) {
        const pr = this._project(ln, this._kxy(lat, lon));
        const sign = brg === null ? 0 : (Math.sin((brg * Math.PI) / 180) * pr.tx + Math.cos((brg * Math.PI) / 180) * pr.ty) >= 0 ? 1 : -1;
        base = { ln, s: pr.s, sign, spd: num(v.spd, 0), state: v.state };
      }
      m.base = base;
    });
    for (const [id, m] of this._markers) {
      if (!seen.has(id)) { m.g.remove(); this._markers.delete(id); }
    }
    this._frame(force);
  }

  _frame() {
    if (!this._markers || !this._geo || !this._full) return;
    const dt = Math.min(45, Math.max(0, (performance.now() - this._anchor) / 1000));
    for (const m of this._markers.values()) {
      const b = m.base;
      if (!b) continue;
      let s = b.s;
      if (b.sign && b.spd > 0 && !/at stop/i.test(b.state || "")) s += b.sign * ((b.spd * dt) / 3600);
      const at = this._at(b.ln, s);
      m.g.style.transform = `translate(${at.x.toFixed(1)}px, ${at.y.toFixed(1)}px)`;
      if (b.sign) m.body.setAttribute("transform", `rotate(${(at.ang + (b.sign < 0 ? 180 : 0)).toFixed(0)})`);
    }
    const f1 = this.shadowRoot.getElementById("f1");
    if (f1 && this._attrs) {
      const upd = Date.parse(this._attrs.updated || "");
      const age = Number.isNaN(upd) ? null : Math.max(0, Math.round((Date.now() - upd) / 1000));
      f1.textContent = age === null ? "" : age < 90 ? `Updated ${age}s ago` : `Updated ${Math.round(age / 60)} min ago`;
      const f2 = this.shadowRoot.getElementById("f2");
      if (f2) f2.textContent = truthy(this._attrs.ptv_enabled) ? "Live data + PTV notices" : "Live data only";
    }
  }
}

if (!customElements.get("vline-network-card")) customElements.define("vline-network-card", VLineNetworkCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "vline-network-card")) {
  window.customCards.push({ type: "vline-network-card", name: "V/Line network map",
    description: "Live schematic map of V/Line trains with a status for every line (v" + VNET_VERSION + ")" });
}
