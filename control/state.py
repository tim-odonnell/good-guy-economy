"""Topic lifecycle: reading current topic, archiving the old investigation,
and scaffolding a fresh one from the generic templates.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import config


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "topic"


def read_topic() -> dict | None:
    try:
        return json.loads(config.TOPIC_FILE.read_text())
    except Exception:
        return None


def read_highlights(limit: int = 5) -> list[str]:
    path = config.INVESTIGATION_DIR / "HIGHLIGHTS.md"
    try:
        lines = [
            ln.strip().lstrip("-").strip()
            for ln in path.read_text().splitlines()
            if ln.strip().startswith("- ")
        ]
        return lines[-limit:]
    except Exception:
        return []


def startup_repair() -> None:
    """If a previous topic-write crashed mid-scaffold (files present, no
    .topic.json commit marker), clear the partial state so the app cleanly
    re-asks for the topic rather than trusting half-written files. Any
    *previous, already-committed* investigation was archived before this
    point, so nothing real is lost — only an incomplete, not-yet-used scaffold.
    """
    d = config.INVESTIGATION_DIR
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        return
    has_files = any(d.iterdir())
    if has_files and not config.TOPIC_FILE.exists():
        shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)


def _archive_current_if_committed() -> None:
    """Move the current investigation dir aside if it holds a previously
    committed topic. No-op if there's no committed topic yet (fresh/empty).
    """
    d = config.INVESTIGATION_DIR
    topic = read_topic()
    if not topic or not d.exists():
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(topic.get("description", "topic"))
    dest = config.ARCHIVE_ROOT / f"{slug}-{ts}"
    config.ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    d.mkdir(parents=True, exist_ok=True)


def _render(template_text: str, topic: str, created_date: str) -> str:
    return template_text.replace("{{TOPIC}}", topic).replace("{{CREATED_DATE}}", created_date)


def set_topic(description: str) -> dict:
    """Archive the current investigation (if any committed topic exists),
    then scaffold a fresh one from the generic templates for the new topic.
    The .topic.json commit marker is written LAST.
    """
    description = description.strip()
    if not description:
        raise ValueError("empty topic")

    _archive_current_if_committed()

    d = config.INVESTIGATION_DIR
    created_date = datetime.now().strftime("%Y-%m-%d")

    # Top-level files from templates
    top_level = ["AGENTS.md", "wanted.md", "subjects.md", "HIGHLIGHTS.md", "sources.md"]
    for name in top_level:
        tmpl = (config.TEMPLATES_DIR / f"{name}.template").read_text()
        (d / name).write_text(_render(tmpl, description, created_date))

    # theories/
    (d / "theories").mkdir(exist_ok=True)
    for name in ["active.md", "archive.md", "scenarios.md"]:
        tmpl = (config.TEMPLATES_DIR / "theories" / f"{name}.template").read_text()
        (d / "theories" / name).write_text(_render(tmpl, description, created_date))

    # corpus/
    (d / "corpus" / "raw").mkdir(parents=True, exist_ok=True)
    (d / "corpus" / "entities").mkdir(parents=True, exist_ok=True)
    idx_tmpl = (config.TEMPLATES_DIR / "corpus" / "entities" / "_index.md.template").read_text()
    (d / "corpus" / "entities" / "_index.md").write_text(_render(idx_tmpl, description, created_date))

    # references/ ships empty for a fresh topic (see plan §3)
    (d / "references").mkdir(exist_ok=True)

    topic_record = {"description": description, "created_at": datetime.now().isoformat()}
    config.TOPIC_FILE.write_text(json.dumps(topic_record, indent=2))
    return topic_record
