import os as _o
HERE = _o.path.dirname(_o.path.abspath(__file__)); APPS = _o.path.join(_o.path.dirname(HERE), 'apps')
import sys, io, zipfile, tempfile
sys.path.insert(0, APPS)
import requests, vline_fetch as vf

def mkzip():
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z: z.writestr("routes.txt", "route_id\n1\n")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z: z.writestr("1/google_transit.zip", inner.getvalue()); z.writestr("2/google_transit.zip", inner.getvalue())
    return outer.getvalue()

class R:
    def __init__(s, code, body=b"", js=None, text=""): s.status_code, s.content, s._js, s.text, s.headers = code, body, js, text, {}
    def raise_for_status(s):
        if s.status_code >= 400:
            e = requests.HTTPError(str(s.status_code)); e.response = s; raise e
    def json(s): return s._js
    def iter_content(s, n): yield s.content
    def __enter__(s): return s
    def __exit__(s, *a): pass

OLD = "https://x/dataset/d/resource/old/download/gtfs.zip"
NEW = "https://x/dataset/d/resource/new/download/gtfs.zip"
def get(url, **k):
    if url == OLD: return R(404)
    if url == vf.DATASET_API:
        return R(200, js={"result": {"resources": [
            {"url": "https://x/dataset/d/resource/older/download/gtfs.zip", "last_modified": "2026-01-01"},
            {"url": NEW, "last_modified": "2026-11-15"}, {"url": "https://x/readme.pdf"}]}})
    if url == NEW: return R(200, mkzip())
    return R(404)
vf.requests.get = get
d = tempfile.mkdtemp()
data, meta = vf.download_regional(OLD, d)
assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["routes.txt"]
assert vf.find_current_urls()[0] == NEW
# API down -> page scrape
def get2(url, **k):
    if url == vf.DATASET_API: return R(500)
    if url == vf.DATASET_PAGE: return R(200, text='<a href="/dataset/aa-1/resource/bb-2/download/gtfs.zip">x</a> https://opendata.transport.vic.gov.au/dataset/aa-1/resource/bb-2/download/gtfs.zip')
    return R(404)
vf.requests.get = get2
assert vf.find_current_urls() == ["https://opendata.transport.vic.gov.au/dataset/aa-1/resource/bb-2/download/gtfs.zip"], vf.find_current_urls()
# non-404 errors are not swallowed
vf.requests.get = lambda url, **k: R(500)
try: vf.download_regional(OLD, d); raise SystemExit("should raise")
except requests.HTTPError: pass
print("fetch resolve OK")
