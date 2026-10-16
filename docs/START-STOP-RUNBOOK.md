# Good-Guy-Economy — Start & Stop Runbook

How Good-Guy-Economy is brought up and down on the author's machine (an Intel N100 mini-laptop,
~11.7 GB RAM, CPU only). Originally written 2026-07-16 for the GPU workstation;
**rewritten 2026-10-13 for the N100 setup** (nightly window, Gemma E2B, no GPUs).

---

## The moving parts

| Service (systemd `--user`) | What it is | Check |
|---|---|---|
| `good-guy-economy-control.service` | The web backend behind the Good-Guy-Economy icon (FastAPI, port 8420). **Enabled**, always running; tiny. | `curl localhost:8420/api/health` → `{"ok":true}` |
| `good-guy-economy-llm.service` | The model engine: `gemma12b-run` serving **Unsloth Gemma-4 E2B** (vision + reasoning, ctx 65,536) on :8099, alias `good-guy-economy-llm`. Profile `~/gemma-4-12b-zero-swap/models/good-guy-economy-unsloth-think.env`. Peak ~5–6 GB RAM. | `curl localhost:8099/health` → `{"status":"ok"}` |
| `camofox-browser.service` | The anti-detect browser for sites that block scripts | `curl localhost:9377/health` |
| `hermes-gateway.service` | The agent + **cron scheduler** — the "master switch" for the jobs | `hermes cron status` |
| `good-guy-economy-notifier.service` | Watches HIGHLIGHTS.md, fires desktop (+ Telegram) alerts | event-driven |
| `good-guy-economy-diskwatch.service` | Pauses cron at 90% disk, resumes at 75% | event-driven |

The dashboard's **Start** = start the gateway; **Pause/Resume** = `hermes cron
pause|resume` on every job; **Stop** = stop gateway + all core services.
Opening the page itself calls `/api/stack/start`, which starts llm, browser,
notifier and diskwatch (but **not** the gateway).

`ollama`, the dual-GPU settings, the GPU power-cap service and the 229,376
context window from the old workstation setup **do not apply here.**

**Nothing but `good-guy-economy-control` and the timers auto-starts.** llm / browser /
gateway / notifier / diskwatch are `disabled`; a reboot leaves them off until
the 1 am window (below) or you start them.

---

## The nightly window (how it normally runs)

| Timer (user) | When | What it does |
|---|---|---|
| `good-guy-economy-window-start.timer` | **01:00** daily, `WakeSystem=true`, `Persistent=true` | Starts `good-guy-economy-window-awake` (sleep/idle/lid inhibitor, max 7 h), then `POST /api/stack/start` and `POST /api/gateway/start` |
| `good-guy-economy-window-stop.timer` | **07:00** | `POST /api/stack/stop?force=true`, releases the inhibitor |
| `econ-report-build.timer` | 04:30 and 06:40 (backup) | Builds `~/Economy-Reports/<date>.html/.md` and `latest.html` |
| `econ-report-notify.timer` | 07:00 | Desktop pop-up with "Open report" |

Cron jobs inside the window (Hermes, `cron.max_parallel_jobs: 1`, so a late
job queues behind the previous one): **01:05 Collect · 01:45 Brainstorm ·
02:25 Scenario · Mon 03:00 Refine · 03:05 Morning note · 03:40 Fact check.**
Each takes ~17–25 min. List them with `hermes cron list`.

Starting `good-guy-economy-llm` first unloads whatever llama-swap has loaded (drop-in
`good-guy-economy-llm.service.d/unload-llama-swap.conf`); the other Gemma/Qwen start
scripts refuse to run while Good-Guy-Economy is up.

> **Missed-fire catch-up (verified 2026-10-13).** If the gateway starts and
> jobs were scheduled while it was down (laptop off, or Stopped), Hermes runs
> **every missed job immediately, one after another** (~2 h of CPU). That is
> what happens when you click **Start** (or `hermes-gateway` starts any other
> way) after a day off. The dashboard's **Start** button now warns first (the API's
> `/api/status` returns `missed_jobs`, the jobs whose `next_run_at` is in the
> past while the gateway is down); `good-guy-economy-start` and `systemctl start
> hermes-gateway` do not. To avoid it, don't start the gateway outside the
> window, or pause the jobs first. To cancel a catch-up already started: stop
> the gateway **and** kill the leftover worker by PID —
> `ps aux | grep cron.scheduler` (the worker outlives `hermes-gateway`; don't
> use `pkill -f`).

---

## ▶️ Starting it by hand

Easiest: open the **Good-Guy-Economy** icon (Desktop → *AI-start-stop*) and click
**Start**. Or from a terminal:

```bash
good-guy-economy-start     # llm + browser + notifier + diskwatch, waits for :8099, then the gateway
```

Check RAM first (`free -m`): the engine needs ~6 GB free; close Open WebUI and
unload other models (`curl localhost:8090/unload`) if short. First model load
after a reboot is the slowest (up to a couple of minutes); with the file
already in the page cache it takes ~10 s.

### Step by step (correct order)

```bash
systemctl --user start good-guy-economy-llm.service
systemctl --user start camofox-browser.service
systemctl --user start good-guy-economy-notifier.service
systemctl --user start good-guy-economy-diskwatch.service
# wait until http://127.0.0.1:8099/health returns {"status":"ok"}, then:
systemctl --user start hermes-gateway.service   # ← this is what triggers catch-up of missed jobs
```

---

## ⏹️ Stopping it

Easiest: the **Stop** button on the dashboard (the 07:00 timer does the same, forced), or:

```bash
good-guy-economy-stop
```

Order matters: gateway first (stops launching sessions), then browser, then
engine, notifier, diskwatch.

**Busy check (fixed 2026-10-13):** the Stop button samples the engine's CPU
over 1 s and only asks "a session looks active" if it is using >50% of a core.
(It used to read `ps -o pcpu`, a lifetime average, which falsely said "busy"
for minutes after every model load.) Confirming is always safe.

If `good-guy-economy-llm` stays pinned after the gateway stops, that is a leftover
generation; `systemctl --user restart good-guy-economy-llm.service` clears it.

```bash
systemctl --user stop hermes-gateway.service
systemctl --user stop camofox-browser.service
systemctl --user stop good-guy-economy-llm.service
```

---

## 🔁 Quick reference

```bash
good-guy-economy-start / good-guy-economy-stop

