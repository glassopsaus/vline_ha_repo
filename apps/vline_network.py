"""Pure logic for the V/Line network map (no AppDaemon / protobuf imports).

Builds, from the static regional-train GTFS:
  * a simplified geometry of every line (path + stations) for the map card
  * a compact per-trip schedule so live delays can be worked out network-wide

and, at runtime, turns the live feeds (+ optional PTV notices) into a list of
train markers and one overall status per line.
"""
import csv
import hashlib
import hmac
import io
import math
import re
from datetime import datetime, timedelta, timezone

from vline_core import TZ, _clean_name, _f, _rows

LEVELS = {"unknown": -1, "ok": 0, "minor": 1, "major": 2}

# Line colours: distinct hues that read on light and dark backgrounds.
PALETTE = ["#7b5cd6", "#0c8fb8", "#d9822b", "#2f9e6b", "#c9487a", "#6b7d8f",
           "#b5a31a", "#d2503e", "#3a6fd8", "#8a5a3c", "#1f9d9d", "#a04bc4"]


# ---------------------------------------------------------------- geometry

def _xy(lat, lon, lat0):
    return lon * math.cos(math.radians(lat0)) * 111.32, lat * 110.57  # km


def simplify(points, tol_km=0.25):
    """Douglas-Peucker on [(lat, lon), ...]; keeps the ends."""
    n = len(points)
    if n < 3:
        return list(points)
    lat0 = points[0][0]
    xy = [_xy(p[0], p[1], lat0) for p in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        best, idx = -1.0, None
        for i in range(a + 1, b):
            px, py = xy[i]
            if seg == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol_km:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def _secs(value):
    """'HH:MM:SS' (may exceed 24h) -> seconds, or None."""
    try:
        h, m, s = (int(x) for x in value.strip().split(":"))
        return h * 3600 + m * 60 + s
    except (AttributeError, ValueError):
        return None


def _line_name(stop_names, long_name):
    """'Ballarat' for a Southern Cross <-> Ballarat route; falls back to the GTFS name."""
    ends = [stop_names[0], stop_names[-1]] if stop_names else []
    far = [e for e in ends if "southern cross" not in e.lower() and "flinders" not in e.lower()]
    if far and len(far) < len(ends):
        return far[0]
    return (long_name or "").strip() or (ends[0] if ends else "Line")


def build_network(zf):
    """Return a JSON-serialisable dict: {"lines": [...], "sched": {...}}.

    Only trips on routes that have a usable path are kept. Works with or without
    shapes.txt (falls back to the stations in order).
    """
    names = set(zf.namelist())
    routes = {r["route_id"]: r for r in _rows(zf, "routes.txt")}
    stops = {r["stop_id"]: r for r in _rows(zf, "stops.txt")}

    trips = {}
    for r in _rows(zf, "trips.txt"):
        if r["route_id"] in routes:
            trips[r["trip_id"]] = {"r": r["route_id"], "s": r.get("service_id", ""),
                                   "h": (r.get("trip_headsign") or "").strip(),
                                   "shape": r.get("shape_id") or None}
    calls = {}
    for r in _rows(zf, "stop_times.txt"):
        t = r["trip_id"]
        if t not in trips:
            continue
        arr, dep = _secs(r.get("arrival_time")), _secs(r.get("departure_time"))
        if arr is None:
            arr = dep
        if dep is None:
            dep = arr
        if arr is None:
            continue
        calls.setdefault(t, []).append((int(r["stop_sequence"]), r["stop_id"], arr, dep))
    for c in calls.values():
        c.sort()

    shapes = {}
    if "shapes.txt" in names:
        raw = {}
        for r in _rows(zf, "shapes.txt"):
            la, lo = _f(r.get("shape_pt_lat")), _f(r.get("shape_pt_lon"))
            if la is None or lo is None:
                continue
            raw.setdefault(r["shape_id"], []).append((int(r["shape_pt_sequence"]), la, lo))
        for sid, pts in raw.items():
            pts.sort()
            shapes[sid] = [(la, lo) for _s, la, lo in pts]

    def station(sid):
        s = stops.get(sid)
        if not s:
            return None
        parent = stops.get(s.get("parent_station") or "", s)
        la, lo = _f(s.get("stop_lat")), _f(s.get("stop_lon"))
        if la is None or lo is None:
            la, lo = _f(parent.get("stop_lat")), _f(parent.get("stop_lon"))
        if la is None or lo is None:
            return None
        return _clean_name(parent["stop_name"]), la, lo

    # Longest trip (most stops) per route is its representative.
    best = {}
    for t, info in trips.items():
        n = len(calls.get(t, ()))
        if n and n > best.get(info["r"], (0, None))[0]:
            best[info["r"]] = (n, t)

    lines = []
    for rid, (_n, t) in sorted(best.items()):
        sts = []
        for _seq, sid, _a, _d in calls[t]:
            st = station(sid)
            if st and (not sts or sts[-1][0] != st[0]):
                sts.append(st)
        if len(sts) < 2:
            continue
        path = shapes.get(trips[t]["shape"]) or [(la, lo) for _n2, la, lo in sts]
        path = simplify(path)
        r = routes[rid]
        lines.append({
            "id": rid,
            "name": _line_name([s[0] for s in sts], r.get("route_long_name")),
            "long_name": (r.get("route_long_name") or "").strip(),
            "path": [[round(la, 4), round(lo, 4)] for la, lo in path],
            "stations": [[n, round(la, 4), round(lo, 4)] for n, la, lo in sts],
        })
    for i, ln in enumerate(lines):
        ln["color"] = PALETTE[i % len(PALETTE)]
    keep = {ln["id"] for ln in lines}

    sched = {}
    for t, info in trips.items():
        if info["r"] in keep and t in calls:
            sched[t] = {"r": info["r"], "h": info["h"],
                        "t": [[seq, arr, dep] for seq, _sid, arr, dep in calls[t]]}
    return {"lines": lines, "sched": sched, "has_shapes": bool(shapes)}


# --------------------------------------------- live trip IDs vs timetable IDs
# V/Line trip IDs look like 01-ABY--11-T0-8610: route, timetable-version tokens, train number.
# The live feed sometimes uses different version tokens (01-ABY--5-T3-8610) from the
# published timetable, so exact matching fails. The route + train number still identify it.
ID_RE = re.compile(r"^(\d+)-([A-Za-z0-9]+)--(\d+)-T(\d+)-(\d+)$")


def route_of(trip_id):
    """'01-ABY--5-T3-8610' -> '1-ABY' (the GTFS route_id), or None."""
    m = ID_RE.match(trip_id or "")
    return f"{int(m.group(1))}-{m.group(2)}" if m else None


_RK_RE = re.compile(r"(\d+)-([A-Za-z0-9]+)(?::|$)")


def route_key(route_id):
    """'aus:vic:vic-02-ALM:' / '2-ALM' -> '2-alm' (one spelling for both timetable and live/PTV ids)."""
    m = None
    for m in _RK_RE.finditer(str(route_id or "")):
        pass
    return f"{int(m.group(1))}-{m.group(2).lower()}" if m else None


def resolve_route(net, trip_id, entry, live=None):
    """Which line a live trip belongs to: timetable entry, static trip->route map, live route_id, or the trip-ID pattern."""
    if entry:
        return entry["r"]
    rid = (net.get("trip_route") or {}).get(trip_id)
    if rid:
        return rid
    alias = net.get("route_alias") or {}
    key = route_key((live or {}).get("route_id"))
    if key and key in alias:
        return alias[key]
    return route_of(trip_id)


def build_alias_index(sched):
    idx = {}
    for tid in sched:
        m = ID_RE.match(tid)
        if m:
            idx.setdefault((int(m.group(1)), m.group(2), m.group(5)), []).append(tid)
    return idx


def _first_time(tu):
    for u in (tu or {}).get("updates") or []:
        for kind in ("arrival", "departure"):
            ev = u.get(kind)
            if ev and ev.get("time"):
                return ev["time"]
    return None


def remap_live(live, sched, index, now, tol_s=5400, known=None, runs_on=None):
    """Rename live trip IDs that don't exist in the timetable to the timetable trip
    with the same route + train number whose times fit. Returns (new_dict, n_aliased, {live_id: timetable_id})."""
    out, n, used = {}, 0, {}
    for tid, val in live.items():
        if tid in sched:
            out[tid] = val
            continue
        if known and known.get(tid) and known[tid] not in out:
            out[known[tid]] = val
            used[tid] = known[tid]
            n += 1
            continue
        m = ID_RE.match(tid)
        best = None
        if m:
            cands = index.get((int(m.group(1)), m.group(2), m.group(5)), [])
            if runs_on and len(cands) > 1:
                sdate = _midnight(val.get("start_date") if isinstance(val, dict) else None, now).date()
                today = [c for c in cands if runs_on(c, sdate)]
                cands = today or cands  # prefer the variant that actually runs on that date
            ft = _first_time(val) if isinstance(val, dict) and "updates" in val else None
            sd = val.get("start_date") if isinstance(val, dict) else None
            mid = _midnight(sd, now).timestamp()
            for c in cands:
                t = sched[c]["t"]
                if not t:
                    continue
                if ft is None:
                    score = 0 if len(cands) == 1 else None
                else:
                    a, b = mid + t[0][2], mid + t[-1][1]
                    score = 0 if a - tol_s <= ft <= b + tol_s else None
                    if score is not None:
                        score = abs(ft - a)
                if score is not None and (best is None or score < best[0]):
                    best = (score, c)
        if best and best[1] not in out:
            out[best[1]] = val
            used[tid] = best[1]
            n += 1
        else:
            out[tid] = val
    return out, n, used


# ------------------------------------------------------------------- live

def _midnight(start_date, now):
    if start_date and re.fullmatch(r"\d{8}", start_date):
        return datetime(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:]), tzinfo=TZ)
    return datetime(now.year, now.month, now.day, tzinfo=TZ)


