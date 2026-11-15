"""Pure logic for the V/Line AppDaemon app (no AppDaemon / protobuf imports).

Kept separate so it can be tested without Home Assistant or the network.
"""
import csv
import io
import math
import zipfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")


def parse_gtfs_time(value, service_date):
    """GTFS times can exceed 24:00:00 (trip runs past midnight)."""
    h, m, s = (int(x) for x in value.strip().split(":"))
    base = datetime(service_date.year, service_date.month, service_date.day, tzinfo=TZ)
    # Add as a timedelta from local midnight so DST changes behave sensibly.
    return base + timedelta(hours=h, minutes=m, seconds=s)


# ---------------------------------------------------------------- static GTFS

def _rows(zf, name):
    with zf.open(name) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))


def resolve_stop_ids(zf, name_prefix):
    """All stop_ids for a station: the stop itself, platforms and children."""
    wanted = name_prefix.lower()
    ids, parents = set(), set()
    rows = list(_rows(zf, "stops.txt"))
    for r in rows:
        if r["stop_name"].lower().startswith(wanted):
            ids.add(r["stop_id"])
            if not r.get("parent_station"):
                parents.add(r["stop_id"])
    for r in rows:
        if r.get("parent_station") in parents:
            ids.add(r["stop_id"])
    return ids


def _clean_name(name):
    for suffix in (" (Melbourne City)", " Railway Station", " Station"):
        name = name.replace(suffix, "")
    return name.strip()


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_timetable(zf, routes, watch_name="Ballan"):
    """Trim the regional-train GTFS down to what the configured routes need.

    routes: list of dicts with keys id, from_name, to_name.
    Returns a JSON-serialisable dict that can be cached.
    """
    stops = {}
    for r in routes:
        stops[r["id"]] = (
            resolve_stop_ids(zf, r["from_name"]),
            resolve_stop_ids(zf, r["to_name"]),
        )
        if not stops[r["id"]][0] or not stops[r["id"]][1]:
            raise ValueError(f"Could not find stops for route {r['id']}")

    interesting = set().union(*[a | b for a, b in stops.values()])
    per_trip = {}
    for r in _rows(zf, "stop_times.txt"):
        if r["stop_id"] in interesting:
            per_trip.setdefault(r["trip_id"], []).append(
                (int(r["stop_sequence"]), r["stop_id"], r["arrival_time"], r["departure_time"])
            )

    candidates = {}  # trip_id -> {route_id: {...}}
    for trip_id, calls in per_trip.items():
        calls.sort()
        for route_id, (from_ids, to_ids) in stops.items():
            origin = next((c for c in calls if c[1] in from_ids), None)
            if not origin:
                continue
            dest = next((c for c in calls if c[1] in to_ids and c[0] > origin[0]), None)
            if not dest:
                continue
            candidates.setdefault(trip_id, {})[route_id] = {
                "from_seq": origin[0], "from_stop": origin[1], "dep": origin[3] or origin[2],
                "to_seq": dest[0], "to_stop": dest[1], "arr": dest[2] or dest[3],
            }

    trips = {}
    for r in _rows(zf, "trips.txt"):
        if r["trip_id"] in candidates:
            trips[r["trip_id"]] = {
                "service_id": r["service_id"],
                "headsign": r.get("trip_headsign", ""),
                "calls": candidates[r["trip_id"]],
            }

    # Watch stop (Ballan): remember the stop before it on every trip so the card can
    # show whether an inbound train has left the previous station.
    watch_ids = resolve_stop_ids(zf, watch_name)
    stop_info = {r["stop_id"]: (_clean_name(r["stop_name"]), _f(r.get("stop_lat")),
                                _f(r.get("stop_lon")))
                 for r in _rows(zf, "stops.txt")}
    full = {}
    for r in _rows(zf, "stop_times.txt"):
        if r["trip_id"] in trips:
            full.setdefault(r["trip_id"], []).append(
                (int(r["stop_sequence"]), r["stop_id"], r["arrival_time"], r["departure_time"]))
    for trip_id, calls in full.items():
        calls.sort()
        idx = next((i for i, c in enumerate(calls) if c[1] in watch_ids), None)
        if idx is None:
            continue
        seq, sid, arr, dep = calls[idx]
        _n, lat, lon = stop_info.get(sid, (watch_name, None, None))
        if not (arr or dep):
            continue
        w = {"seq": seq, "stop": sid, "arr": arr or dep, "dep": dep or arr, "lat": lat, "lon": lon}
        if idx > 0:
            pseq, psid, _parr, pdep = calls[idx - 1]
            pdep = pdep or _parr
            pname, plat, plon = stop_info.get(psid, (psid, None, None))
            w.update({"prev_seq": pseq, "prev_stop": psid, "prev_name": pname,
                      "prev_dep": pdep, "prev_lat": plat, "prev_lon": plon} if pdep else {})
        trips[trip_id]["watch"] = w

    services = {}
    names = zf.namelist()
    if "calendar.txt" in names:
        for r in _rows(zf, "calendar.txt"):
            services[r["service_id"]] = {
                "start": r["start_date"], "end": r["end_date"],
                "days": [r[d] == "1" for d in (
                    "monday", "tuesday", "wednesday", "thursday",
                    "friday", "saturday", "sunday")],
                "add": [], "remove": [],
            }
    if "calendar_dates.txt" in names:
        for r in _rows(zf, "calendar_dates.txt"):
            s = services.setdefault(r["service_id"], {
                "start": "99999999", "end": "00000000", "days": [False] * 7,
                "add": [], "remove": []})
            (s["add"] if r["exception_type"] == "1" else s["remove"]).append(r["date"])

    needed = {t["service_id"] for t in trips.values()}
    return {"trips": trips, "services": {k: v for k, v in services.items() if k in needed}}


