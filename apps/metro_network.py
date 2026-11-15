"""AppDaemon app: live Metro Trains network for the Victorian network map card.

Publishes sensor.metro_network (same shape as sensor.vline_network) and writes the line geometry to
/homeassistant/www/vic_metro_network.json. Uses the same Open Data API key as the V/Line app.
Sensor attribute `diag` explains what was matched, because the metro feed format could not be tested offline.
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

import metro_net
import vline_core as core
import vline_fetch as fetch
import vline_network as vnet

BASE = ("https://api.opendata.transport.vic.gov.au/opendata/"
        "public-transport/gtfs/realtime/v1/metro")
PTV_BASE = "https://timetableapi.ptv.vic.gov.au"
FRESH_SECONDS = 20 * 3600


class MetroNetwork(hass.Hass):
    def initialize(self):
        a = self.args
        self.api_key = a["api_key"]
        self.poll_seconds = max(int(a.get("poll_seconds", 30)), 30)
        self.static_url = a.get("static_gtfs_url")
        self.static_path = a.get("static_gtfs_path", "/config/gtfs_metro_train.zip")
        self.net_json_path = a.get("network_json_path", "/homeassistant/www/vic_metro_network.json")
        self.net_cache_path = a.get("network_cache_path", "/config/metro_network_cache.json")
        self.entity = a.get("entity", "sensor.metro_network")
        self.update_time = str(a.get("timetable_update_time", "03:45:00"))
        self.ptv_devid = str(a.get("ptv_devid") or "").strip()
        self.ptv_key = str(a.get("ptv_key") or "").strip()
        self.ptv_poll_seconds = max(int(a.get("ptv_poll_seconds", 900)), 300)
        self.thresholds = a.get("status_thresholds") or {}
        self.net, self.net_version = None, "0"
        self.rt, self.vehicles = {}, {}
        self.last_rt_ok = self.last_veh_ok = None
        self.notices, self.ptv_ok, self.ptv_error, self._ptv_tried = {}, None, None, -1e9
        self._refreshing, self._n = False, 0
        self.run_in(self._refresh_cb, 2, force=False)
        self.run_daily(self._refresh_cb, self.update_time, force=True)
        self.run_every(self.poll, "now+15", self.poll_seconds)
        if self.ptv_devid and self.ptv_key:
            self.run_every(self._ptv_poll, "now+30", self.ptv_poll_seconds)

    # ------------------------------------------------------------ timetable
    def _refresh_cb(self, kwargs):
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, args=(bool((kwargs or {}).get("force", True)),), daemon=True).start()

    def _fresh(self):
        try:
            return time.time() - os.path.getmtime(self.static_path) < FRESH_SECONDS
        except OSError:
            return False

    def _refresh(self, force):
        try:
            data = None
            if self.static_url and (force or not self._fresh()):
                try:
                    tmp = os.path.join(os.path.dirname(self.static_path) or ".", "metro_tmp")
                    os.makedirs(tmp, exist_ok=True)
                    data, _meta = fetch.download_regional(self.static_url, tmp, None, folder="2")
                    self.log(f"Downloaded metro timetable ({len(data) // 1024} KB)")
                    self._write(self.static_path, data)
                except Exception as exc:
                    self.error(f"Metro timetable download failed, using the saved copy: {exc!r}")
                    data = None
            if data is None:
                if not os.path.exists(self.static_path):
                    raise RuntimeError(f"No metro timetable: set static_gtfs_url (or put the Metro Train GTFS zip at {self.static_path})")
                with open(self.static_path, "rb") as fh:
                    data = fh.read()
            zf = zipfile.ZipFile(io.BytesIO(data))
            if any(n.endswith(".zip") for n in zf.namelist()) and "routes.txt" not in zf.namelist():
                zf = zipfile.ZipFile(io.BytesIO(fetch.extract_regional(zf, "2")))
            net = metro_net.build_light_network(zf)
            self._publish(net)
        except Exception as exc:
            self.error(f"Metro network build failed: {exc!r}")
            if self.net is None and os.path.exists(self.net_cache_path):
                try:
                    with open(self.net_cache_path) as fh:
                        self.net = json.load(fh)
                    self.net_version = str(self.net.get("version", "0"))
                    self.log("Loaded cached metro network")
                except Exception as exc2:
                    self.error(f"Cached metro network unreadable: {exc2!r}")
        finally:
            self._refreshing = False

    @staticmethod
    def _write(path, data):
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def _publish(self, net):
        geo = {"lines": net["lines"], "has_shapes": net["has_shapes"]}
        blob = json.dumps(geo, separators=(",", ":"))
        net["version"] = hashlib.sha1(blob.encode()).hexdigest()[:10]
        geo["version"] = net["version"]
        try:
            os.makedirs(os.path.dirname(self.net_json_path) or ".", exist_ok=True)
            self._write(self.net_json_path, json.dumps(geo, separators=(",", ":")).encode())
        except OSError as exc:
            self.error(f"Could not write {self.net_json_path}: {exc}")
        self._write(self.net_cache_path, json.dumps(net, separators=(",", ":")).encode())
        self.net, self.net_version = net, net["version"]
        self.log(f"Metro network ready: {len(net['lines'])} lines, {len(net['trip_route'])} trips")

    # ---------------------------------------------------------------- PTV
    def _ptv_poll(self, kwargs):
        if not self.net:
            return
        self._ptv_tried = time.monotonic()
        try:
            url = vnet.ptv_signed_url(PTV_BASE, "/v3/disruptions?route_types=0", self.ptv_devid, self.ptv_key)
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            self.notices = vnet.parse_ptv_disruptions(r.json(), [ln["id"] for ln in self.net["lines"]],
                                                      route_type=0, group="metro_train")
            first = self.ptv_ok is None
            self.ptv_ok, self.ptv_error = datetime.now(core.TZ), None
            if first:
                n = sum(1 for v in self.notices.values() for x in v if x["kind"])
                self.log(f"PTV metro notices working: {n} active notice(s)")
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            self.ptv_error = f"HTTP {code}" if code else type(exc).__name__
            self.error(f"PTV metro notices fetch failed: {exc}")

    # ------------------------------------------------------------ realtime
    def _fetch(self, endpoint):
        r = requests.get(f"{BASE}/{endpoint}", headers={"KeyId": self.api_key}, timeout=25)
        r.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(r.content)
        return feed

    def poll(self, kwargs):
        if not self.net:
            return
        try:
            self.rt = core.feed_to_dict(self._fetch("trip-updates"))
            self.last_rt_ok = datetime.now(core.TZ)
        except Exception as exc:
            self.error(f"Metro trip-updates fetch failed: {exc}")
        try:
            self.vehicles = core.feed_to_vehicles(self._fetch("vehicle-positions"))
            self.last_veh_ok = datetime.now(core.TZ)
        except Exception as exc:
            self.error(f"Metro vehicle-positions fetch failed: {exc}")
        now = datetime.now(core.TZ)
        limit = 5 * self.poll_seconds
        stale = self.last_rt_ok is None or (now - self.last_rt_ok).total_seconds() > limit
        veh_stale = self.last_veh_ok is None or (now - self.last_veh_ok).total_seconds() > limit
        net = self.net
        rt = {} if stale else self.rt
        vehicles = [] if veh_stale else vnet.build_vehicles(net, rt, self.vehicles, now)
        stats = vnet.line_stats(net, rt, now)
        ptv_fresh = self.ptv_ok is not None and (now - self.ptv_ok).total_seconds() < 3 * self.ptv_poll_seconds
        statuses = vnet.line_statuses(net, stats, self.notices if ptv_fresh else {}, not stale, self.thresholds)
        worst = max((s["level"] for s in statuses), key=lambda l: vnet.LEVELS[l], default="ok")
        known = sum(1 for t in self.rt if t in net["trip_route"])
        diag = (f"{len(self.rt)} trip updates ({known} in timetable), {len(self.vehicles)} vehicles, "
                f"{len(vehicles)} drawn")
        self._n += 1
        if self._n <= 2 or self._n % 25 == 1:
            self.log("Metro feed: " + diag)
            if self.rt and not known:
                self.log("Sample live metro trip IDs: " + ", ".join(list(self.rt)[:4])
                         + " | sample route_ids: " + ", ".join(sorted({str(v.get('route_id')) for v in self.rt.values()})[:4])
                         + " | timetable: " + ", ".join(list(net["trip_route"])[:3]))
        self.set_state(self.entity, state=str(len(vehicles)), attributes={
            "friendly_name": "Metro trains network", "icon": "mdi:train", "unit_of_measurement": "trains",
            "geometry_version": self.net_version, "worst_level": worst,
            "vehicles": vehicles, "lines": statuses, "stale": stale, "vehicles_stale": veh_stale,
            "ptv_enabled": bool(self.ptv_devid and self.ptv_key), "ptv_ok": ptv_fresh, "ptv_error": self.ptv_error,
            "updated": now.isoformat(), "diag": diag})