def trip_window(entry, now, start_date=None):
    """(start, end) datetimes of a scheduled trip, or None."""
    t = entry["t"]
    if not t:
        return None
    m = _midnight(start_date, now)
    return m + timedelta(seconds=t[0][2]), m + timedelta(seconds=t[-1][1])


def trip_delay_s(entry, tu, now):
    """Current delay in seconds for a trip from its trip update, or None if unknown."""
    if not tu:
        return None
    if entry is None:  # no schedule: only an explicit delay from the feed can be used
        for u in tu.get("updates") or []:
            for kind in ("departure", "arrival"):
                ev = u.get(kind)
                if ev and ev.get("delay") is not None:
                    return int(ev["delay"]) if abs(ev["delay"]) <= 7200 else None
        return None
    m = _midnight(tu.get("start_date"), now)
    by_seq = {c[0]: c for c in entry["t"]}
    now_ts = now.timestamp()
    best = None  # (actual_ts, delay) of the latest stop already reached
    first = None
    for u in tu.get("updates") or []:
        if u.get("skipped"):
            continue
        c = by_seq.get(u.get("seq"))
        for kind, idx in (("departure", 2), ("arrival", 1)):
            ev = u.get(kind)
            if not ev:
                continue
            delay = None
            actual = None
            if ev.get("delay") is not None:
                delay = ev["delay"]
                if c:
                    actual = (m + timedelta(seconds=c[idx])).timestamp() + delay
            elif ev.get("time") and c:
                actual = ev["time"]
                delay = actual - (m + timedelta(seconds=c[idx])).timestamp()
            if delay is None:
                continue
            if first is None:
                first = delay
            if actual is None or actual <= now_ts:
                if best is None or (actual or 0) >= best[0]:
                    best = (actual or 0, delay)
            break
    d = int(best[1]) if best else (int(first) if first is not None else None)
    return d if d is None or abs(d) <= 7200 else None  # >2 h means the schedule isn't this trip's


