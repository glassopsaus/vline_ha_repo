/*
 * vline-journey-card  v1.0.0
 * Pick a departure and an arrival station; see the next direct V/Line services between them.
 * Choosing one station limits the other dropdown to stations with a direct service.
 *
 *   type: custom:vline-journey-card
 *   title: Journey planner            # optional
 *   from: Ballarat                    # optional starting choices
 *   to: Southern Cross
 *   rows: 4                           # services to list
 *   entity: sensor.vline_network      # optional: live delays come from its vehicles
 *   journeys_url: /local/vline_journeys.json
 */
const JC_VERSION = "1.0.0";
const TZN = "Australia/Melbourne";

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// "Now" as Melbourne wall-clock: {y, m, d, mins since today's midnight}
function melNow() {
  const parts = new Intl.DateTimeFormat("en-AU", { timeZone: TZN, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date());
  const g = (t) => Number((parts.find((p) => p.type === t) || {}).value);
  return { y: g("year"), m: g("month"), d: g("day"), mins: g("hour") * 60 + g("minute") };
}
function dayInfo(now, off) {          // date string + weekday (Mon=0) for today+off
  const dt = new Date(Date.UTC(now.y, now.m - 1, now.d + off));
  const ds = `${dt.getUTCFullYear()}${String(dt.getUTCMonth() + 1).padStart(2, "0")}${String(dt.getUTCDate()).padStart(2, "0")}`;
  return { ds, wd: (dt.getUTCDay() + 6) % 7 };
}
const runs = (svc, di) => !svc.r.includes(di.ds) && (svc.a.includes(di.ds) || (svc.s <= di.ds && di.ds <= svc.e && svc.d[di.wd]));
const hhmm = (abs) => { const m = ((abs % 1440) + 1440) % 1440; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; };
const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60 ? (m % 60) + " min" : ""}`.trim() : `${m} min`);

const STYLE = `
:host { display: block; }
ha-card { padding: 16px; overflow: hidden; }
.title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }
.pick { display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: end; }
label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); margin-bottom: 3px; }
select { width: 100%; box-sizing: border-box; font: inherit; font-size: 14px; padding: 9px 8px; border-radius: 10px; color: var(--primary-text-color);
  background: var(--secondary-background-color, rgba(127,127,127,.12)); border: 1px solid var(--divider-color, rgba(127,127,127,.35)); }
select:focus { outline: 2px solid var(--primary-color); outline-offset: 1px; }
button.swap { font: inherit; font-size: 16px; line-height: 1; padding: 9px 10px; border-radius: 10px; cursor: pointer; color: var(--primary-text-color);
  background: none; border: 1px solid var(--divider-color, rgba(127,127,127,.35)); }
