import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); ROOT = _o.path.dirname(HERE)
APPS = _o.path.join(ROOT, 'apps'); STUBS = _o.path.join(HERE, 'stubs'); TOOLS = _o.path.join(ROOT, 'tools')
import io, sys, zipfile, json
from datetime import datetime, timezone
sys.path.insert(0, APPS)
import vline_core as core, vline_network as vn
TZ = core.TZ
def csv(rows): return "\n".join(",".join(r) for r in rows) + "\n"

stops = csv([["stop_id","stop_name","stop_lat","stop_lon","parent_station"],
 ["S","Southern Cross Railway Station (Melbourne City)","-37.818","144.952",""],
 ["S1","Southern Cross Railway Station (Melbourne City)","-37.818","144.952","S"],
 ["X","Bacchus Marsh Railway Station","-37.673","144.437",""],
 ["B","Ballan Railway Station","-37.597","144.226",""],
 ["R","Ballarat Railway Station","-37.558","143.858",""],
 ["G","Geelong Railway Station","-38.144","144.355",""],
 ["T","Tarneit Railway Station","-37.832","144.694",""]])
st=[["trip_id","stop_sequence","stop_id","arrival_time","departure_time"]]
def trip(t,c):
    for seq,sid,a,d in c: st.append([t,str(seq),sid,a,d])
trip("BAT1",[(1,"S1","10:00:00","10:00:00"),(2,"X","10:40:00","10:41:00"),(3,"B","11:00:00","11:01:00"),(4,"R","11:30:00","11:30:00")])
trip("BAT2",[(1,"R","10:00:00","10:00:00"),(2,"B","10:30:00","10:31:00"),(4,"S1","11:30:00","11:30:00")])
trip("GEL1",[(1,"S1","10:10:00","10:10:00"),(2,"T","10:30:00","10:30:00"),(3,"G","11:15:00","11:15:00")])
trip("GEL2",[(1,"G","10:00:00","10:00:00"),(2,"S1","11:00:00","11:00:00")])
trips = csv([["trip_id","route_id","service_id","trip_headsign","shape_id"],
 ["BAT1","1-BAT","WD","Ballarat","sh1"],["BAT2","1-BAT","WD","Southern Cross","sh1"],
 ["GEL1","1-GEL","WD","Geelong",""],["GEL2","1-GEL","WD","Southern Cross",""]])
routes = csv([["route_id","route_long_name"],["1-BAT","Ballarat - Melbourne"],["1-GEL","Geelong - Melbourne"]])
shapes = [["shape_id","shape_pt_lat","shape_pt_lon","shape_pt_sequence"]]
import math
for i in range(200):
    f=i/199; shapes.append(["sh1",str(-37.818+f*(0.26)),str(144.952-f*1.094),str(i)])
buf=io.BytesIO()
def make(with_shapes):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("stops.txt",stops);z.writestr("stop_times.txt",csv(st));z.writestr("trips.txt",trips);z.writestr("routes.txt",routes)
        if with_shapes: z.writestr("shapes.txt",csv(shapes))
    return zipfile.ZipFile(io.BytesIO(b.getvalue()))
net=vn.build_network(make(True))
assert [l["id"] for l in net["lines"]]==["1-BAT","1-GEL"]
bat=net["lines"][0]; gel=net["lines"][1]
assert bat["name"]=="Ballarat" and gel["name"]=="Geelong", (bat["name"],gel["name"])
assert net["has_shapes"] and len(bat["path"])<20, len(bat["path"])   # straight line simplifies hard
assert len(gel["path"])==3 and gel["stations"][0][0]=="Southern Cross"
assert len(bat["stations"])==4
net2=vn.build_network(make(False)); assert not net2["has_shapes"] and len(net2["lines"][0]["path"])==4
json.dumps(net)

