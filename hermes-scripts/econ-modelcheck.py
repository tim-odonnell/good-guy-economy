#!/usr/bin/env python3
"""Model fact check for Good-Guy-Economy's morning report (Hermes job good-guy-economy-factcheck, script only, after MORNING).

The script checks in econ_factcheck.py can't read prose against a source ("the goods and services deficit rose
to $136.6 billion" when the source said that of the *goods* deficit). This stage asks the model narrow
questions, one claim at a time, with the source text beside it, and lets the SCRIPT make every change:

  news-note bullet  -> fetch the bullet's SOURCE page; model answers OK / WRONG / NOT IN SOURCE.
                       WRONG (or NOT IN SOURCE with the same numbers in the source) -> the bullet is replaced
                       by the closest sentence copied from the source, never by the model's own wording.
                       NOT IN SOURCE otherwise -> the bullet is removed. No source text -> left as is, marked unchecked.
  morning sentence  -> model answers OK / WRONG against tonight's computed facts; WRONG -> removed by econ-report.

Talks to the model server directly (no agent, thinking off, ~300-token prompts), so each claim costs about a
minute at night instead of a 12-minute agent prefill. Writes reports/factcheck/<date>-model.json and
reports/factcheck/<date>-notes.md; econ-report uses both. Stops at DEADLINE and leaves the rest unchecked.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import econ_factcheck as F  # noqa: E402
import econ_lib as e  # noqa: E402

BASE = e.BASE
TODAY = e.TODAY
URL = "http://127.0.0.1:8099/v1/chat/completions"
MODEL = "good-guy-economy-llm"
DEADLINE = 50 * 60  # Hermes kills job scripts after 60 min
WAIT_FOR_MORNING = 40 * 60  # if MORNING's reply isn't saved yet, wait this long for it
START = time.time()
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
STOP = set("the a an of in to and for on at by from with that this was were is are be as its it than more less".split())


def ask(prompt, max_tokens=120):
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return (json.load(r)["choices"][0]["message"].get("content") or "").strip()


def nums(text):
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(text)}


def words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2}


def source_sentences(text):
    out = []
    for para in text.splitlines():
        out += [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", para) if len(s.strip()) > 30]
    return out


def closest(claim, sents, k=3):
    """The k source sentences sharing the most numbers and words with the claim."""
    cn, cw = nums(claim), words(claim)
    scored = sorted(sents, key=lambda s: (3 * len(cn & nums(s)) + len(cw & words(s))), reverse=True)
    return scored[:k]


def fetch_source(url, pack):
    """Full text of the bullet's source: the page itself, else tonight's reading-pack text for that URL."""
    texts = [p["text"] for p in pack if p.get("url") == url or url.rstrip("/").endswith(p.get("url", "#").rsplit("/", 1)[-1])]
    try:
        _, _, text = e.excerpt(url, limit=8000)
        if text:
            texts.insert(0, text)
    except Exception:
        pass
    return "\n".join(texts)


def parse_notes(notes):
    """[(block title, source url, [bullet lines], start/end positions)] from the COLLECT notes."""
    blocks = []
    for m in re.finditer(r"^###\s*(.+?)\n(.*?)(?=^###\s|^## |\Z)", notes, re.M | re.S):
        body = m.group(2)
        src = re.search(r"^SOURCE:.*?(https?://[^\s)]+)", body, re.M)
        bullets = re.findall(r"^- \[(DATA|REPORTED|OPINION)\]\s*(.+)$", body, re.M)
        blocks.append((m.group(1).strip(), src.group(1) if src else "", bullets))
    return blocks


NOTE_PROMPT = """You check one news note against the official source text.

SOURCE TEXT:
{src}

NOTE: {claim}

Is the note correct according to the source text? Check every number AND what it describes (which deficit,
which month, which group, up or down). Reply with exactly one line, one of:
OK
WRONG: <the correct sentence, copied from the source text>
NOT IN SOURCE"""

SENTENCE_PROMPT = """You check one sentence of an economy note against tonight's computed facts.

FACTS:
{facts}

SENTENCE: {claim}

