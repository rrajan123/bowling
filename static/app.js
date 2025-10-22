// ---------- utilities ----------
async function fetchJSON(url, opts={}){
  const res = await fetch(url, {headers: {"Content-Type":"application/json"}, ...opts});
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}
function msg(html, type="info"){ return `<div class="alert alert-${type} mt-2">${html}</div>`; }

// ---------- lookups ----------
async function loadLookups(){
  const data = await fetchJSON("/api/lookups");

  // populate alley select
  const aSel = document.getElementById("alley");
  aSel.innerHTML = data.alleys.map(a=>`<option value="${a.id}">${a.name}</option>`).join("");

  // populate bowlers datalist
  const bList = document.getElementById("bowlersList");
  bList.innerHTML = data.bowlers.map(b=>`<option data-id="${b.id}" value="${b.name}"></option>`).join("");

  // simple diagnostics if empty
  const diag = document.getElementById("lookupDiag");
  const aCount = data.alleys.length, bCount = data.bowlers.length;
  diag.textContent = `Loaded ${bCount} bowlers, ${aCount} alleys.`;
}

// ---------- defaults mapping ----------
function setDefaultAlleyForBowler(name){
  if (!name) return;
  const alleySel = document.getElementById("alley");
  const opts = Array.from(alleySel.options);
  const lower = name.toLowerCase();

  let target = null;
  if (lower.includes("medina")) target = "Milwaukie Lanes";
  else if (lower.includes("rajan") || lower.includes("baule")) target = "Zodos Lanes";

  if (!target) return;
  let found = opts.find(o => o.text.toLowerCase() === target.toLowerCase());
  if (!found && target.toLowerCase().startsWith("milwaukie")){
    found = opts.find(o => o.text.toLowerCase().startsWith("milwaukie"));
  }
  if (found) alleySel.value = found.value;
}

// ---------- scores helpers ----------
function updateLiveStats(){
  const scores = getCurrentScores();
  const count = scores.length;
  const avg = count ? (scores.reduce((a,b)=>a+b,0)/count) : 0;
  document.getElementById('scoreCount').textContent = count;
  const el = document.getElementById('liveStats');
  el.innerHTML = `<span class="stat">Games: <strong>${count}</strong></span><span class="stat"> Avg: <strong>${avg.toFixed(2)}</strong></span>`;
}
function addScoreInput(initValue=""){
  const wrap = document.getElementById('scoresWrap');
  const idx = wrap.children.length + 1;
  if (idx>12) return;
  const col = document.createElement('div');
  col.className = 'col';
  col.setAttribute('data-idx', idx);
  col.innerHTML = `<input class="form-control game" inputmode="numeric" placeholder="${idx}" type="number" min="1" max="300" value="${initValue}">`;
  wrap.appendChild(col);
}
function buildScoreInputs(initialCount=4){
  const wrap = document.getElementById('scoresWrap'); wrap.innerHTML = '';
  for (let i=0;i<initialCount;i++) addScoreInput();
  updateLiveStats();
}
function getCurrentScores(){
  return Array.from(document.querySelectorAll('#scoresWrap .game'))
      .map(el => el.value ? parseInt(el.value,10) : null)
      .filter(v => v!==null);
}
function setTodayIfEmpty(){
  const d = document.getElementById("date");
  if (!d.value){
    const t = new Date();
    const m = String(t.getMonth()+1).padStart(2,'0');
    const day = String(t.getDate()).padStart(2,'0');
    d.value = `${t.getFullYear()}-${m}-${day}`;
  }
}

// ---------- save session ----------
function findBowlerIdByNameInput(nameTyped){
  const options = Array.from(document.querySelectorAll("#bowlersList option"));
  // exact (case-insensitive)
  let opt = options.find(o => o.value.toLowerCase() === nameTyped.toLowerCase());
  if (opt) return parseInt(opt.getAttribute("data-id"), 10);
  // prefix (case-insensitive)
  opt = options.find(o => o.value.toLowerCase().startsWith(nameTyped.toLowerCase()));
  if (opt) return parseInt(opt.getAttribute("data-id"), 10);
  return null;
}

