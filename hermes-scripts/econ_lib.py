"""Shared helpers for Good-Guy-Economy's US-economy scripts (stdlib only).

- fetching with per-site client names (FRED and BLS disagree about what they accept)
- harvesting each cron job's final reply into the corpus. E2B reliably writes a good
  final reply but rarely calls write_file, so the reply IS the deliverable and the
  scripts do the saving.
- the "today vs history" pack: fixed conditions checked against decades of FRED data,
  and the recession warning-light panel. Computed here, never by the model.
"""
import json
import re
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path.home() / ".hermes/investigations/active"
JOBS_FILE = Path.home() / ".hermes/cron/jobs.json"
OUTPUT_DIR = Path.home() / ".hermes/cron/output"
TODAY = date.today()
UA = "good-guy-economy-research/1.0 (personal economic research; python-urllib)"


# ---------------------------------------------------------------- fetching
def get(url, timeout=20):
    """FRED blocks custom and browser names but accepts Python's default; BLS is the opposite."""
    order = [None, UA] if "stlouisfed.org" in url else [UA, None]
    last = None
    for ua in order:
        headers = {"Accept": "*/*"}
        if ua:
            headers["User-Agent"] = ua
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
    raise last


def fred_monthly(series, tr="lin"):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&fq=Monthly&transformation={tr}"
    rows = []
    for line in get(url, timeout=30).splitlines()[1:]:
        d, _, v = line.partition(",")
        if v.strip() not in ("", "."):
            rows.append((d[:7], float(v)))
    return rows


def fmt(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"


# ---------------------------------------------------------------- harvesting
def job_ids():
    try:
        d = json.loads(JOBS_FILE.read_text())
        return {j["name"]: j["id"] for j in (d["jobs"] if isinstance(d, dict) else d)}
    except Exception:
        return {}


def scripted(stage):
    """True when the stage runs as a script (no_agent job, `econ-stages script`); False when the model writes it."""
    try:
        jobs = json.loads(JOBS_FILE.read_text())
        jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
    except Exception:
        return False
    return bool(next((j for j in jobs if j.get("name") == f"good-guy-economy-{stage}"), {}).get("no_agent"))


def responses(job_name, day=TODAY):
    """[(output_path, reply_text)] for a job's runs on `day`, oldest first."""
    jid = job_ids().get(job_name)
    if not jid:
        return []
    out = []
    for p in sorted((OUTPUT_DIR / jid).glob(f"{day}_*.md")):
        t = p.read_text(errors="replace")
        if "## Response" not in t:
            continue
        reply = t.split("## Response", 1)[1].strip()
        if reply and reply != "[SILENT]":
            out.append((p, reply))
    return out


def _harvested():
    f = BASE / "data/harvest-state.json"
    try:
        return f, set(json.loads(f.read_text()))
    except Exception:
        return f, set()


def harvest():
    """Save every not-yet-saved job reply into the corpus. Idempotent. Returns list of what was saved."""
    state_file, done = _harvested()
    saved = []
    for p, reply in responses("good-guy-economy-collect"):
        if p.name in done:
            continue
        stamp = p.stem.replace("_", " ")[:16]
        dest = BASE / f"corpus/raw/{TODAY}_collect-notes.md"
        head = "" if dest.exists() else (f"SOURCE: COLLECT run replies (model notes; each item names its own source)\n"
                                         f"ACCESSED: {TODAY}\n\n")
        with open(dest, "a") as f:
            f.write(f"{head}## COLLECT run {stamp}\n\n{reply}\n\n")
        done.add(p.name)
        saved.append(str(dest.relative_to(BASE)))
    for job, dest_name in (("good-guy-economy-brainstorm", "theories/brainstorm-latest.md"),
                           ("good-guy-economy-refine", "theories/refine-latest.md")):
        for p, reply in responses(job):
            if p.name in done:
                continue
            if "### T-" in reply or "heading" in reply.lower():
                hist = BASE / "theories/history"
                hist.mkdir(parents=True, exist_ok=True)
                (hist / f"{p.stem}-{job.split('-')[1]}.md").write_text(reply + "\n")
                (BASE / dest_name).write_text(f"<!-- from {job} run {p.stem} -->\n{reply}\n")
                if job == "good-guy-economy-brainstorm":
                    _replace_calls(reply)
                else:
                    _replace_calls(reply, refine=True)
                saved.append(dest_name)
            done.add(p.name)
    for p, reply in responses("good-guy-economy-scenario"):
        if p.name in done:
            continue
        with open(BASE / "theories/scenarios.md", "a") as f:
            f.write(f"\n<!-- SCENARIO run {p.stem} -->\n{reply}\n")
        done.add(p.name)
        saved.append("theories/scenarios.md")
    for p, reply in responses("good-guy-economy-morning"):
        if p.name in done:
            continue
        dest = BASE / f"reports/drafts/{TODAY}-take.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(reply + "\n")
        done.add(p.name)
        saved.append(str(dest.relative_to(BASE)))
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(sorted(done)[-400:]))
    return saved