def build_vehicles(net, rt, veh, now, delay_floor_s=0):
    """Train markers for every live vehicle that belongs to a known line."""
    out = []
    line_ids = {ln["id"] for ln in net["lines"]}
    for trip_id, v in (veh or {}).items():
        entry = net["sched"].get(trip_id)
        rid = resolve_route(net, trip_id, entry, v)
        if rid not in line_ids or v.get("latitude") is None or v.get("longitude") is None:
            continue
        tu = rt.get(trip_id)
        if tu and tu.get("cancelled"):
            continue
        d = trip_delay_s(entry, tu, now)
        out.append({
            "id": trip_id, "line": rid, "to": entry["h"] if entry else "",
            "lat": v["latitude"], "lon": v["longitude"],
            "brg": v.get("bearing"), "spd": v.get("speed_kmh"),
            "delay_min": (round(d / 60) if d is not None else None),
            "state": v.get("status"),
            "at": v.get("reported_at"),
            "label": v.get("label"),
        })
    return out


def line_stats(net, rt, now, window_before_min=15, window_after_min=180):
    """Per line: running / cancelled / delayed counts from the live trip updates."""
    stats = {ln["id"]: {"running": 0, "cancelled": 0, "delayed": [], "delay_known": 0}
             for ln in net["lines"]}
    now_ts = now.timestamp()
    for trip_id, tu in (rt or {}).items():
        entry = net["sched"].get(trip_id)
        rid = resolve_route(net, trip_id, entry, tu)
        if rid not in stats:
            continue
        if entry:
            win = trip_window(entry, now, tu.get("start_date"))
            if win and not (win[0] - timedelta(minutes=window_after_min) <= now
                            <= win[1] + timedelta(minutes=window_before_min)):
                continue
        else:  # unknown trip: use the times the feed itself reports
            ts = [e["time"] for u in tu.get("updates") or [] for e in (u.get("arrival"), u.get("departure"))
                  if e and e.get("time")]
            if ts and not (min(ts) - window_after_min * 60 <= now_ts <= max(ts) + window_before_min * 60):
                continue
        s = stats[rid]
        if tu.get("cancelled"):
            s["cancelled"] += 1
            continue
        s["running"] += 1
        d = trip_delay_s(entry, tu, now)
        if d is not None:
            s["delayed"].append(d)
            s["delay_known"] += 1
    return stats


# --------------------------------------------------------------- statuses