async function saveSession(){
  const bowlerInput = document.getElementById("bowlerInput");
  const alleySel  = document.getElementById("alley");
  const dateEl    = document.getElementById("date");

  const nameTyped = bowlerInput.value.trim();
  const bowler_id = findBowlerIdByNameInput(nameTyped);

  const alley_id  = alleySel && alleySel.value !== "" ? parseInt(alleySel.value,10) : null;
  const date      = dateEl ? dateEl.value : "";
  const scores = getCurrentScores();

  const out = document.querySelector("#entry .card-body");
  if (bowler_id===null) { out.insertAdjacentHTML("beforeend", msg("Pick a bowler from the list (start typing to search).","danger")); return; }
  if (alley_id===null || !date) { out.insertAdjacentHTML("beforeend", msg("Choose an alley and a date.","danger")); return; }
  if (scores.length===0) { out.insertAdjacentHTML("beforeend", msg("Enter at least one score","danger")); return; }
  if (scores.length>12)  { out.insertAdjacentHTML("beforeend", msg("Max 12 games per session","danger")); return; }
  if (scores.some(x=>Number.isNaN(x) || x<1 || x>300)) { out.insertAdjacentHTML("beforeend", msg("Scores must be 1–300","danger")); return; }

  try{
    const resp = await fetchJSON("/api/session", {method:"POST", body: JSON.stringify({bowler_id, alley_id, session_date: date, scores})});
    out.insertAdjacentHTML("beforeend", msg("Session saved — see Current Session below.","success"));
    await renderSessions(); await renderTotals();
    if (resp && resp.session_id){ await showEntrySession(resp.session_id); }
  }catch(e){
    let txt = e.message || "";
    try {
      const j = JSON.parse(txt);
      if (j && j.session_id) {
        out.insertAdjacentHTML("beforeend", msg(
          `A session already exists for this bowler at this alley on that date. ` +
          `<a href="#" onclick="showSessionGames(${j.session_id});return false;">Click here to edit that session</a>.`,
          "warning"
        ));
        return;
      }
    } catch(_) {}
    out.insertAdjacentHTML("beforeend", msg("Save failed: "+txt, "danger"));
  }
}

