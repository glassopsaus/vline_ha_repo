#!/usr/bin/env python3
"""Check what the PTV Timetable API (v3) returns for the Ballarat line.

Run on your own computer once PTV has emailed you a user ID (devid) and key:

    pip install requests
    export PTV_DEVID=1234567          # the "user Id" PTV emailed you
    export PTV_KEY=xxxxxxxx-xxxx-...  # the API key PTV emailed you
    python3 ptv_api_test.py

It makes read-only requests and prints:
  1. the route types (is regional train / V/Line there?)
  2. the Ballarat line route
  3. current/planned disruptions that mention the Ballarat line or Ballan
  4. the next departures from Ballan, including any platform_number

The key stays on your computer: it is only used to sign requests.
"""
import hashlib
import hmac
import json
import os
import sys

import requests

BASE = "https://timetableapi.ptv.vic.gov.au"


def sign(path_and_query, devid, key):
    """PTV signature: HMAC-SHA1 over '<path>?<query>&devid=<id>', upper-case hex."""
    sep = "&" if "?" in path_and_query else "?"
    request = f"{path_and_query}{sep}devid={devid}"
    digest = hmac.new(key.encode("utf-8"), request.encode("utf-8"), hashlib.sha1)
    return f"{BASE}{request}&signature={digest.hexdigest().upper()}"


def get(path_and_query, devid, key):
    url = sign(path_and_query, devid, key)
    r = requests.get(url, timeout=30)
    if r.status_code in (401, 403):
        sys.exit(f"HTTP {r.status_code}: PTV rejected the devid/key/signature. "
                 "Check the credentials and that the clock on this computer is right.")
    r.raise_for_status()
    return r.json()


def main():
    devid, key = os.environ.get("PTV_DEVID"), os.environ.get("PTV_KEY")
    if not devid or not key:
        sys.exit("Set PTV_DEVID and PTV_KEY first (see the top of this file).")

    print("== 1. Route types")
    types = get("/v3/route_types", devid, key).get("route_types", [])
    for t in types:
        print(f"   {t['route_type']}: {t['route_type_name']}")
    vline = next((t for t in types if "line" in t["route_type_name"].lower()
                  and "v" in t["route_type_name"].lower()[:1]), None)
    if not vline:
        print("   !! No V/Line route type listed. Regional trains may not be covered.")
        return
    rt = vline["route_type"]
    print(f"   -> using route_type {rt} ({vline['route_type_name']})")

    print("\n== 2. Ballarat line route")
    routes = get(f"/v3/routes?route_types={rt}", devid, key).get("routes", [])
    ballarat = [r for r in routes if "ballarat" in r["route_name"].lower()]
    for r in ballarat:
        print(f"   route_id {r['route_id']}: {r['route_name']}")
    if not ballarat:
        print(f"   !! No Ballarat route among {len(routes)} V/Line routes.")
    ids = {r["route_id"] for r in ballarat}

    print("\n== 3. Disruptions mentioning the Ballarat line or Ballan")
    data = get("/v3/disruptions", devid, key).get("disruptions", {})
    total = hits = 0
    for mode, items in data.items():
        for d in items or []:
            total += 1
            on_route = any(x.get("route_id") in ids for x in d.get("routes") or [])
            text = f"{d.get('title', '')} {d.get('description', '')}".lower()
            if on_route or "ballan" in text or "ballarat" in text:
                hits += 1
                print(f"   [{mode}] {d.get('title')}")
                print(f"      status={d.get('disruption_status')} type={d.get('disruption_type')} "
                      f"from={d.get('from_date')} to={d.get('to_date')}")
                print(f"      {(d.get('description') or '')[:160]}")
                print(f"      {d.get('url')}")
    print(f"   ({hits} relevant of {total} disruptions returned; modes: {', '.join(data) or 'none'})")

    print("\n== 4. Departures from Ballan (platform_number, if provided)")
    stops = get(f"/v3/search/Ballan?route_types={rt}", devid, key).get("stops", [])
    ballan = next((s for s in stops if s["stop_name"].lower().startswith("ballan")), None)
    if not ballan:
        print("   !! Ballan not found in search results.")
        return
    deps = get(f"/v3/departures/route_type/{rt}/stop/{ballan['stop_id']}?max_results=6",
               devid, key).get("departures", [])
    for d in deps:
        print(f"   sched={d.get('scheduled_departure_utc')} est={d.get('estimated_departure_utc')} "
              f"platform={d.get('platform_number')!r} route_id={d.get('route_id')}")
    if not deps:
        print("   (no departures returned)")
    print("\nDone. Paste this output back to me (it contains no credentials).")


if __name__ == "__main__":
    main()
