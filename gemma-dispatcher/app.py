"""Gemma Dispatcher — chat window that can actually operate this machine.

On a GPU+CPU box this talked to a small always-on CPU model kept separate
from the big GPU-hosted reasoning model. On a CPU-only box (no GPU to
protect) there's no room or reason for two resident models, so this talks to
the SAME shared model Good-Guy-Economy's investigation loop uses, on 127.0.0.1:8099,
and serves its chat page on 127.0.0.1:8097 as before.
"""

import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import tools

GOOD_GUY_ECONOMY_LLM = "http://127.0.0.1:8099/v1/chat/completions"
MAX_STEPS = 6

SYSTEM = """You are the assistant for this Linux desktop. You operate it by calling tools.

The machine: an Intel N100 (4 cores, no discrete GPU) with ~12GB of RAM,
shared with normal desktop use. There is one small model on this box —
you're talking to it right now on port 8099 — and it does double duty: it's
also what Good-Guy-Economy (a research agent) uses for its investigation loop.
There's no separate, bigger model to delegate heavy work to on this
machine — if hermes_send or opencode_run are available, they still reach the
same port 8099 model, so delegating buys you a fresh context/session, not
more compute. If port 8099 is down, start it with
service_control('good-guy-economy-llm','start').

Call a tool whenever the user asks you to inspect, start, stop, change or find \
something. Do not describe what you would do — do it, then report what happened \
in one or two plain sentences. If a tool refuses or fails, say so plainly and \
suggest the fix."""


class Turn(BaseModel):
    message: str
    history: list = []


app = FastAPI(title="Gemma Dispatcher")


def _call_model(messages):
    r = httpx.post(
        GOOD_GUY_ECONOMY_LLM,
        json={
            "messages": messages,
            "tools": tools.SCHEMAS,
            "max_tokens": 700,
            "temperature": 0.3,
        },
        timeout=600,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


@app.post("/api/chat")
def chat(turn: Turn):
    messages = [{"role": "system", "content": SYSTEM}]
    for h in turn.history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": turn.message})

    trace = []
    try:
        for _ in range(MAX_STEPS):
            msg = _call_model(messages)
            calls = msg.get("tool_calls") or []
            if not calls:
                return JSONResponse(
                    {"reply": msg.get("content") or "(no reply)", "trace": trace}
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": calls,
                }
            )
            for c in calls:
                fn = c["function"]["name"]
                raw = c["function"].get("arguments") or "{}"
                result = tools.execute(fn, raw)
                trace.append({"tool": fn, "args": raw, "result": result[:1500]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": c.get("id", ""),
                        "content": result[:4000],
                    }
                )
        return JSONResponse(
            {"reply": "I ran out of steps on that one — try narrowing the request.",
             "trace": trace}
        )
    except httpx.HTTPError as e:
        return JSONResponse(
            {"reply": f"Couldn't reach the model on port 8099 ({e}). "
                      f"Check: systemctl --user status good-guy-economy-llm",
             "trace": trace},
            status_code=502,
        )


@app.get("/api/health")
def health():
    try:
        httpx.get("http://127.0.0.1:8099/health", timeout=3).raise_for_status()
        return {"ok": True}
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text()
