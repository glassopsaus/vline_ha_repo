"""AppDaemon app: live V/Line departures, arrivals and train positions for Home Assistant.

Reads the V/Line GTFS-Realtime trip-updates and vehicle-positions feeds plus the
static regional-train timetable. For each configured route it publishes:

  sensor.vline_<id>        next departure (timestamp) + `services` attribute list
  sensor.vline_<id>_train  position of the next live train (latitude/longitude
                           attributes, so it shows on a Map card)

and for the network map card:

  sensor.vline_network     every live train + an overall status for every line
  /homeassistant/www/vline_network.json   line paths and stations (rewritten when the
                           timetable changes; served as /local/vline_network.json)

Optional `ptv_devid` / `ptv_key` add PTV disruption notices to the line statuses.

The static timetable refreshes itself: daily at `timetable_update_time`, and
immediately if the live feed's trip IDs stop matching it.

Platform numbers are NOT published for V/Line trains, so `platform` is always null.
"""
import hashlib
import io
import json
import os
import threading
import time
import zipfile
from datetime import datetime

import appdaemon.plugins.hass.hassapi as hass
import requests
from google.transit import gtfs_realtime_pb2

import vline_core as core
import vline_journeys as journeys
import vline_fetch as fetch
import vline_network as vnet

PTV_BASE = "https://timetableapi.ptv.vic.gov.au"
BASE = ("https://api.opendata.transport.vic.gov.au/opendata/"
        "public-transport/gtfs/realtime/v1/vline")

FRESH_SECONDS = 20 * 3600      # on startup, skip the download if the saved copy is newer
HEAL_COOLDOWN = 6 * 3600       # at most one mismatch-triggered refresh per 6 hours
HEAL_AFTER_POLLS = 8           # consecutive polls with zero matching trip IDs


