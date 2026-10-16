const $ = (id) => document.getElementById(id);

let forceTopicForm = false;
let opInProgress = false;
let confirmCallback = null;
let missedJobs = [];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  return { ok: res.ok, status: res.status, data };
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.remove("active"));
  $(id).classList.add("active");
}

function setButtonsDisabled(disabled) {
  ["btn-start", "btn-pause", "btn-stop", "btn-new-topic", "topic-submit"].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = disabled;
  });
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch (_) { return iso; }
}

function renderLoading(status) {
  const steps = [
    { label: "Model engine", ok: status.services["good-guy-economy-llm"] === "active" },
    { label: "Research browser", ok: status.services["camofox-browser"] === "active" },
    { label: "Model finished loading", ok: status.model_ready },
  ];
  $("loading-steps").innerHTML = steps
    .map((s) => `<li class="${s.ok ? "ok" : "pending"}">${s.label}</li>`)
    .join("");
}

function renderDashboard(status) {
  missedJobs = status.missed_jobs || [];
  $("dash-topic").textContent = status.topic ? status.topic.description : "";

  const gatewayUp = status.gateway_active;
  $("btn-start").hidden = gatewayUp;
  $("btn-pause").hidden = !gatewayUp;

  const jobs = Object.values(status.jobs || {});
  const anyPaused = jobs.some((j) => j.state === "paused");
  $("btn-pause").textContent = anyPaused ? "▶ Resume" : "⏸ Pause";

  $("dash-state").textContent = gatewayUp
    ? (anyPaused ? "Investigation is paused." : "Investigation is running on schedule.")
    : "Investigation is stopped.";

  $("jobs-list").innerHTML = jobs.length
    ? jobs
        .map(
          (j) => `<div class="job-row">
            <span class="job-name">${j.label}</span>
            <span class="job-next">${j.state === "paused" ? "paused" : "next: " + fmtDate(j.next_run_at)}</span>
          </div>`
        )
        .join("")
    : `<p class="muted">No schedule data yet.</p>`;

  const hl = status.highlights || [];
  $("highlights-list").innerHTML = hl.length
    ? hl.map((h) => `<li>${escapeHtml(h)}</li>`).reverse().join("")
    : `<li class="empty">No findings yet.</li>`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function render(status) {
  $("topbar-status").textContent =
    status.phase === "loading" ? "starting…" :
    status.gateway_active ? "running" : "idle";

  if (status.phase === "loading") {
    forceTopicForm = false;
    showScreen("screen-loading");
    renderLoading(status);
  } else if (status.phase === "needs_topic" || forceTopicForm) {
    showScreen("screen-topic");
  } else {
    showScreen("screen-dashboard");
    renderDashboard(status);
  }
}

let pollTimer = null;
async function poll() {
  const { ok, data } = await api("/api/status");
  if (ok) render(data);
  const delay = data && data.phase === "loading" ? 1500 : 8000;
  pollTimer = setTimeout(poll, delay);
}

function openModal(message, onConfirm) {
  $("modal-message").textContent = message;
  confirmCallback = onConfirm;
  $("modal-overlay").hidden = false;
}
function closeModal() {
  $("modal-overlay").hidden = true;
  confirmCallback = null;
}

$("modal-cancel").addEventListener("click", closeModal);
$("modal-confirm").addEventListener("click", () => {
  const cb = confirmCallback;
  closeModal();
  if (cb) cb();
});

$("topic-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("topic-input").value.trim();
  $("topic-error").hidden = true;
  if (!text) return;
  setButtonsDisabled(true);
  const { ok, data } = await api("/api/topic", { method: "POST", body: { description: text } });
  setButtonsDisabled(false);
  if (!ok) {
    $("topic-error").textContent = (data && data.detail) || "Something went wrong — try again.";
    $("topic-error").hidden = false;
    return;
  }
  forceTopicForm = false;
  $("topic-input").value = "";
  poll();
});

$("btn-new-topic").addEventListener("click", () => {
  openModal(
    "Starting a new investigation archives the current one (its findings stay saved, just out of the way) and clears the dashboard. Continue?",
    () => { forceTopicForm = true; showScreen("screen-topic"); }
  );
});

async function startInvestigation() {
  setButtonsDisabled(true);
  await api("/api/gateway/start", { method: "POST" });
  setButtonsDisabled(false);
  poll();
}

$("btn-start").addEventListener("click", () => {
  if (missedJobs.length) {
    openModal(
      `Good-Guy-Economy missed ${missedJobs.length} scheduled job${missedJobs.length > 1 ? "s" : ""} ` +
      `(${missedJobs.join(", ")}) while it was off. Starting now makes it run them all, one after ` +
      "another — about two hours of heavy work, and the laptop will feel slow. " +
      "Otherwise it simply runs at 1:00 am. Start anyway?",
      startInvestigation
    );
    return;
  }
  startInvestigation();
});

$("btn-pause").addEventListener("click", async () => {
  const resuming = $("btn-pause").textContent.includes("Resume");
  setButtonsDisabled(true);
  await api(resuming ? "/api/jobs/resume" : "/api/jobs/pause", { method: "POST" });
  setButtonsDisabled(false);
  poll();
});

$("btn-stop").addEventListener("click", async () => {
  setButtonsDisabled(true);
  const { data } = await api("/api/stack/stop", { method: "POST" });
  if (data && data.needs_confirm) {
    setButtonsDisabled(false);
    openModal(data.message, async () => {
      setButtonsDisabled(true);
      await api("/api/stack/stop?force=true", { method: "POST" });
      setButtonsDisabled(false);
      poll();
    });
    return;
  }
  setButtonsDisabled(false);
  poll();
});

// Kick things off: ask the backend to bring the stack up (idempotent if
// already running), then start polling status.
api("/api/stack/start", { method: "POST" }).finally(poll);
