# Good-Guy-Economy — a quick guide

Good-Guy-Economy is a research assistant that works on one subject in the background,
mostly overnight, and leaves you a written report in the morning. Right now it
is set up to follow **the US economy**: factual news and official data, which
way the economy looks to be heading, and how today compares with history.

Everything runs on this laptop. Nothing is sent anywhere except the public
web pages it reads (and optional Telegram alerts, if you set those up).

## The short version

- **You don't have to start it.** Every night at **1:00 am** it starts itself,
  works until **7:00 am**, then shuts itself down to give the laptop its memory
  back. It wakes the laptop if it is asleep and keeps it awake while it works.
  The laptop does need to be **on (or asleep, not shut down)** at 1 am.
- **Your report is in `~/Economy-Reports/`**, one file per day
  (`2026-10-13.html`, plus `latest.html`). At **7:00 am** a desktop pop-up
  appears with an **Open report** button.
- It works from public sources only, so treat the report as a well-organised
  head start, not a finished product.

## The Good-Guy-Economy window (the Start / Pause / Stop buttons)

Open the **Good-Guy-Economy** icon (in the *AI-start-stop* folder on the Desktop). It
opens a page in your browser. If Good-Guy-Economy is not running, the page first shows
**"Starting Good-Guy-Economy…"** while it loads its model. That usually takes **10–60
seconds** (the first load after a reboot is the slow one).

Then you see the dashboard: the current topic, three buttons, the schedule,
and "Recent findings".

| Button | What it does |
|---|---|
| **▶ Start** | Starts the scheduler. Good-Guy-Economy then runs its jobs at the times listed under *Schedule*. |
| **⏸ Pause** / **▶ Resume** | Pauses every scheduled job (the button turns into **Resume**). The model stays loaded, nothing is lost, and the jobs stay paused — even through the 1 am start — until you click **Resume**. |
| **⏻ Stop** | Shuts everything down and frees the memory. If it thinks a job is running it asks "Stop anyway?" — saved work is safe, only the unfinished step is lost. |

**Heads-up about Start after the laptop was off:** if Good-Guy-Economy missed its
scheduled times (laptop shut down overnight, or you Stopped it), clicking
**Start** makes it **catch up on all the missed jobs at once, one after
another**. That is about **two hours of heavy work** and the laptop will feel
slow. Good-Guy-Economy now **warns you before this happens**: if jobs were missed, **Start**
shows which ones and asks "Start anyway?". Choose Cancel to leave it for the
1 am run.

You can close the browser tab at any time; Good-Guy-Economy carries on without it.

## What it does each night

One job at a time (the laptop can only manage one):

| Time | Job | What it does |
|---|---|---|
| 1:05 am | **Collect** | Pulls official numbers (FRED, BLS, BEA, the Fed) and news, and writes notes. |
| 1:45 am | **Brainstorm** | Makes calls on which way things are heading. |
| 2:25 am | **Scenario** | Compares today with past recessions and recoveries. |
| 3:00 am, Mondays | **Refine** | A weekly scorecard of its earlier calls. |
| 3:05 am | **Morning note** | Writes the short summary. |
| 3:40 am | **Fact check** | Re-checks the news statements against their sources. Anything wrong is replaced with the source's own wording or removed. |
| 4:30 am | Report built | The report is put together (with a backup build at 6:40 am). |
| 7:00 am | Pop-up | "Open report". Good-Guy-Economy shuts down. |

Each job takes roughly 15–25 minutes on this laptop; the model is small and
runs on the processor only. The dashboard's **Schedule** list shows the next
time each job will run.

## Findings

- The main output is the **daily report** in `~/Economy-Reports/`.
- The dashboard's **Recent findings** shows the last five lines added to the
  "highlights" file (`~/.hermes/investigations/active/HIGHLIGHTS.md`). For the
  economy topic this list is often empty — that is normal; the report is where
  to look.
- Anything added to highlights also triggers a desktop notification (and a
  Telegram message, if that has been set up).

## Changing the topic

**"Start a new investigation…"** on the dashboard archives the current
investigation (nothing is deleted — it is moved to
`~/.hermes/good-guy-economy-archive/investigations/`) and asks for a new topic.

> **Be careful:** the economy investigation uses instructions that were
> written by hand for it (what to fetch, how to write the report, the fact
> check). A new topic gets the *general* investigative template instead, and
> the economy report stops being produced. Only do this if you really want to
> switch subjects. Ask whoever maintains this machine to restore the economy
> setup afterwards.

## Good-Guy-Economy's limits — worth knowing

- It only uses public sources it can reach on its own. It can't log in to
  anything and can't file public-records/FOIA requests for you (it will tell
  you what to request).
- It runs a small local model, so it is **slow** and sometimes wrong. The
  fact-check step catches many misreadings but not all. Double-check anything
  before relying on it or publishing it.
- It can't run at the same time as the other local AI models on this laptop
  (Gemma 12B, Qwen, the E2B chat icons): there is not enough memory. When
  Good-Guy-Economy starts at 1 am it unloads whatever model was loaded; if Good-Guy-Economy is
  running, those other icons will refuse to start.
- The sources behind the numbers are in
  `~/.hermes/investigations/active/` (the `corpus`, `theories`, `data` and
  `reports` folders).

## Something wrong?

- **The page says "Starting Good-Guy-Economy…" for more than a few minutes.** Click
  the icon again. If it is still stuck, run `good-guy-economy-stop` in a terminal,
  then open the icon again.
- **Nothing happened overnight.** Was the laptop shut down at 1 am? Good-Guy-Economy
  can wake a sleeping laptop but not a powered-off one.
- **The laptop is very slow and you didn't expect it.** A job is running
  (check the Schedule list). Click **Stop** to free everything.
- **Another AI icon won't start.** Good-Guy-Economy is probably running — click
  **Stop** in the Good-Guy-Economy window first.
- Otherwise ask whoever set this machine up; the technical details are in
  `docs/START-STOP-RUNBOOK.md`.
