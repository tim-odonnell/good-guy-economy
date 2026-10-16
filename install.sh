#!/usr/bin/env bash
# Install Good-Guy-Economy for the current user from this checkout. Safe to re-run (also after `git pull`).
#   ./install.sh            put everything in place (commands, scripts, units, icons, example configs)
#   ./install.sh --enable   ...and switch on the control page and the nightly timers
# It never overwrites your configs or a running investigation; it does refresh the code.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
ENABLE=0; [ "${1:-}" = "--enable" ] && ENABLE=1
say() { printf '  %s\n' "$*"; }
link() { ln -sfn "$1" "$2"; }

echo "Checking what this machine has:"
for c in python3 curl systemctl pdftotext notify-send; do
    command -v "$c" >/dev/null && say "ok      $c" || say "MISSING $c"
done
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)')" 2>/dev/null \
    && say "ok      python sqlite FTS5" || say "MISSING python sqlite FTS5 (needed by the document library)"
[ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ] && say "ok      hermes-agent" \
    || say "MISSING hermes-agent in ~/.hermes/hermes-agent (https://github.com/NousResearch/hermes-agent)"

echo "Installing from $REPO:"
mkdir -p ~/.local/bin ~/.config/systemd/user ~/.hermes/scripts ~/.local/share/applications \
         ~/.local/share/icons/good-guy-economy ~/.config/good-guy-economy
chmod +x "$REPO"/bin/* "$REPO"/tui/good-guy-economy "$REPO"/hermes-scripts/*.py
for f in "$REPO"/bin/*; do link "$f" ~/.local/bin/"$(basename "$f")"; done
say "commands linked into ~/.local/bin"
link "$REPO/control" ~/good-guy-economy-control
link "$REPO/tui/good-guy-economy" ~/good-guy-economy-tui
link "$REPO/templates" ~/.hermes/good-guy-economy-templates
link "$REPO/gemma-dispatcher" ~/.local/share/gemma-dispatch

# Hermes only runs pre-run scripts that really live in ~/.hermes/scripts (it refuses links pointing elsewhere),
# so these are copied. Re-run ./install.sh after changing them in the repo.
cp "$REPO"/hermes-scripts/*.py ~/.hermes/scripts/
say "Hermes pre-run scripts copied into ~/.hermes/scripts"

INV="$HOME/.hermes/investigations/active"
if [ -f "$INV/AGENTS.md" ]; then
    say "investigation folder already exists - left as it is"
else
    mkdir -p "$INV"/{corpus/raw,corpus/entities,data/digest,data/history,theories,reports/drafts,reports/factcheck}
    cp -r "$REPO"/investigation/. "$INV"/
    say "US-economy topic installed in $INV"
fi

cp "$REPO"/systemd/*.service "$REPO"/systemd/*.timer ~/.config/systemd/user/
mkdir -p ~/.config/systemd/user/good-guy-economy-llm.service.d
cp "$REPO"/systemd/good-guy-economy-llm.service.d/*.conf ~/.config/systemd/user/good-guy-economy-llm.service.d/
systemctl --user daemon-reload
say "systemd user units installed"

cp "$REPO"/desktop/icons/*.svg ~/.local/share/icons/good-guy-economy/
for f in "$REPO"/desktop/*.desktop; do   # Exec=/Icon= need literal paths
    sed -e "s#/home/user/good-guy-economy#$REPO#g" -e "s#/home/user#$HOME#g" "$f" > ~/.local/share/applications/"$(basename "$f")"
done
say "menu entries installed"

for pair in "paths.env.example:paths.env" "model.env.example:model.env"; do
    src="${pair%%:*}"; dst="$HOME/.config/good-guy-economy/${pair##*:}"
    [ -f "$dst" ] || { cp "$REPO/config/$src" "$dst"; say "created $dst from the example - EDIT IT for this machine"; }
done

if [ "$ENABLE" = 1 ]; then
    systemctl --user enable --now good-guy-economy-control.service
    systemctl --user enable --now good-guy-economy-window-start.timer good-guy-economy-window-stop.timer \
        econ-report-build.timer econ-report-notify.timer econ-library.timer
    say "control page and nightly timers enabled"
else
    echo
    echo "Next: edit ~/.config/good-guy-economy/model.env, create the Hermes jobs (good-guy-economy-create-jobs),"
    echo "then run ./install.sh --enable. Details: docs/INSTALL.md"
fi
