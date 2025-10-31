// ---------- utilities ----------
function apiUrl(path){
  const base = window.location.origin;
  if (!path.startsWith("/")) path = "/" + path;
  return base + path;
}
async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const text = await res.text();
  if (!res.ok) {
    try {
      const j = JSON.parse(text);
      throw new Error(j.error || text || (res.status + ' ' + res.statusText));
    } catch {
      throw new Error(text || (res.status + ' ' + res.statusText));
    }
  }
  try { return JSON.parse(text); } catch { return {}; }
}
function msg(html, type = "info") { return `<div class="alert alert-${type} mt-2">${html}</div>`; }
function setHTML(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; return !!el; }
function getEl(id) { return document.getElementById(id); }

// Keep track of current session shown in modal
let CURRENT_SESSION_ID = null;

// ---------- lookups ----------
async function loadLookups() {
  try {
    const data = await fetchJSON("/api/lookups");
    const aSel = getEl("alley");
    if (aSel) aSel.innerHTML = data.alleys.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
    const bList = getEl("bowlersList");
    if (bList) bList.innerHTML = data.bowlers.map(b => `<option data-id="${b.id}" value="${b.name}"></option>`).join("");
  } catch (e) {
    console.error("loadLookups failed:", e);
  }
}

// ---------- defaults ----------
function setDefaultAlleyForBowler(name) {
  if (!name) return;
  const alleySel = getEl("alley");
  if (!alleySel) return;
  const opts = Array.from(alleySel.options);
  const lower = name.toLowerCase();
  let target = null;
  if (lower.includes("medina")) target = "Milwaukie Bowl";
  else if (lower.includes("rjb")) target = "Milwaukie Bowl";
  else if (lower.includes("rajan") || lower.includes("baule") || lower.includes("barsotti")) target = "Zodos Lanes";
  if (!target) return;
  const found = opts.find(o => o.text.toLowerCase() === target.toLowerCase());
  if (found) alleySel.value = found.value;
}

// ---------- scores ----------
function updateLiveStats() {
  const scores = getCurrentScores();
  const count = scores.length;
  const avg = count ? (scores.reduce((a, b) => a + b, 0) / count) : 0;
  const cntEl = getEl("scoreCount");
  if (cntEl) cntEl.textContent = count;
  const el = getEl("liveStats");
  if (el) el.innerHTML = `<span>Games: <strong>${count}</strong></span> <span>Avg: <strong>${avg.toFixed(2)}</strong></span>`;
}
function addScoreInput(initValue = "") {
  const wrap = getEl("scoresWrap");
  if (!wrap) return;
  const idx = wrap.children.length + 1;
  if (idx > 12) return;
  const col = document.createElement("div");
  col.className = "col";
  col.innerHTML = `<input class="form-control game" placeholder="${idx}" type="number" min="1" max="300" value="${initValue}">`;
  wrap.appendChild(col);
}
function buildScoreInputs(initialCount = 4) {
  const wrap = getEl("scoresWrap");
  if (!wrap) return;
  wrap.innerHTML = "";
  for (let i = 0; i < initialCount; i++) addScoreInput();
  updateLiveStats();
}
function getCurrentScores() {
  const inputs = document.querySelectorAll("#scoresWrap .game");
  return Array.from(inputs)
    .map(el => (el.value ? parseInt(el.value, 10) : null))
    .filter(v => v !== null);
}
function setTodayIfEmpty() {
  const d = getEl("date");
  if (!d || d.value) return;
  const t = new Date();
  const m = String(t.getMonth() + 1).padStart(2, "0");
  const day = String(t.getDate()).padStart(2, "0");
  d.value = `${t.getFullYear()}-${m}-${day}`;
}

// ---------- Save Session ----------
function findBowlerIdByNameInput(nameTyped) {
  const options = Array.from(document.querySelectorAll("#bowlersList option"));
  if (!options.length) return null;
  const opt =
    options.find(o => o.value.toLowerCase() === nameTyped.toLowerCase()) ||
    options.find(o => o.value.toLowerCase().startsWith(nameTyped.toLowerCase()));
  return opt ? parseInt(opt.getAttribute("data-id"), 10) : null;
}

