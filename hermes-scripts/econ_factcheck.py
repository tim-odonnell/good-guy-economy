"""Script fact-check for the model's sentences in the morning report (stdlib only, no model, runs in seconds).

The old number check only asked "does this number appear anywhere in tonight's data?", so a right number
attached to the wrong thing passed. These checks look at what a number is attached to:

  comparison   "core PCE is higher than CPI"            -> compare the two indicators' values
  binding      "oil reached $96.24 in September"         -> the number belongs to the indicator named before it,
                                                            and the period named after it must be that number's period
  history      "five past episodes since 1948"           -> counts, "N of M" and "since YYYY" must match the
                                                            history pack for the condition the sentence is about

Each problem names the sentence; the report drops that sentence and lists it with the reason, so a wrong
sentence never reaches the reader as fact and every correction is logged.
"""
import re

# (FRED id, how the model names it) - more specific names first; an earlier match claims its span
NAMES = [
    ("PCEPILFE", r"core pce"),
    ("CPILFESL", r"core cpi|core consumer price"),
    ("CPIAUCSL", r"\bcpi\b|consumer price"),
    ("UNRATE", r"unemployment rate|jobless rate|\bunemployment\b"),
    ("ICSA", r"jobless claims|initial claims"),
    ("PAYEMS", r"payrolls?\b|jobs added|job growth|nonfarm"),
    ("A191RL1Q225SBEA", r"\bgdp\b|economic growth"),
    ("DCOILWTICO", r"\bwti\b|\boil\b|crude"),
    ("UMCSENT", r"consumer sentiment|\bsentiment\b"),
    ("T10Y2Y", r"10y-2y|10-year minus 2-year"),
    ("T10Y3M", r"10y-3m|10-year minus 3-month"),
    ("DGS10", r"10-?year|10-?yr|ten-year"),
    ("MORTGAGE30US", r"mortgage"),
    ("DFEDTARU", r"fed funds target|federal funds target|policy rate"),
    ("DFF", r"effective (?:fed funds |federal funds )?rate|fed funds rate|federal funds rate"),
    ("RRSFS", r"retail sales"),
    ("INDPRO", r"industrial production"),
    ("HOUST", r"housing starts"),
    ("SAHMREALTIME", r"\bsahm\b"),
    ("BAMLH0A0HYM2", r"high-yield|junk bond"),
    ("BAA10Y", r"\bbaa\b|corporate bond spread"),
]
# history-pack condition key -> how a sentence refers to it
CONDITION_WORDS = {
    "sentiment-low": r"sentiment", "oil-shock": r"\boil\b|crude", "inflation-high": r"inflation|\bcpi\b",
    "mortgage-high": r"mortgage", "rates-jump": r"10-?year|10-?yr|treasury yield", "unemp-rising": r"unemployment",
    "curve-3m-inverted": r"yield curve", "curve-2y-inverted": r"yield curve", "claims-rising": r"jobless claims",
    "credit-widening": r"bond spread|credit spread", "industry-shrinking": r"industrial production",
    "housing-slump": r"housing starts", "payrolls-weak": r"job growth|payrolls", "fed-hiking": r"fed funds|federal funds",
    "fed-cutting": r"fed funds|federal funds",
}
WORD_NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
NUM_RE = re.compile(r"(?<![\w.])\$?(-?\d[\d,]*(?:\.\d+)?)\s*(%|percent|k\b|pt\b)?")
PERIOD_RE = re.compile(r"\b(?:(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{4})|Q([1-4])\s+(\d{4})|(\d{4})\s+Q([1-4]))\b", re.I)
HIGHER = r"higher|greater|more|above|exceeds?|exceeding|outpac\w*"
LOWER = r"lower|less|below|under"
COMPARE_RE = re.compile(rf"\b(?:(?:{HIGHER}|{LOWER})\s+than|above|below|exceeds?|exceeding|outpac\w*)\b", re.I)


def morning_meaning(take):
    """The "What it means" part of MORNING's reply (the rest of the note is written by script)."""
    m = re.search(r"what it means:?\**\s*(.*?)(?=\**\s*watch next|\**\s*what changed|\Z)", take, re.I | re.S)
    return (m.group(1) if m else re.sub(r"^#.*\n", "", take)).replace("**", "").strip()


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[*\"(])", text.strip()) if s.strip()]


def mentions(sentence):
    """[(start, end, FRED id)] in order, each span claimed by the most specific name."""
    taken, out = [], []
    for sid, pat in NAMES:
        for m in re.finditer(pat, sentence, re.I):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), m.end(), sid))
    return sorted(out)


