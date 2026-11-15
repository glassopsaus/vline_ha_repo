import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); ROOT = _o.path.dirname(HERE)
APPS = _o.path.join(ROOT, 'apps'); STUBS = _o.path.join(HERE, 'stubs'); TOOLS = _o.path.join(ROOT, 'tools')
import sys, io, zipfile, tempfile, json
sys.path.insert(0, STUBS); sys.path.insert(0, APPS)
ns={"APPS": APPS}; exec(open(HERE + "/fixture.py").read(), ns)
import vline_trains, vline_core as core
d=tempfile.mkdtemp(); z0=ns["make"](True); b=io.BytesIO()
with zipfile.ZipFile(b,"w") as z:
    for n in z0.namelist(): z.writestr(n,z0.read(n))
open(d+"/g.zip","wb").write(b.getvalue())
args={"api_key":"k","ptv_devid":"1","ptv_key":"k","routes":[{"id":"b","name":"B","from_name":"Ballan","to_name":"Ballarat"}],"static_gtfs_url":None,"static_gtfs_path":d+"/g.zip","cache_path":d+"/tt.json","network_json_path":d+"/www/n.json","network_cache_path":d+"/n.json"}
app=vline_trains.VLineTrains(args); app.initialize()
app._ptv_poll({})            # fires before the network exists: must be a no-op
assert app.ptv_ok is None
app._refresh_worker(False)
class R:
    status_code=200
    def raise_for_status(self): pass
    def json(self): return {"disruptions":{"regional_train":[{"title":"x","disruption_type":"Minor Delays","disruption_status":"Current","from_date":"2026-01-01T00:00:00Z","to_date":"2030-01-01T00:00:00Z","routes":[{"route_type":3,"route_gtfs_id":"1-BAT"}]}]}}
vline_trains.requests.get=lambda *a,**k: R()
app._fetch=lambda e:"x"; core.feed_to_dict=lambda f:{}; core.feed_to_vehicles=lambda f:{}
app.poll({})
assert app.ptv_ok is not None and any("PTV notices working" in l for l in app.logs), app.logs
print("ptv catch-up OK")