Check only facts: numbers, dates, counts, which indicator is higher or lower, up or down, what history shows.
Opinions and forecasts are fine. Reply with exactly one line, one of:
OK
WRONG: <what is wrong, in a few words>"""


def verdict(reply):
    first = reply.strip().splitlines()[0].strip().strip("*").strip() if reply.strip() else ""
    up = first.upper()
    if up.startswith("OK"):
        return "OK", ""
    if up.startswith("WRONG"):
        return "WRONG", first.split(":", 1)[1].strip() if ":" in first else ""
    if up.startswith("NOT IN SOURCE"):
        return "NOT IN SOURCE", ""
    return "UNCLEAR", first[:200]


def check_notes(notes, pack, log):
    out_lines = notes.splitlines()
    for title, url, bullets in parse_notes(notes):
        if not url or not bullets:
            continue
        text = fetch_source(url, pack)
        sents = source_sentences(text)
        for tag, claim in bullets:
            line = f"- [{tag}] {claim}"
            item = {"block": title, "source": url, "original": line}
            log["notes"].append(item)
            if time.time() - START > DEADLINE:
                item.update(action="unchecked", reason="out of time")
                continue
            if not sents:
                item.update(action="unchecked", reason="source text could not be fetched")
                continue
            ev = closest(claim, sents)
            try:
                v, fix = verdict(ask(NOTE_PROMPT.format(src="\n".join(ev), claim=claim)))
            except Exception as ex:
                item.update(action="unchecked", reason=f"model call failed ({type(ex).__name__})")
                continue
            missing = nums(claim) - nums(text)
            item["model"] = v
            if v == "OK" and not missing:
                item["action"] = "kept"
                continue
            if v == "UNCLEAR":
                item.update(action="unchecked", reason=f"model reply not understood: {fix}")
                continue
            # WRONG, NOT IN SOURCE, or "OK" with numbers the source doesn't have: the script decides
            best = closest(claim + " " + fix, sents, k=1)[0]
            same_facts = nums(claim) and nums(claim) <= nums(best)
            if v == "WRONG" or same_facts or (v == "OK" and missing and nums(best) & nums(claim)):
                new = f"- [{tag}] {best}"
                why = f"model said {v}" + (f" ({fix})" if fix else "") + (f"; numbers not in source: {', '.join(sorted(missing))}" if missing else "")
                item.update(action="replaced", new=new, reason=why + " - replaced with the source's own sentence")
                out_lines = [new + "  _(corrected by fact check)_" if l == line else l for l in out_lines]
            else:
                why = f"model said {v}" + (f"; numbers not in source: {', '.join(sorted(missing))}" if missing else "")
                item.update(action="removed", reason=why)
                out_lines = [l for l in out_lines if l != line]
    return "\n".join(out_lines) + "\n"


def facts_text(d, hist):
    rows = [f"- {i['label']}: {e.fmt(i['value'])} {i['unit']} for {i.get('period_label') or i['period']}"
            + (f" (previous {e.fmt(i['prev'][1])})" if i.get("prev") else "") for i in d["indicators"]]
    return "KEY NUMBERS\n" + "\n".join(rows) + ("\n\nHISTORY\n" + e.history_text(hist) if hist else "")


def check_meaning(meaning, d, hist, log):
    facts = facts_text(d, hist)
    for s in F.sentences(meaning):
        item = {"sentence": s}
        log["meaning"].append(item)
        if time.time() - START > DEADLINE:
            item.update(action="unchecked", reason="out of time")
            continue
        try:
            v, why = verdict(ask(SENTENCE_PROMPT.format(facts=facts, claim=s)))
        except Exception as ex:
            item.update(action="unchecked", reason=f"model call failed ({type(ex).__name__})")
            continue
        item["model"] = v
        item.update(action="remove" if v == "WRONG" else "kept", reason=why)


def main():
    # wait for the MODEL's morning reply only when the model writes it - a script-written note has no reply to wait for
    while not e.scripted("morning") and not e.responses("good-guy-economy-morning") and time.time() - START < WAIT_FOR_MORNING:
        time.sleep(60)
    e.harvest()
    try:
        d = json.loads((BASE / f"data/digest/{TODAY}.json").read_text())
    except Exception:
        print("FACTCHECK: no digest for today - nothing to check")
        return
    try:
        hist = json.loads((BASE / f"data/history/{TODAY}.json").read_text())
    except Exception:
        hist = None
    log = {"date": TODAY.isoformat(), "notes": [], "meaning": []}
    notes_f = BASE / f"corpus/raw/{TODAY}_collect-notes.md"
    out = BASE / "reports/factcheck"
    out.mkdir(parents=True, exist_ok=True)
    if notes_f.exists():
        (out / f"{TODAY}-notes.md").write_text(check_notes(notes_f.read_text(), d.get("pack", []), log))
    take_f = BASE / f"reports/drafts/{TODAY}-take.md"
    if take_f.exists() and not e.scripted("morning"):  # a script-written note only states computed facts
        meaning = F.morning_meaning(take_f.read_text())
        script_flags = {s for s, _ in F.check(meaning, d, hist)}  # those go anyway; don't spend model time on them
        check_meaning(F.remove(meaning, [(s, []) for s in script_flags]), d, hist, log)
    log["seconds"] = round(time.time() - START)
    (out / f"{TODAY}-model.json").write_text(json.dumps(log, indent=1))
    n = log["notes"] + log["meaning"]
    count = lambda a: sum(1 for x in n if x.get("action") == a)  # noqa: E731
    print(f"FACTCHECK {TODAY}: {len(n)} claims in {log['seconds']} s - kept {count('kept')}, replaced {count('replaced')}, "
          f"removed {count('removed') + count('remove')}, unchecked {count('unchecked')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"FACTCHECK FAILED: {type(ex).__name__}: {ex}")