button.swap:disabled { opacity: .35; cursor: default; }
.hint { margin: 6px 2px 0; font-size: 11px; color: var(--secondary-text-color); min-height: 14px; }
.list { margin-top: 10px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.3)); }
.svc { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; padding: 10px 0; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.2)); }
.svc:last-child { border-bottom: 0; }
.t { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
.t .arr { font-weight: 400; color: var(--secondary-text-color); font-size: 16px; }
.in { text-align: right; font-weight: 600; font-size: 15px; align-self: center; }
.sub { font-size: 12px; color: var(--secondary-text-color); }
.tag { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px; margin-left: 6px; vertical-align: 2px; }
.tag.late { background: rgba(245,124,0,.16); color: var(--warning-color, #f57c00); }
.tag.ok { background: rgba(67,160,71,.16); color: var(--success-color, #43a047); }
.empty { padding: 16px 0 4px; text-align: center; color: var(--secondary-text-color); font-size: 13px; }
.foot { margin-top: 8px; font-size: 11px; color: var(--secondary-text-color); }
`;

class VLineJourneyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null; this._err = null; this._loading = false;
    this._from = ""; this._to = ""; this._veh = [];
  }

  setConfig(config) {
    this._config = Object.assign({ title: "Journey planner", rows: 4, entity: "sensor.vline_network", journeys_url: "/local/vline_journeys.json" }, config || {});
    this._key = "vline-journey:" + (this._config.id || this._config.title) + ":" + (this._config.from || "") + ">" + (this._config.to || "");
    this._from = this._config.from || ""; this._to = this._config.to || "";
    try {
      const saved = JSON.parse(localStorage.getItem(this._key) || "null");
      if (saved) { this._from = saved.from || ""; this._to = saved.to || ""; }
    } catch (e) { /* storage unavailable: use the configured defaults */ }
    this._build();
    this._load();
  }

  getCardSize() { return 5; }
  static getStubConfig() { return { title: "Journey planner", from: "Ballarat", to: "Southern Cross" }; }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config && this._config.entity];
    this._veh = st && st.attributes && Array.isArray(st.attributes.vehicles) ? st.attributes.vehicles : [];
    if (this._data) this._renderList();
  }

  connectedCallback() { this._timer = setInterval(() => this._data && this._renderList(), 30000); }
  disconnectedCallback() { clearInterval(this._timer); }

  async _load() {
    if (this._data || this._loading || !this._config) return;
    this._loading = true;
    try {
      const r = await fetch(this._config.journeys_url + "?t=" + Math.floor(Date.now() / 3600000), { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      this._index(await r.json());
      this._err = null;
    } catch (e) {
      this._err = "Timetable not available yet (" + this._config.journeys_url + "). Check the AppDaemon log, then reload.";
      this._loading = false;
      this._renderAll();
      return;
    }
    this._loading = false;
    this._renderAll();
  }

  _index(data) {
    this._data = data;
    const n = data.stations.length;
    this._after = Array.from({ length: n }, () => new Set());
    this._before = Array.from({ length: n }, () => new Set());
    for (const t of data.trips) {
      const seq = t[3];
      for (let i = 0; i < seq.length; i++) for (let j = i + 1; j < seq.length; j++) {
        this._after[seq[i][0]].add(seq[j][0]);
        this._before[seq[j][0]].add(seq[i][0]);
      }
    }
    this._idx = new Map(data.stations.map((s, i) => [s.toLowerCase(), i]));
    const fix = (nm) => (this._idx.has(String(nm).toLowerCase()) ? data.stations[this._idx.get(String(nm).toLowerCase())] : "");
    this._from = fix(this._from); this._to = fix(this._to);
    this._reconcile();
  }

  // Drop a choice that is no longer reachable from the other one.
  _reconcile() {
    const f = this._idx.get(this._from.toLowerCase()), t = this._idx.get(this._to.toLowerCase());
    if (f !== undefined && t !== undefined && !this._after[f].has(t)) this._to = "";
  }

  _build() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>
      <div class="title" id="title"></div>
      <div class="pick">
        <div><label for="from">From</label><select id="from"></select></div>
        <button class="swap" id="swap" title="Swap" aria-label="Swap stations">\u21C4</button>
        <div><label for="to">To</label><select id="to"></select></div>
      </div>
      <div class="hint" id="hint"></div>
      <div id="list"></div>
      <div class="foot" id="foot"></div>
    </ha-card>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("title").textContent = this._config.title;
    $("from").addEventListener("change", (e) => { this._from = e.target.value; this._reconcile(); this._save(); this._renderAll(); });
    $("to").addEventListener("change", (e) => {
      this._to = e.target.value;
      const f = this._idx && this._idx.get(this._from.toLowerCase()), t = this._idx && this._idx.get(this._to.toLowerCase());
      if (f !== undefined && t !== undefined && !this._before[t].has(f)) this._from = "";
      this._save(); this._renderAll();
    });
    $("swap").addEventListener("click", () => {
      const a = this._from; this._from = this._to; this._to = a;
      this._reconcile(); this._save(); this._renderAll();
    });
    this._renderAll();
  }

  _save() { try { localStorage.setItem(this._key, JSON.stringify({ from: this._from, to: this._to })); } catch (e) { /* ignore */ } }

  _fill(sel, names, current, placeholder) {
    sel.innerHTML = `<option value="">${esc(placeholder)}</option>` + names.map((n) => `<option value="${esc(n)}"${n === current ? " selected" : ""}>${esc(n)}</option>`).join("");
    sel.value = names.includes(current) ? current : "";
  }

  _renderAll() {
    if (!this.shadowRoot.getElementById("from")) return;
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (!this._data) {
      $("hint").textContent = this._err || "Loading timetable\u2026";
      $("list").innerHTML = ""; $("foot").textContent = "";
      return;
    }
    const names = this._data.stations, alpha = (ids) => ids.map((i) => names[i]).sort((a, b) => a.localeCompare(b));
    const f = this._idx.get(this._from.toLowerCase()), t = this._idx.get(this._to.toLowerCase());
    const fromList = t !== undefined ? alpha([...this._before[t]]) : alpha(names.map((_n, i) => i).filter((i) => this._after[i].size));
    const toList = f !== undefined ? alpha([...this._after[f]]) : alpha(names.map((_n, i) => i).filter((i) => this._before[i].size));
    this._fill($("from"), fromList, this._from, "Choose departure station");
    this._fill($("to"), toList, this._to, "Choose arrival station");
    $("swap").disabled = f === undefined || t === undefined || !this._before[f].has(t);
    $("hint").textContent = f !== undefined && t === undefined ? `${toList.length} stations have a direct service from ${this._from}`
      : t !== undefined && f === undefined ? `${fromList.length} stations have a direct service to ${this._to}` : "";
    this._renderList();
  }

  _delayFor(trip, depAbs, nowMins) {
    const no = (/(\d+)$/.exec(trip[0]) || [])[1];
    if (Math.abs(depAbs - nowMins) > 360) return null;
    const v = this._veh.find((x) => x.id === trip[0]) || (no && this._veh.find((x) => String(x.no) === no));
    return v && v.delay_min !== null && v.delay_min !== undefined ? Number(v.delay_min) : null;
  }

  _renderList() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (!this._data || !$("list")) return;
    const f = this._idx.get(this._from.toLowerCase()), t = this._idx.get(this._to.toLowerCase());
    if (f === undefined || t === undefined) {
      $("list").innerHTML = `<div class="empty">Choose a departure and an arrival station</div>`;
      $("foot").textContent = "";
      return;
    }
    const now = melNow(), rows = [];
    const first = this._data.from, last = this._data.to;
    for (let off = -1; off <= 1; off++) {
      const di = dayInfo(now, off);
      if (di.ds < first || di.ds > last) continue;
      for (const trip of this._data.trips) {
        const svc = this._data.services[trip[2]];
        if (!runs(svc, di)) continue;
        const seq = trip[3];
        const i = seq.findIndex((c) => c[0] === f);
        if (i < 0) continue;
        const j = seq.findIndex((c, k) => k > i && c[0] === t);
        if (j < 0) continue;
        const dep = off * 1440 + (seq[i][2] !== undefined ? seq[i][2] : seq[i][1]);
        const arr = off * 1440 + seq[j][1];
        const delay = this._delayFor(trip, dep, now.mins);
        const eff = dep + (delay > 0 ? delay : 0);
        if (eff < now.mins - 1) continue;
        rows.push({ trip, dep, arr, delay, eff });
      }
    }
    rows.sort((a, b) => a.eff - b.eff);
    const shown = rows.slice(0, Number(this._config.rows) || 4);
    if (!shown.length) {
      $("list").innerHTML = `<div class="empty">No direct services found for the next day or so</div>`;
    } else {
      $("list").innerHTML = `<div class="list">${shown.map((r) => {
        const mins = r.eff - now.mins;
        const inTxt = mins <= 0 ? "Now" : mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`;
        const tag = r.delay === null ? "" : r.delay >= 1 ? `<span class="tag late">+${r.delay} min</span>` : `<span class="tag ok">on time</span>`;
        const day = r.dep >= 1440 ? " (next day)" : r.dep < 0 ? " (yesterday)" : "";
        return `<div class="svc"><div class="t">${hhmm(r.dep)}<span class="arr"> \u2192 ${hhmm(r.arr)}</span>${tag}</div><div class="in">${inTxt}</div>
          <div class="sub">${dur(r.arr - r.dep)}${r.trip[1] ? " \u00B7 to " + esc(r.trip[1]) : ""}${day}</div></div>`;
      }).join("")}</div>`;
    }
    const live = this._veh.length ? " \u00B7 live delays where a train is running" : "";
    $("foot").textContent = "Direct services only" + live;
  }
}

if (!customElements.get("vline-journey-card")) customElements.define("vline-journey-card", VLineJourneyCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "vline-journey-card")) {
  window.customCards.push({ type: "vline-journey-card", name: "V/Line journey planner",
    description: "Pick two stations and see the next direct V/Line services (v" + JC_VERSION + ")" });
}
