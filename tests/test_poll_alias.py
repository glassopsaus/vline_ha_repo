import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); ROOT = _o.path.dirname(HERE)
APPS = _o.path.join(ROOT, 'apps'); STUBS = _o.path.join(HERE, 'stubs'); TOOLS = _o.path.join(ROOT, 'tools')
import sys, io, zipfile, tempfile, json
sys.path.insert(0, STUBS); sys.path.insert(0, APPS)
ns={"APPS": APPS}; exec(open(HERE + "/fixture.py").read(), ns)
import vline_trains, vline_core as core
from datetime import datetime
d=tempfile.mkdtemp(); z0=ns["make"](True); b=io.BytesIO()
with zipfile.ZipFile(b,"w") as z:
    for n in z0.namelist(): z.writestr(n,z0.read(n))
open(d+"/g.zip","wb").write(b.getvalue())
args={"api_key":"k","routes":[{"id":"b","name":"B","from_name":"Ballan","to_name":"Ballarat"}],"static_gtfs_url":None,"static_gtfs_path":d+"/g.zip","cache_path":d+"/tt.json","network_json_path":d+"/www/n.json","network_cache_path":d+"/n.json"}
app=vline_trains.VLineTrains(args); app.initialize(); app._refresh_worker(False)
assert app.net
# rename static IDs in both net and timetable to the "published" style
ren={"BAT1":"01-BAT--11-T0-8133","BAT2":"01-BAT--11-T0-8134","GEL1":"01-GEL--11-T0-8200","GEL2":"01-GEL--11-T0-8201"}
app.net["sched"]={ren[k]:v for k,v in app.net["sched"].items()}
app.timetable["trips"]={ren[k]:v for k,v in app.timetable["trips"].items()}
app.alias_index=vline_trains.vnet.build_alias_index(app.net["sched"])
now=datetime.now(core.TZ)
ep=lambda h,m:int(datetime(now.year,now.month,now.day,h,m,tzinfo=core.TZ).timestamp())
sd=now.strftime("%Y%m%d")
live={"01-BAT--5-T3-8133":{"cancelled":False,"start_date":sd,"updates":[{"seq":2,"stop_id":"X","skipped":False,"arrival":{"time":ep(10,52)},"departure":{"time":ep(10,53)}}]}}
veh={"01-BAT--5-T3-8133":{"latitude":-37.7,"longitude":144.5,"bearing":270,"speed_kmh":90,"status":"in transit","reported_at":"x"}}
app._fetch=lambda ep_: ("rt" if ep_=="trip-updates" else "veh")
core.feed_to_dict=lambda f: live; core.feed_to_vehicles=lambda f: veh
app.poll({})
st,at=app.states["sensor.vline_network"]
print("vehicles:",st,"| matched by number:",app.n_alias,"| overlap with timetable:",len(set(app.rt_m)&set(app.timetable["trips"])))
assert app.n_alias==1 and st=="1", (st,app.n_alias, app.errors)
assert any("matched by route + train number" in l for l in app.logs)
print("poll alias OK")