def _f(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _num(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _same(n, v):
    """Does the number as written match the value at the precision it was written?"""
    if v is None:
        return False
    for val in (v, v / 1000):  # 197,000 claims may be written 197k
        if abs(n - val) < 0.006 or abs(n - round(val, 1)) < 1e-9 or abs(n - round(val)) < 1e-9 and float(n).is_integer() and abs(val) >= 100:
            return True
    return False


def _period_matches(ind, y, m=None, q=None):
    p = ind["period"]
    if q:
        return int(p[:4]) == y and (int(p[5:7]) - 1) // 3 + 1 == q
    return int(p[:4]) == y and int(p[5:7]) == m


def _say_period(ind):
    p = ind["period"]
    if ind.get("cadence") == "q":
        return f"Q{(int(p[5:7]) - 1) // 3 + 1} {p[:4]}"
    if ind.get("cadence") == "d":
        return p
    return f"{MONTHS[int(p[5:7]) - 1].title()} {p[:4]}"


def check_sentence(s, inds, hist):
    """Problems (plain-English strings) with one sentence of the model's note."""
    probs = []
    ms = mentions(s)
    # 1. comparisons between two indicators
    for c in COMPARE_RE.finditer(s):
        before = [x for x in ms if x[1] <= c.start()]
        after = [x for x in ms if x[0] >= c.end() and x[0] - c.end() <= 40]
        if not before or not after:
            continue
        a, b = inds.get(before[-1][2]), inds.get(after[0][2])
        if not a or not b or a is b or a["unit"] != b["unit"]:
            continue
        up = not re.match(rf"(?:{LOWER})\b", c.group(0), re.I)
        if (a["value"] > b["value"]) != up and a["value"] != b["value"]:
            probs.append(f"says {a['label']} ({_f(a['value'])}) is {'higher' if up else 'lower'} than {b['label']} "
                         f"({_f(b['value'])}) - it is {'lower' if up else 'higher'}")
    # 2. each number belongs to the indicator named just before it, and to that indicator's period
    for m in NUM_RE.finditer(s):
        n = _num(m.group(1))
        if n is None or (1900 <= n <= 2100 and float(n).is_integer()):
            continue
        if float(n).is_integer() and abs(n) <= 31 and not m.group(2) and "$" not in m.group(0):
            continue  # counts ("1 of 9", "5 episodes") are checked against the history pack below
        before = [x for x in ms if x[1] <= m.start() and m.start() - x[1] <= 80]
        if not before:
            continue
        ind = inds.get(before[-1][2])
        if not ind:
            continue
        own = [ind["value"]] + [x[1] for x in (ind.get("prev"), ind.get("month_ago"), ind.get("year_ago")) if x]
        if any(_same(n, v) for v in own):
            if _same(n, ind["value"]):
                pm = PERIOD_RE.search(s, m.end(), m.end() + 45)
                if pm:
                    if pm.group(1):
                        ok = _period_matches(ind, int(pm.group(2)), MONTHS.index(next(x for x in MONTHS if x.startswith(pm.group(1).lower()))) + 1)
                    else:
                        ok = _period_matches(ind, int(pm.group(4) or pm.group(5)), q=int(pm.group(3) or pm.group(6)))
                    if not ok:
                        probs.append(f"dates {ind['label']} {m.group(0).strip()} to {pm.group(0)} - that figure is for {_say_period(ind)}")
            continue
        other = [o for o in inds.values() if o is not ind and _same(n, o["value"])]
        if other and float(n) != 0 and not re.search(r"[,;]|\b(?:and|while|but|whereas)\b", s[before[-1][1]:m.start()]):
            probs.append(f"gives {m.group(0).strip()} as {ind['label']} - that is {other[0]['label']}; "
                         f"{ind['label']} is {_f(ind['value'])}")
    # 3. history counts, "N of M" and "since YYYY" for the condition the sentence talks about
    if hist:
        conds = [c for c in hist.get("conditions", []) if c.get("now") and c["key"] in CONDITION_WORDS
                 and re.search(CONDITION_WORDS[c["key"]], s, re.I)]
        if conds:
            for m in re.finditer(r"\b(\d+|" + "|".join(WORD_NUM) + r")\s+(?:past\s+|previous\s+|earlier\s+|historical\s+)?(episodes?|cases|times|occasions)\b", s, re.I):
                k = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1).lower()]
                if not any(k == c["episodes"] or k in (v[1] for v in c["recession"].values()) for c in conds):
                    probs.append(f"says {m.group(0)} - the history data has " + ", ".join(f"{c['episodes']} ({c['text']})" for c in conds))
            for m in re.finditer(r"\bsince\s+(\d{4})\b", s, re.I):
                if not any(m.group(1) == c["since"][:4] for c in conds):
                    probs.append(f"says since {m.group(1)} - the data starts " + ", ".join(f"{c['since'][:4]} ({c['text']})" for c in conds))
            for m in re.finditer(r"\b(\d+|" + "|".join(WORD_NUM) + r")\s+(?:out\s+)?of\s+(?:the\s+)?(\d+|" + "|".join(WORD_NUM) + r")\b", s, re.I):
                a, b = (int(x) if x.isdigit() else WORD_NUM[x.lower()] for x in m.groups())
                pairs = [tuple(v) for c in conds for v in c["recession"].values()]
                if (a, b) not in pairs:
                    probs.append(f"says {m.group(0)} - not one of the computed recession counts for this condition")
    return probs


def check(text, digest, hist):
    """[(sentence, [problems])] for every sentence of `text` that has at least one problem."""
    inds = {i["id"]: i for i in (digest or {}).get("indicators", [])}
    out = []
    for s in sentences(text):
        p = check_sentence(s, inds, hist)
        if p:
            out.append((s, p))
    return out


def remove(text, problems):
    """`text` without the flagged sentences."""
    bad = {s for s, _ in problems}
    return " ".join(s for s in sentences(text) if s not in bad)