def service_runs_on(service, d):
    ds = d.strftime("%Y%m%d")
    if ds in service["remove"]:
        return False
    if ds in service["add"]:
        return True
    return service["start"] <= ds <= service["end"] and service["days"][d.weekday()]


# ------------------------------------------------------- realtime application

def _event_time(ev):
    """Return (absolute_epoch or None, delay_seconds or None) from a stop-time event dict."""
    if not ev:
        return None, None
    return ev.get("time") or None, ev.get("delay") if "delay" in ev else None


def _estimate(updates, seq, stop_id, scheduled, kind):
    """Estimate arrival/departure at a stop from stop_time_updates.

    updates: list of dicts {seq, stop_id, skipped, arrival, departure}
    kind: 'arrival' or 'departure'
    Returns (estimated datetime, has_realtime, skipped)
    """
    exact = next((u for u in updates
                  if (u.get("stop_id") == stop_id) or (u.get("seq") == seq)), None)
    if exact:
        if exact.get("skipped"):
            return scheduled, True, True
        order = (kind, "departure" if kind == "arrival" else "arrival")
        for k in order:
            t, delay = _event_time(exact.get(k))
            if t:
                return datetime.fromtimestamp(t, TZ), True, False
            if delay is not None:
                return scheduled + timedelta(seconds=delay), True, False
    # No exact entry: propagate the delay of the closest earlier update.
    prior = [u for u in updates if u.get("seq") is not None and u["seq"] <= seq]
    if prior:
        last = max(prior, key=lambda u: u["seq"])
        for k in ("departure", "arrival"):
            ev = last.get(k)
            if not ev:
                continue
            if ev.get("delay") is not None:
                return scheduled + timedelta(seconds=ev["delay"]), True, False
            if ev.get("time"):
                # Absolute time only: derive the delay vs. that stop's schedule is
                # not possible without its timetable, so fall through.
                continue
    return scheduled, False, False


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(a))