def classify_notice(n, now_utc):
    """Map a PTV notice to ('coaches'|'major'|'minor'|'works'|None)."""
    typ = (n.get("type") or "").lower()
    text = f"{n.get('title', '')} {n.get('description', '')}".lower()
    if typ in ("planned closure", "service information", "travel alert", "information"):
        return None
    if (n.get("status") or "").lower() == "planned":
        return None
    start, end = n.get("from"), n.get("to")
    if start and start > now_utc:
        return None
    if end and end < now_utc:
        return None
    if "coach" in text and ("replace" in text or "instead" in text):
        return "coaches"
    if "suspend" in typ or "major" in typ or "cancel" in typ:
        return "major"
    if "minor" in typ or "delay" in typ:
        return "minor"
    if "works" in typ:
        return "works"
    return None


def line_statuses(net, stats, notices, live_ok, thresholds=None):
    """One status dict per line, in the order of net['lines']."""
    th = {"minor_delay_min": 5, "major_delay_min": 15, "major_cancelled": 3,
          "major_cancel_share": 0.25}
    th.update(thresholds or {})
    out = []
    for ln in net["lines"]:
        s = stats.get(ln["id"], {"running": 0, "cancelled": 0, "delayed": []})
        ns = [n for n in notices.get(ln["id"], []) if n["kind"]]
        kinds = {n["kind"] for n in ns}
        delays = s["delayed"]
        worst = max(delays) / 60 if delays else 0
        late = sum(1 for d in delays if d >= th["minor_delay_min"] * 60)
        total = s["running"] + s["cancelled"]
        level, label, detail = "ok", "Running normally", []
        if not live_ok:
            level, label = "unknown", "Live data unavailable"
        else:
            canc_major = (s["cancelled"] >= th["major_cancelled"]
                          or (total and s["cancelled"] / total >= th["major_cancel_share"]
                              and s["cancelled"] >= 2))
            if worst >= th["major_delay_min"]:
                level, label = "major", "Major delays"
                detail.append(f"Up to {round(worst)} min late")
            elif worst >= th["minor_delay_min"]:
                level, label = "minor", "Minor delays"
                detail.append(f"Up to {round(worst)} min late")
            if s["cancelled"]:
                detail.append(f"{s['cancelled']} cancelled")
                if canc_major:
                    level, label = "major", "Cancellations"
                elif LEVELS[level] < LEVELS["minor"]:
                    level, label = "minor", "Cancellations"
            if level == "ok" and s["running"] == 0:
                label = "No trains running now"
            elif level == "ok" and s.get("delay_known", 1) == 0:
                label = "Running (delays unknown)"
        if "major" in kinds and LEVELS[level] < 2:
            level, label = "major", "Major delays"
        elif "minor" in kinds and LEVELS[level] < 1:
            level, label = "minor", "Minor delays"
        if "coaches" in kinds:
            level, label = "major", "Coaches replace some trains"
        elif "works" in kinds and level == "ok":
            label = "Planned works"
        out.append({
            "id": ln["id"], "level": level, "label": label,
            "running": s["running"], "cancelled": s["cancelled"], "late": late,
            "max_delay_min": round(worst),
            "detail": detail,
            "notices": [{"title": n["title"], "kind": n["kind"], "url": n.get("url")}
                        for n in ns][:3],
        })
    return out


# --------------------------------------------------------------------- PTV

def ptv_signed_url(base, path_and_query, devid, key):
    sep = "&" if "?" in path_and_query else "?"
    request = f"{path_and_query}{sep}devid={devid}"
    digest = hmac.new(key.encode(), request.encode(), hashlib.sha1).hexdigest().upper()
    return f"{base}{request}&signature={digest}"


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_ptv_disruptions(payload, line_ids, now=None, route_type=3, group="regional_train"):
    """{line_id: [notice, ...]} for the routes we draw (route_type 3 = V/Line, 0 = metro trains)."""
    now = now or datetime.now(timezone.utc)
    wanted = {route_key(i) or i: i for i in line_ids}
    wanted.update({i: i for i in line_ids})
    out = {}
    data = (payload or {}).get("disruptions") or {}
    items = data.get(group) or [
        d for lst in data.values() for d in (lst or [])
        if any(r.get("route_type") == route_type for r in d.get("routes") or [])]
    for d in items:
        n = {"title": d.get("title", ""), "description": d.get("description", ""),
             "type": d.get("disruption_type"), "status": d.get("disruption_status"),
             "url": d.get("url"), "from": _parse_ts(d.get("from_date")),
             "to": _parse_ts(d.get("to_date"))}
        n["kind"] = classify_notice(n, now)
        for r in d.get("routes") or []:
            gid = r.get("route_gtfs_id")
            lid = wanted.get(gid) or wanted.get(route_key(gid))
            if lid:
                out.setdefault(lid, []).append(dict(n))
    return out
