"""Script versions of the economy report's analysis stages (no model). Used by econ-scripted.py.

Written by Gemma 4 E2B under direction, fixed by Claude (see ~/e2b-abilities/tasks/04-economy-scripted).
scenario_text / morning_text: history comparisons and the "What it means" note, from the computed history pack.
TOPICS / make_call / call_text / score: rule-based direction calls (direction of the latest readings) and their scoring.
"""

def fmt(v):
    return f'{v:,.2f}'.rstrip('0').rstrip('.') if abs(v) < 1000 else f'{v:,.0f}'

def scenario_text(pack, day):
    output = ""
    relevant_conditions = []
    for c in pack['conditions']:
        if c.get('now') is True and len(relevant_conditions) < 3:
            relevant_conditions.append(c)

    for n, condition in enumerate(relevant_conditions, 1):
        r = {int(k): v for k, v in condition['recession'].items()}
        history_12m_hits = r[12][0]
        history_12m_total = r[12][1]
        history_24m_hits = r[24][0]
        history_24m_total = r[24][1]
        
        text = f"### S-{day}-{n}: {condition['text']}\n"
        text += f"- TODAY: {fmt(condition['now_value'])} for {condition['now_period']}\n"
        text += f"- HISTORY: {condition['episodes']} past episodes since {condition['since'][:4]}; recession within 12 months in {history_12m_hits} of {history_12m_total}, within 24 months in {history_24m_hits} of {history_24m_total}\n"
        
        verdict = condition.get('verdict') or ''
        meaning = verdict if verdict else 'too few past cases to say'
        
        analysis = ''
        if verdict.startswith('HIGHER'):
            analysis = 'In the past this condition was followed by a recession more often than usual, so it counts as a warning sign.'
        elif verdict.startswith('LOWER'):
            analysis = 'In the past this condition was followed by a recession less often than usual, so it is not a warning sign on its own.'
        elif verdict.startswith('about the USUAL'):
            analysis = 'In the past this condition made no real difference to recession odds, so it is not a warning sign on its own.'
        else:
            analysis = 'There are too few past cases to read anything into it.'

        text += f"- MEANING: {meaning}\n"
        text += f"- WHAT IT SUGGESTS: [ANALYSIS] {analysis}\n\n"

        output += text

    output += f"WARNING LIGHTS: RECESSION WARNING LIGHTS ({pack['lights']['as_of']}): {pack['lights']['on']} of {pack['lights']['total']} on"
    if pack['lights']['on_list']:
        output += f" — {', '.join(pack['lights']['on_list'])}"
    return output

def morning_text(pack, digest):
    L = pack['lights']
    
    # Point 5: Sentence 1
    pct = round(100 * L['followed_12m'] / L['months_with_at_least'])
    if L['on'] == 0:
        s1 = f"None of the {L['total']} recession warning lights is on; since {L['since'][:4]} a recession began within a year after only {pct}% of months like this, against {L['base_rate']}% for any month."
    else:
        s1 = f"{L['on']} of {L['total']} recession warning lights are on ({', '.join(L['on_list'])}); since {L['since'][:4]} a recession began within a year after {pct}% of months like this, against {L['base_rate']}% for any month."

    # Point 6: Sentence 2
    conditions_now_true = [c for c in pack['conditions'] if c.get('now') is True]
    higher_conditions = [c['text'] for c in conditions_now_true if (c.get('verdict') or '').startswith('HIGHER')][:3]
    
    if higher_conditions:
        s2 = ' and '.join(higher_conditions) + ' has come before recessions more often than usual.'
    else:
        s2 = 'None of the conditions true now has come before recessions more often than usual.'

    # Point 7 & 8: Sentence 3
    new_indicators = [d['label'] for d in digest['indicators'] if d['new']]
    s3_parts = []
    if new_indicators:
        s3_parts.append(f'New since the last report: {", ".join(new_indicators[:3])}.')
    else:
        s3_parts.append('No new official data since the last report.')
    s3 = ' '.join(s3_parts)

    # Combine
    output = f'What it means: [ANALYSIS] {s1} {s2} {s3}'
    return output

# ---------------------------------------------------------------- direction calls
TOPICS = [
    ('Growth', [('A191RL1Q225SBEA', 1, 0.3), ('RRSFS', 1, 0.2), ('INDPRO', 1, 0.2)]),
    ('Jobs', [('UNRATE', -1, 0.05), ('ICSA', -1, 5000), ('SAHMREALTIME', -1, 0.05)]),
    ('Inflation', [('CPIAUCSL', 1, 0.05), ('CPILFESL', 1, 0.05), ('PCEPILFE', 1, 0.05)]),
    ('Rates', [('DFEDTARU', 1, 0.1), ('DGS10', 1, 0.1), ('MORTGAGE30US', 1, 0.1)]),
    ('Recession risk', [('SAHMREALTIME', 1, 0.05), ('T10Y3M', -1, 0.1), ('BAA10Y', 1, 0.1)]),
]