def _replace_calls(reply, refine=False):
    """Replace the direction calls in theories/active.md with the reply's T- entries (and, for REFINE,
    the 'Where the economy is heading' summary). Only if the reply really contains entries."""
    path = BASE / "theories/active.md"
    text = path.read_text() if path.exists() else "# Direction calls\n"
    calls = re.findall(r"^###\s*T-\d+.*?(?=^###\s|\Z)", reply, flags=re.M | re.S)
    summary = ""
    if refine:
        m = re.search(r"(Where the economy is heading.*?)(?=^###\s*T-|\Z)", reply, flags=re.S | re.I | re.M)
        summary = m.group(1).strip() if m else ""
    if not calls and not summary:
        return
    calls = [sanitize_history_line(c) for c in calls]
    old_summary = re.search(r"<!-- SUMMARY START -->(.*?)<!-- SUMMARY END -->", text, re.S)
    summary_block = summary or (old_summary.group(1).strip() if old_summary else "")
    # never keep T- entries inside the summary block (an older regex bug put the previous calls there)
    summary_block = re.split(r"^###\s*T-", summary_block, maxsplit=1, flags=re.M)[0].strip()
    out = ["# Direction calls", "",
           "Kept current by scripts from the BRAINSTORM / REFINE replies (dated copies in theories/history/).", ""]
    if summary_block:
        out += ["<!-- SUMMARY START -->", summary_block, "<!-- SUMMARY END -->", ""]
    if calls:
        out += [c.strip() + "\n" for c in calls[:8]]
    else:
        out += [c.strip() + "\n" for c in re.findall(r"^###\s*T-\d+.*?(?=^###\s|\Z)", text, flags=re.M | re.S)]
    path.write_text("\n".join(out) + "\n")


def sanitize_history_line(call):
    """E2B tends to invent or reverse history ('preceded past recessions' when the record is 0 of 3).
    Keep a HISTORY SAYS line only if it quotes one of today's computed MEANING verdicts (or says no match)."""
    try:
        pack = json.loads((BASE / f"data/history/{TODAY}.json").read_text())
        verdicts = [c["verdict"] for c in pack["conditions"] if c.get("verdict")]
    except Exception:
        return call
    def fix(m):
        line = m.group(1)
        low = line.lower()
        if re.search(r"\bno (specific |computed )?(history )?match", low) or any(v[:40].lower() in low for v in verdicts):
            return m.group(0)
        return "- HISTORY SAYS: (removed by script - it did not quote a computed MEANING line)"
    return re.sub(r"^-\s*HISTORY SAYS:(.*)$", fix, call, flags=re.M)


def open_calls_brief(limit=8):
    text = (BASE / "theories/active.md").read_text() if (BASE / "theories/active.md").exists() else ""
    out = []
    for m in re.finditer(r"^###\s*(T-\d+.*)$(.*?)(?=^###\s|\Z)", text, flags=re.M | re.S):
        conf = re.search(r"CONFIDENCE:\s*(.+)", m.group(2))
        out.append(f"- {m.group(1).strip()} (confidence {conf.group(1).strip() if conf else '?'})")
    return out[:limit]


# ---------------------------------------------------------------- history pack
# (key, plain-English condition, series, transform, op, threshold, is_recession_warning_light)
# ops: above, below, rise-from-low (pt above its 12-month low), pct-rise-from-low (% above 12-month low),
#      avg3-below (3-month average below threshold)
CONDITIONS = [
    ("unemp-rising", "Unemployment up 0.5 pt or more from its 12-month low", "UNRATE", "lin", "rise-from-low", 0.5, True),
    ("curve-3m-inverted", "Yield curve inverted (10-yr below 3-month)", "T10Y3M", "lin", "below", 0, True),
    ("curve-2y-inverted", "Yield curve inverted (10-yr below 2-yr)", "T10Y2Y", "lin", "below", 0, True),
    ("claims-rising", "Jobless claims 20%+ above their 12-month low", "ICSA", "lin", "pct-rise-from-low", 20, True),
    ("credit-widening", "Corporate bond spread 1 pt+ above its 12-month low", "BAA10Y", "lin", "rise-from-low", 1.0, True),
    ("industry-shrinking", "Industrial production lower than a year ago", "INDPRO", "pc1", "below", 0, True),
    ("housing-slump", "Housing starts 15%+ below a year ago", "HOUST", "pc1", "below", -15, True),
    ("payrolls-weak", "Job growth under 50k a month (3-month average)", "PAYEMS", "chg", "avg3-below", 50, True),
    ("sentiment-low", "Consumer sentiment below 60", "UMCSENT", "lin", "below", 60, False),
    ("oil-shock", "Oil price up 50%+ from a year ago", "DCOILWTICO", "pc1", "above", 50, False),
    ("rates-jump", "10-yr Treasury yield up 1 pt+ from a year ago", "DGS10", "ch1", "above", 1.0, False),
    ("inflation-high", "CPI inflation above 3%", "CPIAUCSL", "pc1", "above", 3, False),
    ("fed-hiking", "Fed funds rate up 1 pt+ from a year ago", "FEDFUNDS", "ch1", "above", 1.0, False),
    ("fed-cutting", "Fed funds rate down 1 pt+ from a year ago", "FEDFUNDS", "ch1", "below", -1.0, False),
    ("mortgage-high", "30-yr mortgage rate above 7%", "MORTGAGE30US", "lin", "above", 7, False),
]


LATEST_FROM_DAILY = {"T10Y3M", "T10Y2Y", "ICSA", "BAA10Y", "DCOILWTICO", "DGS10", "MORTGAGE30US"}


