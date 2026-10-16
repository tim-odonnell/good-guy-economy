"""Tools the dispatcher can actually execute.

Design rule: no arbitrary shell. Every tool is a named function with validated
arguments that builds an argv list itself. The model chooses *which* tool and
supplies parameters; it never supplies a command line.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

HOME = Path.home()

# Only these services can be touched. Anything else is refused.
SERVICES = {
    "good-guy-economy-llm": "The shared local model (serves port 8099) — used by both Good-Guy-Economy's investigation loop and this dispatcher",
    "hermes-gateway": "Hermes scheduler and messaging gateway",
    "camofox-browser": "Headless browser used for scraping",
    "good-guy-economy-control": "Good-Guy-Economy's dashboard backend (port 8420)",
    "good-guy-economy-notifier": "Good-Guy-Economy desktop notifications",
    "good-guy-economy-diskwatch": "Good-Guy-Economy disk space monitor",
    "searxng": "Local private search engine",
}

# gemma-dispatch-ui is deliberately absent: the dispatcher may not stop itself.

# Hermes subcommands that are safe to expose. Single source of truth: the
# schema advertises exactly what hermes_run() will accept.
HERMES_SUBCOMMANDS = ["status", "cron", "sessions", "memory", "skills",
                      "tools", "config", "insights", "version", "doctor"]

GOOD_GUY_ECONOMY_MODEL_ENV = HOME / ".config/good-guy-economy/model.env"
SEARXNG_URL = "http://127.0.0.1:8888"
GPU_MODEL_URL = "http://127.0.0.1:8099"


def _run(argv, timeout=60, cwd=None):
    """Run an argv list. Never a shell string."""
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError:
        return 127, f"not found: {argv[0]}"


def _sysctl(*args, timeout=120):
    return _run(["systemctl", "--user", *args], timeout=timeout)


# ---------------------------------------------------------------- services


def service_status(name: str = "all") -> str:
    if name in ("all", "", None):
        lines = []
        for svc, desc in SERVICES.items():
            _, state = _sysctl("is-active", f"{svc}.service", timeout=15)
            lines.append(f"{svc}: {state} — {desc}")
        _, ui = _sysctl("is-active", "gemma-dispatch-ui.service", timeout=15)
        lines.append(f"gemma-dispatch-ui: {ui} — this dispatcher (me)")
        return "\n".join(lines)
    if name not in SERVICES:
        return f"Unknown service '{name}'. Known: {', '.join(SERVICES)}"
    _, state = _sysctl("is-active", f"{name}.service", timeout=15)
    return f"{name}: {state} — {SERVICES[name]}"


def service_control(name: str, action: str) -> str:
    if name not in SERVICES:
        return (
            f"Refused: '{name}' is not a service I'm allowed to control. "
            f"Allowed: {', '.join(SERVICES)}"
        )
    if action not in ("start", "stop", "restart"):
        return f"Refused: action must be start, stop or restart (got '{action}')."
    rc, out = _sysctl(action, f"{name}.service")
    _, state = _sysctl("is-active", f"{name}.service", timeout=15)
    if rc != 0:
        return f"Failed to {action} {name}: {out[:400]}"
    return f"{name} {action}ed. Now: {state}"


# ---------------------------------------------------------------- GPUs


def gpu_status() -> str:
    """VRAM on the two WX9100s, and whether the GPU model is serving."""
    lines = []
    vk = HOME / ".lmstudio/extensions/backends/llama.cpp-linux-x86_64-vulkan-avx2-2.27.1"
    server = vk / "llama-server"
    if server.exists():
        # Same ICD pin as good-guy-economy-llm-run. Without it the Intel iGPU appears
        # as Vulkan0 and the WX9100s shift to Vulkan1/Vulkan2 -- which does not
        # match the numbering GOOD_GUY_ECONOMY_GPU_DEVICE uses, so anything reading this
        # list and then setting a device lands on the wrong card.
        env = dict(os.environ, LD_LIBRARY_PATH=str(vk),
                   VK_DRIVER_FILES="/usr/share/vulkan/icd.d/radeon_icd.json")
        try:
            p = subprocess.run(
                [str(server), "--list-devices"],
                capture_output=True, text=True, timeout=60, env=env,
            )
            for ln in (p.stdout or "").splitlines():
                if "Vulkan" in ln:
                    lines.append(ln.strip())
        except Exception as e:
            lines.append(f"(device list unavailable: {e})")
    _, state = _sysctl("is-active", "good-guy-economy-llm.service", timeout=15)
    lines.append(f"good-guy-economy-llm.service: {state}")
    lines.append(gpu_model_status())
    return "\n".join(lines) if lines else "No GPU information available."


def gpu_model_status() -> str:
    """Is the GPU-hosted model answering on port 8099?"""
    try:
        r = httpx.get(f"{GPU_MODEL_URL}/v1/models", timeout=5)
        if r.status_code == 200:
            ids = [m.get("id") for m in r.json().get("data", [])]
            return f"GPU model server (8099) is UP, serving: {', '.join(ids) or 'unknown'}"
    except Exception:
        pass
    return "GPU model server (8099) is DOWN. Start it with service_control('good-guy-economy-llm','start')."


def gpu_model_get_config() -> str:
    """Read Good-Guy-Economy's model.env — which GGUF and which GPUs it will use."""
    if not GOOD_GUY_ECONOMY_MODEL_ENV.exists():
        return f"{GOOD_GUY_ECONOMY_MODEL_ENV} not found."
    keep = ("GOOD_GUY_ECONOMY_MODEL_PATH", "GOOD_GUY_ECONOMY_GPU_DEVICE", "GOOD_GUY_ECONOMY_CTX",
            "GOOD_GUY_ECONOMY_LLAMA_SERVER_BIN")
    out = []
    for ln in GOOD_GUY_ECONOMY_MODEL_ENV.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith(keep):
            out.append(ln)
    return "\n".join(out) or "No settings found."


