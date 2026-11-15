import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); ROOT = _o.path.dirname(HERE)
APPS = _o.path.join(ROOT, 'apps'); STUBS = _o.path.join(HERE, 'stubs'); TOOLS = _o.path.join(ROOT, 'tools')
import sys
sys.path.insert(0, APPS)
ns={"APPS": APPS}; exec(open(HERE + "/fixture.py").read(), ns)
import vline_network as vn, vline_core as core
from datetime import datetime
TZ=core.TZ
net=vn.build_network(ns["make"](True))
ren={"BAT1":"01-BAT--11-T0-8133","BAT2":"01-BAT--11-T0-8134","GEL1":"01-GEL--11-T0-8200","GEL2":"01-GEL--11-T0-8201"}
net["sched"]={ren[k]:v for k,v in net["sched"].items()}
# a second, wrong-time trip with the same number (e.g. a weekend variant at 18:00)
import copy
other=copy.deepcopy(net["sched"]["01-BAT--11-T0-8133"]); other["t"]=[[q,a+8*3600,d+8*3600] for q,a,d in other["t"]]
net["sched"]["01-BAT--11-T1-8133"]=other
idx=vn.build_alias_index(net["sched"])
now=datetime(2026,11,15,10,45,tzinfo=TZ); ep=lambda h,m:int(datetime(2026,11,15,h,m,tzinfo=TZ).timestamp())
assert vn.route_of("01-ABY--5-T3-8610")=="1-ABY" and vn.route_of("junk") is None
rt={"01-BAT--5-T3-8133":{"cancelled":False,"start_date":"20261115","updates":[{"seq":2,"stop_id":"X","skipped":False,"arrival":{"time":ep(10,50)},"departure":{"time":ep(10,51)}}]},
    "01-GEL--5-T3-8200":{"cancelled":True,"start_date":"20261115","updates":[]},
    "01-XYZ--5-T3-1":{"cancelled":False,"start_date":"20261115","updates":[]}}
veh={"01-BAT--5-T3-8133":{"latitude":-37.7,"longitude":144.5,"bearing":270,"speed_kmh":80,"status":"in transit"},
     "01-GEL--5-T3-9999":{"latitude":-37.9,"longitude":144.6,"bearing":240,"speed_kmh":60}}
m,n,used=vn.remap_live(rt,net["sched"],idx,now)
assert used=={"01-BAT--5-T3-8133":"01-BAT--11-T0-8133","01-GEL--5-T3-8200":"01-GEL--11-T0-8200"},used   # picked the 10:xx one, not the 18:xx variant
assert "01-XYZ--5-T3-1" in m and n==2
vm,_,_=vn.remap_live(veh,net["sched"],idx,now,known=used); assert "01-BAT--11-T0-8133" in vm and "01-GEL--5-T3-9999" in vm
vs=vn.build_vehicles(net,m,vm,now); ids={v["id"]:v for v in vs}
assert set(ids)=={"01-BAT--11-T0-8133","01-GEL--5-T3-9999"} and ids["01-GEL--5-T3-9999"]["line"]=="1-GEL" and ids["01-GEL--5-T3-9999"]["delay_min"] is None
assert ids["01-BAT--11-T0-8133"]["delay_min"]==10
stt=vn.line_stats(net,m,now); assert stt["1-GEL"]["cancelled"]==1 and stt["1-BAT"]["running"]==1
# unmatched trip with explicit delay only
rt2={"01-GEL--5-T3-7777":{"cancelled":False,"start_date":"20261115","updates":[{"seq":1,"stop_id":"G","skipped":False,"departure":{"delay":420}}]}}
s2=vn.line_stats(net,rt2,now); assert s2["1-GEL"]["running"]==1 and s2["1-GEL"]["delayed"]==[420]
# unmatched, no delay info -> honest label
rt3={"01-GEL--5-T3-7778":{"cancelled":False,"start_date":"20261115","updates":[{"seq":1,"stop_id":"G","skipped":False,"departure":{"time":ep(10,40)}}]}}
st3=vn.line_statuses(net,vn.line_stats(net,rt3,now),{},True); assert st3[1]["label"]=="Running (delays unknown)",st3[1]
# no times at all + time guard: implausible schedule match yields unknown delay
tu={"start_date":"20261115","updates":[{"seq":2,"skipped":False,"arrival":{"time":ep(15,0)}}]}
assert vn.trip_delay_s(net["sched"]["01-BAT--11-T0-8133"],tu,now) is None
print("alias tests OK")
# two time-fitting variants: the one that runs on the date wins
import copy
net["sched"]["01-BAT--11-T1-8133"]=copy.deepcopy(net["sched"]["01-BAT--11-T0-8133"])
idx=vn.build_alias_index(net["sched"])
rt={"01-BAT--5-T3-8133":{"cancelled":False,"start_date":"20261115","updates":[{"seq":2,"skipped":False,"arrival":{"time":ep(10,50)}}]}}
m1,_,u1=vn.remap_live(rt,net["sched"],idx,now,runs_on=lambda t,d: t.endswith("T1-8133"))
assert list(u1.values())==["01-BAT--11-T1-8133"],u1
print("calendar pick OK")
