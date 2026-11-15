import io, os, sys, json, zipfile
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "apps"))
APPS = os.path.join(os.path.dirname(HERE), "apps")
ns = {"APPS": APPS, "__file__": os.path.join(HERE, "fixture.py")}
exec(open(os.path.join(HERE, "fixture.py")).read(), ns)
import vline_journeys as vj

def with_calendar():
    b = io.BytesIO()
    src = ns["make"](False)
    with zipfile.ZipFile(b, "w") as z:
        for n in src.namelist(): z.writestr(n, src.read(n))
        z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                   "WD,1,1,1,1,1,1,1,20200101,20990101\n")
    return zipfile.ZipFile(io.BytesIO(b.getvalue()))

d = vj.build_journeys(with_calendar(), date(2026, 11, 17))
assert set(d["stations"]) == {"Southern Cross", "Bacchus Marsh", "Ballan", "Ballarat", "Geelong", "Tarneit"}, d["stations"]
assert len(d["trips"]) == 4
names = d["stations"]
after = {}
for t in d["trips"]:
    seq = [names[c[0]] for c in t[3]]
    for i, a in enumerate(seq):
        after.setdefault(a, set()).update(seq[i + 1:])
assert after["Ballan"] == {"Ballarat", "Southern Cross"}
assert "Geelong" not in after["Ballan"] and "Ballan" not in after["Geelong"]
assert d["trips"][0][3][0][1] == 600        # 10:00 -> minutes
# out of window / no calendar match -> empty
assert vj.build_journeys(with_calendar(), date(2000, 1, 1))["trips"] == []
json.dump(d, open(os.path.join(HERE, "journeys_fixture.json"), "w"))
print("journeys ok")
