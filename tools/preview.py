"""Render the real cards with the data from tools/live_check.py.

    python tools/preview.py            # writes out/shots/*.png (needs: pip install playwright; playwright install chromium)
    python tools/preview.py --serve    # serves http://localhost:8000/ (Codespaces forwards the port)

Nothing here is Home Assistant: a small page fakes `hass.states` from out/sensors.json and serves
/local/* from out/ and www/, exactly the files Home Assistant would serve.
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WWW = os.path.join(ROOT, "www")

PAGE = """<!doctype html><meta charset=utf-8><title>Victorian trains: live</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{margin:0;padding:12px;font-family:system-ui,sans-serif;background:#f2f3f5;--card-background-color:#fff;--primary-text-color:#1c1c1e;
--secondary-text-color:#6b6b70;--divider-color:#8885;--primary-color:#0a64d6;--success-color:#2e7d4f;--warning-color:#a86200;--error-color:#c62d2a}
@media (prefers-color-scheme:dark){body{background:#111;--card-background-color:#1c1c1e;--primary-text-color:#f2f2f7;--secondary-text-color:#9a9aa0}}
ha-card{display:block;background:var(--card-background-color);border-radius:14px;max-width:1300px;margin:0 auto 16px}
nav{display:flex;gap:6px;max-width:1300px;margin:0 auto 12px;border-bottom:1px solid var(--divider-color)}
nav a{padding:10px 16px;color:var(--secondary-text-color);text-decoration:none;font-weight:600;border-bottom:3px solid transparent}
nav a.on{color:var(--primary-color);border-color:var(--primary-color)}
.pane{display:none}.pane.on{display:block}.pane.grid{max-width:1300px;margin:0 auto}.pane.grid.on{display:grid;grid-template-columns:1fr 1fr;gap:12px}
</style>
<body>
<nav><a href="#ballan" data-t="ballan">Ballan Services</a><a href="#network" data-t="network">V/Line Network</a><a href="#victoria" data-t="victoria">Full Victorian Network</a></nav>
<div class="pane grid" id=ballan><vline-train-card id=c></vline-train-card><vline-train-card id=d></vline-train-card><vline-journey-card id=e></vline-journey-card><vline-journey-card id=f></vline-journey-card></div>
<div class=pane id=network><vline-network-card id=b></vline-network-card></div>
<div class=pane id=victoria><vic-network-card id=a></vic-network-card></div>
<script type="module" src="/local/vic-network-card.js"></script><script type="module" src="/local/vline-network-card.js"></script><script type="module" src="/local/vline-train-card.js"></script><script type="module" src="/local/vline-journey-card.js"></script>
<script type="module">
const show=()=>{const t=(location.hash||"#ballan").slice(1);
  document.querySelectorAll(".pane").forEach(e=>e.classList.toggle("on",e.id===t));
  document.querySelectorAll("nav a").forEach(e=>e.classList.toggle("on",e.dataset.t===t));};
addEventListener("hashchange",show);show();
const g=id=>document.getElementById(id);
let first=true;
async function load(){
  try{
    const s=await (await fetch("/local/sensors.json?t="+Date.now(),{cache:"no-store"})).json();
    const st={}, now=new Date().toISOString();
    for (const k in s) st[k]={state:String(s[k].state),last_updated:now,attributes:s[k].attributes};
    if(first){first=false;
      g("a").setConfig({}); g("b").setConfig({});
      g("c").setConfig({entity:"sensor.vline_ballan_to_ballarat",title:"Ballan to Ballarat"});
      g("d").setConfig({entity:"sensor.vline_ballan_to_southern_cross",title:"Ballan to Southern Cross",direction:"rtl"});
      g("e").setConfig({title:"Journey planner"});
      g("f").setConfig({title:"Journey planner"});}
    for (const id of ["a","b","c","d","e","f"]) g(id).hass={states:st};
  }catch(e){console.error(e)}
}
load(); setInterval(load,60000);
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(PAGE.encode(), "text/html")
        if p.startswith("/local/"):
            name = os.path.basename(p)
            for d in (OUT, WWW):
                f = os.path.join(d, name)
                if os.path.isfile(f):
                    return self._send(open(f, "rb").read(), mimetypes.guess_type(f)[0] or "application/octet-stream")
        self.send_error(404)

    def _send(self, body, ctype):
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)


class Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):   # browsers abort requests on reload; ignore
        pass


def serve(port):
    return Quiet(("0.0.0.0", port), H)


def shots(port):
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.join(OUT, "shots"), exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            for w in (1300, 420):
                pg = b.new_page(viewport={"width": w, "height": 900}, color_scheme=scheme, device_scale_factor=1)
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                for tab in ("ballan", "network", "victoria"):
                    pg.goto(f"http://localhost:{port}/#{tab}"); pg.reload(); pg.wait_for_timeout(2500)
                    f = os.path.join(OUT, "shots", f"{tab}_{scheme}_{w}.png")
                    pg.screenshot(path=f, full_page=True)
                    print("wrote", f, "| browser errors:", errs[:3] or "none")
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--serve", action="store_true"); ap.add_argument("--port", type=int, default=8000)
    o = ap.parse_args()
    if not os.path.exists(os.path.join(OUT, "sensors.json")):
        sys.exit("Run tools/live_check.py first (it writes out/sensors.json).")
    srv = serve(o.port)
    if o.serve:
        print(f"Open http://localhost:{o.port}/"); srv.serve_forever()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    shots(o.port)