def gpu_model_set_config(key: str, value: str) -> str:
    """Change one setting in Good-Guy-Economy's model.env, then apply it."""
    allowed = {"GOOD_GUY_ECONOMY_MODEL_PATH", "GOOD_GUY_ECONOMY_GPU_DEVICE", "GOOD_GUY_ECONOMY_CTX"}
    if key not in allowed:
        return f"Refused: may only change {', '.join(sorted(allowed))}."
    if not GOOD_GUY_ECONOMY_MODEL_ENV.exists():
        return f"{GOOD_GUY_ECONOMY_MODEL_ENV} not found."
    if key == "GOOD_GUY_ECONOMY_MODEL_PATH":
        if not Path(value).is_file():
            return f"Refused: no such model file: {value}"
    if key == "GOOD_GUY_ECONOMY_CTX" and not re.fullmatch(r"\d{3,7}", value):
        return "Refused: context must be a number."
    if key == "GOOD_GUY_ECONOMY_GPU_DEVICE" and not re.fullmatch(r"Vulkan\d(,Vulkan\d)*", value):
        return "Refused: device must look like 'Vulkan1' or 'Vulkan1,Vulkan2'."

    text = GOOD_GUY_ECONOMY_MODEL_ENV.read_text()
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text += f"\n{key}={value}\n"
    GOOD_GUY_ECONOMY_MODEL_ENV.write_text(text)
    rc, out = _run([str(HOME / ".local/bin/good-guy-economy-apply-model")], timeout=300)
    tail = "\n".join(out.splitlines()[-4:])
    return f"Set {key}={value}. Applied (exit {rc}):\n{tail}"


# ---------------------------------------------------------------- Good-Guy-Economy


def good_guy_economy_control(action: str) -> str:
    """Start or stop the whole Good-Guy-Economy stack (model + browser + scheduler)."""
    if action not in ("start", "stop"):
        return "Refused: action must be start or stop."
    order = ["good-guy-economy-llm", "camofox-browser", "good-guy-economy-notifier",
             "good-guy-economy-diskwatch", "hermes-gateway"]
    if action == "stop":
        order = list(reversed(order))
    results = []
    for svc in order:
        rc, _ = _sysctl(action, f"{svc}.service")
        _, state = _sysctl("is-active", f"{svc}.service", timeout=15)
        results.append(f"  {svc}: {state}")
    return f"Good-Guy-Economy {action}:\n" + "\n".join(results)


# ---------------------------------------------------------------- opencode


def opencode_run(prompt: str, directory: str = str(Path.home())) -> str:
    """Give a coding/agent task to opencode, which runs on the GPU model."""
    up = gpu_model_status()
    if "DOWN" in up:
        return ("opencode uses the GPU model on port 8099, which is down. "
                "Start it first with service_control('good-guy-economy-llm','start').")
    d = Path(directory).expanduser()
    if not d.is_dir():
        return f"Refused: not a directory: {directory}"
    binary = HOME / ".opencode/bin/opencode"
    if not binary.exists():
        return "opencode is not installed."
    rc, out = _run([str(binary), "run", prompt], timeout=900, cwd=str(d))
    out = out[-3000:] if len(out) > 3000 else out
    return f"opencode finished (exit {rc}) in {d}:\n{out}"


