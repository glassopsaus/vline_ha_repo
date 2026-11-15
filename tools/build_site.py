"""Build site/ (static GitHub Pages site) from out/ and www/.  Run after tools/live_check.py."""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview

ROOT = preview.ROOT
site = os.path.join(ROOT, "site"); loc = os.path.join(site, "local")
shutil.rmtree(site, ignore_errors=True); os.makedirs(loc)
for f in os.listdir(preview.WWW):
    src = os.path.join(preview.WWW, f)
    if f.endswith(".js"):
        open(os.path.join(loc, f), "w").write(open(src).read().replace('"/local/', '"./local/'))
    else:
        shutil.copy(src, loc)
for f in ("sensors.json", "vline_network.json", "vic_metro_network.json", "vline_journeys.json"):
    shutil.copy(os.path.join(preview.OUT, f), loc)
open(os.path.join(site, "index.html"), "w").write(preview.PAGE.replace("/local/", "./local/"))
open(os.path.join(site, ".nojekyll"), "w").write("")
print("site built:", sorted(os.listdir(loc)))
