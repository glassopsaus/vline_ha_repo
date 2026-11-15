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

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{margin:0;padding:12px;font-family:system-ui,sans-serif;background:#f2f3f5;--card-background-color:#fff;--primary-text-color:#1c1c1e;
--secondary-text-color:#6b6b70;--divider-color:#8885;--primary-color:#0a64d6;--success-color:#2e7d4f;--warning-color:#a86200;--error-color:#c62d2a}
@media (prefers-color-scheme:dark){body{background:#111;--card-background-color:#1c1c1e;--primary-text-color:#f2f2f7;--secondary-text-color:#9a9aa0}}
ha-card{display:block;background:var(--card-background-color);border-radius:14px;max-width:1300px;margin:0 auto 16px}
</style>
<body><vic-network-card id=a></vic-network-card><vline-network-card id=b></vline-network-card>
<script type="module" src="/local/vic-network-card.js"></script><script type="module" src="/local/vline-network-card.js"></script>
<script type="module">
fetch("/local/sensors.json").then(r=>r.json()).then(s=>{
  const st={}, now=new Date().toISOString();
  for (const k in s) st[k]={state:String(s[k].state),last_updated:now,attributes:s[k].attributes};
  const a=document.getElementById("a"), b=document.getElementById("b");
  a.setConfig({}); b.setConfig({title:"V/Line network"});
  a.hass=b.hass={states:st};
});
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


def serve(port):
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    return srv


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
                pg.goto(f"http://localhost:{port}/"); pg.wait_for_timeout(2500)
                f = os.path.join(OUT, "shots", f"{scheme}_{w}.png")
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