def base(ind):
    if ind['cadence'] == 'd':
        if isinstance(ind['month_ago'], list):
            return ind['month_ago'][1]
        return ind['month_ago']
    elif ind['prev'] is not None:
        if isinstance(ind['prev'], list):
            return ind['prev'][1]
        return ind['prev']
    return None

def vote(ind, sign, tol):
    b = base(ind)
    if b is None:
        return None
    m = (ind['value'] - b) * sign
    if m > tol:
        return 1
    elif m < -tol:
        return -1
    return 0

def evidence(ind):
    fmt_val = fmt(ind['value'])
    u = ' ' + ind['unit'] if ind['unit'] else ''
    period_label = ind.get('period_label', 'N/A')
    base_val = fmt(base(ind)) if base(ind) is not None else 'N/A'
    return f"{ind['label']} {fmt_val}{u} for {period_label} (was {base_val})"

def make_call(topic, rules, by_id):
    votes = []
    for rule_id, sign, tol in rules:
        if rule_id in by_id:
            b = base(by_id[rule_id])
            if b is None:
                continue
            m = (by_id[rule_id]['value'] - b) * sign
            if m > tol:
                votes.append((rule_id, sign, tol, 1))
            elif m < -tol:
                votes.append((rule_id, sign, tol, -1))
            else:
                votes.append((rule_id, sign, tol, 0))

    if not votes:
        return {'topic': topic, 'direction': 'steady', 'confidence': 'low', 'for': [], 'against': [], 'key_id': None, 'key_value': None, 'wrong_if': 'the next <label> reading moves more than <fmt(tol)> from <fmt(value)>'}

    S = sum(v[3] for v in votes)
    if S >= 2:
        direction = 'rising'
        confidence = 'high' if S == 3 else 'medium'
        want = 1
    elif S <= -2:
        direction = 'falling'
        confidence = 'high' if S == -3 else 'medium'
        want = -1
    else:
        direction = 'steady'
        confidence = 'medium' if all(v[3] == 0 for v in votes) else 'low'
        want = 0

    for_list = []
    against_list = []
    for rule_id, _s, _t, vote in votes:
        evidence_line = evidence(by_id[rule_id])
        if vote == want:
            for_list.append(evidence_line)
        else:
            against_list.append(evidence_line)

    key_rule = votes[0]
    key_id = key_rule[0]
    key_value = by_id[key_id]['value']
    sign, tol = key_rule[1], key_rule[2]
    key_label = by_id[key_id]['label']
    key_value_fmt = fmt(key_value)

    wrong_if = ''
    if direction == 'steady':
        key_label = by_id[key_id]['label']
        key_value_fmt = fmt(key_value)
        tol_fmt = fmt(tol)
        wrong_if = f'the next {key_label} reading moves more than {tol_fmt} from {key_value_fmt}'
    elif direction in ['rising', 'falling']:
        up = (direction == 'rising') == (sign == 1)
        if up:
            wrong_if = f'the next {key_label} reading is below {key_value_fmt}'
        else:
            wrong_if = f'the next {key_label} reading is above {key_value_fmt}'
    
    return {'topic': topic, 'direction': direction, 'confidence': confidence, 'for': for_list, 'against': against_list, 'key_id': key_id, 'key_value': key_value, 'wrong_if': wrong_if}


def call_text(n, call, check_by):
    lines = [f"### T-{n}: {call['topic']}: {call['direction']}",
             f"- CONFIDENCE: {call['confidence']}",
             f"- EVIDENCE FOR: {'; '.join(call['for']) or 'none'}",
             f"- EVIDENCE AGAINST: {'; '.join(call['against']) or 'none'}",
             f"- WOULD BE WRONG IF: {call['wrong_if']}",
             f"- CHECK BY: {check_by}",
             '- STATUS: OPEN']
    return '\n'.join(lines) + '\n'

def score(direction, sign, tol, old, new):
    m = (new - old) * sign
    if direction == 'steady':
        return 'RIGHT' if abs(m) <= tol else 'WRONG'
    elif direction == 'falling':
        # first set m = -m, then like rising
        m_adjusted = -m
        if m_adjusted > tol:
            return 'RIGHT'
        elif m_adjusted < -tol:
            return 'WRONG'
        else:
            return 'NO CHANGE'
    elif direction == 'rising':
        if m > tol:
            return 'RIGHT'
        elif m < -tol:
            return 'WRONG'
        else:
            return 'NO CHANGE'
    return 'NO CHANGE'