def watch_info(w, ups, veh, sdate, now, live):
    """Progress of one trip towards the watch stop (Ballan).

    phase: scheduled (no live data) | not_left | left | at_station
    progress_pct: how far along previous stop -> Ballan (0-100).
    """
    sched_arr = parse_gtfs_time(w["arr"], sdate)
    est_arr, arr_rt, _ = _estimate(ups, w["seq"], w["stop"], sched_arr, "arrival")
    if abs(est_arr - sched_arr) > timedelta(hours=6):
        est_arr, arr_rt = sched_arr, False
    live = bool(live or arr_rt)
    info = {"ballan_arrival": est_arr.isoformat(),
            "ballan_delay_min": round((est_arr - sched_arr).total_seconds() / 60)}
    if "prev_seq" not in w:
        info["phase"] = "at_station" if (live and est_arr <= now) else "scheduled"
        return info

    sched_pdep = parse_gtfs_time(w["prev_dep"], sdate)
    est_pdep, _, _ = _estimate(ups, w["prev_seq"], w["prev_stop"], sched_pdep, "departure")
    if abs(est_pdep - sched_pdep) > timedelta(hours=6):
        est_pdep = sched_pdep
    info["previous_stop"] = w["prev_name"]
    info["previous_departure"] = est_pdep.isoformat()

    left, progress = None, 0
    coords = (w.get("lat"), w.get("lon"), w.get("prev_lat"), w.get("prev_lon"))
    if veh and veh.get("latitude") is not None and None not in coords:
        span = _km(w["prev_lat"], w["prev_lon"], w["lat"], w["lon"])
        d_w = _km(veh["latitude"], veh["longitude"], w["lat"], w["lon"])
        d_p = _km(veh["latitude"], veh["longitude"], w["prev_lat"], w["prev_lon"])
        if span > 0.5:
            left = d_w < span and d_p > 0.3
            if left:
                progress = max(0, min(100, round(100 * (1 - d_w / span))))
    if left is None:  # no usable position: fall back to times
        left = est_pdep <= now
        total = (est_arr - est_pdep).total_seconds()
        if left and total > 0:
            progress = max(0, min(100, round(100 * (now - est_pdep).total_seconds() / total)))

    if not live:
        info["phase"] = "scheduled"
    elif est_arr <= now:
        info["phase"] = "at_station"
    else:
        info["phase"] = "left" if left else "not_left"
        info["progress_pct"] = progress if left else 0
    return info