async function saveSession() {
  const nameTyped = (getEl("bowlerInput")?.value || "").trim();
  const bowler_id = findBowlerIdByNameInput(nameTyped);
  const alley_id = parseInt(getEl("alley")?.value || 0);
  const date = getEl("date")?.value || "";
  const scores = getCurrentScores();
  const out = document.querySelector("#entry .card-body") || document.body;

  if (!bowler_id) return out.insertAdjacentHTML("beforeend", msg("Select a bowler.", "danger"));
  if (!alley_id || !date) return out.insertAdjacentHTML("beforeend", msg("Select alley and date.", "danger"));
  if (!scores.length) return out.insertAdjacentHTML("beforeend", msg("Enter at least one score.", "danger"));
  if (scores.length > 12 || scores.some(x => x < 1 || x > 300))
    return out.insertAdjacentHTML("beforeend", msg("Scores must be 1–300 (max 12).", "danger"));

  try {
    await fetchJSON("/api/session", {
      method: "POST",
      body: JSON.stringify({ bowler_id, alley_id, session_date: date, scores }),
    });
    out.insertAdjacentHTML("beforeend", msg("Session saved.", "success"));
    await renderSessions();
    await renderTotals();
    await renderHonorRoll();
    await renderLikesTotal();
  } catch (e) {
    out.insertAdjacentHTML("beforeend", msg("Save failed: " + e.message, "danger"));
  }
}

