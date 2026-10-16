# Good-Guy-Economy

A local, single-icon AI research-assistant appliance. Point it at a topic —
a person, an organization, a contract, an event — and it works the story in
the background on a schedule: gathering public records, cross-referencing
names and money, building and stress-testing theories, and surfacing
findings worth a human's attention. Everything runs locally; no investigation
data leaves the machine except optional desktop/Telegram alerts.

## Layout

- `control/` — the backend behind the desktop icon: a small FastAPI app
  (`server.py`) plus `orchestration.py` (systemd/hermes subprocess calls),
  `state.py` (topic lifecycle: archive/scaffold an investigation from
  `templates/`), `config.py` (paths), and `static/` (the frontend).
- `tui/good-guy-economy` — a terminal dashboard, kept as a dev/debug console.
- `bin/` — the shell/Python entry points systemd and the desktop icon call
  (`good-guy-economy-open`, `good-guy-economy-start`/`stop`, `good-guy-economy-llm-run`,
  `good-guy-economy-notifier`, `good-guy-economy-diskwatch`, `good-guy-economy-apply-model`,
  `good-guy-economy-telegram-setup`).
- `systemd/` — the `--user` unit files for the four Good-Guy-Economy-owned services
  (control server, LLM, notifier, disk watchdog).
- `templates/` — the generic scaffold used to start a new investigation
  (`AGENTS.md.template` and the theories/corpus/wanted/sources templates).
- `config/*.example` — example `model.env` / `paths.env` / `gemma-model.env` /
  `searxng-settings.yml` / `hermes-config.yaml`; copy each to its real
  location (see `docs/INSTALL.md`) with the `.example` suffix dropped, and
  edit for your machine.
- `desktop/` — the `.desktop` launchers.
- `docs/` — the reporter-facing quick guide and the ops runbook.
- `gemma-dispatcher/` — a small CPU-only "operate this machine" assistant
  (chat UI + tool loop: service control, GPU/model status, file search,
  delegating heavy work to opencode/hermes) that runs alongside Good-Guy-Economy
  without competing for its GPUs.

## How it fits together

One icon (`desktop/Good-Guy-Economy.desktop`) runs `bin/good-guy-economy-open`, which starts
`good-guy-economy-control.service` (`control/server.py`, port 8420) and opens it in
the browser. The page drives three states — loading, "what are you
researching?", and a Start/Pause/Stop dashboard — described in
`docs/Good-Guy-Economy-Guide.md`.