# ---------------------------------------------------------------- hermes


def hermes_run(subcommand: str, argument: str = "") -> str:
    """Run a read-only-ish hermes subcommand."""
    if subcommand not in HERMES_SUBCOMMANDS:
        return ("Refused: allowed hermes subcommands are "
                f"{', '.join(sorted(HERMES_SUBCOMMANDS))}.")
    argv = [str(HOME / ".local/bin/hermes"), subcommand]
    if argument:
        if not re.fullmatch(r"[\w.:/=-]{1,80}", argument):
            return "Refused: argument contains unexpected characters."
        argv.append(argument)
    rc, out = _run(argv, timeout=180)
    return f"hermes {subcommand} (exit {rc}):\n{out[-2500:]}"


def hermes_send(message: str) -> str:
    """Hand a task to Hermes, which runs on the GPU model."""
    up = gpu_model_status()
    if "DOWN" in up:
        return ("Hermes uses the GPU model on 8099, which is down. "
                "Start it with service_control('good-guy-economy-llm','start').")
    rc, out = _run([str(HOME / ".local/bin/hermes"), "-z", message], timeout=900)
    return f"hermes (exit {rc}):\n{out[-3000:]}"


# ---------------------------------------------------------------- desktop


def find_file(pattern: str, directory: str = str(Path.home()), limit: int = 25) -> str:
    d = Path(directory).expanduser()
    if not d.is_dir():
        return f"Refused: not a directory: {directory}"
    if not re.fullmatch(r"[\w.*?\[\]-]{1,80}", pattern):
        return "Refused: pattern contains unexpected characters."
    rc, out = _run(
        ["find", str(d), "-maxdepth", "6", "-iname", pattern, "-not", "-path", "*/.git/*"],
        timeout=90,
    )
    lines = [l for l in out.splitlines() if l.strip()][: max(1, min(limit, 100))]
    return "\n".join(lines) if lines else f"No files matching '{pattern}' under {d}."


def list_dir(path: str = str(Path.home())) -> str:
    p = Path(path).expanduser()
    if not p.is_dir():
        return f"Not a directory: {path}"
    entries = []
    for e in sorted(p.iterdir())[:80]:
        entries.append(("[dir]  " if e.is_dir() else "       ") + e.name)
    return "\n".join(entries) or "(empty)"


def read_file(path: str, max_bytes: int = 4000) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        return f"Not a file: {path}"
    if p.stat().st_size > 5_000_000:
        return f"Refused: {path} is too large ({p.stat().st_size} bytes)."
    try:
        data = p.read_text(errors="replace")[:max_bytes]
    except Exception as e:
        return f"Could not read {path}: {e}"
    return data