// ---------- Sessions ----------
async function renderSessions() {
  try {
    const rows = await fetchJSON("/api/sessions");
    const el = getEl("sessionsTable");
    if (!el) return; // container missing — skip silently
    if (!rows.length) {
      el.innerHTML = msg("No sessions yet.", "secondary");
      return;
    }
    let html = `<table class="table table-sm align-middle">
      <thead>
        <tr><th>Date</th><th>Bowler</th><th>Alley</th><th class="text-end">Games</th><th class="text-end">Avg</th></tr>
      </thead><tbody>`;
    for (const r of rows) {
      const avg = r.session_avg == null ? "—" : Number(r.session_avg).toFixed(2);
      html += `<tr>
        <td>${r.session_date}</td>
        <td>${r.bowler}</td>
        <td>${r.alley}</td>
        <td class="text-end"><a href="#" onclick="return showSessionGames(${r.id});">${r.games}</a></td>
        <td class="text-end">${avg}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    el.innerHTML = html;
  } catch (e) {
    console.error("renderSessions failed:", e);
    setHTML("sessionsTable", msg("Failed to load sessions.", "danger"));
  }
}

// ---------- Session Modal + Likes ----------
async function showSessionGames(sid) {
  try {
    const data = await fetchJSON(`/api/session/${sid}/games`);
    CURRENT_SESSION_ID = sid;
    const metaEl = getEl("sessionMeta");
    if (metaEl) metaEl.textContent = `${data.bowler} · ${data.alley} · ${data.session_date}`;

    const statsHost = getEl("sessionStats");
    if (statsHost) {
      statsHost.innerHTML = `
        <div class="row text-center mb-3">
          <div class="col"><strong>Avg:</strong> ${data.stats.avg ?? "—"}</div>
          <div class="col"><strong>Low:</strong> ${data.stats.low ?? "—"}</div>
          <div class="col"><strong>High:</strong> ${data.stats.high ?? "—"}</div>
        </div>`;
    }

    const tbody = getEl("sessionGamesTbody");
    if (tbody) {
      tbody.innerHTML = "";
      data.games.forEach(g => {
        const likeBtnId = `like-btn-${g.id ?? 'sid'+sid+'-gn'+g.game_number}`;
        const likeCountId = `like-count-${g.id ?? 'sid'+sid+'-gn'+g.game_number}`;
        const gidAttr = (typeof g.id === "number" && g.id > 0) ? g.id : "";
        tbody.innerHTML += `
          <tr data-gn="${g.game_number}">
            <td>${g.game_number}</td>
            <td class="text-end">${g.score}</td>
            <td class="text-end">
              <button id="${likeBtnId}" class="btn btn-sm btn-outline-primary" onclick="return likeGameSmart('${gidAttr}', ${sid}, ${g.game_number});">
                👍 Like
              </button>
              <span class="ms-2 small text-secondary" id="${likeCountId}">${g.like_count ?? 0}</span>
            </td>
          </tr>`;
      });
    }

    const modalEl = getEl("sessionModal");
    if (modalEl && window.bootstrap) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  } catch (e) {
    console.error("showSessionGames failed:", e);
    alert("Failed to load session.");
  }
  return false;
}

async function likeGameSmart(gameIdStr, sessionId, gameNumber) {
  // First try by game id if valid
  const gid = parseInt(gameIdStr, 10);
  try {
    if (Number.isInteger(gid) && gid > 0) {
      const res = await fetchJSON(apiUrl(`/api/game/${gid}/like`), { method: "POST" });
      const cntEl = document.getElementById(`like-count-${gid}`) || document.getElementById(`like-count-sid${sessionId}-gn${gameNumber}`);
      if (cntEl) cntEl.textContent = res.likes;
      await renderLikesTotal();
      return false;
    }
    // Fallback to session/game_number route
    const res = await fetchJSON(apiUrl(`/api/session/${sessionId}/game/${gameNumber}/like`), { method: "POST" });
    const key = `sid${sessionId}-gn${gameNumber}`;
    const cntEl = document.getElementById(`like-count-${res.game_id}`) || document.getElementById(`like-count-${key}`);
    if (cntEl) cntEl.textContent = res.likes;
    await renderLikesTotal();
    return false;
  } catch (e) {
    console.error("likeGameSmart failed:", e);
    alert("Failed to like this game: " + e.message);
    return false;
  }
}

// ---------- Totals ----------
async function renderTotals() {
  try {
    const data = await fetchJSON("/api/totals");
    const el = document.getElementById("totalsBlock");
    if (!el) return;

    if (!data.totals || !data.totals.length) {
      el.innerHTML = `<div class="alert alert-secondary mt-2">No data yet.</div>`;
      return;
    }

    let html = "";
    for (const t of data.totals) {
      const badge = `<span class="badge bg-primary ms-2">${t.bix.toFixed(2)}</span>`;
      const line =
        t.bix_group === "A"
          ? `Games: ${t.games} · Avg: ${t.avg.toFixed(2)} · 200+: ${t.c200} · 210+: ${t.c210} ${badge}`
          : `Games: ${t.games} · Avg: ${t.avg.toFixed(2)} · 150+: ${t.c150} ${badge}`;

      html += `<div class="mb-4">
        <h5 class="mb-1 d-flex align-items-center justify-content-between">
          <span>${t.name}</span>
          <span class="badge bg-success" title="Total likes for ${t.name}">Likes: ${t.likes ?? 0}</span>
        </h5>
        <div class="text-secondary mb-2">${line}</div>`;

      // Header row for Alleys + Likes badge shown just above the table
      html += `<div class="d-flex justify-content-between align-items-center mt-2 mb-1">
        <span class="text-secondary">Alleys</span>
        <span class="badge bg-success" title="Total likes for ${t.name}">Likes: ${t.likes ?? 0}</span>
      </div>`;

      // Alleys table
      if (t.alleys?.length) {
        html += `<div class="table-responsive"><table class="table table-sm table-striped align-middle">
          <thead><tr><th>Alley</th><th class="text-end">Avg</th><th class="text-end">Games</th></tr></thead><tbody>`;
        t.alleys.forEach(a => {
          html += `<tr><td>${a.alley}</td><td class="text-end">${(a.avg ?? 0).toFixed(2)}</td><td class="text-end">${a.games}</td></tr>`;
        });
        html += `</tbody></table></div>`;
      } else {
        html += `<div class="text-secondary">No alley breakdown yet.</div>`;
      }

      html += `</div>`;
    }

    if (data.bix_message) html += `<div class="alert alert-info">${data.bix_message}</div>`;
    el.innerHTML = html;
  } catch (e) {
    console.error("renderTotals failed:", e);
    const el = document.getElementById("totalsBlock");
    if (el) el.innerHTML = `<div class="alert alert-danger">Failed to load totals.</div>`;
  }
}

// ---------- Honor Roll ----------
async function renderHonorRoll() {
  try {
    const el = getEl("honorRollBlock");
    if (!el) return; // container missing — skip
    const data = await fetchJSON("/api/honor-roll");
    const wk = data.week.range.join("–");
    const mo = data.month.range.join("–");
    const yearTop = data.year.top_score
      ? `${data.year.top_score.score} — ${data.year.top_score.bowler} (${data.year.top_score.session_date} @ ${data.year.top_score.alley})`
      : "No scores yet.";

    el.innerHTML = `
      <h4>Honor Roll</h4>
      <div class="row g-3">
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Scores — Week (${wk})</div>
          <div class="card-body">
            ${data.week.top_scores.map(r => `${r.score} — ${r.bowler} <span class="text-secondary">(${r.session_date} @ ${r.alley})</span>`).join("<br>") || "No scores."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Scores — Month (${mo})</div>
          <div class="card-body">
            ${data.month.top_scores.map(r => `${r.score} — ${r.bowler} <span class="text-secondary">(${r.session_date} @ ${r.alley})</span>`).join("<br>") || "No scores."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Avg — Week</div>
          <div class="card-body">
            ${data.week.top_avgs.map(r => `${r.avg.toFixed(2)} — ${r.bowler} <span class="text-secondary">(${r.games} games)</span>`).join("<br>") || "No data."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Avg — Month</div>
          <div class="card-body">
            ${data.month.top_avgs.map(r => `${r.avg.toFixed(2)} — ${r.bowler} <span class="text-secondary">(${r.games} games)</span>`).join("<br>") || "No data."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Score — Year</div>
          <div class="card-body">${yearTop}</div></div>
        </div>
      </div>`;
  } catch (e) {
    console.error("renderHonorRoll failed:", e);
    setHTML("honorRollBlock", msg("Failed to load honor roll.", "danger"));
  }
}

// ---------- Likes Total Badge (optional) ----------
async function renderLikesTotal() {
  try {
    const host = getEl("likesTotalHost");
    const badge = getEl("likesTotalBadge");
    if (!host && !badge) return; // no placeholder in DOM
    const data = await fetchJSON("/api/likes/total");
    if (badge) badge.textContent = data.total_likes;
    else if (host) host.innerHTML = `Total Likes <span class="badge bg-success ms-2" id="likesTotalBadge">${data.total_likes}</span>`;
  } catch (e) {
    console.error("renderLikesTotal failed:", e);
  }
}

// ---------- Boot ----------
document.addEventListener("DOMContentLoaded", async () => {
  try {
    buildScoreInputs(4);
    await loadLookups();
    setTodayIfEmpty();
    await renderSessions();
    await renderTotals();
    await renderHonorRoll();
    await renderLikesTotal();
  } catch (e) {
    console.error("DOMContentLoaded pipeline error:", e);
  } finally {
    const bi = getEl("bowlerInput");
    if (bi) {
      bi.addEventListener("input", e => setDefaultAlleyForBowler(e.target.value));
      bi.addEventListener("change", e => setDefaultAlleyForBowler(e.target.value));
    }
    getEl("save")?.addEventListener("click", saveSession);
    getEl("clear")?.addEventListener("click", () => buildScoreInputs(4));
    getEl("scoresWrap")?.addEventListener("input", e => {
      if (e.target.classList.contains("game")) updateLiveStats();
    });
    const yr = getEl("year");
    if (yr) yr.textContent = new Date().getFullYear();
  }
});
