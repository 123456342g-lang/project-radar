const $ = (id) => document.getElementById(id);

const state = {
  scanId: null,
  poller: null,
  report: null,
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep statusText */ }
    throw new Error(detail);
  }
  return response.json();
}

function showError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.classList.remove("hidden");
}

function clearError() {
  $("errorBox").classList.add("hidden");
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    $("judgeMode").textContent = `judge: ${health.judge_mode}`;
    $("tokenPill").textContent = `github token: ${health.github_token ? "set" : "missing (60 req/h)"}`;
  } catch (_) {
    $("judgeMode").textContent = "judge: unavailable";
  }
}

function setProgress(stage, progress, label) {
  $("progressBar").style.width = `${Math.round(progress * 100)}%`;
  $("progressLabel").textContent = label || stage;
}

async function startScan(repo) {
  clearError();
  $("scanBtn").disabled = true;
  $("topSection").classList.add("hidden");
  $("candidatesSection").classList.add("hidden");
  $("contextSection").classList.add("hidden");
  $("repoMeta").classList.add("hidden");
  $("progressWrap").classList.remove("hidden");
  setProgress("starting", 0.02, "starting…");

  try {
    const created = await api("/api/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo }),
    });
    state.scanId = created.scan_id;
    state.poller = setInterval(pollScan, 1200);
  } catch (error) {
    showError(error.message);
    $("scanBtn").disabled = false;
    $("progressWrap").classList.add("hidden");
  }
}

async function pollScan() {
  try {
    const scan = await api(`/api/scans/${state.scanId}`);
    setProgress(scan.stage || scan.status, scan.progress || 0, `${scan.stage || scan.status} · ${Math.round((scan.progress || 0) * 100)}%`);
    if (scan.status === "failed") {
      stopPolling();
      showError(scan.error || "scan failed");
      return;
    }
    if (scan.status === "done") {
      stopPolling();
      await loadReport();
    }
  } catch (error) {
    stopPolling();
    showError(error.message);
  }
}

function stopPolling() {
  if (state.poller) clearInterval(state.poller);
  state.poller = null;
  $("scanBtn").disabled = false;
  $("progressWrap").classList.add("hidden");
}

async function loadReport() {
  try {
    const report = await api(`/api/scans/${state.scanId}/report`);
    state.report = report;
    renderRepo(report);
    renderTop(report.top || []);
    renderCandidates(report.candidates || []);
    renderContext(report.context || {});
  } catch (error) {
    showError(error.message);
  }
}

function renderRepo(report) {
  const meta = $("repoMeta");
  const repo = report.repo || {};
  const scan = report.scan || {};
  meta.innerHTML = `<strong>${esc(repo.full_name || "")}</strong> — scanned
    ${scan.finished_at ? new Date(scan.finished_at * 1000).toLocaleString() : ""}
    · ${report.judge_mode === "jev" ? "judged by Jev" : "offline heuristic judge"}`;
  meta.classList.remove("hidden");
}

function renderTop(top) {
  const list = $("topList");
  list.innerHTML = "";
  if (!top.length) {
    list.innerHTML = `<div class="top-card"><p>No clusters found. The repo may be too small or too quiet for this scan window.</p></div>`;
  }
  top.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "top-card";
    card.innerHTML = `
      <div class="rank-row">
        <span class="rank-badge">#${item.rank || index + 1}</span>
        <h3>${esc(item.title || "Untitled problem")}</h3>
        <span class="type-chip">${esc((item.problem_type || "other").replace(/_/g, " "))}</span>
      </div>
      <div class="why-block">
        <div class="why-line"><b>Why it exists</b>${esc(item.why || "")}</div>
        <div class="why-line"><b>Why unresolved</b>${esc(unresolvedLine(item))}</div>
        <div class="why-line"><b>Why worth it</b>${esc(worthLine(item))}</div>
        <div class="why-line"><b>Minimal fix</b>${esc(minimalFix(item))}</div>
      </div>
      ${statGrid(item)}
      ${judgmentRow(item)}
      <div class="card-actions">
        <button data-act="evidence">Why? — evidence chain</button>
        <button data-act="confirm">This problem is real</button>
        <button data-act="split">Misjudged / different problems</button>
        <button data-act="solved">Actually solved</button>
        <button data-act="minor">Not that important</button>
      </div>
      <div class="evidence">${evidenceHtml(item)}</div>
    `;
    wireActions(card, item);
    list.appendChild(card);
  });
  $("topSection").classList.remove("hidden");
}

