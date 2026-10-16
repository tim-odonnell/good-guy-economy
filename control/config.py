"""Shared paths/constants for the Good-Guy-Economy control server."""
from pathlib import Path

HOME = Path.home()


def _read_env_file(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


_PATHS = _read_env_file(HOME / ".config/good-guy-economy/paths.env")

INVESTIGATION_DIR = Path(_PATHS.get(
    "GOOD_GUY_ECONOMY_INVESTIGATION_DIR", str(HOME / ".hermes/investigations/active")
))
TOPIC_FILE = INVESTIGATION_DIR / ".topic.json"

TEMPLATES_DIR = HOME / ".hermes/good-guy-economy-templates"
JOBS_FILE = HOME / ".hermes/cron/jobs.json"
ARCHIVE_ROOT = HOME / ".hermes/good-guy-economy-archive/investigations"

LLAMA_HEALTH_URL = "http://127.0.0.1:8099/health"
CAMOFOX_HEALTH_URL = "http://localhost:9377/health"

# Services started as part of "the service" (everything except the
# investigation loop itself, which is hermes-gateway — controlled separately
# via /api/gateway/start|stop so Start/Pause/Stop on the dashboard map cleanly
# onto: start the loop / pause the loop / power everything down).
CORE_STACK_SERVICES = [
    "good-guy-economy-llm",
    "camofox-browser",
    "good-guy-economy-notifier",
    "good-guy-economy-diskwatch",
]
GATEWAY_SERVICE = "hermes-gateway"

JOB_NAMES = ["good-guy-economy-collect", "good-guy-economy-brainstorm", "good-guy-economy-scenario", "good-guy-economy-refine", "good-guy-economy-morning", "good-guy-economy-factcheck"]
JOB_LABELS = {
    "good-guy-economy-collect": "Collect",
    "good-guy-economy-brainstorm": "Brainstorm",
    "good-guy-economy-scenario": "Scenario",
    "good-guy-economy-refine": "Refine",
    "good-guy-economy-morning": "Morning note",
    "good-guy-economy-factcheck": "Fact check",
}