def fred_daily(series, days=800):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={(TODAY - timedelta(days=days)).isoformat()}"
    rows = []
    for line in get(url, timeout=30).splitlines()[1:]:
        d, _, v = line.partition(",")
        if v.strip() not in ("", "."):
            rows.append((d[:10], float(v)))
    return rows


def umich_latest():
    """Newest consumer sentiment from the University of Michigan's own page. FRED only gets it about a month later
    (licence), so on 2026-10-10 FRED still had August while UMich had September final and October preliminary.
    Returns {"period": "YYYY-MM", "value", "prev", "year_ago", "prelim"}."""
    raw = get("https://www.sca.isr.umich.edu/")
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    m = re.search(r"(Preliminary|Final) Results for ([A-Z][a-z]+) (\d{4}).*?Index of Consumer Sentiment ([\d.]+) ([\d.]+) ([\d.]+)", t)
    if not m or m.group(2)[:3].lower() not in _MONTHS:
        raise ValueError("UMich page layout not recognised")
    return {"period": f"{m.group(3)}-{_MONTHS[m.group(2)[:3].lower()]:02d}", "value": float(m.group(4)),
            "prev": float(m.group(5)), "year_ago": float(m.group(6)), "prelim": m.group(1) == "Preliminary"}


def _latest_status(sid, tr, op, thr):
    """(condition true?, value, date) from the newest daily/weekly reading (or UMich's own page for sentiment)."""
    if sid == "UMCSENT":
        u = umich_latest()
        v = u["value"]
        return (v > thr if op == "above" else v < thr), v, u["period"] + (" prelim" if u["prelim"] else "")
    rows = fred_daily(sid)
    d, v = rows[-1]
    yr = (date.fromisoformat(d) - timedelta(days=365)).isoformat()
    if tr in ("pc1", "ch1"):
        base = [x for dd, x in rows if dd <= yr][-1]
        v = (v / base - 1) * 100 if tr == "pc1" else v - base
    if op == "above":
        ok = v > thr
    elif op == "below":
        ok = v < thr
    else:  # rise-from-low / pct-rise-from-low over the last 12 months of readings
        low = min(x for dd, x in rows if dd >= yr)
        ok = (v - low >= thr) if op == "rise-from-low" else (low > 0 and (v / low - 1) * 100 >= thr)
    return ok, round(v, 2), d


def _flags(rows, op, thr):
    vals = [v for _, v in rows]
    out = []
    for i, v in enumerate(vals):
        win = vals[max(0, i - 12):i + 1]
        if op == "above":
            ok = v > thr
        elif op == "below":
            ok = v < thr
        elif op == "avg3-below":
            ok = i >= 2 and sum(vals[i - 2:i + 1]) / 3 < thr
        elif len(win) < 13:
            ok = False
        elif op == "rise-from-low":
            ok = v - min(win) >= thr
        else:  # pct-rise-from-low
            ok = min(win) > 0 and (v / min(win) - 1) * 100 >= thr
        out.append(ok)
    return out


