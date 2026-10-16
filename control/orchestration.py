"""Thin wrappers around systemctl/hermes subprocess calls.

These intentionally mirror the exact command patterns already used by
good-guy-economy-start / good-guy-economy-stop / the good-guy-economy TUI, rather than inventing new
ones — this is just those same commands, callable from the API.
"""
import json
import os
import time
import subprocess
import urllib.request

import config

# The control server runs as a systemd user service with a minimal PATH that lacks
# ~/.local/bin, so a bare "hermes" fails with ENOENT (Pause/Resume silently did nothing).
HERMES_BIN = str(config.HOME / ".local/bin/hermes")


def systemctl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True, timeout=timeout,
    )


def is_active(service: str) -> str:
    r = systemctl("is-active", f"{service}.service", timeout=5)
    return r.stdout.strip() or "unknown"


# `systemctl start` on a Type=simple unit returns as soon as the process
# forks, so it doesn't actually wait for TimeoutStartSec — but `systemctl
# stop` DOES block until the process exits (up to TimeoutStopSec), which for
# hermes-gateway is 210s to let an in-flight session wind down gracefully
# (observed directly taking ~40s+ in practice). A short subprocess timeout
# here would kill the systemctl client mid-wait — the systemd stop job keeps
# running regardless, so the client would just crash while the real stop
# silently continues, a confusing failure for no reason. 220s comfortably
# covers the worst case (hermes-gateway) with headroom.
_SLOW_TIMEOUT = 220


def start_service(service: str) -> tuple[bool, str]:
    try:
        r = systemctl("start", f"{service}.service", timeout=_SLOW_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"timed out waiting for {service} to start"
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def stop_service(service: str) -> tuple[bool, str]:
    try:
        r = systemctl("stop", f"{service}.service", timeout=_SLOW_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"timed out waiting for {service} to stop (it may still be stopping in the background)"
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def reset_failed(service: str) -> None:
    systemctl("reset-failed", f"{service}.service", timeout=10)


def fetch_json(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def model_ready() -> bool:
    h = fetch_json(config.LLAMA_HEALTH_URL)
    return bool(h and h.get("status") == "ok")


def camofox_ready() -> bool:
    h = fetch_json(config.CAMOFOX_HEALTH_URL)
    return bool(h and h.get("ok"))


def _cpu_ticks(pid: str) -> int:
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])  # utime + stime


def llama_busy() -> bool:
    """Is the model engine generating right now? Samples CPU over 1s (the old
    `ps -o pcpu` is a lifetime average, so it read 'busy' for minutes after a
    model load) and matches the process name exactly, not any command line
    that merely mentions llama-server."""
    try:
        r = subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True, text=True, timeout=5)
        pids = r.stdout.split()
        if not pids:
            return False
        before = {p: _cpu_ticks(p) for p in pids}
        time.sleep(1.0)
        hz = os.sysconf("SC_CLK_TCK")
        used = sum(_cpu_ticks(p) - before[p] for p in pids)
        return used / hz * 100 > 50.0  # >50% of one core over the sample
    except Exception:
        return False


def start_core_stack() -> list[tuple[str, bool, str]]:
    return [(svc, *start_service(svc)) for svc in config.CORE_STACK_SERVICES]


def stop_core_stack() -> list[tuple[str, bool, str]]:
    return [(svc, *stop_service(svc)) for svc in reversed(config.CORE_STACK_SERVICES)]


def start_gateway() -> tuple[bool, str]:
    return start_service(config.GATEWAY_SERVICE)


def stop_gateway() -> tuple[bool, str]:
    ok, err = stop_service(config.GATEWAY_SERVICE)
    # hermes-gateway exits 1 on SIGTERM (cosmetic) and self-rewrites its own
    # unit file on start/stop, so a unit-file fix doesn't stick — clear the
    # resulting "failed" flag here instead, same as good-guy-economy-stop does.
    reset_failed(config.GATEWAY_SERVICE)
    return ok, err


def stack_status() -> dict[str, str]:
    return {svc: is_active(svc) for svc in [*config.CORE_STACK_SERVICES, config.GATEWAY_SERVICE]}


def load_jobs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        data = json.loads(config.JOBS_FILE.read_text())
        by_name = {j["name"]: j for j in data.get("jobs", [])}
        for name in config.JOB_NAMES:
            if name in by_name:
                out[name] = by_name[name]
    except Exception:
        pass
    return out


def hermes_cron(action: str, job_id: str) -> tuple[bool, str]:
    if action == "run":
        # `hermes cron run` with no inherited gateway session key runs the
        # WHOLE session synchronously inside that one CLI process (hermes-agent's
        # own _job_action forces this -- see its comment on
        # _SESSION_ASYNC_DELIVERY -- specifically so a background-dispatched
        # run can't be orphaned mid-LLM-call). A real investigation turn on
        # this hardware can run for many minutes to hours (AGENTS.md's own
        # "run dozens of steps" instruction), so ANY subprocess.run timeout
        # here -- 30s or 220s, both tried and both wrong -- kills the entire
        # session, not a stuck trigger call. Fire-and-forget instead: launch
        # detached and return immediately. Progress is visible via `hermes
        # cron runs <id>` / jobs.json state, not this call's return value.
        try:
            subprocess.Popen(
                [HERMES_BIN, "cron", "run", job_id],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, "started (runs in the background; check `hermes cron runs` for progress)"
        except Exception as e:
            return False, str(e)
    try:
        r = subprocess.run(
            [HERMES_BIN, "cron", action, job_id],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    except Exception as e:
        return False, str(e)


def pause_all_jobs() -> list[tuple[str, bool, str]]:
    jobs = load_jobs()
    return [(name, *hermes_cron("pause", j["id"])) for name, j in jobs.items()]


def resume_all_jobs() -> list[tuple[str, bool, str]]:
    jobs = load_jobs()
    return [(name, *hermes_cron("resume", j["id"])) for name, j in jobs.items()]


def run_job(name: str) -> tuple[bool, str]:
    jobs = load_jobs()
    job = jobs.get(name)
    if not job:
        return False, f"no job data for {name}"
    return hermes_cron("run", job["id"])
