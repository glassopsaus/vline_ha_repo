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

import pickle
z=make(True)