def _months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def history_pack():
    """Check every condition now, and for each one that holds, what followed each past time it began."""
    rec = dict(fred_monthly("USREC"))
    months = sorted(rec)
    rec_starts = [m for i, m in enumerate(months) if rec[m] == 1 and (i == 0 or rec[months[i - 1]] == 0)]
    def base12_since(since):
        """Share of non-recession months (from `since` on) followed by a recession start within 12 months."""
        nonrec = [m for m in months if m >= since and rec[m] == 0 and _months_between(m, months[-1]) >= 12]
        if not nonrec:
            return None
        return sum(1 for m in nonrec if any(0 < _months_between(m, r) <= 12 for r in rec_starts)) / len(nonrec)
    unrate = dict(fred_monthly("UNRATE"))
    cpi = dict(fred_monthly("CPIAUCSL", "pc1"))
    results, flags_by_key, failed = [], {}, []
    for key, text, sid, tr, op, thr, light in CONDITIONS:
        try:
            rows = fred_monthly(sid, tr)
        except Exception as e:
            failed.append(f"{sid} ({type(e).__name__})")
            continue
        fl = _flags(rows, op, thr)
        flags_by_key[key] = dict(zip([d for d, _ in rows], fl))
        mon_d = rows[-1][0]
        # "true now" comes from the newest reading, not the last monthly average: a monthly average lags a
        # daily or weekly series by up to 5 weeks (on 2026-10-10 it showed the 7.40% mortgage rate as "not above 7%")
        now_flag, now_v, now_d = fl[-1], rows[-1][1], mon_d
        if sid in LATEST_FROM_DAILY or sid == "UMCSENT":
            try:
                now_flag, now_v, now_d = _latest_status(sid, tr, op, thr)
            except Exception as e:
                failed.append(f"{sid} newest reading ({type(e).__name__}; used the monthly average)")
        episodes = []
        for (d, _), ok in zip(rows, fl):
            if ok and (not episodes or _months_between(episodes[-1][1], d) > 6):
                episodes.append([d, d])
            elif ok:
                episodes[-1][1] = d
        past = []
        for start, end in episodes:
            if _months_between(start, mon_d) < 6 and fl[-1]:
                continue  # the current episode
            nxt = next((r for r in rec_starts if r >= start), None)
            lead = _months_between(start, nxt) if nxt else None
            in_rec = rec.get(start) == 1
            u12 = _at(unrate, start, 12)
            c12 = _at(cpi, start, 12)
            past.append({"start": start, "end": end, "in_recession": in_rec, "lead": lead,
                         "unemp_change_12m": None if u12 is None or start not in unrate else round(u12 - unrate[start], 1),
                         "cpi_12m_later": None if c12 is None else round(c12, 1)})
        judge = {h: [0, 0] for h in (6, 12, 24)}
        for p in past:
            if p["in_recession"]:
                continue
            for h in judge:
                if p["lead"] is not None and p["lead"] <= h:
                    judge[h][0] += 1
                    judge[h][1] += 1
                elif _months_between(p["start"], rows[-1][0]) >= h:
                    judge[h][1] += 1
        ue = [p["unemp_change_12m"] for p in past if p["unemp_change_12m"] is not None and not p["in_recession"]]
        hits, n = judge[12]
        base12 = base12_since(rows[0][0])
        if n < 3:
            verdict = "too few past cases to say"
        elif base12 is None:
            verdict = ""
        else:
            rate = hits / n
            if rate >= 2 * base12:
                verdict = f"HIGHER recession risk than usual ({hits} of {n} = {round(100 * rate)}% vs {round(100 * base12)}% for any month since the data begins)"
            elif rate <= 0.5 * base12:
                verdict = f"LOWER recession risk than usual ({hits} of {n} = {round(100 * rate)}% vs {round(100 * base12)}% for any month since the data begins)"
            else:
                verdict = f"about the USUAL recession risk ({hits} of {n} = {round(100 * rate)}% vs {round(100 * base12)}% for any month since the data begins) - no extra signal"
        med = sorted(ue)[len(ue) // 2] if ue else None
        if med is not None:
            verdict += ("; unemployment usually ROSE afterwards" if med >= 0.3 else
                        "; unemployment usually FELL afterwards" if med <= -0.3 else "; unemployment usually little changed afterwards")
        results.append({"key": key, "text": text, "series": sid, "now": now_flag, "now_value": now_v, "now_period": now_d, "verdict": verdict,
                        "since": rows[0][0], "episodes": len(past), "recession": judge, "light": light,
                        "unemp_change_median": sorted(ue)[len(ue) // 2] if ue else None,
                        "past_starts": [p["start"] for p in past][-8:]})
    lights = _warning_lights(flags_by_key, rec, rec_starts)
    return {"date": TODAY.isoformat(), "conditions": results, "lights": lights, "failed": failed}


def _at(series, start, months):
    y, m = int(start[:4]), int(start[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return series.get(f"{y:04d}-{m:02d}")


def _warning_lights(flags_by_key, rec, rec_starts):
    keys = [c[0] for c in CONDITIONS if c[6] and c[0] in flags_by_key]
    common = sorted(set.intersection(*(set(flags_by_key[k]) for k in keys))) if keys else []
    if not common:
        return None
    counts = {m: sum(flags_by_key[k][m] for k in keys) for m in common}
    latest = common[-1]
    on_now = [c[1] for c in CONDITIONS if c[0] in keys and flags_by_key[c[0]][latest]]
    k = len(on_now)
    match = (lambda c: c >= k) if k else (lambda c: c == 0)
    hist_m = [m for m in common if match(counts[m]) and rec.get(m) == 0 and _months_between(m, latest) >= 12]
    followed = [m for m in hist_m if any(0 < _months_between(m, r) <= 12 for r in rec_starts)]
    base = [m for m in common if rec.get(m) == 0 and _months_between(m, latest) >= 12]
    base_f = [m for m in base if any(0 < _months_between(m, r) <= 12 for r in rec_starts)]
    return {"as_of": latest, "since": common[0], "total": len(keys), "on": k, "on_list": on_now,
            "months_with_at_least": len(hist_m), "followed_12m": len(followed),
            "base_rate": round(100 * len(base_f) / len(base)) if base else None}


def history_text(pack):
    lines = []
    L = pack.get("lights")
    if L:
        lines.append(f"RECESSION WARNING LIGHTS ({L['as_of']}): {L['on']} of {L['total']} on"
                     + (f" — {', '.join(L['on_list'])}" if L["on_list"] else ""))
        if L["months_with_at_least"]:
            lines.append(f"  Since {L['since'][:4]}: in {L['months_with_at_least']} months with {str(L['on']) + '+' if L['on'] else 'no'} lights on (outside recessions), "
                         f"a recession began within 12 months in {L['followed_12m']} "
                         f"({round(100 * L['followed_12m'] / L['months_with_at_least'])}%). Base rate for any month: {L['base_rate']}%.")
    lines.append("")
    lines.append("CONDITIONS TRUE NOW (newest reading; the history behind them uses monthly averages), and what followed each past time they began:")
    for c in pack["conditions"]:
        if not c["now"]:
            continue
        r = {int(k): v for k, v in c["recession"].items()}  # JSON turns the int keys into strings
        weak = " (WEAK: fewer than 3 past cases)" if r[12][1] < 3 else ""
        ue = f"; unemployment 12 months later: median {c['unemp_change_median']:+} pt" if c["unemp_change_median"] is not None else ""
        lines.append(f"- {c['text']} (now {fmt(c['now_value'])} for {c['now_period']}; data since {c['since'][:4]}): "
                     f"{c['episodes']} past episodes; recession within 12 months in {r[12][0]} of {r[12][1]}, "
                     f"within 24 months in {r[24][0]} of {r[24][1]}{ue}{weak}. Past starts: {', '.join(c['past_starts'][-5:])}")
        if c.get("verdict"):
            lines.append(f"  MEANING (computed): {c['verdict']}")
    off = [c["text"] for c in pack["conditions"] if not c["now"]]
    if off:
        lines.append("Not true now: " + "; ".join(off))
    if pack.get("failed"):
        lines.append("Could not fetch: " + "; ".join(pack["failed"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- reading pack
_ECON_TERMS = re.compile(r"inflation|price|employ|unemploy|payroll|wage|labor|growth|gdp|output|spending|consum|"
                         r"deficit|debt|revenue|outlay|export|import|tariff|rate|polic|demand|activity|percent|billion|"
                         r"trillion|increase|decrease|rose|fell|declin|slow|weak|strong", re.I)


def _econ_fetch_module():
    import importlib.machinery
    import importlib.util
    ld = importlib.machinery.SourceFileLoader("econ_fetch", str(Path.home() / ".local/bin/econ-fetch"))
    sp = importlib.util.spec_from_loader("econ_fetch", ld)
    m = importlib.util.module_from_spec(sp)
    ld.exec_module(m)
    return m


def excerpt(url, limit=1000):
    """The most informative paragraphs of an official release page, in document order.
    Follows an FOMC-minutes press release through to the minutes themselves."""
    ef = _econ_fetch_module()
    raw = get(url)
    title, text, links = ef.html_to_text(raw)
    if "open market committee" in title.lower() and "minutes" in title.lower():
        from urllib.parse import urljoin
        target = next((urljoin(url, h) for t, h in links if re.search(r"fomcminutes\d+\.htm", h or "")), None)
        if target:
            title, text, links = ef.html_to_text(get(target))
            url = target
            i = text.find("Participants' Views on Current Conditions")
            if i > 0:  # the policymakers' own views, not the market-operations section
                text = text[i:]
    return re.sub(r"\s+", " ", title).strip()[:110], url, excerpt_text(text, limit)


def excerpt_text(text, limit=1000):
    """The most informative paragraphs of an official document's plain text, in document order."""
    # rejoin hard-wrapped text (BLS releases break sentences across short lines)
    joined, buf = [], ""
    for ln in text.splitlines():
        if ln.lstrip().startswith("|") or ln.count(" | ") >= 2:
            continue  # table cells, not prose
        if buf and len(ln) >= 120:  # a long prose line starts its own paragraph (don't glue it to menu fragments)
            joined.append(buf)
            buf = ""
        buf = f"{buf} {ln}".strip() if buf else ln
        if re.search(r"[.:;)]\s*$", ln) or len(buf) > 1200:
            joined.append(buf)
            buf = ""
    if buf:
        joined.append(buf)
    paras = []
    for ln in joined:
        if len(ln) < 140 or ln.startswith(("Table ", "Chart ")) or re.search(r"cookie|javascript|subscribe|skip to|submitted projections|media contact", ln, re.I):
            continue
        score = len(_ECON_TERMS.findall(ln)) + 2 * len(re.findall(r"\d[\d,.]*\s*(percent|%|billion|trillion|million)", ln))
        if score >= 3:
            paras.append(ln)
    out = ""
    for p in paras:
        if len(out) + len(p) > limit:
            if not out:
                out = p[:limit]
            break
        out += p + "\n"
    return out.strip()


# ---------------------------------------------------------------- release calendar
BLS_SCHEDULES = [  # (code, plain name) — per-release schedule pages: "| <ref month> | <Mon. DD, YYYY>"
    ("empsit", "jobs report (Employment Situation)"),
    ("cpi", "CPI inflation report"),
    ("ppi", "PPI producer prices"),
    ("jolts", "JOLTS job openings"),
    ("eci", "Employment Cost Index"),
]
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _parse_day(text, default_year):
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?", text)
    if not m or m.group(1).lower()[:3] not in _MONTHS:
        return None
    try:
        return date(int(m.group(3) or default_year), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
    except ValueError:
        return None


CALENDAR_CACHE = BASE / "data/calendar-cache.json"


def _bls_calendar(horizon):
    out = []
    # BLS: the monthly calendar grids (this month + next). The per-release pages omit the current month.
    keep = {"Consumer Price Index": "CPI inflation report", "Employment Situation": "jobs report (Employment Situation)",
            "Producer Price Index": "PPI producer prices", "Job Openings and Labor Turnover Survey": "JOLTS job openings",
            "Employment Cost Index": "Employment Cost Index", "U.S. Import and Export Price Indexes": "import/export prices",
            "Productivity and Costs": "productivity and labor costs"}
    period_re = r"((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}|(?:First|Second|Third|Fourth) Quarter \d{4}|Annual \d{4})"
    for k in range(2):
        y, m = TODAY.year + (TODAY.month - 1 + k) // 12, (TODAY.month - 1 + k) % 12 + 1
        raw = get(f"https://www.bls.gov/schedule/{y}/{m:02d}_sched.htm")
        cur_y, cur_m, last_day, started = y, m, 0, False
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S):
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
                txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell)).replace("&nbsp;", " ").strip()
                dm = re.match(r"(\d{1,2})\b(.*)", txt)
                if not dm:
                    continue
                day = int(dm.group(1))
                if not started:  # leading days from the previous month
                    started = True
                    if day > 20:
                        cur_y, cur_m = (y, m - 1) if m > 1 else (y - 1, 12)
                if day < last_day:  # wrapped into the next month
                    cur_y, cur_m = (cur_y, cur_m + 1) if cur_m < 12 else (cur_y + 1, 1)
                last_day = day
                try:
                    d = date(cur_y, cur_m, day)
                except ValueError:
                    continue
                for name, per in re.findall(r"([A-Z][A-Za-z.&,'() /-]+?) " + period_re + r" \d\d:\d\d [AP]M", dm.group(2)):
                    name = name.strip()
                    if name in keep and TODAY <= d <= horizon:
                        out.append((d, f"{keep[name]} for {per}", "BLS"))
    if not out:
        raise ValueError("no releases found - page layout may have changed")
    return out


def _bea_calendar(horizon):
    ef = _econ_fetch_module()
    out = []
    _, text, _ = ef.html_to_text(get("https://www.bea.gov/news/schedule"))
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        d = _parse_day(ln, TODAY.year) if re.fullmatch(r"[A-Z][a-z]+ \d{1,2}", ln.strip()) else None
        if not d:
            continue
        title = next((l.strip("| ").strip() for l in lines[i + 1:i + 5] if l.startswith("|")), "")
        if d < TODAY - timedelta(days=60):  # calendar rolled into next year
            d = d.replace(year=d.year + 1)
        if title and TODAY <= d <= horizon:
            out.append((d, title, "BEA"))
    return out


def _fed_calendar(horizon):
    ef = _econ_fetch_module()
    out = []
    _, text, _ = ef.html_to_text(get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"))
    seg = text.split(f"{TODAY.year} FOMC Meetings", 1)[1].split(f"{TODAY.year - 1} FOMC Meetings", 1)[0]
    lines = [l.strip() for l in seg.splitlines() if l.strip()]
    for i, ln in enumerate(lines[:-1]):
        mon = ln.split("/")[-1].strip()
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})\*?", lines[i + 1])
        if mon[:3].lower() in _MONTHS and m:
            d = date(TODAY.year, _MONTHS[mon[:3].lower()], int(m.group(2)))
            if TODAY <= d <= horizon:
                out.append((d, "Fed rate decision (FOMC meeting ends)", "Fed"))
    return out


def upcoming_releases(days=21):
    """([(date, name, source)], [issues]) for official releases in the next `days` days, from the agencies' own
    calendars. Each calendar is tried twice; if it still fails, the copy saved on the last good night is used and
    the report says so. (On 2026-10-10 the BLS fetch failed silently at 01:27 and the CPI release dropped out of
    "Watch next".)"""
    import time
    horizon = TODAY + timedelta(days=days)
    try:
        cache = json.loads(CALENDAR_CACHE.read_text())
    except Exception:
        cache = {}
    out, issues = [], []
    for src, fn in (("BLS", _bls_calendar), ("BEA", _bea_calendar), ("Fed", _fed_calendar)):
        items, err = None, None
        for attempt in range(2):
            try:
                items = fn(TODAY + timedelta(days=60))
                break
            except Exception as e:
                err = e
                if attempt == 0:
                    time.sleep(5)
        if items is not None:
            cache[src] = {"saved": TODAY.isoformat(), "items": [(d.isoformat(), n, s) for d, n, s in items]}
        else:
            saved = cache.get(src)
            if saved:
                items = [(date.fromisoformat(d), n, s) for d, n, s in saved["items"]]
                issues.append(f"{src} calendar unreachable tonight ({type(err).__name__}); used the copy saved {saved['saved']}")
            else:
                items = []
                issues.append(f"{src} calendar unreachable tonight ({type(err).__name__}); its releases may be missing")
        out += [x for x in items if TODAY <= x[0] <= horizon]
    try:
        CALENDAR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CALENDAR_CACHE.write_text(json.dumps(cache, indent=1))
    except Exception:
        pass
    return sorted(set(out)), issues


# ---------------------------------------------------------------- script-written parts of the morning note
SOURCE_OF = {"A191RL1Q225SBEA": "BEA", "UNRATE": "BLS", "PAYEMS": "BLS", "ICSA": "Labor Dept", "SAHMREALTIME": "FRED",
             "CPIAUCSL": "BLS", "CPILFESL": "BLS", "PCEPILFE": "BEA", "DFEDTARU": "Fed", "DFF": "Fed", "DGS10": "Treasury",
             "T10Y2Y": "Treasury", "T10Y3M": "Treasury", "MORTGAGE30US": "Freddie Mac", "BAMLH0A0HYM2": "ICE BofA",
             "BAA10Y": "Moody's", "UMCSENT": "Univ. of Michigan", "RRSFS": "Census", "INDPRO": "Fed", "HOUST": "Census",
             "DCOILWTICO": "EIA"}
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"]


def say_period(ind):
    d, cad = ind["period"], ind.get("cadence", "m")
    if cad == "q":
        return f"Q{(int(d[5:7]) - 1) // 3 + 1} {d[:4]}"
    if cad == "m":
        return f"{_MONTH_NAMES[int(d[5:7]) - 1]} {d[:4]}" + (" (preliminary)" if ind.get("prelim") else "")
    return f"{_MONTH_NAMES[int(d[5:7]) - 1][:3]} {int(d[8:10])}"


def _previous_digest(digest_date):
    files = sorted(p for p in (BASE / "data/digest").glob("*.json") if p.stem < digest_date)
    try:
        return json.loads(files[-1].read_text()) if files else None
    except Exception:
        return None


def what_changed(d, limit=5):
    """Plain sentences about data that is new since the previous day's digest — numbers, periods and sources
    straight from the data, so the morning note can't misdate or mis-compare them."""
    prev = _previous_digest(d["date"])
    old = {i["id"]: i["period"] for i in prev["indicators"]} if prev else {}
    old_v = {i["id"]: i["value"] for i in prev["indicators"]} if prev else {}
    new = [i for i in d["indicators"] if (i["period"] != old.get(i["id"]) if prev else i["new"])]
    # daily market series move every day; mention them only for large moves
    def notable(i):
        if i["id"] == "DFEDTARU":  # a policy rate: news only when it moves (its date changes every day)
            base = old_v.get(i["id"], i["prev"][1] if i["prev"] else None)
            return base is not None and abs(i["value"] - base) > 1e-9
        if i.get("cadence") != "d" or i["id"] == "ICSA":
            return True
        p = i["prev"][1] if i["prev"] else None
        return p is not None and abs(i["value"] - p) >= (0.15 if i["unit"] in ("%", "pt") else 0.05 * abs(p))
    new = [i for i in new if notable(i)]
    def u(v, unit):
        return f"{fmt(v)}%" if unit == "%" else f"{fmt(v)}k jobs" if unit == "k jobs" else f"{fmt(v)}k" if unit == "k" else \
            f"${fmt(v)}/bbl" if unit == "$/bbl" else f"{fmt(v)} {unit}".strip()
    out = []
    for i in new[:limit]:
        p = i["prev"]
        if i["id"] == "DFEDTARU" and i["id"] in old_v:  # compare with the last report, not yesterday (after a gap they differ)
            p = [old.get(i["id"]), old_v[i["id"]]]
        was = ""
        if p:
            arrow = "up from" if i["value"] > p[1] else "down from" if i["value"] < p[1] else "unchanged from"
            was = f", {arrow} {u(p[1], i['unit'])}"
        out.append(f"{i['label']}: {u(i['value'], i['unit'])} for {say_period(i)}{was} ({SOURCE_OF.get(i['id'], 'FRED')}).")
    if not out:
        out.append("No new official data since the previous report.")
    rel = [r for r in d.get("releases", []) if r["src"] != "BLS" or "news.release" in (r.get("link") or "")]
    if rel:
        out.append("New releases: " + "; ".join(f"{r['title']} ({r['src']}, {r['date'][5:].replace('-', '/')})" for r in rel[:4]) + ".")
    return out


def watch_next(upcoming, limit=3):
    out = []
    for d_, name, src in upcoming[:limit]:
        dd = date.fromisoformat(d_) if isinstance(d_, str) else d_
        out.append(f"{name} — {dd:%a} {_MONTH_NAMES[dd.month - 1][:3]} {dd.day} ({src})")
    return out


# ---------------------------------------------------------------- report state / gap (added 2026-10-16)
# A report is only built after a real night (COLLECT, BRAINSTORM, SCENARIO, MORNING all ran today).
# `data/report-state.json` remembers the last report that was built, so the next real run knows how
# many days it has to cover, and what the data looked like then ("new" = new since the last REPORT,
# not since the last time a script happened to run).
REPORT_STATE = BASE / "data/report-state.json"
NIGHT_JOBS = ["good-guy-economy-collect", "good-guy-economy-brainstorm", "good-guy-economy-scenario", "good-guy-economy-morning"]


def report_state():
    try:
        return json.loads(REPORT_STATE.read_text())
    except Exception:
        return {}


def baseline_date():
    """Date of the last report built BEFORE today's (a same-day rebuild keeps the same baseline)."""
    s = report_state()
    last = s.get("last_report_date")
    if last == TODAY.isoformat():
        last = s.get("previous_report_date")
    try:
        return date.fromisoformat(last) if last else None
    except ValueError:
        return None


def gap_days():
    """Days this report has to cover: 1 on a normal night, 4 after three missed nights."""
    b = baseline_date()
    return max(1, (TODAY - b).days) if b else 1


def gap_line():
    b = baseline_date()
    n = gap_days()
    if not b:
        return ""
    if n <= 1:
        return f"Last report: {b} (normal nightly run)."
    return (f"CATCH-UP: no report since {b} — this run covers the last {n} days "
            f"({b + timedelta(days=1)} to {TODAY}). Look for what happened in ALL of those days, not just last night.")


def night_status():
    """({job: finished OK today?}, error). Read from Hermes' own job records."""
    try:
        jobs = json.loads(JOBS_FILE.read_text())
        jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
    except Exception as ex:
        return {}, f"cannot read the cron job records ({type(ex).__name__})"
    by = {j.get("name"): j for j in jobs}
    return {n.replace("good-guy-economy-", ""): ((by.get(n) or {}).get("last_run_at") or "")[:10] == TODAY.isoformat()
            and (by.get(n) or {}).get("last_status") == "ok" for n in NIGHT_JOBS}, None


def mark_reported(partial=()):
    """Called by econ-report after a real report is built: remember the date and the data snapshot."""
    s = report_state()
    if s.get("last_report_date") != TODAY.isoformat():
        s["previous_report_date"] = s.get("last_report_date")
    s["last_report_date"] = TODAY.isoformat()
    s["last_report_at"] = datetime.now().isoformat(timespec="minutes")
    s["last_partial"] = list(partial)  # model stages that did not finish for this report
    try:
        ds = json.loads((BASE / "data/digest-state.json").read_text())
        s["reported_period"] = ds.get("last_period", {})
        s["reported_umich"] = ds.get("umich_seen")
    except Exception:
        pass
    REPORT_STATE.write_text(json.dumps(s, indent=1))


# ---------------------------------------------------------------- Good-Guy-Economy-Library (step 2, 2026-10-16)
# COLLECT's reading pack is filled first from documents in ~/Good-Guy-Economy-Library (downloaded at 00:20 by
# econ-library) that were RELEASED since the last report, so nothing old is presented as news.
LIBRARY_DB = Path.home() / "Good-Guy-Economy-Library/library.db"
LIBRARY_PRIORITY = {  # lower = more important for the pack
    ("fed", "fomc-statement"): 0, ("fed", "fomc-minutes"): 1, ("fed", "beige-book"): 1,
    ("bls", "empsit"): 2, ("bls", "cpi"): 2, ("bea", "gdp"): 2, ("fed", "monetary-policy-report"): 2,
    ("bea", "personal-income-outlays"): 3, ("bls", "ppi"): 3, ("bls", "jolts"): 3,
    ("bls", "eci"): 4, ("bea", "trade"): 4, ("cbo", "publication"): 4,
    ("bea", "international-transactions"): 5, ("bls", "realer"): 5, ("fed", "fomc-projections"): 6,
}
LIBRARY_SRC = {"fed": "Fed", "bls": "BLS", "bea": "BEA", "cbo": "CBO"}


def library_released(doc_date, kind):
    """The day a library document became public. The catalogue dates FOMC minutes by their meeting;
    they are published three weeks later."""
    d = date.fromisoformat(doc_date)
    return d + timedelta(days=21) if kind == "fomc-minutes" else d


_LIB_BOILER = re.compile(r"EMBARGOED|Inquiries|@\w|\b\d{3}-\d{3}-\d{4}\b|^(SOURCE|DATE):|Information about|is available here|"
                         r"(\. ){4,}|Homepage|Overview|FAQs?\b", re.I)


def _lib_junk(para):
    """Name lists, menus, headings: mostly Capitalised words and no finding (no number word, no verb of change)."""
    w = para.split()
    return len(w) >= 6 and sum(x[:1].isupper() for x in w) / len(w) > 0.6 and not re.search(
        r"\b(percent|billion|million|increased|decreased|rose|fell|declined|changed|was|were)\b", para)


def library_text(raw, kind):
    """Plain text of a library document -> one clean paragraph per line, ready for excerpt_text().
    PDFs (pdftotext) are hard-wrapped with blank lines between paragraphs; contact/embargo blocks are dropped."""
    start = {"fomc-minutes": "Participants' Views on Current Conditions", "beige-book": "National Summary"}.get(kind)
    if start and raw.find(start) > 0:
        raw = raw[raw.find(start):]
    if raw.count("\n\n") < 10:  # HTML text (one line per element, no blank lines): drop boilerplate lines,
        # and let excerpt_text rejoin hard-wrapped lines as it does for live pages
        lines = raw.splitlines()
        first = next((i for i, ln in enumerate(lines) if len(ln) >= 80), 0)  # skip the site menu above the release
        return "\n".join(ln for ln in lines[first:] if not _LIB_BOILER.search(ln))
    paras = []
    for block in re.split(r"\n\s*\n", raw):
        para = " ".join(block.split())
        if not para or _LIB_BOILER.search(para) or _lib_junk(para):
            continue
        while len(para) > 900:  # keep paragraphs small enough to fit the 1,000-character slot
            cut = para.rfind(". ", 0, 900)
            cut = cut + 1 if cut > 200 else 900
            paras.append(para[:cut].strip())
            para = para[cut:].strip()
        paras.append(para)
    return "\n".join(paras)


def library_new(since, limit=5):
    """Library documents released on/after `since` (the last report's day: its 01:05 run could not
    have seen that day's 8:30/14:00 releases) and up to today, most important first.
    Returns (pack items, other new titles). Never raises: a missing library just means an empty list."""
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True)
        rows = c.execute("SELECT src, kind, date, title, url, textfile FROM docs").fetchall()
    except Exception:
        return [], []
    new = []
    for src, kind, d, title, url, tf in rows:
        rel = library_released(d, kind)
        if since <= rel <= TODAY:
            new.append((LIBRARY_PRIORITY.get((src, kind), 5), -rel.toordinal(), src, kind, rel, title, url, tf))
    new.sort()
    pack, rest = [], []
    for _, _, src, kind, rel, title, url, tf in new:
        text = ""
        if len(pack) < limit:
            try:
                text = excerpt_text(library_text((LIBRARY_DB.parent / tf).read_text(), kind))
                if src == "cbo":  # CBO is RSS summary only: drop its title line, keep the summary if there is one
                    text = text.replace(title, "", 1).strip()
                if len(text) < 120:
                    text = ""  # no real text: list the title instead of wasting a pack slot
            except Exception:
                text = ""
        if text:
            pack.append({"src": LIBRARY_SRC.get(src, src.upper()), "title": title, "url": url,
                         "date": rel.isoformat(), "text": text, "from": "library"})
        else:
            rest.append(f"[{LIBRARY_SRC.get(src, src.upper())}] {rel} {title}")
    return pack, rest
