"""Build report/README.md (+ screenshots) from live_check.txt and out/shots, for viewing on GitHub."""
import os, shutil, sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rep = os.path.join(ROOT, "report"); shutil.rmtree(rep, ignore_errors=True); os.makedirs(rep + "/shots")
shots = os.path.join(ROOT, "out", "shots")
have = sorted(os.listdir(shots)) if os.path.isdir(shots) else []
for f in have:
    shutil.copy(os.path.join(shots, f), rep + "/shots/" + f)
log = open(os.path.join(ROOT, "live_check.txt")).read() if os.path.exists(os.path.join(ROOT, "live_check.txt")) else "(no live check output)"
mel = datetime.now(timezone(timedelta(hours=11))).strftime("%a %d %b %Y, %H:%M (Melbourne, AEDT)")
problems = log.split("Problems:")[-1].strip().splitlines()[:6] if "Problems:" in log else []
ok = problems[:1] == ["none"] or (problems and problems[0].strip() == "none")

out = [f"# Live check report\n", f"Run: {mel}\n", ("**Result: no problems found.**\n" if ok else "**Result: problems found, see the log at the bottom.**\n")]
for tab, title in (("ballan", "Ballan Services"), ("network", "V/Line Network (geographic map)"), ("victoria", "Full Victorian Network (official map)")):
    out.append(f"\n## {title}\n")
    for w, label in ((1300, "Wide"), (420, "Phone")):
        for scheme in ("light", "dark"):
            f = f"{tab}_{scheme}_{w}.png"
            if f in have:
                out.append(f"<details{' open' if (w, scheme) == (1300, 'light') else ''}><summary>{label}, {scheme}</summary>\n\n![{tab} {label} {scheme}](shots/{f})\n\n</details>\n")
if not have:
    out.append("\n_No screenshots were produced (see the log)._\n")
out.append("\n## Live check log\n\n```\n" + log[-12000:] + "\n```\n")
open(rep + "/README.md", "w").write("\n".join(out))
print("wrote", rep + "/README.md", "with", len(have), "screenshots")
