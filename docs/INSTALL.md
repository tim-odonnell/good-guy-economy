# Installing Good-Guy-Economy on a new machine

This covers moving the Good-Guy-Economy *application* (this repo) to another
computer. It does not cover moving an in-progress investigation — that's a
separate, manual copy of `~/.hermes/investigations/active/` if you want one.

## 0. What this machine needs already installed (not vendored here)

- [hermes-agent](https://github.com/NousResearch/hermes-agent) — cron
  scheduler, the `osint-investigation` skill, `config.yaml`. Its venv is
  expected at `~/.hermes/hermes-agent/venv`.
- A llama.cpp server binary for Good-Guy-Economy's reasoning model. Either:
  - a **Vulkan** build (GPU offload, any vendor), or
  - a **CPU-only build/fork** — this is the case this doc calls out
    specifically below.
- A separate llama.cpp build for Gemma Dispatcher if you're installing that
  too (needs the `gemma4-assistant` MTP architecture, b10588+) — CPU-only
  regardless of what Good-Guy-Economy's own backend is.
- `camofox` (anti-detect browser service) if Collect mode will hit gov/public
  record sites.
- [SearXNG](https://github.com/searxng/searxng) cloned to
  `~/.local/share/searxng` (or point `bin/searxng-run` elsewhere).
- The actual model weights (GGUF files) — not in this repo, download
  separately.

## 1. Clone and deploy

```bash
git clone https://github.com/tim-odonnell/good-guy-economy.git ~/good-guy-economy
cd ~/good-guy-economy
./install.sh
```

`install.sh` is safe to re-run (do it after every `git pull`). It:

- links every command in `bin/` into `~/.local/bin`, and `control/`, `tui/`, `templates/`,
  `gemma-dispatcher/` to the fixed places the units expect (`~/good-guy-economy-control`,
  `~/good-guy-economy-tui`, `~/.hermes/good-guy-economy-templates`, `~/.local/share/gemma-dispatch`);
- **copies** `hermes-scripts/*.py` into `~/.hermes/scripts/` — Hermes refuses pre-run scripts that are
  links pointing outside that folder, so after changing them in the repo, re-run `./install.sh`;
- installs the US-economy topic into `~/.hermes/investigations/active/` **only if** that folder has no
  `AGENTS.md` yet (it never touches a running investigation);
- copies the systemd user units and timers, the icons and the menu entries (with your real paths);
- creates `~/.config/good-guy-economy/{paths,model}.env` from the examples if they don't exist.

`./install.sh --enable` additionally enables the control page and the nightly timers.

## 2. Config — copy each `.example`, drop the suffix, edit

```bash
mkdir -p ~/.config/good-guy-economy ~/.config/gemma-dispatcher ~/.config/searxng
cp config/paths.env.example        ~/.config/good-guy-economy/paths.env
cp config/model.env.example        ~/.config/good-guy-economy/model.env
cp config/gemma-model.env.example  ~/.config/gemma-dispatcher/model.env
cp config/searxng-settings.yml.example ~/.config/searxng/settings.yml
cp config/hermes-config.yaml.example   ~/.hermes/config.yaml
```

Edit each for this machine — in particular:

- `~/.config/good-guy-economy/model.env` — see **CPU-inference machines** below.
- `~/.config/searxng/settings.yml` — **regenerate `secret_key`**
  (`openssl rand -hex 32`); the shipped example has it redacted.
- `~/.hermes/config.yaml` — this is hermes-agent's own config, included here
  only for convenience (see the header comment in the `.example`). Check
  `web.searxng_url` — it defaults to the public `searx.be`, not the local
  SearXNG this repo runs on :8888; point it at `http://127.0.0.1:8888` if you
  want local search actually used.

## 3. Secrets

`~/.hermes/.env` holds runtime secrets (e.g. a Telegram bot token for
`good-guy-economy-notifier`) and is never part of this repo. Copy it from the old
machine by hand (`scp`, USB, etc.) if you want the same bot/notifications, or
run `good-guy-economy-telegram-setup` fresh on the new machine.

## 4. CPU-inference machines (no Vulkan/GPU backend)

> The author's N100 machine doesn't use this path: it sets
> `GOOD_GUY_ECONOMY_BACKEND=gemma12b-run` (Gemma E2B via a separate zero-swap launcher; see
> `docs/APPLIANCE.md` → "The N100 variant" and `config/good-guy-economy-gemma-profile.env.example`). The `cpu` backend below is for a plain
> llama.cpp CPU build.

If this machine is building/running a CPU-only llama.cpp fork instead of a
Vulkan build, edit `~/.config/good-guy-economy/model.env`:

```bash
GOOD_GUY_ECONOMY_BACKEND=cpu
GOOD_GUY_ECONOMY_LLAMA_SERVER_BIN=/path/to/your/cpu-fork/llama-server
GOOD_GUY_ECONOMY_LLAMA_LIB_DIR=/path/to/your/cpu-fork
GOOD_GUY_ECONOMY_THREADS=<physical core count>
# GOOD_GUY_ECONOMY_GPU_DEVICE is ignored when BACKEND=cpu — leave it or delete it.
```

`good-guy-economy-llm-run` reads `GOOD_GUY_ECONOMY_BACKEND` and skips every GPU-only flag
(`-dev`, `-ngl`, the Vulkan ICD pin) when it's `cpu`. If your fork needs
something else entirely (different flag names, no flash-attention support,
etc.), `GOOD_GUY_ECONOMY_CACHE_TYPE_K`/`_V`, `GOOD_GUY_ECONOMY_FLASH_ATTN`, and the catch-all
`GOOD_GUY_ECONOMY_EXTRA_ARGS` in `model.env.example` cover the rest without editing
the script.

**Known gap:** `gemma-dispatcher`'s `gpu_status`/`gpu_model_set_config` tools
(in `gemma-dispatcher/tools.py`) are still Vulkan/WX9100-specific — they
assume `Vulkan<N>` device strings and this machine's specific backend path.
On a CPU-only Good-Guy-Economy install they degrade harmlessly (the Vulkan binary
just won't exist, so `gpu_status` reports nothing), but the dispatcher can't
change a CPU backend's settings the way it can a Vulkan one's. Not addressed
here — flag if you need the dispatcher to manage a CPU config too.

## 5. Create the nightly Hermes jobs

```bash
systemctl --user stop hermes-gateway 2>/dev/null   # it rewrites jobs.json while running
good-guy-economy-create-jobs --dry-run             # shows the six jobs it will add
good-guy-economy-create-jobs
```

The jobs (schedules, prompts, tool lists) are defined in `hermes/jobs.example.json`. The helper uses
`hermes cron create` and then sets each job's tool list, which the CLI has no flag for: Collect gets
`web`, the others `file`. An empty list would give the small model every tool (~11k tokens) each run.

## 6. Start it

```bash
./install.sh --enable          # control page + nightly timers (window 01:00-07:00, report 04:30/06:40, notify 07:00, library 00:20)
good-guy-economy-apply-model   # loads the model per your model.env, syncs hermes config
good-guy-economy-open          # or the Good-Guy-Economy menu icon: the control page on http://127.0.0.1:8420
```

The first report appears the morning after the first full night. See `docs/START-STOP-RUNBOOK.md` for
day-to-day start/stop.
