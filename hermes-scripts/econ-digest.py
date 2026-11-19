#!/usr/bin/env python3
"""econ-digest — deterministic data collection for Good-Guy-Economy's US-economy desk.

Runs as the COLLECT job's pre-run script (Hermes injects stdout into the prompt),
and is also called by the morning report builder if today's digest is missing.
No model involved: fetches the watch-list from FRED, official release feeds and
wire headlines, then WRITES the facts itself so they exist even if the model
stops early:
  corpus/entities/<slug>.md   data block between DATA markers (model notes kept)
  subjects.md                 the watch-list table (regenerated)
  corpus/raw/<date>_official-data.md
  data/digest/<date>.json     input for the morning report
  HIGHLIGHTS.md               one line per newly triggered alert rule
Prints a compact digest (~1-2k tokens) for the model. Stdlib only.
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE = Path.home() / ".hermes/investigations/active"
TODAY = date.today()
NOW = datetime.now()
STATE_FILE = BASE / "data/digest-state.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import econ_lib  # noqa: E402

# days this run has to cover: 1 on a normal night, more after missed nights (see econ_lib.gap_days)
GAP = econ_lib.gap_days()
NEWS_DAYS = min(GAP, 14)
UA = "good-guy-economy-research/1.0 (personal economic research; python-urllib)"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&transformation={tr}&cosd={cosd}"

# id, label, transform, slug, unit, cadence (d=daily/weekly, m=monthly, q=quarterly)
WATCH = [
    ("A191RL1Q225SBEA", "Real GDP growth (annualized)", "lin", "real-gdp-growth", "%", "q"),
    ("UNRATE", "Unemployment rate", "lin", "unemployment-rate", "%", "m"),
    ("PAYEMS", "Payrolls, monthly change", "chg", "payrolls", "k jobs", "m"),
    ("ICSA", "Initial jobless claims (weekly)", "lin", "jobless-claims", "", "d"),
    ("SAHMREALTIME", "Sahm recession indicator", "lin", "sahm-indicator", "pt", "m"),
    ("CPIAUCSL", "CPI inflation y/y", "pc1", "cpi-inflation", "%", "m"),
    ("CPILFESL", "Core CPI y/y", "pc1", "core-cpi", "%", "m"),
    ("PCEPILFE", "Core PCE y/y", "pc1", "core-pce", "%", "m"),
    ("DFEDTARU", "Fed funds target (upper)", "lin", "fed-funds-target", "%", "d"),
    ("DFF", "Fed funds effective", "lin", "fed-funds-rate", "%", "d"),
    ("DGS10", "10-yr Treasury", "lin", "treasury-10y", "%", "d"),
    ("T10Y2Y", "Yield curve 10y-2y", "lin", "yield-curve-10y2y", "pt", "d"),
    ("T10Y3M", "Yield curve 10y-3m", "lin", "yield-curve-10y3m", "pt", "d"),
    ("MORTGAGE30US", "30-yr mortgage rate", "lin", "mortgage-30y", "%", "d"),
    ("BAMLH0A0HYM2", "High-yield spread", "lin", "high-yield-spread", "pt", "d"),
    ("BAA10Y", "Corporate Baa spread", "lin", "baa-spread", "pt", "d"),
    ("UMCSENT", "Consumer sentiment (UMich)", "lin", "consumer-sentiment", "", "m"),
    ("RRSFS", "Real retail sales y/y", "pc1", "real-retail-sales", "%", "m"),
    ("INDPRO", "Industrial production y/y", "pc1", "industrial-production", "%", "m"),
    ("HOUST", "Housing starts (annual rate)", "lin", "housing-starts", "k", "m"),
    ("DCOILWTICO", "WTI oil", "lin", "oil-wti", "$/bbl", "d"),
]

FEEDS = [  # official release feeds: (label, url)
    ("BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("Fed", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
    ("CBO", "https://www.cbo.gov/publications/all/rss.xml"),
]
Q = "(%22US+economy%22+OR+inflation+OR+%22Federal+Reserve%22+OR+tariffs+OR+%22jobs+report%22+OR+%22Wall+Street%22)"
NEWS = [  # wire headlines via Google News RSS (the sites themselves block scripts)
    ("AP", f"https://news.google.com/rss/search?q={Q}+site:apnews.com+when:{NEWS_DAYS}d&hl=en-US&gl=US&ceid=US:en"),
    ("Reuters", f"https://news.google.com/rss/search?q={Q}+site:reuters.com+when:{NEWS_DAYS}d&hl=en-US&gl=US&ceid=US:en"),
]
ECON_WORDS = re.compile(r"econom|inflation|prices\b|price (rise|increase|hike)|jobs (report|data|market|numbers)|job (market|growth|openings|cuts)|"
                        r"jobless|unemploy|hiring|\blayoffs?\b|wages?\b|\bfed\b|fed's|federal reserve|interest rates?|rate (cut|hike|decision)|"
                        r"yields?\b|bonds?\b|treasur|tariff|trade (war|deal|deficit|talks|policy|gap)|gdp|recession|consumer|"
                        r"spending|retail|housing|mortgage|home (sales|prices)|stocks?\b|wall st|s&p|nasdaq|\bdow\b|deficit|"
                        r"debt|budget|banks?\b|\boil\b|crude|manufactur|factory|\btax|earnings|sentiment|\bcpi\b|\bpce\b|"
                        r"payroll|dollar|credit|wealth", re.I)
FOREIGN = re.compile(r"\b(china|chinese|japan|yen|euro\b|eu\b|europe|uk\b|britain|bank of england|ecb|canada|"
                     r"india|germany|france|thailand|malaysia|russia|ukraine|brazil|mexico|korea|australia)", re.I)
CBO_NOISE = re.compile(r"^(H\.R\.|S\.|H\.J\. ?Res|S\.J\. ?Res|H\. ?Res|S\. ?Res)\s?\d", re.I)
FEED_DAYS = max(3, GAP + 1)
NEWS_MAX = min(8 * GAP, 16)
PACK_MAX = min(3 + GAP - 1, 5)


def get(url, timeout=20):
    """Sites disagree about client names: FRED blocks custom and browser names but accepts
    Python's default; BLS blocks curl/browsers but accepts an honest custom name. Try in turn."""
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


