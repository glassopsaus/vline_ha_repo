/*
 * vline-train-card: animated "train approaching Ballan" card for Home Assistant.
 *
 * Reads a sensor.vline_<route> entity published by the vline_trains AppDaemon app.
 * No dependencies. Usage:
 *   type: custom:vline-train-card
 *   entity: sensor.vline_ballan_to_ballarat
 *   title: Ballan to Ballarat      # optional
 *   max_rows: 3                    # optional, upcoming trains listed below the graphic
 */
const VLINE_CARD_VERSION = "1.1.0";

const X0 = 84;   // previous-station x in the SVG
const X1 = 330;  // Ballan x in the SVG
const STOP = 24; // train rests this far short of the Ballan marker at the platform
const RAIL_Y = 62;

const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const truthy = (v) => ["true", "1"].includes(String(v).toLowerCase());

const pickHero = (services) =>
  (services || []).find((s) => s.status !== "cancelled" && s.ballan_arrival) || null;

class VLineTrainCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Set an entity, e.g. sensor.vline_ballan_to_ballarat");
    }
    this._config = { max_rows: 3, ...config };
    this._key = null;
    this._rowsHtml = null;
    this._build();
  }

  static getStubConfig() {
    return { entity: "sensor.vline_ballan_to_ballarat" };
  }

  getCardSize() {
    return 5;
  }

  set hass(hass) {
    this._hass = hass;
    this._ingest();
    this._update();
  }

  connectedCallback() {
    if (!this._onVisible) {
      this._onVisible = () => {
        if (document.visibilityState === "visible") { this._ingest(); this._update(); }
      };
    }
    document.addEventListener("visibilitychange", this._onVisible);
    if (this._timer) return;
    this._timer = setInterval(() => this._update(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
    document.removeEventListener("visibilitychange", this._onVisible);
  }

  // ------------------------------------------------------------------ build
  _build() {
    if (!this._root) this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; overflow: hidden; }
        .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .title { font-size: 16px; font-weight: 600; color: var(--primary-text-color); }
        .chip { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
                background: var(--secondary-background-color); color: var(--secondary-text-color);
                white-space: nowrap; }
        .chip.ok { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent);
                   color: var(--success-color, #43a047); }
        .chip.late { background: color-mix(in srgb, var(--warning-color, #f57c00) 20%, transparent);
                     color: var(--warning-color, #f57c00); }
        .chip.bad { background: color-mix(in srgb, var(--error-color, #d32f2f) 18%, transparent);
                    color: var(--error-color, #d32f2f); }
        .count { display: flex; align-items: baseline; gap: 8px; margin: 6px 0 0; }
        .big { font-size: 44px; font-weight: 700; line-height: 1; letter-spacing: -1px;
               color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .unit { font-size: 15px; color: var(--secondary-text-color); }
        svg { width: 100%; height: auto; display: block; margin-top: 4px; }
        .rail-base { stroke: var(--divider-color, #bbb); stroke-width: 3; stroke-linecap: round; }
        .sleepers { stroke: var(--divider-color, #bbb); stroke-width: 9; stroke-dasharray: 2 11;
                    opacity: .55; }
        .rail-fill { stroke: var(--primary-color, #03a9f4); stroke-width: 3; stroke-linecap: round; }
        .stn { fill: var(--card-background-color, #fff); stroke: var(--primary-color, #03a9f4);
               stroke-width: 3; transition: fill .4s; }
        .stn.done { fill: var(--primary-color, #03a9f4); }
        .stn-label { font-size: 12px; font-weight: 600; fill: var(--primary-text-color);
                     text-anchor: middle; }
        .stn-time { font-size: 11px; fill: var(--secondary-text-color); text-anchor: middle; }
        .train { transition: transform 1s linear, opacity .4s; }
        .train.snap { transition: none; }
        .train-body { fill: var(--primary-color, #03a9f4); }
        .train-win { fill: var(--card-background-color, #fff); opacity: .92; }
        .train-wheel { fill: var(--primary-text-color); }
        .train-light { fill: #ffd54f; }
        .ph-not_left .train { opacity: .55; }
        .ph-scheduled .train { opacity: 0; }
        .ph-scheduled .rail-fill { opacity: 0; }
        .ph-not_left .stn.prev { animation: pulse 1.6s ease-in-out infinite; }
        @keyframes pulse { 50% { stroke-width: 6; } }
        .status { font-size: 14px; color: var(--primary-text-color); margin: 2px 0 10px; }
        .status .muted { color: var(--secondary-text-color); }
        .warn { font-size: 12px; color: var(--warning-color, #f57c00); margin-bottom: 6px; }
        .list { border-top: 1px solid var(--divider-color, #ddd); padding-top: 6px; }
        .row { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center;
               padding: 6px 0; font-size: 14px; color: var(--primary-text-color); }
        .row + .row { border-top: 1px solid color-mix(in srgb, var(--divider-color, #ddd) 50%, transparent); }
        .row .dep { font-weight: 600; font-variant-numeric: tabular-nums; }
        .row .arr { color: var(--secondary-text-color); font-weight: 400; }
        .row .eta { font-variant-numeric: tabular-nums; min-width: 52px; text-align: right; }
        .row .tag { font-size: 12px; min-width: 70px; text-align: right;
                    color: var(--secondary-text-color); }
        .row .tag.live { color: var(--success-color, #43a047); font-weight: 600; }
        .row .tag.bad { color: var(--error-color, #d32f2f); font-weight: 600; }
        .foot { font-size: 11px; color: var(--secondary-text-color); margin-top: 8px; }
        .foot .fresh { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; }
        .foot .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success-color, #43a047); }
        .foot .fresh.old { color: var(--warning-color, #f57c00); }
        .foot .fresh.old .dot { background: var(--warning-color, #f57c00); }
        .foot .fresh.none .dot { background: var(--disabled-text-color, #9e9e9e); }
        .empty { padding: 18px 0; text-align: center; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="head">
          <div class="title" id="title"></div>
          <div class="chip" id="chip"></div>
        </div>
        <div id="body"></div>
      </ha-card>`;
    this._body = this._root.getElementById("body");
    this._built = null;
  }

  // Build the hero (graphic) markup once; later ticks only move things.
  _ensureHero() {
    if (this._built === "hero") return;
    this._body.innerHTML = `
      <div id="hero">
        <div class="count"><span class="big" id="big"></span><span class="unit" id="unit"></span></div>
        <svg id="svg" viewBox="0 0 400 110" role="img" aria-label="Train progress to Ballan">
          <line class="rail-base" x1="${X0}" y1="${RAIL_Y}" x2="${X1}" y2="${RAIL_Y}"/>
          <line class="sleepers" x1="${X0}" y1="${RAIL_Y + 1}" x2="${X1}" y2="${RAIL_Y + 1}"/>
          <line class="rail-fill" id="fill" x1="${X0}" y1="${RAIL_Y}" x2="${X0}" y2="${RAIL_Y}"/>
          <circle class="stn prev" id="stn-prev" cx="${X0}" cy="${RAIL_Y}" r="8"/>
          <circle class="stn" id="stn-ballan" cx="${X1}" cy="${RAIL_Y}" r="8"/>
          <text class="stn-label" id="lbl-prev" x="${X0}" y="92"></text>
          <text class="stn-time" id="time-prev" x="${X0}" y="106"></text>
          <text class="stn-label" id="lbl-ballan" x="${X1}" y="92">Ballan</text>
          <text class="stn-time" id="time-ballan" x="${X1}" y="106"></text>
          <g class="train snap" id="train" style="transform: translate(${X0 - 44}px, 0px)">
            <rect class="train-body" x="-34" y="32" width="31" height="21" rx="5"/>
            <path class="train-body" d="M0 53 V35 Q0 31 4 31 H14 L28 43 V53 Z"/>
            <rect class="train-body" x="-4" y="46" width="5" height="3"/>
            <rect class="train-win" x="-30" y="36" width="7" height="7" rx="2"/>
            <rect class="train-win" x="-20" y="36" width="7" height="7" rx="2"/>
            <rect class="train-win" x="-10" y="36" width="5" height="7" rx="2"/>
            <rect class="train-win" x="4" y="35" width="7" height="8" rx="2"/>
            <path class="train-win" d="M14 35 L23 43 H14 Z"/>
            <circle class="train-light" cx="26" cy="49" r="2"/>
            <circle class="train-wheel" cx="-24" cy="57" r="3.6"/>
            <circle class="train-wheel" cx="-11" cy="57" r="3.6"/>
            <circle class="train-wheel" cx="7" cy="57" r="3.6"/>
            <circle class="train-wheel" cx="20" cy="57" r="3.6"/>
          </g>
        </svg>
        <div class="status" id="status"></div>
        <div class="warn" id="warn" hidden></div>
      </div>
      <div class="list" id="list"></div>
      <div class="foot"><span class="fresh" id="fresh"><span class="dot"></span><span id="fresh-text"></span></span>
        · Platform numbers aren't published for V/Line trains. Check the station display.</div>`;
    this._el = {};
    for (const id of ["hero", "big", "unit", "fill", "stn-prev", "stn-ballan", "lbl-prev",
      "time-prev", "time-ballan", "train", "status", "warn", "list", "svg", "fresh", "fresh-text"]) {
      this._el[id] = this._root.getElementById(id);
    }
    this._built = "hero";
    this._firstPaint = true;
  }

  // ----------------------------------------------------------------- state
  _ingest() {
    if (!this._hass || !this._config) return;
    const st = this._hass.states[this._config.entity];
    this._st = st;
    if (!st) return;
    // Anchor the animation each time the app publishes fresh data.
    const a = st.attributes || {};
    const sig = [st.last_updated, a.last_realtime_update, a.last_vehicle_update].join("|");
    if (sig !== this._key) {
      this._key = sig;
      this._hero = pickHero(st.attributes.services);
      if (this._hero) {
        this._anchor = { t0: Date.now(), pct: Number(this._hero.progress_pct || 0) };
      }
    }
  }

  _update() {
    if (!this._root || !this._config) return;
    const titleEl = this._root.getElementById("title");
    const chip = this._root.getElementById("chip");
    const st = this._st;
    const attrs = st ? st.attributes : {};
    titleEl.textContent = this._config.title || attrs.friendly_name || this._config.entity;

    if (!st || st.state === "unavailable") {
      this._built = null;
      this._body.innerHTML = `<div class="empty">${st ? "Sensor unavailable" :
        "Entity not found: " + esc(this._config.entity) + ". Is the AppDaemon app running?"}</div>`;
      chip.textContent = "";
      chip.className = "chip";
      return;
    }

    const services = attrs.services || [];
    const hero = this._hero;
    if (!hero) {
      this._built = null;
      const legacy = services.length && !services.some((s) => s.ballan_arrival);
      this._body.innerHTML = `<div class="empty">${legacy
        ? "Trains found, but the app isn't sending Ballan data. Update vline_core.py and vline_trains.py, then check the AppDaemon log."
        : "No trains in the next 12 hours"}</div>`;
      chip.textContent = "";
      chip.className = "chip";
      return;
    }

    this._ensureHero();
    const now = Date.now();
    const phase = hero.phase || "scheduled";
    const arrMs = Date.parse(hero.ballan_arrival);
    const prev = hero.previous_stop || "Previous stop";

    // Position along the track (0-100), extrapolated between 45 s updates.
    let pct = null;
    if (phase === "at_station") pct = 100;
    else if (phase === "left") {
      const a = this._anchor;
      const remaining = arrMs - a.t0;
      pct = remaining > 0
        ? a.pct + (100 - a.pct) * Math.min(1, Math.max(0, (now - a.t0) / remaining))
        : 100;
    } else if (phase === "not_left") pct = 0;

    const root = this._el.hero;
    root.className = "ph-" + phase;
    const span = X1 - STOP - X0;
    let x = X0 - 44;
    if (pct !== null && phase !== "not_left") x = X0 + (span * pct) / 100;
    this._el.train.style.transform = `translate(${x}px, 0px)`;
    this._el.fill.setAttribute("x2",
      String(phase === "at_station" ? X1 : Math.max(X0, Math.min(X1, x))));
    this._el["stn-prev"].classList.toggle("done", phase === "left" || phase === "at_station");
    this._el["stn-ballan"].classList.toggle("done", phase === "at_station");
    if (this._firstPaint) {
      // let the first position apply without sliding in from the corner
      requestAnimationFrame(() => requestAnimationFrame(() => this._el.train.classList.remove("snap")));
      this._firstPaint = false;
    }

    // Counter
    const ms = arrMs - now;
    if (phase === "at_station" || ms <= 0) {
      this._el.big.textContent = "Now";
      this._el.unit.textContent = "at Ballan";
    } else if (ms < 60000) {
      this._el.big.textContent = "<1";
      this._el.unit.textContent = "min to Ballan";
    } else {
      this._el.big.textContent = String(Math.ceil(ms / 60000));
      this._el.unit.textContent = "min to Ballan";
    }

    // Labels
    this._el["lbl-prev"].textContent = prev;
    this._el["time-prev"].textContent = fmtTime(hero.previous_departure);
    this._el["time-ballan"].textContent = fmtTime(hero.ballan_arrival);

    // Status line
    const pdt = fmtTime(hero.previous_departure);
    let status = "";
    if (phase === "left") status = `✅ <b>Left ${esc(prev)}</b>${pdt ? ` at ${pdt}` : ""}`;
    else if (phase === "not_left") status = `⏳ <b>Not yet left ${esc(prev)}</b>${pdt ? ` (due ${pdt})` : ""}`;
    else if (phase === "at_station") status = `📍 <b>At Ballan</b>`;
    else status = `<span class="muted">🕐 Timetable only, no live position</span>`;
    this._el.status.innerHTML = status;

    // Warning when the live feed is stale
    const stale = truthy(attrs.stale);
    this._el.warn.hidden = !stale;
    this._el.warn.textContent = stale ? "Live data unavailable, showing timetable" : "";

    // Delay chip
    const delay = Number(hero.ballan_delay_min || 0);
    if (phase === "scheduled") {
      chip.textContent = "Timetable";
      chip.className = "chip";
    } else if (delay > 0) {
      chip.textContent = `${delay} min late`;
      chip.className = "chip late";
    } else if (delay < 0) {
      chip.textContent = `${-delay} min early`;
      chip.className = "chip ok";
    } else {
      chip.textContent = "On time";
      chip.className = "chip ok";
    }

    // How fresh is the live data?
    const lr = Date.parse(attrs.last_realtime_update);
    const fresh = this._el.fresh;
    if (isNaN(lr) || stale) {
      fresh.className = "fresh none";
      this._el["fresh-text"].textContent = "Timetable only";
    } else {
      const age = Math.max(0, Math.round((now - lr) / 1000));
      fresh.className = "fresh" + (age > 150 ? " old" : "");
      this._el["fresh-text"].textContent = age < 5 ? "Live, just now"
        : age < 90 ? `Live, ${age}s ago` : `Live, ${Math.round(age / 60)} min ago`;
    }

    // Upcoming list (rebuilt only when its text changes)
    const rows = services.slice(0, Number(this._config.max_rows)).map((s) => {
      const cancelled = s.status === "cancelled";
      const wa = Date.parse(s.ballan_arrival);
      let eta = "";
      if (!cancelled && !isNaN(wa)) {
        const m = Math.max(0, Math.ceil((wa - now) / 60000));
        eta = m === 0 ? "now" : `${m} min`;
      }
      const d = Number(s.departure_delay_min || 0);
      const live = truthy(s.realtime);
      const tag = cancelled ? `<span class="tag bad">Cancelled</span>`
        : `<span class="tag ${live ? "live" : ""}">${live ? "Live" : "Timetable"}${live && d ? ` (${d > 0 ? "+" : ""}${d})` : ""}</span>`;
      return `<div class="row"><div class="dep">${fmtTime(s.estimated_departure)}
        <span class="arr">→ ${fmtTime(s.estimated_arrival)}</span></div>
        <div class="eta">${eta}</div>${tag}</div>`;
    }).join("");
    if (rows !== this._rowsHtml) {
      this._el.list.innerHTML = rows;
      this._rowsHtml = rows;
    }
  }
}

if (!customElements.get("vline-train-card")) {
  customElements.define("vline-train-card", VLineTrainCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "vline-train-card",
  name: "V/Line train approaching",
  description: "Animated progress of the next V/Line train to Ballan, with a minutes counter.",
});
console.info(`%c VLINE-TRAIN-CARD %c v${VLINE_CARD_VERSION} `,
  "color:#fff;background:#8e24aa;font-weight:700", "color:#8e24aa");
