// app.addgame.js — wires the '+ Add Game' button
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("addGame");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const wrap = document.getElementById("scoresWrap");
    if (!wrap) return;
    if (wrap.children.length >= 12) {
      // Optional: flash a quick message if needed
      btn.blur();
      return;
    }
    if (typeof addScoreInput === "function") {
      addScoreInput();
      if (typeof updateLiveStats === "function") updateLiveStats();
    }
  });
});
