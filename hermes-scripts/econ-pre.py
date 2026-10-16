#!/usr/bin/env python3
"""Pre-run context for BRAINSTORM / SCENARIO / REFINE / MORNING (Good-Guy-Economy, US economy).

First saves every earlier job reply into the corpus (harvest), then prints exactly the
context the job needs, so the model reads a short brief instead of hunting through files.
The job is chosen by the name this file is called through (econ-pre-<mode>.py symlinks).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import econ_lib as e  # noqa: E402

BASE = e.BASE
MODE = globals().get("FORCED_MODE") or Path(sys.argv[0]).stem.replace("econ-pre-", "").upper()


def section(title, body):
    if body and body.strip():
        print(f"\n=== {title} ===\n{body.strip()}")


def main():
    saved = e.harvest()
    print(f"CONTEXT for {MODE} — {e.TODAY:%A %Y-%m-%d} (this IS today's date; no need to run date)")
    if e.gap_line() and e.gap_days() > 1:
        print(e.gap_line() + " The notes and data below already cover the whole gap.")
    if saved:
        print("Saved earlier replies: " + ", ".join(sorted(set(saved))))
    subj = (BASE / "subjects.md").read_text() if (BASE / "subjects.md").exists() else ""
    table = "\n".join(l for l in subj.splitlines() if l.startswith("|"))
    section("KEY NUMBERS (FRED, fetched by script)", table)
    notes = BASE / f"corpus/raw/{e.TODAY}_collect-notes.md"
    if notes.exists():
        txt = notes.read_text()
        section("TODAY'S NEWS NOTES (from COLLECT)", txt[-3500:])
    hist_f = BASE / f"data/history/{e.TODAY}.json"
    try:
        hist = json.loads(hist_f.read_text())
    except Exception:
        try:
            hist = e.history_pack()
            hist_f.parent.mkdir(parents=True, exist_ok=True)
            hist_f.write_text(json.dumps(hist, indent=1))
        except Exception as ex:
            hist = None
            print(f"\n(history pack failed: {type(ex).__name__})")
    if hist:
        section("TODAY VS HISTORY (computed by script from FRED + NBER recession dates)", e.history_text(hist))
    calls = e.open_calls_brief()
    section("CURRENT DIRECTION CALLS", "\n".join(calls) if calls else "(none yet)")
    if MODE in ("BRAINSTORM", "REFINE"):
        active = (BASE / "theories/active.md").read_text() if (BASE / "theories/active.md").exists() else ""
        full = "\n".join(m.group(0).strip() for m in re.finditer(r"^###\s*T-\d+.*?(?=^###\s|\Z)", active, flags=re.M | re.S))
        section("FULL TEXT OF CURRENT CALLS", full[:4000])
    if MODE == "MORNING":
        try:
            d = json.loads((BASE / f"data/digest/{e.TODAY}.json").read_text())
            section("WHAT CHANGED (already written by script for the report — do not repeat it)", "\n".join(e.what_changed(d)))
            section("WATCH NEXT (already written by script from official calendars)", "\n".join(e.watch_next(d.get("upcoming") or [])) or "none in the next 3 weeks")
            new = [f"- {i['label']}: {e.fmt(i['value'])} {i['unit']} for {i.get('period_label', i['period'])}" for i in d["indicators"] if i["new"]]
            section("NEW DATA SINCE THE LAST RUN", "\n".join(new) or "none")
            section("ALERTS", "\n".join(d.get("alerts") or []) or "none")
        except Exception:
            pass
        latest = sorted((BASE / "theories/history").glob(f"{e.TODAY}_*"))
        scen = [p for p, _ in e.responses("good-guy-economy-scenario")]
        if scen:
            section("TODAY'S HISTORY NOTE (from SCENARIO)", scen[-1].read_text().split("## Response", 1)[1].strip()[:1500])


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"CONTEXT SCRIPT FAILED: {type(ex).__name__}: {ex} — read subjects.md and theories/ yourself")
