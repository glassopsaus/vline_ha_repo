"""All-stations V/Line timetable for the journey-planner card (pure logic, no AppDaemon imports).

build_journeys(zf, today) -> a compact JSON-serialisable dict covering yesterday .. today+3:

    {"generated": "...", "from": "YYYYMMDD", "to": "YYYYMMDD",
     "stations": ["Ballan", ...],
     "services": [{"d": [mon..sun bools], "s": "start", "e": "end", "a": [added dates], "r": [removed dates]}, ...],
     "trips": [[trip_id, headsign, service_index, [[station_index, arr_min, dep_min?], ...]], ...]}

Times are minutes after the service day's midnight (may exceed 1440 for trains running past midnight);
dep_min is left out when it equals arr_min. The card does the rest in the browser.
"""
from datetime import datetime, timedelta

from vline_core import _clean_name, _rows


def _mins(value):
    try:
        h, m, _s = (int(x) for x in value.strip().split(":"))
        return h * 60 + m
    except (AttributeError, ValueError):
        return None


def _runs(svc, d):
    ds = d.strftime("%Y%m%d")
    if ds in svc["r"]:
        return False
    if ds in svc["a"]:
        return True
    return svc["s"] <= ds <= svc["e"] and svc["d"][d.weekday()]


def build_journeys(zf, today, days_ahead=3):
    names = set(zf.namelist())
    cal = {}
    if "calendar.txt" in names:
        for r in _rows(zf, "calendar.txt"):
            cal[r["service_id"]] = {"s": r["start_date"], "e": r["end_date"], "a": [], "r": [],
                                    "d": [r[k] == "1" for k in ("monday", "tuesday", "wednesday", "thursday",
                                                                 "friday", "saturday", "sunday")]}
    if "calendar_dates.txt" in names:
        for r in _rows(zf, "calendar_dates.txt"):
            s = cal.setdefault(r["service_id"], {"s": "99999999", "e": "00000000", "a": [], "r": [], "d": [False] * 7})
            (s["a"] if r["exception_type"] == "1" else s["r"]).append(r["date"])

    window = [today + timedelta(days=k) for k in range(-1, days_ahead + 1)]
    live_services = {sid for sid, svc in cal.items() if any(_runs(svc, d) for d in window)}

    trips = {}
    for r in _rows(zf, "trips.txt"):
        if r.get("service_id") in live_services:
            trips[r["trip_id"]] = (r["service_id"], (r.get("trip_headsign") or "").strip())

    stops = {r["stop_id"]: r for r in _rows(zf, "stops.txt")}

    def station_name(sid):
        s = stops.get(sid)
        if not s:
            return None
        parent = stops.get(s.get("parent_station") or "", s)
        return _clean_name(parent["stop_name"]) or None

    calls = {}
    for r in _rows(zf, "stop_times.txt"):
        t = r["trip_id"]
        if t not in trips:
            continue
        arr, dep = _mins(r.get("arrival_time")), _mins(r.get("departure_time"))
        if arr is None:
            arr = dep
        if dep is None:
            dep = arr
        nm = station_name(r["stop_id"])
        if arr is None or not nm:
            continue
        calls.setdefault(t, []).append((int(r["stop_sequence"]), nm, arr, dep))

    stations, sidx, svc_list, svc_idx, out = [], {}, [], {}, []
    for t, cs in calls.items():
        cs.sort()
        if len(cs) < 2:
            continue
        sid, head = trips[t]
        if sid not in svc_idx:
            svc_idx[sid] = len(svc_list)
            svc_list.append(cal[sid])
        seq = []
        for _n, nm, arr, dep in cs:
            if seq and stations[seq[-1][0]] == nm:       # two platforms of one station in a row
                seq[-1] = [seq[-1][0], seq[-1][1], dep] if dep != seq[-1][1] else seq[-1]
                continue
            if nm not in sidx:
                sidx[nm] = len(stations)
                stations.append(nm)
            seq.append([sidx[nm], arr, dep] if dep != arr else [sidx[nm], arr])
        out.append([t, head, svc_idx[sid], seq])
    out.sort(key=lambda x: x[3][0][1])
    return {"generated": datetime.now().isoformat(timespec="seconds"),
            "from": window[0].strftime("%Y%m%d"), "to": window[-1].strftime("%Y%m%d"),
            "stations": stations, "services": svc_list, "trips": out}
