"""Run the real apps against the real Open Data feeds and report what works.

    VLINE_API_KEY=... python tools/live_check.py [--out out]

Writes out/vline_network.json, out/vic_metro_network.json and out/sensors.json
(used by tools/preview.py) and prints diagnostics. Exit code 1 on hard failures.
"""
import argparse
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps"))


class Hass:                      # minimal stand-in for AppDaemon's Hass base class
    def __init__(self, args):
        self.args, self.logs, self.errors, self.states = args, [], [], {}

    def log(self, m, *a, **k):
        self.logs.append(str(m)); print("  log  ", m)

    def error(self, m, *a, **k):
        self.errors.append(str(m)); print("  ERROR", m)

    def run_in(self, *a, **k): pass
    def run_daily(self, *a, **k): pass
    def run_every(self, *a, **k): pass

    def set_state(self, ent, state=None, attributes=None):
        self.states[ent] = {"state": state, "attributes": attributes or {}}


for name in ("appdaemon", "appdaemon.plugins", "appdaemon.plugins.hass", "appdaemon.plugins.hass.hassapi"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["appdaemon.plugins.hass.hassapi"].Hass = Hass
sys.modules["appdaemon.plugins.hass"].hassapi = sys.modules["appdaemon.plugins.hass.hassapi"]

URL = ("https://opendata.transport.vic.gov.au/dataset/3f4e292e-7f8a-4ffe-831f-1953be0fe448/resource/"
       "8af7737c-5c9e-4022-aa98-911aa04370a7/download/gtfs.zip")


def nkey(s):                      # same rules as nkey() in vic-network-card.js
    s = str(s or "").lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"railway station|\bstation\b", "", s)
    s = re.sub(r"\bmt\b", "mount", s)
    s = re.sub(r"\bsaint\b", "st", s)
    return re.sub(r"[^a-z0-9]", "", s)


def key_check(key):
    """Show why a key is rejected (GitHub hides the key itself in the log, but not its shape)."""
    import requests
    shape = ("UUID-shaped" if re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key) else "NOT UUID-shaped")
    print(f"\n== Key check ==\n  length {len(key)}, {shape}")
    url = "https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1/vline/trip-updates"
    ok = False
    for hdr in ("KeyId", "Ocp-Apim-Subscription-Key"):
        try:
            r = requests.get(url, headers={hdr: key}, timeout=30)
            print(f"  header {hdr}: HTTP {r.status_code}, {len(r.content)} bytes" + ("" if r.status_code == 200 else f", body: {r.text[:160]!r}"))
            ok = ok or r.status_code == 200
        except Exception as exc:
            print(f"  header {hdr}: {exc!r}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    o = ap.parse_args()
    key = os.environ.get("VLINE_API_KEY", "").strip().strip("\"'").strip()
    if not key:
        sys.exit("Set VLINE_API_KEY (your Open Data key).")
    out = os.path.abspath(o.out); work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)

    import vline_trains, metro_network
    problems, warnings = [], []
    if not key_check(key):
        problems.append("the realtime API rejects this key (see Key check above)")

    print("\n== Regional (V/Line) ==")
    reg = vline_trains.VLineTrains({
        "api_key": key, "static_gtfs_url": URL, "static_gtfs_path": f"{work}/regional.zip",
        "cache_path": f"{work}/tt.json", "network_cache_path": f"{work}/rnet.json",
        "network_json_path": f"{out}/vline_network.json",
        "routes": [{"id": "ballan_to_ballarat", "name": "Ballan to Ballarat", "from_name": "Ballan", "to_name": "Ballarat"}]})
    reg.initialize(); reg._refresh_worker(True)
    if not reg.net:
        problems.append("regional network failed to build")
    else:
        reg.poll({})
        print("  feed:", [l for l in reg.logs if l.startswith("Feed:")][-1:] or "no Feed line")

    print("\n== Metro ==")
    met = metro_network.MetroNetwork({
        "api_key": key, "static_gtfs_url": URL, "static_gtfs_path": f"{work}/metro.zip",
        "network_cache_path": f"{work}/mnet.json", "network_json_path": f"{out}/vic_metro_network.json"})
    met.initialize(); met._refresh(True)
    if not met.net:
        problems.append("metro network failed to build")
    else:
        met.poll({})
        known = sum(1 for t in met.rt if t in met.net["trip_route"])
        if not met.rt:
            warnings.append("metro trip-updates feed returned nothing (normal only outside service hours)")
        elif not known:
            problems.append("no live metro trip matches the timetable (see the sample IDs above)")

    for app in (reg, met):
        problems += [e for e in app.errors if "fetch failed" in e or "build failed" in e]

    print("\n== Map coverage (stations found on the official map) ==")
    anchors = json.load(open(os.path.join(ROOT, "www", "vic_network_anchors.json")))["stations"]
    for label, app in (("Metro", met), ("Regional", reg)):
        for ln in (app.net or {}).get("lines", []):
            names = [s[0] for s in ln["stations"]]
            hit = sum(1 for n in names if nkey(n) in anchors)
            flag = "" if hit >= max(2, 0.6 * len(names)) else "   <-- LOW"
            if hit < 2:
                problems.append(f"{label} {ln['name']}: only {hit} stations on the map")
            elif flag:
                warnings.append(f"{label} {ln['name']}: {hit}/{len(names)} stations on the map")
            print(f"  {label:8} {ln['name']:<24} {hit:>3}/{len(names):<3}{flag}")

    sensors = {k: v for a in (reg, met) for k, v in a.states.items()}
    json.dump(sensors, open(f"{out}/sensors.json", "w"))
    print("\n== Sensors ==")
    for k, v in sensors.items():
        a = v["attributes"]
        print(f"  {k}: state={v['state']} vehicles={len(a.get('vehicles', []))} worst={a.get('worst_level')} diag={a.get('diag', '')}")
    for k in ("sensor.vline_network", "sensor.metro_network"):
        if k not in sensors:
            problems.append(f"{k} was never published")

    print("\nWarnings:", *(warnings or ["none"]), sep="\n  ")
    print("Problems:", *(problems or ["none"]), sep="\n  ")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