class VLineTrains(hass.Hass):
    def initialize(self):
        self.api_key = self.args["api_key"]
        self.routes = self.args["routes"]  # [{id, name, from_name, to_name}]
        self.poll_seconds = max(int(self.args.get("poll_seconds", 45)), 30)
        self.static_url = self.args.get("static_gtfs_url")
        self.static_path = self.args.get("static_gtfs_path", "/config/gtfs_regional_train.zip")
        self.cache_path = self.args.get("cache_path", "/config/vline_timetable.json")
        self.meta_path = self.cache_path + ".meta"
        self.update_time = str(self.args.get("timetable_update_time", "03:30:00"))
        self.auto_heal = bool(self.args.get("auto_refresh_on_mismatch", True))
        self.watch_stop = self.args.get("watch_stop", "Ballan")
        self.limit = int(self.args.get("services_per_route", 4))
        self.net_json_path = self.args.get("network_json_path", "/homeassistant/www/vline_network.json")
        self.net_cache_path = self.args.get("network_cache_path", "/config/vline_network_cache.json")
        self.journeys_json_path = self.args.get("journeys_json_path", "/homeassistant/www/vline_journeys.json")
        self.ptv_devid = str(self.args.get("ptv_devid") or "").strip()
        self.ptv_key = str(self.args.get("ptv_key") or "").strip()
        self.ptv_poll_seconds = max(int(self.args.get("ptv_poll_seconds", 900)), 300)
        self.thresholds = self.args.get("status_thresholds") or {}
        self.net = None
        self.alias_index = {}
        self.rt_m, self.veh_m, self.n_alias = {}, {}, 0
        self.net_version = "0"
        self.notices = {}
        self.ptv_ok = None
        self.ptv_error = None
        self._ptv_tried = -1e9
        self.timetable = None
        self.rt = {}
        self.vehicles = {}
        self.last_rt_ok = None
        self.last_veh_ok = None
        self._refreshing = False
        self._last_refresh = None
        self._mismatch_polls = 0
        self._poll_n = 0

        self.run_in(self._refresh_cb, 1, force=False)
        self.run_daily(self._refresh_cb, self.update_time, force=True)
        self.run_every(self.poll, "now+10", self.poll_seconds)
        if self.ptv_devid and self.ptv_key:
            self.run_every(self._ptv_poll, "now+20", self.ptv_poll_seconds)
        else:
            self.log("No ptv_devid/ptv_key set: network map uses live data only")

    # ------------------------------------------------------------- timetable
    def _refresh_cb(self, kwargs):
        self.refresh_timetable(force=bool((kwargs or {}).get("force", True)))

    def refresh_timetable(self, force=True):
        """Start a refresh in the background so polling is never blocked."""
        if self._refreshing:
            return
        self._refreshing = True
        self._last_refresh = time.monotonic()
        threading.Thread(target=self._refresh_worker, args=(force,), daemon=True).start()

    def _saved_copy_is_fresh(self):
        try:
            return time.time() - os.path.getmtime(self.static_path) < FRESH_SECONDS
        except OSError:
            return False

    def _load_meta(self):
        try:
            with open(self.meta_path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_atomic(path, data):
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def _refresh_worker(self, force):
        try:
            regional, downloaded, new_meta = None, False, None
            if self.static_url and (force or not self._saved_copy_is_fresh()):
                try:
                    self.log("Checking for a newer timetable...")
                    tmp_dir = os.path.dirname(self.static_path) or "."
                    regional, new_meta = fetch.download_regional(
                        self.static_url, tmp_dir, self._load_meta())
                    if regional is None:
                        self.log("Timetable is already up to date")
                        if self.timetable is not None:
                            self._journeys_from_saved()   # keep the journey planner's date window moving
                            return
                    else:
                        downloaded = True
                        self.log(f"Downloaded new timetable ({len(regional) // 1024} KB regional feed)")
                except Exception as exc:
                    self.error(f"Timetable download failed, using the saved copy: {exc}")
                    regional = None

            if regional is None:
                if not os.path.exists(self.static_path):
                    raise RuntimeError(
                        f"No timetable: download unavailable and {self.static_path} not found")
                with open(self.static_path, "rb") as fh:
                    regional = fh.read()

            zf = zipfile.ZipFile(io.BytesIO(regional))
            if "stops.txt" not in zf.namelist():  # a whole-of-Victoria bundle was supplied
                zf = zipfile.ZipFile(io.BytesIO(fetch.extract_regional(zf)))
            routes = [{"id": r["id"], "from_name": r["from_name"], "to_name": r["to_name"]}
                      for r in self.routes]
            new = core.build_timetable(zf, routes, watch_name=self.watch_stop)

            # Only a timetable that built successfully replaces anything on disk.
            if downloaded:
                self._write_atomic(self.static_path, regional)
                self._write_atomic(self.meta_path, json.dumps(new_meta or {}).encode())
            self._write_atomic(self.cache_path, json.dumps(new).encode())
            try:
                self._publish_network(vnet.build_network(zf))
            except Exception as exc:
                self.error(f"Network map build failed (route cards unaffected): {exc!r}")
            self._publish_journeys(zf)
            self.timetable = new
            self.log(f"Timetable ready: {len(new['trips'])} candidate trips")
        except Exception as exc:
            self.error(f"Timetable refresh failed: {exc}")
            if self.timetable is None and os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path) as fh:
                        self.timetable = json.load(fh)
                    self.log("Loaded cached timetable")
                    if self.net is None and os.path.exists(self.net_cache_path):
                        with open(self.net_cache_path) as fh:
                            self.net = json.load(fh)
                        self.net_version = str(self.net.get("version", "0"))
                except Exception as exc2:
                    self.error(f"Cached timetable unreadable: {exc2}")
        finally:
            self._refreshing = False

    def _publish_journeys(self, zf):
        """All-stations timetable for the journey-planner card; never allowed to break the route cards."""
        try:
            data = journeys.build_journeys(zf, datetime.now(core.TZ).date())
            os.makedirs(os.path.dirname(self.journeys_json_path) or ".", exist_ok=True)
            self._write_atomic(self.journeys_json_path, json.dumps(data, separators=(",", ":")).encode())
            self.log(f"Journey planner timetable ready: {len(data['stations'])} stations, {len(data['trips'])} trips")
        except Exception as exc:
            self.error(f"Journey planner timetable failed (other cards unaffected): {exc!r}")

    def _journeys_from_saved(self):
        try:
            with open(self.static_path, "rb") as fh:
                zf = zipfile.ZipFile(io.BytesIO(fh.read()))
            if "stops.txt" not in zf.namelist():
                zf = zipfile.ZipFile(io.BytesIO(fetch.extract_regional(zf)))
            self._publish_journeys(zf)
        except Exception as exc:
            self.error(f"Journey planner refresh failed: {exc!r}")

    def _publish_network(self, net):
        geometry = {"lines": net["lines"], "has_shapes": net["has_shapes"]}
        blob = json.dumps(geometry, separators=(",", ":"))
        net["version"] = hashlib.sha1(blob.encode()).hexdigest()[:10]
        geometry["version"] = net["version"]
        try:
            os.makedirs(os.path.dirname(self.net_json_path) or ".", exist_ok=True)
            self._write_atomic(self.net_json_path, json.dumps(geometry, separators=(",", ":")).encode())
        except OSError as exc:
            self.error(f"Could not write the map shape to {self.net_json_path}: {exc}. "
                       "The map card cannot load it until network_json_path points at "
                       "Home Assistant's www folder (usually /homeassistant/www/vline_network.json).")
        self._write_atomic(self.net_cache_path, json.dumps(net, separators=(",", ":")).encode())
        self.net = net
        self.alias_index = vnet.build_alias_index(net["sched"])
        self.net_version = net["version"]
        self.log(f"Network map ready: {len(net['lines'])} lines, {len(net['sched'])} trips"
                 f"{'' if net['has_shapes'] else ' (no shapes.txt: lines drawn station to station)'}")

    # ------------------------------------------------------------------- PTV
    def _ptv_poll(self, kwargs):
        if not self.net:
            return
        self._ptv_tried = time.monotonic()
        try:
            url = vnet.ptv_signed_url(PTV_BASE, "/v3/disruptions?route_types=3",
                                      self.ptv_devid, self.ptv_key)
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            self.notices = vnet.parse_ptv_disruptions(
                r.json(), [ln["id"] for ln in self.net["lines"]])
            first = self.ptv_ok is None
            self.ptv_ok = datetime.now(core.TZ)
            self.ptv_error = None
            if first:
                n = sum(1 for v in self.notices.values() for x in v if x["kind"])
                self.log(f"PTV notices working: {n} active notice(s) on V/Line lines")
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            self.ptv_error = f"HTTP {code}" if code else type(exc).__name__
            self.error(f"PTV notices fetch failed (keeping the last ones): {exc}")

    def _publish_network_state(self, now, stale, veh_stale):
        if not self.net:
            return
        live_ok = not stale
        rt = {} if stale else self.rt_m
        vehicles = [] if veh_stale else vnet.build_vehicles(self.net, rt, self.veh_m, now)
        stats = vnet.line_stats(self.net, rt, now)
        ptv_fresh = (self.ptv_ok is not None
                     and (now - self.ptv_ok).total_seconds() < 3 * self.ptv_poll_seconds)
        notices = self.notices if ptv_fresh else {}
        statuses = vnet.line_statuses(self.net, stats, notices, live_ok, self.thresholds)
        worst = max((s["level"] for s in statuses), key=lambda l: vnet.LEVELS[l], default="ok")
        self.set_state(
            "sensor.vline_network",
            state=str(len(vehicles)),
            attributes={
                "friendly_name": "V/Line network",
                "icon": "mdi:train",
                "unit_of_measurement": "trains",
                "geometry_version": self.net_version,
                "worst_level": worst,
                "vehicles": vehicles,
                "lines": statuses,
                "stale": stale,
                "vehicles_stale": veh_stale,
                "ptv_enabled": bool(self.ptv_devid and self.ptv_key),
                "ptv_ok": ptv_fresh,
                "ptv_error": self.ptv_error,
                "updated": now.isoformat(),
            })

    # -------------------------------------------------------------- realtime
    def _fetch(self, endpoint):
        r = requests.get(f"{BASE}/{endpoint}", headers={"KeyId": self.api_key}, timeout=20)
        r.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(r.content)
        return feed

    def poll(self, kwargs):
        if self.timetable is None:
            return
        # The two feeds fail independently; keep the last good data for each.
        try:
            self.rt = core.feed_to_dict(self._fetch("trip-updates"))
            self.last_rt_ok = datetime.now(core.TZ)
        except Exception as exc:
            self.error(f"Trip-updates fetch failed: {exc}")
        try:
            self.vehicles = core.feed_to_vehicles(self._fetch("vehicle-positions"))
            self.last_veh_ok = datetime.now(core.TZ)
        except Exception as exc:
            self.error(f"Vehicle-positions fetch failed: {exc}")

        now = datetime.now(core.TZ)
        # Live IDs that differ from the timetable's are matched by route + train number.
        sched = (self.net or {}).get("sched", {})
        try:
            self.rt_m, n1, mapping = vnet.remap_live(self.rt, sched, self.alias_index, now,
                                                     runs_on=self._runs_on)
            self.veh_m, _n2, _m2 = vnet.remap_live(self.vehicles, sched, self.alias_index, now,
                                                   known=mapping, runs_on=self._runs_on)
            self.n_alias = n1
        except Exception as exc:
            self.error(f"Trip-number matching failed, using exact IDs only: {exc!r}")
            self.rt_m, self.veh_m, self.n_alias = self.rt, self.vehicles, 0
        limit_s = 5 * self.poll_seconds
        stale = (self.last_rt_ok is None
                 or (now - self.last_rt_ok).total_seconds() > limit_s)
        veh_stale = (self.last_veh_ok is None
                     or (now - self.last_veh_ok).total_seconds() > limit_s)
        vehicles = {} if veh_stale else self.veh_m

        # How many trip IDs in the live feed also exist in our static timetable?
        n_overlap = len(set(self.rt_m) & set(self.timetable["trips"]))
        overlap = str(n_overlap)
        self._poll_n += 1
        net_trips = (self.net or {}).get("sched", {})
        n_net = len(set(self.rt_m) & set(net_trips))
        n_veh = len(set(self.veh_m) & set(net_trips))
        if self._poll_n % 25 == 1 or (self._poll_n <= 3):
            self.log(f"Feed: {len(self.rt)} trip updates, {len(self.vehicles)} vehicles, "
                     f"{overlap} trip IDs match the timetable "
                     f"(realtime stale={stale}, vehicles stale={veh_stale})")
            self.log(f"Match check: {n_net} of {len(self.rt)} trip updates and {n_veh} of "
                     f"{len(self.vehicles)} vehicles match the whole-network timetable "
                     f"({self.n_alias} trip IDs matched by route + train number) "
                     f"({len(net_trips)} trips)")
            if self.rt and (n_net == 0 or n_overlap == 0):
                self.log("Sample live trip IDs: " + ", ".join(list(self.rt)[:5])
                         + " | sample timetable trip IDs: " + ", ".join(list(net_trips)[:5]))
                dates = sorted({str(v.get("start_date")) for v in self.rt.values()})[:4]
                self.log(f"Live start_dates: {dates}")
        self._maybe_heal(now, n_overlap, stale)

        if self._poll_n <= 2 or self._poll_n % 25 == 1:
            try:
                self._log_card_diag(now)
            except Exception as exc:
                self.error(f"Diagnostics failed: {exc!r}")
        # The scheduled PTV poll can fire before the network map is built; catch up here.
        if (self.ptv_devid and self.ptv_key and self.net and self.ptv_ok is None
                and time.monotonic() - self._ptv_tried > 60):
            self._ptv_poll({})
        try:
            self._publish_network_state(now, stale, veh_stale)
        except Exception as exc:
            self.error(f"Network map update failed (route cards unaffected): {exc!r}")

        for route in self.routes:
            try:
                services = core.compute_services(
                    self.timetable, {} if stale else self.rt_m, route["id"], now,
                    limit=self.limit, vehicles=vehicles)
            except Exception as exc:
                self.error(f"Could not compute services for {route['id']}: {exc!r}")
                continue
            if stale:
                for s in services:
                    if not s.get("vehicle"):
                        s["realtime"] = False
                        s["status"] = "scheduled (live data unavailable)"
            nxt = services[0] if services else None
            self.set_state(
                f"sensor.vline_{route['id']}",
                state=nxt["estimated_departure"] if nxt else "unknown",
                attributes={
                    "friendly_name": route["name"],
                    "device_class": "timestamp",
                    "icon": "mdi:train",
                    "services": services,
                    "platform_note": "Platform numbers are not published for V/Line trains",
                    "stale": stale,
                    "vehicles_stale": veh_stale,
                    # Diagnostics: strings, because Home Assistant drops zero values
                    "diag_feed_trip_updates": str(len(self.rt)),
                    "diag_feed_vehicles": str(len(self.vehicles)),
                    "diag_trip_id_overlap": overlap,
                    "diag_trip_ids_matched_by_number": str(self.n_alias),
                    "diag_feed_sample_trip_id": next(iter(self.rt), "none"),
                    "diag_timetable_sample_trip_id": next(iter(self.timetable["trips"]), "none"),
                    "last_realtime_update": (self.last_rt_ok.isoformat()
                                             if self.last_rt_ok else None),
                    "last_vehicle_update": (self.last_veh_ok.isoformat()
                                            if self.last_veh_ok else None),
                })

            # Map entity: the soonest service that has a reported position.
            live = next((s for s in services
                         if s.get("vehicle") and s["vehicle"].get("latitude") is not None
                         and s["status"] != "cancelled"), None)
            if live:
                v = live["vehicle"]
                self.set_state(
                    f"sensor.vline_{route['id']}_train",
                    state=v.get("status") or "tracking",
                    attributes={
                        "friendly_name": f"{route['name']} (train)",
                        "icon": "mdi:train-variant",
                        "latitude": v["latitude"],
                        "longitude": v["longitude"],
                        "bearing": v.get("bearing"),
                        "speed_kmh": v.get("speed_kmh"),
                        "reported_at": v.get("reported_at"),
                        "scheduled_departure": live["scheduled_departure"],
                        "estimated_arrival": live["estimated_arrival"],
                        "trip_id": live["trip_id"],
                    })
            else:
                self.set_state(
                    f"sensor.vline_{route['id']}_train",
                    state="no live train",
                    attributes={"friendly_name": f"{route['name']} (train)",
                                "icon": "mdi:train-variant"})

    def _runs_on(self, trip_id, sdate):
        """True unless the timetable knows this trip and says it doesn't run on that date."""
        tr = self.timetable["trips"].get(trip_id) if self.timetable else None
        if not tr:
            return True
        svc = self.timetable["services"].get(tr.get("service_id"))
        return True if not svc else core.service_runs_on(svc, sdate)

    def _log_card_diag(self, now):
        """Why a route card might show 'timetable only': compare live updates with the timetable."""
        matched = [t for t in self.rt_m if t in self.timetable["trips"]][:3]
        for t in matched:
            tr = self.timetable["trips"][t]
            ups = self.rt_m[t].get("updates") or []
            live = [(u.get("seq"), u.get("stop_id")) for u in ups[:4]]
            calls = {r: (c.get("from_seq"), c.get("from_stop"), c.get("to_seq"), c.get("to_stop"))
                     for r, c in tr["calls"].items()}
            w = tr.get("watch") or {}
            self.log(f"Card diag {t}: start_date={self.rt_m[t].get('start_date')} "
                     f"cancelled={self.rt_m[t].get('cancelled')} updates={len(ups)} first={live} "
                     f"| timetable calls={calls} ballan seq/stop={w.get('seq')}/{w.get('stop')} "
                     f"| vehicle={'yes' if t in self.veh_m else 'no'}")
        for route in self.routes:
            try:
                svcs = core.compute_services(self.timetable, self.rt_m, route["id"], now,
                                             limit=2, vehicles=self.veh_m)
            except Exception:
                continue
            for sv in svcs:
                tid = sv["trip_id"]
                m = vnet.ID_RE.match(tid)
                same = [k for k in list(self.rt) + list(self.vehicles)
                        if m and k.endswith("-" + m.group(5)) and k.startswith(tid[:6])]
                self.log(f"Card diag next {route['id']}: {tid} status={sv['status']} "
                         f"in_live={tid in self.rt_m} live ids with same number: {same[:4]}")
        if not matched:
            self.log("Card diag: no live trip matches a Ballan-route timetable trip right now")

    def _maybe_heal(self, now, n_overlap, stale):
        """Refresh the timetable if live trip IDs stop matching it (new timetable version)."""
        if not (self.auto_heal and self.static_url) or stale:
            return
        daytime = 6 <= now.hour < 22  # at night there may be no Ballarat-line trains at all
        if self.rt and n_overlap == 0 and daytime:
            self._mismatch_polls += 1
        else:
            self._mismatch_polls = 0
            return
        cooled = (self._last_refresh is None
                  or time.monotonic() - self._last_refresh > HEAL_COOLDOWN)
        if self._mismatch_polls >= HEAL_AFTER_POLLS and cooled and not self._refreshing:
            self.log("Live trip IDs don't match the timetable: checking for a newer one")
            self._mismatch_polls = 0
            self.refresh_timetable(force=True)