def compute_services(timetable, rt_by_trip, route_id, now, horizon_hours=12, limit=4, vehicles=None):
    """Build the next services for one route.

    rt_by_trip: {trip_id: {"cancelled": bool, "updates": [...]}}
    vehicles: {trip_id: {...}} from feed_to_vehicles (optional)
    """
    vehicles = vehicles or {}
    out = []
    for offset in (-1, 0, 1):  # yesterday catches trips running past midnight
        sdate = (now + timedelta(days=offset)).date()
        for trip_id, trip in timetable["trips"].items():
            call = trip["calls"].get(route_id)
            if not call:
                continue
            service = timetable["services"].get(trip["service_id"])
            if not service or not service_runs_on(service, sdate):
                continue
            sched_dep = parse_gtfs_time(call["dep"], sdate)
            sched_arr = parse_gtfs_time(call["arr"], sdate)
            rt = rt_by_trip.get(trip_id)
            # Trip IDs repeat day to day: only use live data for the matching run.
            if rt and rt.get("start_date") and rt["start_date"] != sdate.strftime("%Y%m%d"):
                rt = None
            cancelled = bool(rt and rt.get("cancelled"))
            est_dep, dep_rt, dep_skip = sched_dep, False, False
            est_arr, arr_rt, arr_skip = sched_arr, False, False
            if rt and not cancelled:
                ups = rt["updates"]
                est_dep, dep_rt, dep_skip = _estimate(
                    ups, call["from_seq"], call["from_stop"], sched_dep, "departure")
                est_arr, arr_rt, arr_skip = _estimate(
                    ups, call["to_seq"], call["to_stop"], sched_arr, "arrival")
            # Guard against mismatched data producing absurd estimates.
            if abs(est_dep - sched_dep) > timedelta(hours=6):
                est_dep, est_arr, dep_rt, arr_rt = sched_dep, sched_arr, False, False
            veh = vehicles.get(trip_id)
            if veh and veh.get("start_date") and veh["start_date"] != sdate.strftime("%Y%m%d"):
                veh = None
            watch = trip.get("watch")
            # When Ballan is the destination, keep the train listed until it arrives,
            # even though it has already left the origin.
            in_transit = bool(watch and watch["seq"] == call["to_seq"] and not cancelled
                              and est_arr >= now - timedelta(minutes=1))
            if est_dep < now - timedelta(minutes=1) and not in_transit:
                continue
            if est_dep > now + timedelta(hours=horizon_hours):
                continue
            winfo = {}
            if watch and not cancelled:
                try:
                    winfo = watch_info(watch, rt["updates"] if rt else [], veh, sdate, now,
                                       bool(dep_rt or arr_rt or veh))
                except Exception:  # bad data for this trip: just omit the Ballan extras
                    winfo = {}
            status = "cancelled" if cancelled else (
                "skips stop" if (dep_skip or arr_skip) else (
                    "live" if (dep_rt or arr_rt or veh) else "scheduled"))
            out.append({
                "trip_id": trip_id,
                "headsign": trip["headsign"],
                "status": status,
                "realtime": bool(dep_rt or arr_rt or veh),
                "scheduled_departure": sched_dep.isoformat(),
                "estimated_departure": est_dep.isoformat(),
                "departure_delay_min": round((est_dep - sched_dep).total_seconds() / 60),
                "scheduled_arrival": sched_arr.isoformat(),
                "estimated_arrival": est_arr.isoformat(),
                "arrival_delay_min": round((est_arr - sched_arr).total_seconds() / 60),
                "platform": None,  # not published for V/Line trains
                "vehicle": veh,
                **winfo,
            })
    out.sort(key=lambda s: s["estimated_departure"])
    # de-duplicate (a trip can appear for two service dates only if data is odd)
    seen, unique = set(), []
    for s in out:
        key = (s["trip_id"], s["scheduled_departure"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:limit]


# ------------------------------------------------------------ protobuf bridge

def feed_to_dict(feed):
    """Convert a parsed gtfs_realtime FeedMessage into plain dicts."""
    out = {}
    for ent in feed.entity:
        if not ent.HasField("trip_update"):
            continue
        tu = ent.trip_update
        cancelled = tu.trip.schedule_relationship == 3  # CANCELED
        updates = []
        for stu in tu.stop_time_update:
            def ev(name):
                if not stu.HasField(name):
                    return None
                e = getattr(stu, name)
                d = {}
                if e.HasField("time"):
                    d["time"] = e.time
                if e.HasField("delay"):
                    d["delay"] = e.delay
                return d or None
            updates.append({
                "seq": stu.stop_sequence if stu.HasField("stop_sequence") else None,
                "stop_id": stu.stop_id or None,
                "skipped": stu.schedule_relationship == 1,  # SKIPPED
                "arrival": ev("arrival"),
                "departure": ev("departure"),
            })
        out[tu.trip.trip_id] = {
            "route_id": tu.trip.route_id or None,
            "cancelled": cancelled,
            "start_date": tu.trip.start_date or None,  # YYYYMMDD
            "updates": updates,
        }
    return out


STATUS = {0: "approaching stop", 1: "at stop", 2: "in transit"}


def feed_to_vehicles(feed):
    """Convert a parsed vehicle-positions FeedMessage into {trip_id: dict}."""
    out = {}
    for ent in feed.entity:
        if not ent.HasField("vehicle"):
            continue
        v = ent.vehicle
        if not v.HasField("trip") or not v.trip.trip_id:
            continue
        pos = v.position if v.HasField("position") else None
        out[v.trip.trip_id] = {
            "route_id": v.trip.route_id or None,
            "start_date": v.trip.start_date or None,
            "latitude": round(pos.latitude, 6) if pos else None,
            "longitude": round(pos.longitude, 6) if pos else None,
            "bearing": round(pos.bearing) if pos and pos.HasField("bearing") else None,
            "speed_kmh": round(pos.speed * 3.6) if pos and pos.HasField("speed") else None,
            "current_stop_sequence": (v.current_stop_sequence
                                      if v.HasField("current_stop_sequence") else None),
            "stop_id": v.stop_id or None,
            "status": STATUS.get(v.current_status) if v.HasField("current_status") else None,
            "reported_at": (datetime.fromtimestamp(v.timestamp, TZ).isoformat()
                            if v.HasField("timestamp") else None),
            "label": v.vehicle.label or v.vehicle.id or None,
        }
    return out
