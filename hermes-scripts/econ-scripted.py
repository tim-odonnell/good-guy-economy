#!/usr/bin/env python3
"""Script versions of the BRAINSTORM / SCENARIO / REFINE / MORNING stages (Good-Guy-Economy, no model).

Run as a Hermes no_agent job through econ-script-<mode>.py, or by hand: econ-scripted.py <mode>.
Each stage reads the data the scripts already computed (digest + history pack), writes the same files the
model's reply used to be harvested into, and prints one summary line. A non-zero exit marks the stage
failed, so econ-report builds a PARTIAL report exactly as before.
Switch between script and model stages with `econ-stages script|model|status`.
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import econ_lib as e  # noqa: E402
import econ_stages as st  # noqa: E402

BASE = e.BASE
TODAY = e.TODAY
CALL_DAYS = 35  # a call is checked after about one monthly release cycle
STATE = BASE / "data/calls-state.json"
SCORECARD = BASE / "data/calls-scorecard.json"
WORD = {"rising": "up", "falling": "down", "steady": "flat"}


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def digest():
    d = load_json(BASE / f"data/digest/{TODAY}.json", None)
    if not d or not d.get("indicators"):
        sys.exit(f"no digest for {TODAY} (COLLECT did not run today) - nothing to work from")
    return d


def pack():
    p = load_json(BASE / f"data/history/{TODAY}.json", None)
    if p:
        return p
    p = e.history_pack()
    f = BASE / f"data/history/{TODAY}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(p, indent=1))
    return p


def stamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def scenario():
    text = st.scenario_text(pack(), f"{TODAY:%Y%m%d}")
    with open(BASE / "theories/scenarios.md", "a") as f:
        f.write(f"\n<!-- SCENARIO script run {stamp()} -->\n{text}\n")
    return f"SCENARIO (script): {text.count('### S-')} history comparisons; {text.strip().splitlines()[-1]}"


def morning():
    text = st.morning_text(pack(), digest())
    # "What changed" (just above it in the report) already lists the new data, so end with the calls instead
    state = load_json(STATE, {})
    if state:
        calls = ", ".join(f"{t.lower()} {WORD[state[t]['direction']]}" for t, _ in st.TOPICS if t in state)
        text = re.sub(r" (New since the last report: .*|No new official data since the last report\.)$",
                      f" Direction of the latest readings: {calls}.", text)
    dest = BASE / f"reports/drafts/{TODAY}-take.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text + "\n")
    return f"MORNING (script): {len(text.split())} words -> {dest.relative_to(BASE)}"


def brainstorm():
    by_id = {i["id"]: i for i in digest()["indicators"]}
    state = load_json(STATE, {})
    card = load_json(SCORECARD, [])
    rules_of = dict(st.TOPICS)
    texts, notes = [], []
    for n, (topic, rules) in enumerate(st.TOPICS, 1):
        call = st.make_call(topic, rules, by_id)
        old = state.get(topic)
        if old:
            due = TODAY.isoformat() > old["check_by"]
            changed = old["direction"] != call["direction"]
            if not due and not changed:
                # same call, still running: keep its start date, baseline and test; refresh the evidence
                call.update({k: old[k] for k in ("key_id", "key_value", "wrong_if")})
                texts.append(st.call_text(n, call, old["check_by"]))
                state[topic] = dict(old, confidence=call["confidence"])
                continue
            now = (by_id.get(old["key_id"]) or {}).get("value")
            rule = next((r for r in rules_of[topic] if r[0] == old["key_id"]), None)
            result = st.score(old["direction"], rule[1], rule[2], old["key_value"], now) if now is not None and rule else "NOT SCORED"
            card.append({"topic": topic, "direction": old["direction"], "made": old["made"], "closed": TODAY.isoformat(),
                         "why_closed": "check date reached" if due else f"direction changed to {call['direction']}",
                         "key_id": old["key_id"], "from": old["key_value"], "to": now, "result": result})
            notes.append(f"{topic} {old['direction']} -> {result}")
        check_by = (TODAY + timedelta(days=CALL_DAYS)).isoformat()
        texts.append(st.call_text(n, call, check_by))
        state[topic] = {"direction": call["direction"], "confidence": call["confidence"], "made": TODAY.isoformat(),
                        "key_id": call["key_id"], "key_value": call["key_value"], "wrong_if": call["wrong_if"], "check_by": check_by}
    reply = "\n".join(texts)
    hist = BASE / "theories/history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{stamp()}-brainstorm-script.md").write_text(reply)
    (BASE / "theories/brainstorm-latest.md").write_text(f"<!-- from econ-scripted brainstorm {stamp()} -->\n{reply}")
    e._replace_calls(reply)
    STATE.write_text(json.dumps(state, indent=1))
    SCORECARD.write_text(json.dumps(card, indent=1))
    calls = ", ".join(f"{t} {state[t]['direction']}" for t, _ in st.TOPICS)
    refine()  # keep the "Where the economy is heading" summary in step with today's calls (seconds, not weekly)
    return f"BRAINSTORM (script): {calls}" + (f"; scored: {'; '.join(notes)}" if notes else "")


def refine():
    by_id = {i["id"]: i for i in digest()["indicators"]}
    state = load_json(STATE, {})
    if not state:
        sys.exit("no direction calls yet - run the brainstorm stage first")
    card = load_json(SCORECARD, [])
    lines = ["Where the economy is heading:"]
    texts = []
    for n, (topic, rules) in enumerate(st.TOPICS, 1):
        call = st.make_call(topic, rules, by_id)
        s = state[topic]
        reason = (call["for"] or call["against"] or ["no data"])[0]
        lines.append(f"- {topic}: {WORD[s['direction']]} ({s['confidence']} confidence) - {reason}")
        call.update({k: s[k] for k in ("direction", "confidence", "key_id", "key_value", "wrong_if")})
        texts.append(st.call_text(n, call, s["check_by"]))
    scored = [c for c in card if c["result"] in ("RIGHT", "WRONG", "NO CHANGE")]
    if scored:
        r = sum(c["result"] == "RIGHT" for c in scored)
        w = sum(c["result"] == "WRONG" for c in scored)
        lines.append(f"- Scorecard so far: {r} right, {w} wrong, {len(scored) - r - w} no change, of {len(scored)} calls checked")
    else:
        lines.append("- Scorecard so far: no call has reached its check date yet")
    reply = "\n".join(lines) + "\n\n" + "\n".join(texts)
    (BASE / "theories/history").mkdir(parents=True, exist_ok=True)
    (BASE / f"theories/history/{stamp()}-refine-script.md").write_text(reply)
    (BASE / "theories/refine-latest.md").write_text(f"<!-- from econ-scripted refine {stamp()} -->\n{reply}")
    e._replace_calls(reply, refine=True)
    return "REFINE (script): " + lines[-1][2:]


STAGES = {"SCENARIO": scenario, "MORNING": morning, "BRAINSTORM": brainstorm, "REFINE": refine}


def main():
    mode = (globals().get("FORCED_MODE") or (sys.argv[1] if len(sys.argv) > 1 else "")).upper()
    if mode not in STAGES:
        sys.exit("usage: econ-scripted.py brainstorm|scenario|refine|morning")
    e.harvest()  # save COLLECT's notes (and any model replies) first, as the model stages' pre-scripts did
    print(STAGES[mode]())


if __name__ == "__main__":
    main()
