# Good-Guy-Economy

A small, local AI analyst that watches the **US economy** overnight and leaves a dated report on your
desktop every morning: what changed in the official data, what it means, where the economy looks to
be heading, and how today compares with decades of history.

It runs entirely on your own machine — built and tested on a fanless Intel N100 mini-laptop with
12 GB of RAM and no GPU, using a ~2B-parameter local model (Gemma E2B) through
[llama.cpp](https://github.com/ggml-org/llama.cpp) and the
[Hermes agent](https://github.com/NousResearch/hermes-agent) scheduler. No cloud AI, no API keys.

## What you get each morning

`~/Economy-Reports/YYYY-MM-DD.html` (+ `.md`, and `latest.html`), with a desktop notification at 07:00:

- **What changed** — new official numbers since the last report (jobs, CPI/PCE inflation, GDP, claims,
  rates, spreads, sentiment, …), written by a script straight from the data.
- **What it means** — 2–3 sentences of analysis by the model, fact-checked before it reaches you.
- **Key numbers** and **Today vs history** — each condition (e.g. "yield curve inverted") checked
  against decades of FRED data and NBER recession dates, plus an 8-light recession panel. Computed, never
  guessed by the model.
- **Direction calls** — the model's open calls on growth, jobs, inflation, rates and recession risk,
  each with evidence for/against and what would prove it wrong; re-tested weekly.
- **News notes** — summaries of official releases (Fed, BLS, BEA, CBO), each with its source.

## How it works

The model is small, so **scripts do everything that must be exact** — fetching, saving, numbers,
history — and the model only writes short pieces of text in a fixed format, which scripts then check.

| Time  | Step | Who |
|-------|------|-----|
| 01:00 | Start the model server and the scheduler; keep the machine awake until 03:10 | systemd |
| 01:05 | Download newly released official documents into the local library | script (`econ-library`) |
| 01:10 | **Collect** — FRED watch-list, release feeds, headlines, a reading pack of official text → news notes | script + model |
| 01:30 | **Brainstorm** — update the direction calls | script (`econ-stages model` switches back to the model) |
| 01:32 | **Scenario** — compare today's conditions with history | script (`econ-stages model` switches back to the model) |
| 01:34 | **Refine** (Mondays) — weekly scorecard of the calls | script (`econ-stages model` switches back to the model) |
| 01:36 | **Morning** — the "What it means" note | script (`econ-stages model` switches back to the model) |
| 01:40 | **Fact check** — every news-note bullet re-checked against its source text, one claim at a time | model (no tools) |
| 02:05 | Build the report (06:40 backup); a script fact check drops sentences that misread the data | script (`econ-report`) |
| 03:10 | Model and scheduler stop; the machine may sleep again | systemd |
| 07:00 | Notification | systemd |

Rules it follows:

- **No night, no report.** If the machine was off overnight, nothing is written in the morning —
  booting does not produce a report from stale analysis.
- **Catch-up.** The next real night knows how many days it missed and widens every look-back
  (headlines, releases, alerts, "new since") to cover the gap; the report says so at the top.
- **Partial reports are labelled.** If data was collected but a model stage failed, the report says
  which, and leaves that stage's old analysis out instead of showing it as today's.
- **Nothing old is presented as news.** The reading pack only holds documents released since the
  last report.

### Nightly or on demand

`econ-mode nightly` runs the schedule above every night; `econ-mode manual` turns all of it off (timers disabled,
Hermes jobs paused) so it only runs when you ask; `econ-mode status` shows which is active. In either mode,
`econ-run-now` runs the whole pipeline once, right away (about 25 minutes by day on an Intel N150): it starts the
model, runs each stage in order, builds the report, stops the model and pops up the notification. It runs as its
own systemd user unit (closing a terminal can't kill it), refuses a second run while one is going, and logs to
`~/Economy-Reports/run-now.log`. Desktop icons: **Economy Report - Run Now**, **- Nightly Auto**, **- Manual Mode**.

### The document library

`~/Good-Guy-Economy-Library` keeps the official documents the analysis draws on — FOMC statements,
minutes and projections, Beige Books, Monetary Policy Reports, BLS releases (jobs, CPI, PPI, JOLTS,
ECI, real earnings), BEA releases (GDP, personal income and outlays, trade), CBO summaries — as
originals plus extracted, full-text-searchable text (SQLite FTS5).

```
econ-library status
econ-library search consumer spending softened
```

It tidies itself from **3 GB** down to 2.7 GB (oldest ordinary documents first; key Fed documents and
CBO outlooks are kept forever) and never writes past a **6 GB** hard ceiling.

## Requirements

- Linux with systemd user services (tested on Ubuntu 26.04, GNOME)
- Python 3 (tested with 3.14; the economy scripts use the standard library only), `curl`, `pdftotext` (poppler-utils),
  `notify-send`
- [hermes-agent](https://github.com/NousResearch/hermes-agent) installed at `~/.hermes/hermes-agent`
- a llama.cpp `llama-server` build and a GGUF model with **≥64k context** (Hermes requires 64,000).
  Tested with Gemma E2B (`gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf`), about 5–6 GB RAM at peak.
- Optional: a camofox browser service and SearXNG for the model's web-search tool.

## Install

```bash
git clone https://github.com/tim-odonnell/good-guy-economy.git ~/good-guy-economy
cd ~/good-guy-economy
./install.sh                          # puts everything in place, checks dependencies
$EDITOR ~/.config/good-guy-economy/model.env   # point it at your llama-server and model
good-guy-economy-create-jobs          # the six nightly Hermes jobs
./install.sh --enable                 # control page + nightly timers on
```

Step-by-step details, configuration and CPU-only notes: [`docs/INSTALL.md`](docs/INSTALL.md).
Day-to-day start/stop: [`docs/START-STOP-RUNBOOK.md`](docs/START-STOP-RUNBOOK.md).

## Repository layout

| Path | What |
|------|------|
| `bin/` | commands: `econ-report`, `econ-library`, `econ-mode`, `econ-run-now`, `econ-fetch`, `econ-history`, `good-guy-economy-*` (start/stop, model runner, notifier, disk watchdog, job setup) |
| `hermes-scripts/` | the pre-run scripts Hermes runs before each stage (`econ-digest.py`, `econ-pre-*.py`, `econ-modelcheck.py`) and the shared `econ_lib.py` / `econ_factcheck.py` — copied into `~/.hermes/scripts` by `install.sh` |
| `hermes/jobs.example.json` | the six cron jobs: schedules, prompts, tool lists |
| `investigation/` | the US-economy brief the model works from (`AGENTS.md`) and a catalog of ~310 official sources |
| `systemd/` | user units and timers (nightly window, report build/notify, library fetch, model server) |
| `control/`, `tui/`, `desktop/` | the desktop icon's control page (port 8420), a terminal dashboard, launchers |
| `config/` | example configs (`model.env`, `paths.env`, Hermes config, a Gemma model profile) |
| `templates/` | scaffold for starting a different investigation topic from the control page |
| `gemma-dispatcher/` | optional: a small tool-calling assistant for managing local models |
| `docs/` | install guide, runbook, user guide, and [`APPLIANCE.md`](docs/APPLIANCE.md) (the general control-page design) |

## Data sources and etiquette

FRED (St. Louis Fed), BLS, BEA, the Federal Reserve Board, CBO, and AP/Reuters headlines via Google
News RSS. All official sources are US-government public data. The scripts identify themselves honestly
(`good-guy-economy-research/1.0`), pause between requests, and fall back to cached data when a site is
down. Some sites block scripts (CBO's pages, AP and Reuters directly); those are reached only through
their RSS feeds.

## Limits

- A ~2B model writes short, careful text; it is not a substitute for reading the releases. Every
  model sentence is labelled **[ANALYSIS]**, and two fact checks remove sentences that misread the data.
- On a 4-core CPU each nightly stage takes 15–25 minutes; the whole night runs 01:00–~04:00.
- Not investment advice.

## License

MIT — see [`LICENSE`](LICENSE).