// ---------- sessions (table) ----------
async function renderSessions(){
  const rows = await fetchJSON("/api/sessions");
  const el = document.getElementById("sessionsTable");
  if (rows.length===0){ el.innerHTML = msg("No sessions yet.","secondary"); return; }
  let html = `<table class="table table-sm align-middle"><thead><tr><th>Date</th><th>Bowler</th><th>Alley</th><th class="text-end">Games</th></tr></thead><tbody>`;
  for (const r of rows){
    html += `<tr><td>${r.session_date}</td><td>${r.bowler}</td><td>${r.alley}</td>` +
            `<td class="text-end"><a href="#" class="link-primary text-decoration-none" onclick="return showSessionGames(${r.id});">${r.games}</a></td></tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;
}

// ---------- session modal (view + edit) ----------
let __currentSession = null;
function buildGameInputsFromList(list){
  const tbody = document.getElementById('sessionGamesTbody');
  tbody.innerHTML = '';
  for (let i=0;i<list.length;i++){
    const num = i+1;
    const val = list[i];
    tbody.innerHTML += `<tr>
      <td>${num}</td>
      <td class="text-end"><input type="number" class="form-control form-control-sm text-end game-edit" min="1" max="300" value="${val}"></td>
    </tr>`;
  }
}
function readGameInputs(){
  return Array.from(document.querySelectorAll('#sessionGamesTbody .game-edit'))
    .map(el => el.value ? parseInt(el.value,10) : null)
    .filter(v => v!==null);
}
function enterEditMode(scores){
  const ctrls = document.getElementById('editControls');
  ctrls.innerHTML = `
    <button class="btn btn-outline-secondary btn-sm" id="addGameBtn">Add Game</button>
    <button class="btn btn-success btn-sm" id="saveGamesBtn">Save Changes</button>
  `;
  buildGameInputsFromList(scores);
  document.getElementById('addGameBtn').onclick = () => {
    const curr = readGameInputs();
    if (curr.length >= 12) return;
    curr.push("");
	 
    buildGameInputsFromList(curr);
  };
  document.getElementById('saveGamesBtn').onclick = async () => {
    const curr = readGameInputs();
    if (curr.length === 0){ alert('Enter at least one score'); return; }
    if (curr.length > 12){ alert('Max 12 games'); return; }
    if (curr.some(x => Number.isNaN(x) || x<1 || x>300)){ alert('Scores must be 1–300'); return; }
    try {
      await fetchJSON(`/api/session/${__currentSession}/games`, {method:'PUT', body: JSON.stringify({scores: curr})});
      await renderSessions(); await renderTotals();
      showSessionGames(__currentSession);
    } catch(e){
      alert('Save failed: ' + e.message);
    }
  };
}
async function showSessionGames(sid){
  try{
    const data = await fetchJSON(`/api/session/${sid}/games`);
    __currentSession = sid;
    const meta = `${data.bowler} · ${data.alley} · ${data.session_date}`;
    document.getElementById('sessionMeta').textContent = meta;
    const tbody = document.getElementById('sessionGamesTbody');
    tbody.innerHTML = '';
    for (const g of data.games){
      tbody.innerHTML += `<tr><td>${g.game_number}</td><td class="text-end">${g.score}</td></tr>`;
    }
    const ctrls = document.getElementById('editControls');
    ctrls.innerHTML = `<button class="btn btn-primary btn-sm" id="editGamesBtn">Edit</button>`;
    document.getElementById('editGamesBtn').onclick = () => {
      const scores = data.games.map(g => g.score);
      enterEditMode(scores);
    };
    const modalEl = document.getElementById('sessionModal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  }catch(e){
    alert('Failed to load session: ' + e.message);
  }
  return false;
}


// ---------- entry-session inline editor ----------
let __entrySessionId = null;
function renderEntryGames(scores){
  const tbody = document.getElementById('entrySessionGames');
  tbody.innerHTML = '';
  for (let i=0;i<scores.length;i++){
    const n = i+1, val = scores[i];
    tbody.innerHTML += `<tr>
      <td class="text-secondary">${n}</td>
      <td class="text-end" style="width:140px">
        <input type="number" class="form-control form-control-sm text-end entry-game" min="1" max="300" value="${val}">
      </td>
    </tr>`;
  }
}
function readEntryGames(){
  return Array.from(document.querySelectorAll('#entrySessionGames .entry-game'))
    .map(el => el.value ? parseInt(el.value,10) : null)
    .filter(v => v!==null);
}
async function showEntrySession(sid){
  const sec = document.getElementById('entrySessionSection');
  const meta = document.getElementById('entrySessionMeta');
  const data = await fetchJSON(`/api/session/${sid}/games`);
  __entrySessionId = sid;
  meta.textContent = `${data.bowler} · ${data.alley} · ${data.session_date}`;
  renderEntryGames(data.games.map(g=>g.score));
  sec.style.display = '';
}
function wireEntrySessionButtons(){
  const addBtn = document.getElementById('entryAddGameBtn');
  const saveBtn = document.getElementById('entrySaveGamesBtn');
  const msgEl = document.getElementById('entrySaveMsg');
  addBtn.onclick = () => {
    const curr = readEntryGames();
    if (curr.length >= 12) return;
    curr.push("");
	
    renderEntryGames(curr);
  };
  saveBtn.onclick = async () => {
    const curr = readEntryGames();
    if (curr.length===0){ msgEl.innerHTML = msg('Enter at least one score', 'danger'); return; }
    if (curr.length>12){ msgEl.innerHTML = msg('Max 12 games', 'danger'); return; }
    if (curr.some(x=>Number.isNaN(x)||x<1||x>300)){ msgEl.innerHTML = msg('Scores must be 1–300', 'danger'); return; }
    try{
      await fetchJSON(`/api/session/${__entrySessionId}/games`, {method:'PUT', body: JSON.stringify({scores: curr})});
      msgEl.innerHTML = msg('Saved!', 'success');
      await renderTotals();
      await renderSessions();
    }catch(e){
      msgEl.innerHTML = msg('Save failed: ' + e.message, 'danger');
    }
  };
}

// ---------- totals ----------
async function renderTotals(){
  const data = await fetchJSON("/api/totals");
  const el = document.getElementById("totalsBlock");
  if (!data || !data.totals || data.totals.length===0){
    el.innerHTML = msg("No data yet.","secondary"); return;
  }
  let html = "";
  for (const t of data.totals){
    const isGroupA = t.bix_group === "A";
    const badge = `<span class="badge rounded-pill text-bg-primary ms-2">${t.bix.toFixed(2)}</span>`;
    const line = isGroupA
      ? `Games: <strong>${t.games}</strong> &nbsp; Avg: <strong>${t.avg.toFixed(2)}</strong> &nbsp; 200+ games: <strong>${t.c200||0}</strong> &nbsp; 210+: <strong>${t.c210||0}</strong> &nbsp; BIX: ${badge}`
      : `Games: <strong>${t.games}</strong> &nbsp; Avg: <strong>${t.avg.toFixed(2)}</strong> &nbsp; 150+ games: <strong>${t.c150||0}</strong> &nbsp; BIX: ${badge}`;
    html += `<div class="mb-4">
      <div class="fw-semibold fs-5 mb-1">${t.name}</div>
      <div class="mb-3 text-secondary">${line}</div>`;
    if (t.alleys && t.alleys.length){
      html += `<div class="table-responsive"><table class="table table-sm table-striped align-middle">
        <thead><tr><th>Alley</th><th class="text-end">Avg</th><th class="text-end">Games</th></tr></thead><tbody>`;
      for (const a of t.alleys){
        html += `<tr><td>${a.alley}</td><td class="text-end">${(a.avg ?? 0).toFixed(2)}</td><td class="text-end">${a.games}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    } else {
      html += `<div class="text-secondary small">No alley breakdown yet.</div>`;
    }
    html += `</div>`;
  }
  if (data.bix_message){
    html += `<div class="alert alert-info mt-2"><strong>BIX Difference:</strong> ${data.bix_message}</div>`;
  }
  const months = new Set([...(Object.keys(data.monthly_avgs.Rajan||{})), ...(Object.keys(data.monthly_avgs.Medina||{}))]);
  const monthList = Array.from(months).sort().reverse();
  if (monthList.length){
    html += `<div class="mt-4"><h6 class="mb-2">Monthly Averages (Rajan vs Medina)</h6>
      <div class="table-responsive"><table class="table table-sm align-middle">
      <thead><tr><th>Month</th><th class="text-end">Rajan Avg</th><th class="text-end">Medina Avg</th></tr></thead><tbody>`;
    for (const ym of monthList){
      const r = data.monthly_avgs.Rajan?.[ym]; const m = data.monthly_avgs.Medina?.[ym];
      html += `<tr><td>${ym}</td><td class="text-end">${r!=null? r.toFixed(2):"—"}</td><td class="text-end">${m!=null? m.toFixed(2):"—"}</td></tr>`;
    }
    html += `</tbody></table></div></div>`;
  }
  el.innerHTML = html;
}