TOTAL_DEADLINE = 90  # seconds for ALL fetches; a stuck source must not hold up the night's run
_FETCHED = {}


def prefetch(urls):
    """Fetch every URL in parallel; whatever isn't back by the deadline counts as failed."""
    import concurrent.futures as cf
    ex = cf.ThreadPoolExecutor(max_workers=4)  # gentle: bursts got us throttled
    futs = {ex.submit(get, u): u for u in urls}
    done, pending = cf.wait(futs, timeout=TOTAL_DEADLINE)
    for f in done:
        _FETCHED[futs[f]] = f.exception() or f.result()
    for f in pending:
        _FETCHED[futs[f]] = TimeoutError("no answer within the overall deadline")
    ex.shutdown(wait=False, cancel_futures=True)


def fetched(url):
    r = _FETCHED.get(url)
    if r is None:
        r = get(url)
    if isinstance(r, Exception):
        raise r
    return r


def fred_url(series, tr, years=3):
    return FRED.format(id=series, tr=tr, cosd=(TODAY - timedelta(days=365 * years + 40)).isoformat())


def fred(series, tr, years=3):
    rows = []
    for line in fetched(fred_url(series, tr, years)).splitlines()[1:]:
        d, _, v = line.partition(",")
        if v.strip() not in ("", "."):
            rows.append((d, float(v)))
    return rows


def ago(rows, days):
    """Value of the last observation on/before (latest date - days)."""
    target = (datetime.fromisoformat(rows[-1][0]) - timedelta(days=days)).date().isoformat()
    older = [r for r in rows if r[0] <= target]
    return older[-1] if older else None


def period_label(d, cad):
    if cad == "q":
        return f"{d[:4]} Q{(int(d[5:7]) - 1) // 3 + 1}"
    return d[:7] if cad == "m" else d