function unresolvedLine(item) {
  if (item.why) return item.why;
  const j = item.judgment || {};
  const e = item.evidence || {};
  return `${e.open_ratio > 0.5 ? "most artifacts still open" : "mixed states"},
    ${e.merged_fixes || 0} merged fixes, unresolved p=${fmt(j.unresolved)}.`;
}

function worthLine(item) {
  const j = item.judgment || {};
  const e = item.evidence || {};
  return `${e.independent_authors || 0} independent authors, ${e.surfaces || 1} evidence surfaces,
    worth building ${fmt(j.worth_building)}/3.`;
}

function minimalFix(item) {
  return item.minimal_fix || "See evidence chain, start from the oldest report.";
}

function statGrid(item) {
  const e = item.evidence || {};
  const stats = [
    [e.issues, "issues"],
    [e.discussions, "discussions"],
    [e.pull_requests, "PRs"],
    [e.independent_authors, "authors"],
    [`${Math.round((e.span_days || 0) / 30)}mo`, "span"],
    [e.merged_fixes, "merged fixes"],
    [e.failed_pr_attempts, "failed PRs"],
  ];
  return `<div class="stat-grid">${stats
    .map(([v, k]) => `<div class="stat"><div class="v">${v ?? 0}</div><div class="k">${k}</div></div>`)
    .join("")}</div>`;
}

function judgmentRow(item) {
  const j = item.judgment || {};
  const rows = [
    ["same problem", fmt(j.same_problem)],
    ["recurring", fmt(j.recurring)],
    ["unresolved", fmt(j.unresolved)],
    ["worth building", `${fmt(j.worth_building)}/3`],
    ["priority", fmt(item.priority)],
    ["judge", j.judge_mode || "?"],
  ];
  return `<div class="judgment-row">${rows
    .map(([k, v]) => `<span class="j">${k}<b>${v}</b></span>`)
    .join("")}</div>`;
}

function evidenceHtml(item) {
  const chain = item.artifacts || [];
  if (!chain.length) return "<p>No artifact links stored for this candidate.</p>";
  return chain
    .map((a) => {
      const label = `${a.kind === "pull_request" ? "PR" : a.kind} #${a.number}`;
      const title = esc(a.title || "");
      const inner = a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${title}</a>` : title;
      return `<div class="chain-item">
        <span class="date">${esc(a.date || "")}</span>
        <span class="label">${esc(label)}</span>
        ${inner}
        <span class="state ${esc(a.state || "")}">${esc(a.state || "")}</span>
      </div>`;
    })
    .join("");
}

function wireActions(card, item) {
  const evidence = card.querySelector(".evidence");
  card.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", async () => {
      const act = button.dataset.act;
      if (act === "evidence") {
        evidence.classList.toggle("open");
        button.classList.toggle("active");
        return;
      }
      if (!item.problem_id) return;
      try {
        await api(`/api/problems/${item.problem_id}/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: act, note: "" }),
        });
        card.querySelectorAll(".card-actions button:not([data-act=evidence])")
          .forEach((b) => b.classList.remove("active"));
        button.classList.add("active");
        button.textContent = "Saved — next scan will use it";
      } catch (error) {
        showError(error.message);
      }
    });
  });
}

function renderCandidates(candidates) {
  const rows = $("candidateRows");
  rows.innerHTML = candidates
    .map(
      (c, i) => `<tr>
        <td class="rank-cell">${c.rank || i + 1}</td>
        <td>${esc(c.canonical_title || "")}</td>
        <td>${esc((c.problem_type || "").replace(/_/g, " "))}</td>
        <td class="num">${fmt(c.priority)}</td>
        <td class="num">${fmt(c.same_problem)}</td>
        <td class="num">${fmt(c.unresolved)}</td>
        <td class="num">${fmt(c.worth_building)}</td>
      </tr>`
    )
    .join("");
  $("candidatesSection").classList.remove("hidden");
}

function renderContext(context) {
  $("contextBox").textContent = JSON.stringify(context, null, 2);
  $("contextSection").classList.remove("hidden");
}

function fmt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(2);
}

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

$("scanForm").addEventListener("submit", (event) => {
  event.preventDefault();
  startScan($("repoInput").value.trim());
});

loadHealth();
