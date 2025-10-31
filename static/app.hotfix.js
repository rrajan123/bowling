// ---------- utilities (hotfix) ----------
function apiUrl(path){
  const base = window.location.origin; // handles http(s)://host:port
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

// ---------- like helpers (hotfix) ----------
function isValidGameId(gid){
  return Number.isInteger(gid) && gid > 0;
}
async function likeGame(gameId) {
  if (!isValidGameId(gameId)) {
    alert("Invalid game id received from server. Please refresh the page.");
    console.warn("likeGame invalid id:", gameId);
    return false;
  }
  try {
    const res = await fetchJSON(apiUrl(`/api/game/${gameId}/like`), { method: "POST" });
    const cntEl = getEl(`like-count-${gameId}`);
    if (cntEl) cntEl.textContent = res.likes;
    // update total likes badge if present
    if (typeof renderLikesTotal === "function") await renderLikesTotal();
  } catch (e) {
    console.error("likeGame failed:", e);
    alert("Failed to like this game: " + e.message);
  }
  return false;
}
