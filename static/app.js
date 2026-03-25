// ---------- utilities ----------
async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const text = await res.text();
  if (!res.ok) {
    try { const j = JSON.parse(text); throw new Error(j.error || text || res.statusText); }
    catch { throw new Error(text || res.statusText); }
  }
  try { return JSON.parse(text); } catch { return {}; }
}
function msg(html, type = "info") { return `<div class="alert alert-${type} mt-2">${html}</div>`; }
function getEl(id) { return document.getElementById(id); }
function escapeHtml(s){ return (s||"").replace(/[&<>"']/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

// Keep track of current session shown in modal
let CURRENT_SESSION_ID = null;

// ---------- lookups ----------
async function loadLookups() {
  const data = await fetchJSON("/api/lookups");
  const aSel = getEl("alley");
  if (aSel) aSel.innerHTML = data.alleys.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
  const bList = getEl("bowlersList");
  if (bList) bList.innerHTML = data.bowlers.map(b => `<option data-id="${b.id}" value="${escapeHtml(b.name)}"></option>`).join("");
}

// ---------- defaults ----------
function setTodayIfEmpty() {
  const d = getEl("date");
  if (!d || d.value) return;
  const t = new Date();
  const m = String(t.getMonth() + 1).padStart(2, "0");
  const day = String(t.getDate()).padStart(2, "0");
  d.value = `${t.getFullYear()}-${m}-${day}`;
}
function setDefaultAlleyForBowler(name) {
  if (!name) return;
  const alleySel = getEl("alley");
  if (!alleySel) return;
  const opts = Array.from(alleySel.options);
  const lower = name.toLowerCase();
  let target = null;
  if (lower.includes("larry")) target = "Camarillo Bowl";
else if (lower.includes("medina") || lower.includes("rjb") || lower.includes("barsotti") || lower.includes("william") || lower.includes("edward")) target = "Milwaukie Bowl";
else if (lower.includes("rajan") || lower.includes("baule")) target = "Zodos Lanes";
  if (!target) return;
  const found = opts.find(o => o.text.toLowerCase() === target.toLowerCase());
  if (found) alleySel.value = found.value;
}

// ---------- scores ----------
function updateLiveStats() {
  const scores = getCurrentScores();
  const count = scores.length;
  const avg = count ? (scores.reduce((a, b) => a + b, 0) / count) : 0;
  const el = getEl("liveStats");
  if (el) el.innerHTML = `<span>Games: <strong>${count}</strong></span> <span class="ms-3">Avg: <strong>${avg.toFixed(2)}</strong></span>`;
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
  const alley_id = parseInt(getEl("alley")?.value || 0, 10);
  const session_date = getEl("date")?.value || "";
  const scores = getCurrentScores();
  const is_league = !!getEl("isLeague")?.checked;
  const out = document.querySelector("#entry .card-body") || document.body;

  if (!bowler_id) return out.insertAdjacentHTML("beforeend", msg("Select a bowler.", "danger"));
  if (!alley_id || !session_date) return out.insertAdjacentHTML("beforeend", msg("Select alley and date.", "danger"));
  if (!scores.length) return out.insertAdjacentHTML("beforeend", msg("Enter at least one score.", "danger"));
  if (scores.length > 12 || scores.some(x => x < 1 || x > 300))
    return out.insertAdjacentHTML("beforeend", msg("Scores must be 1–300 (max 12).", "danger"));

  try {
    await fetchJSON("/api/session", {
      method: "POST",
      body: JSON.stringify({ bowler_id, alley_id, session_date, scores, is_league }),
    });
    out.insertAdjacentHTML("beforeend", msg("Session saved.", "success"));
    await renderSessions();
    await renderLeagueSessions();
    await renderLeagueStandings();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
    await renderHistory();
  } catch (e) {
    out.insertAdjacentHTML("beforeend", msg("Save failed: " + escapeHtml(e.message), "danger"));
  }
}

// ---------- Sessions (list) ----------
async function renderSessions() {
  const rows = await fetchJSON("/api/sessions");
  const el = getEl("sessionsTable");
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = msg("No sessions yet.", "secondary");
    return;
  }
  let html = `<table class="table table-sm align-middle">
    <thead>
      <tr><th>Date</th><th>Bowler</th><th>Alley</th><th class="text-end">Games</th><th class="text-end">Avg</th><th>Notes</th></tr>
    </thead><tbody>`;
  for (const r of rows) {
    const avg = r.session_avg == null ? "—" : Number(r.session_avg).toFixed(2);
    const leagueBadge = r.is_league ? ` <span class="badge bg-warning text-dark">League</span>` : "";
    const hasNotes = (r.notes || "").trim().length > 0;
    const notesText = hasNotes ? "View Notes" : "Add Notes";
    const notesLink = `<a href="#" onclick="return openNotesModal(${r.id});">${notesText}</a>`;
    html += `<tr>
      <td>${escapeHtml(r.session_date)}</td>
      <td>${escapeHtml(r.bowler)}${leagueBadge}</td>
      <td>${escapeHtml(r.alley)}</td>
      <td class="text-end"><a href="#" onclick="return showSessionGames(${r.id});">${r.games}</a></td>
      <td class="text-end">${avg}</td>
      <td>${notesLink}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
}

// ---------- League Sessions ----------
async function renderLeagueSessions(){
  const el = getEl("leagueSessionsBlock");
  if (!el) return;
  try{
    const rows = await fetchJSON("/api/league-sessions");
    if (!rows.length){
      el.innerHTML = msg("No league sessions yet.", "secondary");
      return;
    }
    let html = `<table class="table table-sm align-middle">
      <thead>
        <tr><th>Date</th><th>Bowler</th><th>Alley</th><th class="text-end">Games</th><th class="text-end">Total Pins</th><th class="text-end">Average</th></tr>
      </thead><tbody>`;
    for (const r of rows){
      html += `<tr>
        <td>${escapeHtml(r.session_date)}</td>
        <td>${escapeHtml(r.bowler)}</td>
        <td>${escapeHtml(r.alley)}</td>
        <td class="text-end"><a href="#" onclick="return showSessionGames(${r.session_id});">${r.games}</a></td>
        <td class="text-end">${r.total_pins}</td>
        <td class="text-end">${r.session_avg}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
  }catch(e){
    console.error(e);
    el.innerHTML = msg("Failed to load league sessions.", "danger");
  }
}

// ---------- League Standings (avg + total games + league-only BIX) ----------
async function renderLeagueStandings(){
  const el = getEl("leagueStandingsBlock");
  if (!el) return;
  try{
    const data = await fetchJSON("/api/league-standings");
    const rows = data.standings || [];
    let html = "";

    if (data.league_bix_table && data.league_bix_table.length){
      html += `<div class="mb-4">
        <h5 class="mb-2">League-only BIX Leaderboard (Rajan · Medina · William · Edward · Larry)</h5>
        <div class="table-responsive">
          <table class="table table-sm table-striped align-middle">
            <thead><tr><th>Bowler</th><th class="text-end">BIX</th><th class="text-end">Diff</th><th class="text-center">Leader</th></tr></thead>
            <tbody>
              ${data.league_bix_table.map(r => `
                <tr ${r.leader ? 'class="table-success"' : ''}>
                  <td>${escapeHtml(r.name)}</td>
                  <td class="text-end">${Number(r.bix).toFixed(2)}</td>
                  <td class="text-end">${Number(r.diff).toFixed(2)}</td>
                  <td class="text-center">${r.leader ? "🏆" : ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
    }

    if (!rows.length){
      el.innerHTML = html + msg("No league data yet.", "secondary");
      return;
    }

    html += `<div class="table-responsive"><table class="table table-sm align-middle">
      <thead><tr><th>Bowler</th><th class="text-end">Games</th><th class="text-end">Total Pins</th><th class="text-end">Average</th><th class="text-end">League BIX</th></tr></thead>
      <tbody>`;
    for (const r of rows){
      html += `<tr>
        <td>${escapeHtml(r.name)}</td>
        <td class="text-end">${r.games}</td>
        <td class="text-end">${r.total_pins}</td>
        <td class="text-end">${r.avg}</td>
        <td class="text-end">${Number(r.bix).toFixed(2)}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
    el.innerHTML = html;
  }catch(e){
    console.error(e);
    el.innerHTML = msg("Failed to load league standings.", "danger");
  }
}

// ---------- Session Modal (edit/delete/add games) ----------
async function showSessionGames(sid) {
  try {
    const data = await fetchJSON(`/api/session/${sid}/games`);
    CURRENT_SESSION_ID = sid;

    const metaEl = getEl("sessionMeta");
    if (metaEl) metaEl.textContent = `${data.bowler} · ${data.alley} · ${data.session_date}`;

    const statsHost = getEl("sessionStats");
    if (statsHost) {
      const avg = (data.stats.avg == null) ? "—" : Number(data.stats.avg).toFixed(2);
      statsHost.innerHTML = `
        <div class="row text-center mb-3">
          <div class="col"><strong>Avg:</strong> ${avg}</div>
          <div class="col"><strong>Low:</strong> ${data.stats.low ?? "—"}</div>
          <div class="col"><strong>High:</strong> ${data.stats.high ?? "—"}</div>
        </div>`;
    }

    const tbody = getEl("sessionGamesTbody");
    if (tbody) {
      tbody.innerHTML = "";
      data.games.forEach(g => {
        const row = document.createElement("tr");
        row.setAttribute("data-gid", g.id);
        row.innerHTML = `
          <td style="width:60px">${g.game_number}</td>
          <td class="text-end">
            <div class="d-flex justify-content-end gap-2">
              <input type="number" min="1" max="300" class="form-control form-control-sm js-score-input" value="${g.score}" style="max-width:120px">
              <button class="btn btn-sm btn-outline-primary js-save-game" title="Save score">Save</button>
              <button class="btn btn-sm btn-outline-danger js-del-game" title="Delete game">Delete</button>
            </div>
          </td>
        `;
        tbody.appendChild(row);
      });

      const addRow = document.createElement("tr");
      addRow.innerHTML = `
        <td colspan="2">
          <div class="d-flex justify-content-end align-items-center gap-2">
            <input type="number" min="1" max="300" class="form-control form-control-sm" id="addGameScore" placeholder="New score" style="max-width:140px">
            <button class="btn btn-sm btn-primary" id="addGameBtn">Add Game</button>
            <span class="ms-2 small text-muted" id="addGameMsg"></span>
          </div>
        </td>
      `;
      tbody.appendChild(addRow);

      addRow.querySelector("#addGameBtn").addEventListener("click", addGameToCurrentSession);
      tbody.querySelectorAll(".js-save-game").forEach(btn => btn.addEventListener("click", onSaveGameClick));
      tbody.querySelectorAll(".js-del-game").forEach(btn => btn.addEventListener("click", onDeleteGameClick));
    }

    const modalEl = getEl("sessionModal");
    if (modalEl && window.bootstrap) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  } catch (e) {
    console.error(e);
    alert("Failed to load session.");
  }
  return false;
}

async function onSaveGameClick(e){
  const row = e.currentTarget.closest("tr");
  const gid = parseInt(row.getAttribute("data-gid"), 10);
  const input = row.querySelector(".js-score-input");
  const v = input.value ? parseInt(input.value, 10) : null;
  if (!v || v < 1 || v > 300) { alert("Enter a score 1–300."); return; }
  try{
    await fetchJSON(`/api/games/${gid}`, { method: "PUT", body: JSON.stringify({ score: v }) });
    await showSessionGames(CURRENT_SESSION_ID);
    await renderSessions();
    await renderLeagueSessions();
    await renderLeagueStandings();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
    await renderHistory();
  }catch(err){
    alert("Save failed: " + err.message);
  }
}

async function onDeleteGameClick(e){
  const row = e.currentTarget.closest("tr");
  const gid = parseInt(row.getAttribute("data-gid"), 10);
  if (!confirm("Delete this game?")) return;
  try{
    await fetchJSON(`/api/games/${gid}`, { method: "DELETE" });
    await showSessionGames(CURRENT_SESSION_ID);
    await renderSessions();
    await renderLeagueSessions();
    await renderLeagueStandings();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
    await renderHistory();
  }catch(err){
    alert("Delete failed: " + err.message);
  }
}

async function addGameToCurrentSession() {
  const scoreEl = getEl("addGameScore");
  const msgEl = getEl("addGameMsg");
  if (!scoreEl) return;
  const v = scoreEl.value ? parseInt(scoreEl.value, 10) : null;
  if (!v || v < 1 || v > 300) {
    if (msgEl) msgEl.textContent = "Enter a score 1–300.";
    return;
  }
  try {
    await fetchJSON(`/api/sessions/${CURRENT_SESSION_ID}/games`, {
      method: "POST",
      body: JSON.stringify({ score: v })
    });
    if (msgEl) msgEl.textContent = "Added!";
    scoreEl.value = "";
    await showSessionGames(CURRENT_SESSION_ID);
    await renderSessions();
    await renderLeagueSessions();
    await renderLeagueStandings();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
    await renderHistory();
  } catch (e) {
    console.error(e);
    if (msgEl) msgEl.textContent = "Failed: " + e.message;
  }
}

// ---------- Totals ----------
async function renderTotals() {
  const data = await fetchJSON("/api/totals");
  const el = getEl("totalsBlock");
  if (!el) return;

  let html = "";

  // Tip of day (optional)
  if (data.tip_of_day){
    html += `<div class="alert alert-secondary mb-3"><strong>Tip of the day:</strong> ${escapeHtml(data.tip_of_day)}</div>`;
  }

  // BIX comparison table for 4 rivals
  if (data.bix_table && data.bix_table.length){
    html += `<div class="mb-4">
      <h5 class="mb-2">BIX Leaderboard (Rajan · Medina · William · Edward · Larry)</h5>
      <div class="table-responsive">
        <table class="table table-sm table-striped align-middle">
          <thead>
<tr>
  <th>Bowler</th>
  <th class="text-end">Avg</th>
  <th class="text-end">BIX</th>
  <th class="text-end">Diff</th>
  <th class="text-center">Leader</th>
</tr>
</thead>
          <tbody>
            ${data.bix_table.map(r => {
  const t = data.totals.find(x => x.name === r.name);
  return `
    <tr ${r.leader ? 'class="table-success"' : ''}>
      <td>${escapeHtml(r.name)}</td>
      <td class="text-end">${t ? Number(t.avg).toFixed(2) : "0.00"}</td>
      <td class="text-end">${Number(r.bix).toFixed(2)}</td>
      <td class="text-end">${Number(r.diff).toFixed(2)}</td>
      <td class="text-center">${r.leader ? "🏆" : ""}</td>
    </tr>
  `;
}).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
  }

  if (!data.totals || !data.totals.length) {
    el.innerHTML = html + msg("No data yet.", "secondary");
    return;
  }

  for (const t of data.totals) {
    const badge = `<span class="badge bg-primary ms-2">${Number(t.bix).toFixed(2)}</span>`;
    const line =
      t.bix_group === "A"
        ? `Games: ${t.games} · Avg: ${Number(t.avg).toFixed(2)} · Std Dev: ${Number(t.stddev ?? 0).toFixed(2)} · 200+: ${t.c200} · 210+: ${t.c210} · ${t.conversion_label || 'Conv'}: ${Number(t.conversion_rate ?? 0).toFixed(2)}% ${badge}`
        : `Games: ${t.games} · Avg: ${Number(t.avg).toFixed(2)} · Std Dev: ${Number(t.stddev ?? 0).toFixed(2)} · 150+: ${t.c150} · ${t.conversion_label || 'Conv'}: ${Number(t.conversion_rate ?? 0).toFixed(2)}% ${badge}`;

    html += `<div class="mb-4">
      <h5 class="mb-1 d-flex align-items-center justify-content-between">
        <span>${escapeHtml(t.name)}</span>
      </h5>
      <div class="text-secondary mb-2">${line}</div>`;

    // Alleys (clickable)
    html += `<div class="d-flex justify-content-between align-items-center mt-2 mb-1">
      <span class="text-secondary">Alleys</span>
    </div>`;

    if (t.alleys?.length) {
      html += `<div class="table-responsive"><table class="table table-sm table-striped align-middle">
        <thead><tr><th>Alley</th><th class="text-end">Avg</th><th class="text-end">Games</th></tr></thead><tbody>`;
      t.alleys.forEach(a => {
        html += `<tr>
          <td><a href="#" onclick="return showAlleyGames(${t.bowler_id}, ${a.alley_id}, '${escapeHtml(t.name)}', '${escapeHtml(a.alley)}');">${escapeHtml(a.alley)}</a></td>
          <td class="text-end">${Number(a.avg ?? 0).toFixed(2)}</td>
          <td class="text-end">${a.games}</td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    } else {
      html += `<div class="text-secondary">No alley breakdown yet.</div>`;
    }

    html += `</div>`;
  }

  el.innerHTML = html;
}

// ---------- Alley drilldown modal ----------
async function showAlleyGames(bowler_id, alley_id, bowlerName, alleyName){
  try{
    const rows = await fetchJSON(`/api/bowlers/${bowler_id}/alleys/${alley_id}/games`);
    const title = getEl("alleyModalTitle");
    const body = getEl("alleyModalBody");
    if (title) title.textContent = `${bowlerName} · ${alleyName}`;
    if (body){
      if (!rows.length){
        body.innerHTML = msg("No games found for this alley.", "secondary");
      } else {
        let html = `<div class="table-responsive"><table class="table table-sm align-middle">
          <thead><tr><th>Date</th><th class="text-end">Game #</th><th class="text-end">Score</th></tr></thead><tbody>`;
        rows.forEach(r=>{
          html += `<tr><td>${escapeHtml(r.session_date)}</td><td class="text-end">${r.game_number}</td><td class="text-end">${r.score}</td></tr>`;
        });
        html += `</tbody></table></div>`;
        body.innerHTML = html;
      }
    }
    const modalEl = getEl("alleyModal");
    if (modalEl && window.bootstrap){
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  }catch(e){
    alert("Failed to load alley games: " + e.message);
  }
  return false;
}


// ---------- High Scores ----------
async function renderHighScores(){
  const el = getEl("highScoresBlock");
  if (!el) return;
  try{
    const data = await fetchJSON("/api/high-scores");

    function block(title, obj, rangeText=""){
      if (!obj){
        return `<div class="alert alert-secondary text-center">
          <div style="font-size:1.35rem;font-weight:800;">🏆 SPECIAL CONGRATULATIONS 🏆</div>
          <div style="font-size:1.1rem;font-weight:800;">${escapeHtml(title)}</div>
          <div class="text-muted">No games recorded${rangeText ? " for " + escapeHtml(rangeText) : ""}.</div>
        </div>`;
      }
      return `<div class="alert alert-success text-center">
        <div style="font-size:1.35rem;font-weight:900;">🏆 SPECIAL CONGRATULATIONS 🏆</div>
        <div style="font-size:1.15rem;font-weight:900;">${escapeHtml(title)}</div>
        <div style="font-size:1.2rem;font-weight:800;">${escapeHtml(obj.bowler)}</div>
        <div style="font-size:1.05rem;">
          Score: <strong>${obj.score}</strong><br>
          ${escapeHtml(obj.session_date)} @ ${escapeHtml(obj.alley)}
          ${rangeText ? `<div class="text-muted small mt-1">${escapeHtml(rangeText)}</div>` : ""}
        </div>
      </div>`;
    }

    const wkRange = data.week?.range ? `${data.week.range[0]} – ${data.week.range[1]}` : "";
    const moRange = data.month?.range ? `${data.month.range[0]} – ${data.month.range[1]}` : "";
    const yrRange = data.year?.range ? `${data.year.range[0]} – ${data.year.range[1]}` : "";
    const lyRange = data.league_year?.range ? `${data.league_year.range[0]} – ${data.league_year.range[1]}` : yrRange;

    let html = `<h4>High Scores</h4>`;
    html += block("High Score for Week", data.week?.best, wkRange);
    html += block("High Score for Month", data.month?.best, moRange);
    html += block(`High Score for Year${data.year?.year ? " (" + data.year.year + ")" : ""}`, data.year?.best, yrRange);
    html += block("League High Score for Year", data.league_year?.best, lyRange);
    html += block("All-Time High Score", data.all_time?.best, "");

    el.innerHTML = html;
  }catch(e){
    console.error(e);
    el.innerHTML = msg("Failed to load high scores.", "danger");
  }
}


// ---------- Honor Roll ----------
async function renderHonorRoll() {
  const el = getEl("honorRollBlock");
  if (!el) return;
  try {
    const data = await fetchJSON("/api/honor-roll");

    let html = `<h4>Honor Roll</h4>`;

    // Special congratulations
    if (data.monthly_champion) {
      const c = data.monthly_champion;
      html += `
        <div class="alert alert-success text-center mt-3">
          <div style="font-size:1.6rem; font-weight:800;">
            🏆 SPECIAL CONGRATULATIONS 🏆
          </div>
          <div style="font-size:1.25rem; font-weight:800;">
            ${escapeHtml(c.bowler)}
          </div>
          <div style="font-size:1.05rem;">
            Highest score this month: <strong>${c.score}</strong><br>
            ${escapeHtml(c.session_date)} @ ${escapeHtml(c.alley)}
          </div>
        </div>
      `;
    }

    const wk = data.week.range.join("–");
    const mo = data.month.range.join("–");

    const yearLines = (data.year.top_scores && data.year.top_scores.length)
      ? data.year.top_scores
          .map(r => `${r.score} — ${escapeHtml(r.bowler)} <span class="text-secondary">(${escapeHtml(r.session_date)} @ ${escapeHtml(r.alley)})</span>`)
          .join("<br>")
      : "No scores yet.";

    const months = data.months || [];
    let monthsHtml = "";
    months.forEach(m => {
      if (!m.top_scores || !m.top_scores.length) return;
      const list = m.top_scores.map((r, idx) =>
        `${idx + 1}. <strong>${r.score}</strong> — ${escapeHtml(r.bowler)} <span class="text-secondary">(${escapeHtml(r.session_date)} @ ${escapeHtml(r.alley)})</span>`
      ).join("<br>");
      monthsHtml += `
        <div class="card mb-2">
          <div class="card-header">
            ${escapeHtml(m.month)} <span class="text-muted small">(${m.range[0]} – ${m.range[1]})</span>
          </div>
          <div class="card-body small">
            ${list}
          </div>
        </div>
      `;
    });

    const monthlySection = monthsHtml
      ? `<div class="mt-4">
           <h5>Top 3 Scores by Month (Current Year)</h5>
           ${monthsHtml}
         </div>`
      : "";

    html += `
      <div class="row g-3">
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Scores — Week (${wk})</div>
          <div class="card-body">
            ${data.week.top_scores.map(r => `${r.score} — ${escapeHtml(r.bowler)} <span class="text-secondary">(${escapeHtml(r.session_date)} @ ${escapeHtml(r.alley)})</span>`).join("<br>") || "No scores."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Scores — Month (${mo})</div>
          <div class="card-body">
            ${data.month.top_scores.map(r => `${r.score} — ${escapeHtml(r.bowler)} <span class="text-secondary">(${escapeHtml(r.session_date)} @ ${escapeHtml(r.alley)})</span>`).join("<br>") || "No scores."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Avg — Week</div>
          <div class="card-body">
            ${data.week.top_avgs.map(r => `${r.avg.toFixed(2)} — ${escapeHtml(r.bowler)} <span class="text-secondary">(${r.games} games)</span>`).join("<br>") || "No data."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Avg — Month</div>
          <div class="card-body">
            ${data.month.top_avgs.map(r => `${r.avg.toFixed(2)} — ${escapeHtml(r.bowler)} <span class="text-secondary">(${r.games} games)</span>`).join("<br>") || "No data."}
          </div></div>
        </div>
        <div class="col-md-6">
          <div class="card"><div class="card-header">Top Scores — Year</div>
          <div class="card-body">
            ${yearLines}
          </div></div>
        </div>
      </div>
      ${monthlySection}
    `;

    el.innerHTML = html;
  } catch (e) {
    console.error(e);
    el.innerHTML = msg("Failed to load honor roll.", "danger");
  }
}

// ---------- History ----------
async function renderHistory(){
  const el = getEl("historyBlock");
  if (!el) return;
  try{
    const data = await fetchJSON("/api/history");
    const years = data.years || [];
    const rows = data.data || {};
    if (!years.length){
      el.innerHTML = msg("No historical data yet.", "secondary");
      return;
    }
    let html = `<div class="table-responsive"><table class="table table-sm table-striped align-middle">
      <thead><tr><th>Bowler</th>${years.map(y=>`<th class="text-end">${escapeHtml(y)}</th>`).join("")}</tr></thead><tbody>`;
    Object.keys(rows).sort().forEach(bowler=>{
      html += `<tr><td>${escapeHtml(bowler)}</td>`;
      years.forEach(y=>{
        const cell = rows[bowler][y];
        html += `<td class="text-end">${cell ? `${Number(cell.avg).toFixed(2)} <span class="text-muted">(${cell.games})</span>` : "—"}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table></div>`;
    el.innerHTML = html;
  }catch(e){
    console.error(e);
    el.innerHTML = msg("Failed to load historical averages.", "danger");
  }
}

// ---------- Admin: Add Alley ----------
async function addAlley(){
  const input = getEl("newAlleyName");
  const host = getEl("addAlleyMsg");
  const name = (input?.value || "").trim();
  if (!name){
    if (host) host.innerHTML = msg("Enter an alley name.", "danger");
    return;
  }
  try{
    await fetchJSON("/api/alleys", { method: "POST", body: JSON.stringify({ name }) });
    if (host) host.innerHTML = msg(`Added "${escapeHtml(name)}"`, "success");
    if (input) input.value = "";
    await loadLookups();
    buildAvgYearSelect();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
  }catch(e){
    if (host) host.innerHTML = msg(e.message, "danger");
  }
}


// ---------- Averages by Month ----------
let avgSelectedBowlerId = null;

function monthLabel(m) {
  const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return names[m-1] || String(m);
}

function buildAvgYearSelect() {
  const sel = getEl("avgYear");
  if (!sel) return;
  const nowY = new Date().getFullYear();
  const years = [];
  for (let y = nowY; y >= nowY - 5; y--) years.push(y);
  sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join("");
  sel.value = String(nowY);
}

async function renderAverages() {
  const host = getEl("averagesBlock");
  if (!host) return;
  const sel = getEl("avgYear");
  const chk = getEl("avgLeagueOnly");
  const year = sel ? sel.value : String(new Date().getFullYear());
  const leagueOnly = chk && chk.checked ? "1" : "";
  try {
    host.innerHTML = "Loading…";
    const bowlerQ = avgSelectedBowlerId ? `&bowler_id=${encodeURIComponent(avgSelectedBowlerId)}` : "";
    const data = await fetchJSON(`/api/monthly-averages?year=${encodeURIComponent(year)}${leagueOnly ? `&league_only=1` : ""}${bowlerQ}`);
    const rows = data.rows || [];
    const months = Array.from({length:12}, (_,i)=>i+1);

    const filterBar = () => {
      if (!avgSelectedBowlerId) return "";
      const name = rows.length ? rows[0].name : "";
      return `<div class="d-flex align-items-center gap-2 mb-2">
        <span class="badge text-bg-secondary">Filtered</span>
        <span class="fw-semibold">${escapeHtml(name)}</span>
        <a href="#" class="ms-2" data-avg-clear="1">Show all bowlers</a>
      </div>`;
    };

    // Table header
    let html = `<div class="table-responsive"><table class="table table-sm table-striped align-middle">
      <thead><tr>
        <th>Bowler</th>
        ${months.map(m=>`<th class="text-end">${monthLabel(m)}</th>`).join("")}
        <th class="text-end">YTD</th>
        <th class="text-end">Games</th>
      </tr></thead><tbody>`;

    let anyGames = false;
    for (const r of rows) {
      const ytd = r.ytd_avg;
      const games = r.ytd_games || 0;
      if (games) anyGames = true;
      html += `<tr>
        <td>${avgSelectedBowlerId ? escapeHtml(r.name) : `<a href="#" class="avg-bowler-link" data-avg-bowler="${r.bowler_id}">${escapeHtml(r.name)}</a>`}</td>
        ${months.map(m=>{
          const v = r.months && r.months[m] != null ? Number(r.months[m]).toFixed(2) : "";
          return `<td class="text-end">${v}</td>`;
        }).join("")}
        <td class="text-end fw-semibold">${ytd != null ? Number(ytd).toFixed(2) : ""}</td>
        <td class="text-end">${games}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;

    if (!anyGames) {
      html = msg(`No games found for ${year}${leagueOnly ? " (league only)" : ""} yet.`, "secondary") + html;
    }
    host.innerHTML = filterBar() + html;

  } catch (e) {
    host.innerHTML = msg(e.message || "Failed to load averages.", "danger");
  }
}

// Click handling for filtering
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-avg-bowler]");
  if (a) {
    e.preventDefault();
    avgSelectedBowlerId = a.getAttribute("data-avg-bowler");
    renderAverages();
    return;
  }
  const c = e.target.closest("[data-avg-clear]");
  if (c) {
    e.preventDefault();
    avgSelectedBowlerId = null;
    renderAverages();
  }
});

// refresh averages when controls change
document.addEventListener("change", (e) => {
  if (e.target && (e.target.id === "avgYear" || e.target.id === "avgLeagueOnly")) {
    renderAverages();
  }
});

// ---------- Boot ----------
document.addEventListener("DOMContentLoaded", async () => {
  try {
    buildScoreInputs(4);
    await loadLookups();
    buildAvgYearSelect();
    setTodayIfEmpty();
    await renderSessions();
    await renderLeagueSessions();
    await renderLeagueStandings();
    await renderTotals();
    await renderAverages();
    await renderHonorRoll();
    await renderHighScores();
    await renderHistory();
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
    getEl("addGame")?.addEventListener("click", () => addScoreInput());
    getEl("scoresWrap")?.addEventListener("input", e => {
      if (e.target.classList.contains("game")) updateLiveStats();
    });
    const yr = getEl("year");
    if (yr) yr.textContent = new Date().getFullYear();
    getEl("addAlleyBtn")?.addEventListener("click", addAlley);
    getEl("notesModalSave")?.addEventListener("click", saveNotesModal);
  }
});



// ------------------------------
// Notes (hyperlink -> modal)
// Shows all notes for the same bowler + date (e.g., league + non-league)
// ------------------------------
let _notesModalInstance = null;
let _notesModalContext = null; // { bowler, session_date, sessions: [{id,is_league,notes}] }

function ensureNotesModal() {
  const el = document.getElementById("notesModal");
  if (!el) return null;
  if (!_notesModalInstance) {
    _notesModalInstance = new bootstrap.Modal(el);
  }
  return _notesModalInstance;
}

function leagueLabel(isLeague) {
  return isLeague ? "League" : "Non-League";
}

function buildNotesEditor(sessionsForDay) {
  const container = document.getElementById("notesModalBody");
  if (!container) return;

  if (!sessionsForDay || sessionsForDay.length === 0) {
    container.innerHTML = `<div class="text-muted">No sessions found.</div>`;
    return;
  }

  let html = "";
  for (const s of sessionsForDay) {
    const label = leagueLabel(!!s.is_league);
    const safeNotes = escapeHtml(s.notes || "");
    html += `
      <div class="mb-3">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <strong>${label} notes</strong>
          <span class="text-muted small">Session #${s.id}</span>
        </div>
        <textarea class="form-control notesEditorTextarea" data-session-id="${s.id}"
                  rows="6" style="resize: vertical;"
                  placeholder="Write notes for this ${label.toLowerCase()} session...">${safeNotes}</textarea>
      </div>
    `;
  }
  container.innerHTML = html;
}

async function loadSessionsForSameDay(sessionId) {
  const res = await fetch("/api/sessions");
  const all = await res.json();

  const clicked = all.find(s => Number(s.id) === Number(sessionId));
  if (!clicked) return null;

  const bowler = clicked.bowler;
  const session_date = clicked.session_date;

  // all sessions for that bowler + date (allows league + non-league)
  const sessionsForDay = all
    .filter(s => s.bowler === bowler && s.session_date === session_date)
    .map(s => ({ id: s.id, is_league: s.is_league, notes: s.notes || "" }))
    .sort((a, b) => Number(b.is_league) - Number(a.is_league));

  return { bowler, session_date, sessionsForDay };
}

async function saveNotesForDay() {
  const areas = Array.from(document.querySelectorAll(".notesEditorTextarea"));
  const updates = areas.map(a => ({
    id: Number(a.getAttribute("data-session-id")),
    notes: a.value || ""
  }));

  // save sequentially to keep it simple and predictable
  for (const u of updates) {
    await fetch(`/api/sessions/${u.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: u.notes })
    });
  }
}

// Global function for inline onclick handlers in the Sessions table
window.openNotesModal = async function(sessionId) {
  try {
    const ctx = await loadSessionsForSameDay(sessionId);
    if (!ctx) return false;

    _notesModalContext = ctx;

    const titleEl = document.getElementById("notesModalTitle");
    if (titleEl) {
      titleEl.textContent = `${ctx.bowler} — ${ctx.session_date} — Notes`;
    }

    buildNotesEditor(ctx.sessionsForDay);

    const modal = ensureNotesModal();
    if (modal) modal.show();

  } catch (e) {
    console.error("openNotesModal failed:", e);
    alert("Could not load notes. Check the browser console for details.");
  }
  return false;
};

// Wire Save button (id from index.html)
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("notesModalSave");
  if (btn) {
    btn.addEventListener("click", async () => {
      try {
        await saveNotesForDay();
        // refresh sessions table (your app already has loadSessions)
        if (typeof loadSessions === "function") {
          await loadSessions();
        } else if (typeof refreshAll === "function") {
          await refreshAll();
        }
        if (_notesModalInstance) _notesModalInstance.hide();
      } catch (e) {
        console.error("saveNotesForDay failed:", e);
        alert("Could not save notes. Check the browser console for details.");
      }
    });
  }
});