Once a topic is set, `hermes-gateway` (external — see
[hermes-agent](https://github.com/NousResearch/hermes-agent), not included
here) runs four scheduled modes against the active investigation directory,
each following `templates/AGENTS.md.template`:

- **Collect** — gather public records only, cite everything, no theorizing.
- **Brainstorm** — free-form theory generation, cross-referencing entities
  for non-obvious overlaps (shared addresses, co-ownership, donor/vendor
  ties, the "nominee" pattern of hiding an interest under a relative's name).
- **Scenario** — imagine a mechanism first, then check whether its
  structural preconditions actually exist here.
- **Refine** — a weekly skeptic pass that tries to refute each theory before
  promoting anything to `HIGHLIGHTS.md`.

The reasoning model is a local MoE (Qwen3.6-35B-A3B by default) served by
`llama.cpp`'s Vulkan backend via `bin/good-guy-economy-llm-run`, configured entirely
through `config/model.env.example` — the one file meant to be edited for a
model swap or a hardware move.

## Gemma Dispatcher + SearXNG

Two supporting services that aren't Good-Guy-Economy-specific but are needed for
the full setup:

- **Gemma Dispatcher** (`gemma-dispatcher/`, `bin/gemma-dispatcher-*`,
  `systemd/gemma-dispatcher.service` + `gemma-dispatch-ui.service`,
  `config/gemma-model.env.example`) — a separate, much smaller model
  (Gemma) that runs **CPU-only**, deliberately never touching the GPUs
  Good-Guy-Economy needs. It's a chat window (`gemma-dispatch-ui`, port 8097) over
  a small llama.cpp server (`gemma-dispatcher`, port 8098) with tools
  (`gemma-dispatcher/tools.py`) for starting/stopping services, checking
  GPU/model status, editing Good-Guy-Economy's own model config, and delegating
  anything heavy — code, long research — to opencode or Hermes rather than
  attempting it itself. Its systemd units carry non-obvious OOM/cgroup
  tuning (`MemorySwapMax=0`, `MemoryMin`/`MemoryLow`, `ManagedOOMPreference`)
  worked out after real incidents where it got silently swapped out or
  killed while the big model loaded on the GPUs — read the comments in
  `systemd/gemma-dispatcher.service` before changing them.
- **SearXNG** (`bin/searxng-run`, `systemd/searxng.service`,
  `config/searxng-settings.yml.example`) — a local meta-search engine
  (JSON API, port 8888) used as a search backend. The SearXNG application
  itself is upstream, third-party software
  ([searxng/searxng](https://github.com/searxng/searxng)) and is **not**
  vendored here — clone it separately to `~/.local/share/searxng` (or
  point `bin/searxng-run` elsewhere) and drop the settings file into
  `~/.config/searxng/settings.yml`. **Regenerate `secret_key`** in that
  file before running it (`openssl rand -hex 32`) — the shipped example has
  it redacted, not a usable value.

## Installing on a new machine

See `docs/INSTALL.md` for the full walkthrough, including the case this
repo was made portable for: a machine running a **CPU-only llama.cpp
build/fork** for Good-Guy-Economy's model instead of the Vulkan GPU backend used
here (`GOOD_GUY_ECONOMY_BACKEND=cpu` in `model.env` — see `config/model.env.example`).

## The N100 variant (this checkout)

This checkout targets an Intel N100 (4 cores, no discrete GPU, ~11.7GB RAM,
shared with normal desktop use — not a dedicated appliance). That hardware has
no room for the original two-tier design (a big GPU-hosted reasoning model plus
a small always-on CPU dispatcher), so it collapses to **one model process** on
port 8099 (`good-guy-economy-llm`). `gemma-dispatcher.service` is undeployed on this
variant — `gemma-dispatch-ui` talks directly to `good-guy-economy-llm`.

**Current model (since 2026-10-09): Unsloth Gemma-4 E2B** with vision and
reasoning, launched through `gemma12b-run` (`GOOD_GUY_ECONOMY_BACKEND=gemma12b-run` in
`~/.config/good-guy-economy/model.env`, profile `good-guy-economy-unsloth-think.env`, ctx 65,536).
The earlier LFM2.5-8B-A1B and Huihui E2B setups are history. The `cpu` backend
described in `docs/INSTALL.md` still works for a plain llama.cpp CPU build.

**Current topic: US economy**, run as a **nightly 01:00–07:00 window** (systemd
timers start the stack and the Hermes gateway, then stop them at 07:00) with a
daily report in `~/Economy-Reports/`. See `docs/Good-Guy-Economy-Guide.md` (user view)
and `docs/START-STOP-RUNBOOK.md` (operations, incl. the missed-job catch-up
behaviour when the gateway is started after downtime). The job list is
Collect / Brainstorm / Scenario / Refine / Morning note / Fact check; the
Collect/Brainstorm/Scenario/Refine descriptions above are the generic design —
the economy topic redefines them in its own hand-written `AGENTS.md`.

Findings from the earlier LFM2.5 trial on this hardware, in case they transfer
to a similar box:

- **`GOOD_GUY_ECONOMY_CTX` is not free to tune down.** hermes-agent hard-refuses to
  run its agentic tool-calling loop below a 64,000-token context window
  ("Model X has a context window of N tokens, which is below the minimum
  64,000 required"). That's the floor here, not a memory-driven choice — see
  the comment above `GOOD_GUY_ECONOMY_CTX` in `config/model.env.example`.
- LFM2.5's `lfm2moe` architecture (short-conv + a handful of full-attention
  layers) has cheap KV growth — measured RSS barely moved between ctx=4096
  and ctx=65536 on this box (~7.3GB → ~7.6GB), unlike a dense-attention model
  where that context range would balloon. That's what makes the 64K floor
  affordable at all on 12GB.
- LFM2.5 has no MTP head — `bin/good-guy-economy-llm-run`'s self-speculative decoding
  flags are now gated behind `GOOD_GUY_ECONOMY_SPEC_DECODE` (default `on`, matching
  Qwen3.6's behavior); set to `off` for this model.
- **The full `hermes-cli` toolset's system prompt + tool schemas cost ~11,000
  tokens of prefill** before any real work starts — at this box's ~15-20
  tok/s CPU prefill, that's 10+ minutes on the very first turn of a session
  (later turns reuse the cached prefix and are fast). Trimmed the toolset
  with `hermes tools disable image_gen tts vision computer_use connections`
  — none of those are relevant to a local OSINT research assistant, and
  removing them measurably shrinks that one-time tax. Worth revisiting if
  the investigation loop needs something back.
- Camofox (`jo-inc/camofox-browser`, not vendored — see "Not included")
  pre-warms its browser engine on startup (~190MB RSS observed) and self-shuts
  it down to a ~40MB baseline 5 minutes after the last session closes
  (`BROWSER_IDLE_TIMEOUT_MS`, default 300000) — not a constant tax, just a
  warm-while-used one. `hermes-agent`'s browser tool talks to it natively via
  `browser.cloud_provider: camofox` in `config.yaml` (`CAMOFOX_URL` defaults
  to `http://localhost:9377`, matching `config.py`'s `CAMOFOX_HEALTH_URL`).
  No `camofox-browser.service` is shipped upstream (see "Not included") —
  authored one here (`systemd/camofox-browser.service`) matching the rest of
  the stack's systemd --user pattern.

## Not included

This repo is the Good-Guy-Economy-specific application layer, plus a convenience
copy of hermes-agent's `config.yaml` (see `config/hermes-config.yaml.example`
— hermes-agent's own file, not Good-Guy-Economy's, included so it travels with the
repo instead of being hand-rebuilt per machine). It still assumes an
existing [hermes-agent](https://github.com/NousResearch/hermes-agent)
install itself (cron scheduler, the `osint-investigation` skill), a
llama.cpp build for Good-Guy-Economy's model (Vulkan or a CPU-only fork — see
"Installing on a new machine" above), a separate llama.cpp build for
Gemma's MTP architecture (see `config/gemma-model.env.example`), an
anti-detect browser service (`camofox`), and SearXNG itself (see above) —
external dependencies, not vendored here. No investigation data, API
credentials, or Telegram tokens are stored in this repo; secrets live in
`~/.hermes/.env` on the host machine and are read at runtime. Two
exceptions were redacted before committing: SearXNG's `secret_key`, and
every credential-shaped field in `hermes-config.yaml.example` (all were
already blank on the source machine).