def launch_app(app: str) -> str:
    """Launch a desktop application."""
    if not re.fullmatch(r"[\w.+-]{1,60}", app):
        return "Refused: application name contains unexpected characters."
    exe = shutil.which(app)
    if exe:
        subprocess.Popen(
            [exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Launched {app}."
    if shutil.which("gtk-launch"):
        rc, out = _run(["gtk-launch", app], timeout=20)
        if rc == 0:
            return f"Launched {app} via its desktop entry."
    return (f"Couldn't find '{app}'. Try the exact command name, or ask me to "
            f"search for it with find_file.")


def open_path(path: str) -> str:
    """Open a file or folder in its default application."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"No such path: {path}"
    subprocess.Popen(
        ["xdg-open", str(p)], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return f"Opened {p}."


def install_package(name: str) -> str:
    """apt needs a password this dispatcher does not have — hand it back."""
    if not re.fullmatch(r"[\w.+-]{1,60}", name):
        return "Refused: package name contains unexpected characters."
    return (
        f"I can't install '{name}' myself — apt needs a sudo password and I "
        f"don't hold one. Run this in a terminal:\n\n    sudo apt install {name}\n\n"
        f"Tell me when it's done and I'll carry on."
    )


# ---------------------------------------------------------------- search


def web_search(query: str, count: int = 5) -> str:
    """Search the web through the local SearXNG instance."""
    try:
        r = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=30,
        )
        r.raise_for_status()
        results = r.json().get("results", [])[: max(1, min(count, 10))]
    except Exception as e:
        return (f"Search failed ({e}). Is searxng running? "
                f"Check with service_status('searxng').")
    if not results:
        return f"No results for '{query}'."
    out = []
    for i, res in enumerate(results, 1):
        out.append(f"{i}. {res.get('title','')}\n   {res.get('url','')}\n"
                   f"   {(res.get('content','') or '')[:220]}")
    return "\n".join(out)


# ---------------------------------------------------------------- registry

REGISTRY = {
    "service_status": service_status,
    "service_control": service_control,
    "gpu_status": gpu_status,
    "gpu_model_status": gpu_model_status,
    "gpu_model_get_config": gpu_model_get_config,
    "gpu_model_set_config": gpu_model_set_config,
    "good_guy_economy_control": good_guy_economy_control,
    "opencode_run": opencode_run,
    "hermes_run": hermes_run,
    "hermes_send": hermes_send,
    "find_file": find_file,
    "list_dir": list_dir,
    "read_file": read_file,
    "launch_app": launch_app,
    "open_path": open_path,
    "install_package": install_package,
    "web_search": web_search,
}


def _t(name, desc, props, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


S = {"type": "string"}

# Enumerated so the model cannot invent a name. Without these it guesses
# plausible-but-wrong values ("local-search-engine" for searxng).
SVC = {"type": "string", "enum": sorted(SERVICES)}
SVC_ANY = {"type": "string", "enum": sorted(SERVICES) + ["all"]}
HERMES_SUB = {"type": "string", "enum": HERMES_SUBCOMMANDS}

SCHEMAS = [
    _t("service_status", "Check whether background services are running. Use 'all' to see everything.",
       {"name": SVC_ANY}, []),
    _t("service_control", "Start, stop or restart one background service.",
       {"name": SVC, "action": {"type": "string", "enum": ["start", "stop", "restart"]}},
       ["name", "action"]),
    _t("gpu_status", "Show the two graphics cards, their free memory, and whether the GPU model is serving.",
       {}, []),
    _t("gpu_model_status", "Check whether the big model on the GPUs is up and answering.", {}, []),
    _t("gpu_model_get_config", "Show which model file and which GPUs the GPU model server is set to use.", {}, []),
    _t("gpu_model_set_config",
       "Change the GPU model server's settings and restart it. key is "
       "GOOD_GUY_ECONOMY_MODEL_PATH (full path to a .gguf), GOOD_GUY_ECONOMY_GPU_DEVICE (this "
       "machine has exactly two cards: Vulkan0 is the first, Vulkan1 the "
       "second, 'Vulkan0,Vulkan1' for both) or GOOD_GUY_ECONOMY_CTX. To free VRAM "
       "entirely, stop the server with good_guy_economy_control instead.",
       {"key": S, "value": S}, ["key", "value"]),
    _t("good_guy_economy_control", "Start or stop the whole Good-Guy-Economy research stack at once.",
       {"action": {"type": "string", "enum": ["start", "stop"]}}, ["action"]),
    _t("opencode_run",
       "Hand a coding or file-editing task to opencode, which runs on the big GPU model. Use for multi-step work on a codebase.",
       {"prompt": S, "directory": S}, ["prompt"]),
    _t("hermes_run", "Run a Hermes CLI subcommand such as status, cron, sessions, memory, skills.",
       {"subcommand": HERMES_SUB, "argument": S}, ["subcommand"]),
    _t("hermes_send", "Give a task to the Hermes agent, which runs on the big GPU model.",
       {"message": S}, ["message"]),
    _t("find_file", "Find files by name pattern, e.g. '*.gguf'.",
       {"pattern": S, "directory": S}, ["pattern"]),
    _t("list_dir", "List what is in a folder.", {"path": S}, ["path"]),
    _t("read_file", "Read the beginning of a text file.", {"path": S}, ["path"]),
    _t("launch_app", "Launch a desktop application by its command name, e.g. firefox.",
       {"app": S}, ["app"]),
    _t("open_path", "Open a file or folder in its default application.", {"path": S}, ["path"]),
    _t("install_package", "Install software with apt.", {"name": S}, ["name"]),
    _t("web_search", "Search the web for current information.",
       {"query": S, "count": {"type": "integer"}}, ["query"]),
]


def execute(name: str, arguments: str) -> str:
    fn = REGISTRY.get(name)
    if fn is None:
        return f"No such tool: {name}"
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return f"Could not parse arguments for {name}: {arguments!r}"
    if not isinstance(args, dict):
        return f"Arguments for {name} must be an object."
    try:
        return str(fn(**args))
    except TypeError as e:
        return f"Wrong arguments for {name}: {e}"
    except Exception as e:
        return f"{name} failed: {e}"