// ---------- alley add ----------
async function addAlley(){
  const name = document.getElementById("newAlley").value.trim();
  if (!name) return;
  try {
    const row = await fetchJSON("/api/alleys", {method:"POST", body: JSON.stringify({name})});
    const aSel = document.getElementById("alley");
    const opt = document.createElement("option"); opt.value = row.id; opt.textContent = row.name;
    aSel.appendChild(opt); document.getElementById("newAlley").value = "";
  } catch(e){ alert("Add alley failed: " + e.message); }
}

// ---------- boot ----------
document.addEventListener("DOMContentLoaded", async () => {
  buildScoreInputs(4); await loadLookups(); setTodayIfEmpty();
  await renderSessions(); await renderTotals();

  // Default alley on bowler typing or change
  document.getElementById("bowlerInput").addEventListener("input", (e)=> setDefaultAlleyForBowler(e.target.value));
  document.getElementById("bowlerInput").addEventListener("change", (e)=> setDefaultAlleyForBowler(e.target.value));

  document.getElementById("save").addEventListener("click", saveSession);
  document.getElementById("clear").addEventListener("click", () => buildScoreInputs(4));
  document.getElementById("addAlley").addEventListener("click", addAlley);
  document.getElementById("addScoreBtn").addEventListener("click", () => addScoreInput());
  document.getElementById("clearScoresBtn").addEventListener("click", () => buildScoreInputs(4));
  document.getElementById("scoresWrap").addEventListener("input", (e)=>{ if(e.target.classList.contains("game")) updateLiveStats(); });
  document.getElementById('year').textContent = new Date().getFullYear();
  wireEntrySessionButtons();
});