now=datetime(2026,11,4,10,45,tzinfo=TZ); ep=lambda h,m:int(datetime(2026,11,4,h,m,tzinfo=TZ).timestamp())
rt={
 "BAT1":{"cancelled":False,"start_date":"20261104","updates":[{"seq":2,"stop_id":"X","skipped":False,"arrival":{"time":ep(10,52)},"departure":{"time":ep(10,53)}}]},  # +12
 "BAT2":{"cancelled":True,"start_date":"20261104","updates":[]},
 "GEL1":{"cancelled":False,"start_date":"20261104","updates":[{"seq":2,"stop_id":"T","skipped":False,"arrival":{"delay":0},"departure":{"delay":60}}]},
 "GEL2":{"cancelled":False,"start_date":"20261104","updates":[{"seq":1,"stop_id":"G","skipped":False,"departure":{"delay":960}}]},
 "OLD":{"cancelled":True,"start_date":"20261104","updates":[]},
}
d=vn.trip_delay_s(net["sched"]["BAT1"],rt["BAT1"],now); assert d==720,d
assert vn.trip_delay_s(net["sched"]["GEL2"],rt["GEL2"],now)==960
assert vn.trip_delay_s(net["sched"]["BAT1"],None,now) is None
stats=vn.line_stats(net,rt,now)
assert stats["1-BAT"]["cancelled"]==1 and stats["1-BAT"]["running"]==1
veh={"BAT1":{"latitude":-37.7,"longitude":144.5,"bearing":270,"speed_kmh":90,"status":"in transit","reported_at":"x","label":"VL1"},
     "BAT2":{"latitude":-37.6,"longitude":144.0},"NOPE":{"latitude":1,"longitude":1}}
vs=vn.build_vehicles(net,rt,veh,now); assert [v["id"] for v in vs]==["BAT1"] and vs[0]["delay_min"]==12 and vs[0]["to"]=="Ballarat"

def ptv(items): return {"disruptions":{"regional_train":items}}
def item(title,typ,rids,frm="2026-11-03T00:00:00Z",to="2026-11-10T16:00:00Z",status="Current",desc=""):
    return {"title":title,"description":desc,"disruption_type":typ,"disruption_status":status,"url":"u","from_date":frm,"to_date":to,
            "routes":[{"route_type":3,"route_gtfs_id":r} for r in rids]}
nowu=datetime(2026,11,4,0,0,tzinfo=timezone.utc)
n=vn.parse_ptv_disruptions(ptv([
  item("Ballarat Line: Coaches replace evening trains","Planned Works",["1-BAT","1-ART"],desc="Coaches replace evening trains"),
  item("Extra services","Service Information",["1-BAT","1-GEL"]),
  item("Melton car park","Planned Closure",["1-BAT"]),
  item("Geelong minor delays","Minor Delays",["1-GEL"]),
  item("Future works","Planned Works",["1-GEL"],frm="2026-12-01T00:00:00Z",to=None),
  item("Expired","Major Delays",["1-GEL"],to="2026-11-01T00:00:00Z"),
]),["1-BAT","1-GEL"],nowu)
kinds={k:[x["kind"] for x in v] for k,v in n.items()}
assert kinds["1-BAT"]==["coaches",None,None] and kinds["1-GEL"]==[None,"minor",None,None],kinds
assert "1-ART" not in n

st_=vn.line_statuses(net,stats,n,True); b,g=st_
assert b["level"]=="major" and b["label"]=="Coaches replace some trains" and b["cancelled"]==1 and len(b["notices"])==1
assert g["level"]=="major" and g["label"]=="Major delays" and "Up to 16 min late" in g["detail"], g   # 16 min delay beats minor notice
st2=vn.line_statuses(net,stats,{},True); assert st2[0]["level"]=="minor" and st2[0]["label"]=="Minor delays", st2[0]  # 12 min
th=vn.line_statuses(net,stats,{},True,{"minor_delay_min":20}); assert th[0]["level"]=="minor" and th[0]["label"]=="Cancellations"
assert vn.line_statuses(net,stats,{},False)[0]["level"]=="unknown"
quiet=vn.line_statuses(net,vn.line_stats(net,{},now),{},True); assert quiet[0]["label"]=="No trains running now"
# signing is stable and matches the existing probe's algorithm
sys.path.insert(0, TOOLS); import ptv_api_test as pt
a=vn.ptv_signed_url(pt.BASE,"/v3/disruptions?route_types=3","123","k"); assert a==pt.sign("/v3/disruptions?route_types=3","123","k")
print("network tests OK"); json.dump({"net":net,"rt_status":st_},open("out.json","w"))
