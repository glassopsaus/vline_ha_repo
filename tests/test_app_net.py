import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); ROOT = _o.path.dirname(HERE)
APPS = _o.path.join(ROOT, 'apps'); STUBS = _o.path.join(HERE, 'stubs'); TOOLS = _o.path.join(ROOT, 'tools')
import sys, os, json, tempfile, zipfile, io
sys.path.insert(0, STUBS); sys.path.insert(0, APPS)
ns={"APPS": APPS}; exec(open(HERE + "/fixture.py").read(), ns)
import vline_trains, vline_core as core, vline_network as vn
from datetime import datetime
d=tempfile.mkdtemp()
args={"api_key":"k","routes":[{"id":"b","name":"B","from_name":"Ballan","to_name":"Ballarat"}],"static_gtfs_url":None,
      "static_gtfs_path":d+"/g.zip","cache_path":d+"/tt.json","network_json_path":d+"/www/vline_network.json","network_cache_path":d+"/net.json"}
# regional zip on disk
b=io.BytesIO()
z0=ns["make"](True)
with zipfile.ZipFile(b,"w") as z:
    for n in z0.namelist(): z.writestr(n,z0.read(n))
open(args["static_gtfs_path"],"wb").write(b.getvalue())
app=vline_trains.VLineTrains(args); app.initialize()
assert app.ptv_devid=="" and any("live data only" in l for l in app.logs)
app._refresh_worker(False)
assert app.net and len(app.net["lines"])==2, app.errors
geo=json.load(open(args["network_json_path"])); assert geo["version"]==app.net_version and "sched" not in geo
now=datetime(2026,11,4,10,45,tzinfo=core.TZ); ep=lambda h,m:int(datetime(2026,11,4,h,m,tzinfo=core.TZ).timestamp())
app.rt={"BAT1":{"cancelled":False,"start_date":"20261104","updates":[{"seq":2,"stop_id":"X","skipped":False,"arrival":{"time":ep(10,52)},"departure":{"time":ep(10,53)}}]}}
app.vehicles={"BAT1":{"latitude":-37.7,"longitude":144.5,"bearing":270,"speed_kmh":90,"status":"in transit","reported_at":"x","label":"V"}}
app.rt_m, app.veh_m = app.rt, app.vehicles
app._publish_network_state(now,False,False)
st,at=app.states["sensor.vline_network"]; assert st=="1" and at["lines"][0]["running"]==1 and at["vehicles"][0]["delay_min"]==12
assert len(json.dumps(at))<16000
app._publish_network_state(now,True,True); st,at=app.states["sensor.vline_network"]; assert st=="0" and at["lines"][0]["level"]=="unknown" and at["worst_level"]=="unknown"
# network failure must not kill the route-card timetable
bad=io.BytesIO()
with zipfile.ZipFile(bad,"w") as z:
    for n in z0.namelist():
        if n!="routes.txt": z.writestr(n,z0.read(n))
open(args["static_gtfs_path"],"wb").write(bad.getvalue())
a2=dict(args); a2["network_json_path"]=d+"/w2/n.json"; app2=vline_trains.VLineTrains(a2); app2.initialize()
app2._refresh_worker(False)
print("app2 timetable ok:",app2.timetable is not None,"| net:",app2.net,"| errors:",[e[:60] for e in app2.errors])
print("app network tests OK")