def fmt(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"


def feed_items(xml_text):
    root = ET.fromstring(xml_text)
    a = "{http://www.w3.org/2005/Atom}"
    out = []
    for it in root.findall(".//item") + root.findall(f".//{a}entry"):
        def f(*names):
            for n in names:
                el = it.find(n)
                if el is not None:
                    return (el.text or el.get("href") or "").strip()
            return ""
        title = re.sub(r"\s+", " ", f("title", a + "title"))
        when = f("pubDate", a + "updated", a + "published")
        try:
            dt = parsedate_to_datetime(when)
        except Exception:
            try:
                dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
            except Exception:
                dt = None
        link = f("link", a + "link")
        desc = re.sub(r"<[^>]+>", " ", f("description", a + "summary"))
        out.append({"title": title, "date": dt.date().isoformat() if dt else "", "link": "" if "news.google.com" in link else link, "url": link,
                    "desc": re.sub(r"\s+", " ", desc).strip()[:600]})
    return out


def check_alerts(sid, rows, state):
    """Alert rules from AGENTS.md. Returns list of (key, text)."""
    alerts = []
    last_d, last_v = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    if sid == "PAYEMS" and last_v < 0:
        alerts.append((f"payrolls-neg-{last_d}", f"Payrolls fell {fmt(last_v)}k in {last_d[:7]}"))
    if sid == "UNRATE" and prev and last_v - prev[1] >= 0.3:
        alerts.append((f"unrate-jump-{last_d}", f"Unemployment up {last_v - prev[1]:.1f} pt to {fmt(last_v)}% in {last_d[:7]}"))
    if sid == "SAHMREALTIME" and last_v >= 0.5:
        alerts.append((f"sahm-{last_d}", f"Sahm recession indicator at {fmt(last_v)} (trigger 0.50) for {last_d[:7]}"))
    if sid in ("CPILFESL", "PCEPILFE") and prev and abs(last_v - prev[1]) >= 0.3:
        alerts.append((f"{sid}-move-{last_d}", f"{sid} y/y moved {last_v - prev[1]:+.2f} pt to {fmt(last_v)}% in {last_d[:7]}"))
    if sid in ("T10Y2Y", "T10Y3M"):
        old_sign = state.get("sign", {}).get(sid)
        sign = "neg" if last_v < 0 else "pos"
        if old_sign and old_sign != sign:
            alerts.append((f"{sid}-sign-{last_d}", f"{sid} yield curve turned {'negative (inverted)' if sign == 'neg' else 'positive'}: {fmt(last_v)} on {last_d}"))
        state.setdefault("sign", {})[sid] = sign
    if sid == "DFEDTARU":
        old = state.get("fedtarget")
        if old is not None and abs(old - last_v) > 1e-9:
            alerts.append((f"fed-{last_d}", f"Fed target (upper) changed {fmt(old)}% -> {fmt(last_v)}% on {last_d}"))
        state["fedtarget"] = last_v
    return alerts


def write_dashboard(slug, label, block):
    path = BASE / "corpus/entities" / f"{slug}.md"
    start, end = "<!-- DATA START (auto, econ-digest) -->", "<!-- DATA END -->"
    text = path.read_text() if path.exists() else f"# {label}\n\n{start}\n{end}\n\n## Notes (COLLECT/BRAINSTORM may add below)\n"
    if start not in text:
        text = f"{start}\n{end}\n\n" + text
    text = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: f"{start}\n{block}\n{end}", text, flags=re.S)
    path.write_text(text)


