// Context-sensitive help: help IDs map to DITA help topics through csh.json, which the help build writes.
(() => {
  const CFG = window.AEGIS || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let csh = {};
  let current = document.documentElement.dataset.helpDefault || "overview";
  fetch((CFG.help || "../help/") + "csh.json").then((r) => (r.ok ? r.json() : {})).then((j) => { csh = j; }).catch(() => {});
  function open(id = current) {
    const t = csh[id];
    $("help-title").textContent = t ? t.title : "Help";
    $("help-short").textContent = t ? t.shortdesc : "The help set explains each part of this page.";
    $("help-steps").innerHTML = t ? (t.steps || []).map((s) => `<li>${esc(s)}</li>`).join("") : "";
    $("help-related").innerHTML = t && t.related && t.related.length
      ? `<h3>Related</h3>${t.related.map((r) => `<a class="rel" href="${esc(CFG.help + r.href)}" target="_blank" rel="noopener">${esc(r.title)}</a>`).join("")}` : "";
    $("help-open").href = t ? CFG.help + t.href : CFG.help;
    $("help").classList.add("open"); $("help").setAttribute("aria-hidden", "false");
    $("help-btn").setAttribute("aria-expanded", "true"); $("help-close").focus();
  }
  function close() {
    $("help").classList.remove("open"); $("help").setAttribute("aria-hidden", "true");
    $("help-btn").setAttribute("aria-expanded", "false");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-help]");
    if (b) { current = b.dataset.help; open(current); }
  });
  $("help-btn").addEventListener("click", () => ($("help").classList.contains("open") ? close() : open()));
  $("help-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
})();