# Pause / Resume the whole schedule: use the dashboard buttons (they run
# `hermes cron pause|resume <job-id>` on each job; ids from `hermes cron list`).

hermes cron status        # gateway up? next run? any catch-up warnings
hermes cron list          # every job, schedule, last run
systemctl --user list-timers --all | grep -E 'good-guy-economy|econ'

# Terminal dashboard (dev/debug): `good-guy-economy`
#   c Collect · b Brainstorm · v Scenario · f Refine (run now)
#   p pause/resume · u start stack · s stop stack · q quit
```

---

## Notes

- **Data safety:** the investigation's memory is the files under
  `~/.hermes/investigations/active/` (corpus, theories, data, reports,
  wanted.md, HIGHLIGHTS.md). Previous investigations are archived (not
  deleted) in `~/.hermes/good-guy-economy-archive/investigations/` whenever a new topic
  is started. These survive reboots and power loss.
- **Topic: US economy** (since 2026-10-09). `AGENTS.md` in the active folder
  is hand-written for it. The dashboard's "Start a new investigation…"
  replaces it with the generic template — avoid unless intended.
- **Pause is sticky:** jobs paused from the dashboard stay paused through the
  1 am window start until **Resume**.
- **Model/config changes:** edit `~/.config/good-guy-economy/model.env`, then
  `good-guy-economy-apply-model`. Current backend line: `GOOD_GUY_ECONOMY_BACKEND=gemma12b-run`
  with `GOOD_GUY_ECONOMY_GEMMA_ENV_FILE=…/good-guy-economy-unsloth-think.env`. The earlier
  `cpu`/LFM settings above it in the file are ignored by that backend.
  Hermes needs a context ≥ 64,000, so don't lower the ctx below 65,536.
- **Control server caveat:** it runs with a minimal PATH, so it calls Hermes
  by absolute path (`~/.local/bin/hermes`). A bare `hermes` there made
  Pause/Resume silently fail until 2026-10-13.
- **Autostart is off** (except the timers). A UPS is still recommended.