def main():
    for d in ("corpus/raw", "corpus/entities", "data/digest"):
        (BASE / d).mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}
    seen = state.setdefault("last_period", {})
    rstate = econ_lib.report_state()
    reported = rstate.get("reported_period", {})  # what the last report already showed
    base = econ_lib.baseline_date()
    alerted = set(state.setdefault("alerted", []))

    indicators, new_alerts, failed = [], [], []
    prefetch([fred_url(w[0], w[2]) for w in WATCH] + [u for _, u in FEEDS] + [u for _, u in NEWS])
    for sid, label, tr, slug, unit, cad in WATCH:
        try:
            rows = fred(sid, tr)
            if not rows:
                raise ValueError("no rows")
        except Exception as e:
            failed.append(f"{sid} ({type(e).__name__})")
            continue
        last_d, last_v = rows[-1]
        prev = rows[-2] if len(rows) > 1 else None
        if cad == "d":
            m1, y1 = ago(rows, 30), ago(rows, 365)
        else:
            m1 = prev
            y1 = ago(rows, 360 if cad == "m" else 365)
        is_new = reported.get(sid, seen.get(sid)) != last_d
        at_last = None
        if base:
            old = [r for r in rows if r[0] <= base.isoformat()]
            at_last = old[-1] if old else None
        seen[sid] = last_d
        hist = rows[-13:] if cad != "d" else [r for r in rows if r[0] >= ago(rows, 365)[0]][::21][-13:]
        lo, hi = min(v for _, v in rows[-260 if cad == "d" else -13:]), max(v for _, v in rows[-260 if cad == "d" else -13:])
        ind = {"id": sid, "label": label, "transform": tr, "unit": unit, "period": last_d, "value": last_v,
               "prev": prev, "month_ago": m1, "year_ago": y1, "new": is_new, "at_last_report": at_last, "lo12": lo, "hi12": hi, "cadence": cad,
               "period_label": period_label(last_d, cad)}
        indicators.append(ind)
        for key, text in check_alerts(sid, rows, state):
            if key not in alerted:
                alerted.add(key)
                new_alerts.append(text + f" — FRED {sid}")
        block = "\n".join([
            f"`[DATA]` FRED `{sid}` ({'y/y %' if tr == 'pc1' else 'monthly change' if tr == 'chg' else 'level'}), fetched {TODAY} — revised data as of that date",
            f"- **Latest:** {fmt(last_v)} {unit} for {period_label(last_d, cad)}",
            f"- Previous: {fmt(prev[1])} for {prev[0]}" if prev else "",
            f"- ~1 year earlier: {fmt(y1[1])} for {y1[0]}" if y1 else "",
            f"- 12-month range: {fmt(lo)} to {fmt(hi)}",
            "- Recent: " + ", ".join(f"{d[:7] if cad != 'd' else d}: {fmt(v)}" for d, v in hist[-7:]),
            f"- Source: https://fred.stlouisfed.org/series/{sid}",
        ])
        write_dashboard(slug, label, "\n".join(l for l in block.splitlines() if l))

    # consumer sentiment: FRED gets UMich's numbers about a month late, so prefer UMich's own page when it is newer
    sent = next((i for i in indicators if i["id"] == "UMCSENT"), None)
    if sent:
        try:
            u = econ_lib.umich_latest()
            if u["period"] > sent["period"][:7]:
                prev_m = f"{u['period'][:4]}-{int(u['period'][5:]) - 1:02d}" if u["period"][5:] != "01" else f"{int(u['period'][:4]) - 1}-12"
                sent.update({"period": u["period"] + "-01", "value": u["value"], "prev": [prev_m + "-01", u["prev"]],
                             "month_ago": [prev_m + "-01", u["prev"]], "year_ago": [f"{int(u['period'][:4]) - 1}{u['period'][4:]}-01", u["year_ago"]],
                             "lo12": min(sent["lo12"], u["value"]), "hi12": max(sent["hi12"], u["value"]),
                             "period_label": u["period"] + (" prelim" if u["prelim"] else ""), "prelim": u["prelim"], "source": "UMich site"})
                key = f"{u['period']}{' prelim' if u['prelim'] else ''}"
                sent["new"] = rstate.get("reported_umich", state.get("umich_seen")) != key
                state["umich_seen"] = key
        except Exception as e:
            failed.append(f"UMich site ({type(e).__name__}; sentiment is FRED's older reading)")

    releases, headlines = [], []
    cutoff = (TODAY - timedelta(days=FEED_DAYS)).isoformat()
    for src, url in FEEDS:
        try:
            for it in feed_items(fetched(url)):
                if it["date"] >= cutoff and not (src == "CBO" and CBO_NOISE.match(it["title"])):
                    releases.append({"src": src, **it})
        except Exception as e:
            failed.append(f"{src} feed ({type(e).__name__})")
    for src, url in NEWS:
        try:
            kept = 0
            for it in feed_items(fetched(url)):
                head = re.sub(r"\s+-\s+(AP News|Reuters)$", "", it["title"])
                # keep US economic stories; drop topic hub pages ("Tariffs and global trade") and foreign-only items
                if len(head.split()) < 5 or not ECON_WORDS.search(head) or (FOREIGN.search(head) and not re.search(r"\bUS\b|U\.S\.|America|Fed\b|Fed's", head)):
                    continue
                headlines.append({"src": src, **it, "title": head})
                kept += 1
                if kept >= NEWS_MAX:
                    break
        except Exception as e:
            failed.append(f"{src} headlines ({type(e).__name__})")
    beige = [r for r in releases if "beige book" in r["title"].lower()]

    # reading pack: the text of the most important new official releases, so the model summarises
    # instead of hunting (E2B searches slowly and rarely finishes a tool loop).
    # First from ~/Good-Guy-Economy-Library: documents RELEASED since the last report (econ-library downloads them at 00:20);
    # the live feeds below only fill slots that are left, and skip what the library already covered.
    pack, library_more = econ_lib.library_new(base or TODAY - timedelta(days=FEED_DAYS), PACK_MAX)
    covered = {(p_["src"], p_["date"]) for p_ in pack}
    def prio(r):
        t = r["title"].lower()
        return (0 if r["src"] == "Fed" or "beige" in t else 1 if r["src"] in ("BLS", "BEA") else 2, r["date"][::-1])
    for r in sorted(releases, key=prio):
        if len(pack) >= PACK_MAX:
            break
        if (r["src"], r["date"]) in covered:
            continue  # the library already gave this day's release from this agency
        if r["src"] == "BLS" and "news.release" not in r["link"]:
            continue  # BLS index pages, not a release
        if r["src"] == "CBO":
            if r.get("desc") and re.search(r"budget review|deficit|outlook|debt", r["title"], re.I):
                pack.append({"src": "CBO", "title": r["title"], "url": r["link"], "date": r["date"], "text": r["desc"]})
            continue
        try:
            title, url, text = econ_lib.excerpt(r["link"])
            if text:
                pack.append({"src": r["src"], "title": r["title"], "url": url, "date": r["date"], "text": text})
        except Exception as e:
            failed.append(f"excerpt {r['link']} ({type(e).__name__})")
    try:
        upcoming, calendar_issues = econ_lib.upcoming_releases(21)
        upcoming = [(d.isoformat(), n, s) for d, n, s in upcoming]
    except Exception as e:
        upcoming, calendar_issues = [], [f"release calendars failed ({type(e).__name__})"]
    failed += calendar_issues
    try:
        hist = econ_lib.history_pack()
        (BASE / "data/history").mkdir(parents=True, exist_ok=True)
        (BASE / f"data/history/{TODAY}.json").write_text(json.dumps(hist, indent=1))
    except Exception as e:
        hist = None
        failed.append(f"history pack ({type(e).__name__})")

    # subjects.md — the table is owned by this script now
    tbl = ["# Subjects — US economy watch-list", "",
           f"Auto-generated by econ-digest on {NOW:%Y-%m-%d %H:%M} from FRED (revised data as of that date).",
           "Model notes go in the indicator files under corpus/entities/, not here.", "",
           "| Indicator | FRED id | Latest | Period | Previous | ~1 yr ago | New? |", "|---|---|---|---|---|---|---|"]
    for i in indicators:
        tbl.append(f"| {i['label']} | {i['id']} | {fmt(i['value'])} {i['unit']} | {i['period_label']} | "
                   f"{fmt(i['prev'][1]) if i['prev'] else ''} | {fmt(i['year_ago'][1]) if i['year_ago'] else ''} | {'NEW' if i['new'] else ''} |")
    (BASE / "subjects.md").write_text("\n".join(tbl) + "\n")

    raw = [f"SOURCE: FRED (fred.stlouisfed.org), official release feeds (BLS, Fed, BEA, CBO), Google News RSS for AP/Reuters",
           f"ACCESSED: {TODAY}", "", "## Data [DATA] (period: value)"]
    raw += [f"- {i['id']} {i['label']}: {fmt(i['value'])} {i['unit']} for {i['period']}" + (" (NEW)" if i["new"] else "") for i in indicators]
    raw += ["", f"## Official releases, last {FEED_DAYS} days"] + [f"- [{r['src']}] {r['date']} {r['title']} {r['link']}" for r in releases]
    raw += ["", f"## Wire headlines, last {NEWS_DAYS} day(s) [REPORTED — headline only, not yet read]"] + [f"- [{h['src']}] {h['title']}" for h in headlines]
    if failed:
        raw += ["", "## Failed fetches (no data — not 'nothing happened')"] + [f"- {f}" for f in failed]
    (BASE / f"corpus/raw/{TODAY}_official-data.md").write_text("\n".join(raw) + "\n")

    if new_alerts:
        with open(BASE / "HIGHLIGHTS.md", "a") as h:
            for a in new_alerts:
                h.write(f"- {NOW:%Y-%m-%d %H:%M} | DATA | {a}\n")

    state["alerted"] = sorted(alerted)[-500:]
    STATE_FILE.write_text(json.dumps(state, indent=1))
    digest = {"date": TODAY.isoformat(), "generated": NOW.isoformat(timespec="minutes"), "indicators": indicators,
              "releases": releases, "headlines": headlines, "alerts": new_alerts, "beige_book": beige, "failed": failed,
              "gap_days": GAP, "since": base.isoformat() if base else None, "pack": pack, "library_more": library_more, "upcoming": upcoming, "calendar_issues": calendar_issues}
    (BASE / f"data/digest/{TODAY}.json").write_text(json.dumps(digest, indent=1))

    # compact digest for the model's prompt
    print(f"ECON-DIGEST {NOW:%Y-%m-%d %H:%M} — already saved by script: subjects.md table, "
          f"{len(indicators)} indicator files (DATA block), corpus/raw/{TODAY}_official-data.md. Do NOT re-fetch these numbers.")
    if econ_lib.gap_line():
        print("\n" + econ_lib.gap_line())
    moves = [i for i in indicators if i["cadence"] == "d" and i.get("at_last_report") and i["at_last_report"][1] != i["value"]]
    if GAP > 1 and moves:
        print(f"\nDAILY SERIES, change since the last report ({base}):")
        for i in moves:
            print(f"- {i['label']}: {fmt(i['at_last_report'][1])} on {i['at_last_report'][0]} -> {fmt(i['value'])} on {i['period']}")
    new = [i for i in indicators if i["new"]]
    print(f"\nNEW DATA since the last report ({len(new)}):" if new else "\nNEW DATA since the last report: none")
    for i in new:
        p = f", previous {fmt(i['prev'][1])}" if i["prev"] else ""
        print(f"- {i['label']}: {fmt(i['value'])} {i['unit']} for {i['period_label']}{p}")
    print("\nALERTS triggered (already written to HIGHLIGHTS.md):" if new_alerts else "\nALERTS: none")
    for a in new_alerts:
        print(f"- {a}")
    print(f"\nOFFICIAL RELEASES, last {FEED_DAYS} days:")
    for r in releases[:12]:
        print(f"- [{r['src']}] {r['date']} {r['title']} {r['link']}")
    if beige:
        print("\nNEW BEIGE BOOK published (its text is in the READING PACK if it fit).")
    print("\nREADING PACK — official text, quoted exactly (summarise THESE):")
    for i, r in enumerate(pack, 1):
        print(f"\n[{i}] {r['src']} — {r['title']} ({r['date']})\nURL: {r['url']}\n{r['text']}")
    if not pack:
        print("(nothing new from official sources in the last 3 days)")
    if library_more:
        print("\nALSO RELEASED SINCE THE LAST REPORT (in the library, not in the pack — titles only):")
        for t in library_more[:8]:
            print(f"- {t}")
    print(f"\nWIRE HEADLINES, last {NEWS_DAYS} day(s) (headline only — read the story before filing facts):")
    for h in headlines:
        print(f"- [{h['src']}] {h['title']}")
    if failed:
        print("\nFAILED FETCHES (no data, log in wanted.md): " + "; ".join(failed))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block the agent run; say what broke
        print(f"ECON-DIGEST FAILED: {type(e).__name__}: {e} — collect data manually per AGENTS.md")
    sys.stdout.flush()
    os._exit(0)  # don't wait for any fetch thread still stuck past the deadline
