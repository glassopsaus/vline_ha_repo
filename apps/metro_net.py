"""Static-timetable side of the Metro Trains network card (no AppDaemon imports).

Unlike the V/Line network, the metro bundle is far too big to keep a per-trip schedule for, so this
builds only: one line per route (path + stations from a representative trip) and a trip -> route
lookup. Live delays then come from the feed's own stop-time updates (no schedule needed).
"""
import hashlib
import json

from vline_core import _clean_name, _f, _rows
from vline_network import PALETTE, route_key, simplify


def build_light_network(zf):
    names = set(zf.namelist())
    routes = {r["route_id"]: r for r in _rows(zf, "routes.txt")}
    stops = {r["stop_id"]: r for r in _rows(zf, "stops.txt")}

    shapes = {}
    if "shapes.txt" in names:
        raw = {}
        for r in _rows(zf, "shapes.txt"):
            la, lo = _f(r.get("shape_pt_lat")), _f(r.get("shape_pt_lon"))
            if la is not None and lo is not None:
                raw.setdefault(r["shape_id"], []).append((int(r["shape_pt_sequence"]), la, lo))
        for sid, pts in raw.items():
            pts.sort()
            shapes[sid] = [(la, lo) for _s, la, lo in pts]

    trip_route = {}
    rep = {}                       # route_id -> (shape_points, trip_id, shape_id)
    for r in _rows(zf, "trips.txt"):
        rid = r["route_id"]
        if rid not in routes:
            continue
        trip_route[r["trip_id"]] = rid
        sid = r.get("shape_id")
        n = len(shapes.get(sid, ())) if sid else 0
        if rid not in rep or n > rep[rid][0]:
            rep[rid] = (n, r["trip_id"], sid)

    wanted = {t for _n, t, _s in rep.values()}
    calls = {}
    ends = {}                      # trip_id -> [first_seq, first_stop, last_seq, last_stop]
    for r in _rows(zf, "stop_times.txt"):
        t = r["trip_id"]
        if t in trip_route:
            q = int(r["stop_sequence"])
            e = ends.get(t)
            if e is None:
                ends[t] = [q, r["stop_id"], q, r["stop_id"]]
            elif q < e[0]:
                e[0], e[1] = q, r["stop_id"]
            elif q > e[2]:
                e[2], e[3] = q, r["stop_id"]
        if t in wanted:
            calls.setdefault(t, []).append((int(r["stop_sequence"]), r["stop_id"]))
    for c in calls.values():
        c.sort()

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

    lines = []
    for rid, (_n, t, sid) in sorted(rep.items()):
        sts = []
        for _seq, stop_id in calls.get(t, ()):
            st = station(stop_id)
            if st and (not sts or sts[-1][0] != st[0]):
                sts.append(st)
        if len(sts) < 2:
            continue
        path = simplify(shapes.get(sid) or [(la, lo) for _n2, la, lo in sts])
        r = routes[rid]
        name = (r.get("route_long_name") or r.get("route_short_name") or sts[-1][0]).strip()
        for suffix in (" Line", " line"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        col = (r.get("route_color") or "").strip().lstrip("#")
        lines.append({
            "id": rid, "name": name, "long_name": (r.get("route_long_name") or "").strip(),
            "path": [[round(la, 4), round(lo, 4)] for la, lo in path],
            "stations": [[n, round(la, 4), round(lo, 4)] for n, la, lo in sts],
            "gtfs_color": f"#{col}" if len(col) == 6 else None,
        })
    # Some lines come as several routes with one name (variants, old and new ids): show one tab per
    # name (the variant with most stations) and send the others' trips to it.
    best = {}
    for ln in lines:
        b = best.get(ln["name"].lower())
        if b is None or len(ln["stations"]) > len(b["stations"]):
            best[ln["name"].lower()] = ln
    redirect = {ln["id"]: best[ln["name"].lower()]["id"] for ln in lines}
    lines = [ln for ln in lines if best[ln["name"].lower()] is ln]
    for i, ln in enumerate(lines):
        ln["color"] = ln["gtfs_color"] or PALETTE[i % len(PALETTE)]
    od_names, od_idx = [], {}

    def ni(stop_id):
        s = stops.get(stop_id)
        if not s:
            return -1
        n = _clean_name(stops.get(s.get("parent_station") or "", s)["stop_name"])
        if n not in od_idx:
            od_idx[n] = len(od_names)
            od_names.append(n)
        return od_idx[n]

    trip_od = {t: [ni(e[1]), ni(e[3])] for t, e in ends.items() if trip_route.get(t) in redirect}
    return {
        "od_names": od_names, "trip_od": trip_od,
        "lines": lines, "sched": {}, "has_shapes": bool(shapes),
        "trip_route": {t: redirect[r] for t, r in trip_route.items() if r in redirect},
        "route_alias": {route_key(r): k for r, k in redirect.items() if route_key(r)},
    }
