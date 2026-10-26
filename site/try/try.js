(() => {
  const params = new URLSearchParams(location.search);
  const API = (params.get("api") || (window.AEGIS || {}).api || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CORPUS = "https://github.com/siddharthraop/dita-corpus";
  const READERS = [
    { id: "authority", who: "AI Office", what: "Authority pack", set: "Annex XI, Section 1 · 11 items" },
    { id: "downstream", who: "Downstream provider", what: "Downstream pack", set: "Annex XII · 11 items" },
    { id: "public", who: "Public", what: "Model card", set: "Model card sections · 11" },
  ];
  const STATUS = {
    ready: "Ready to release", "ready-with-recorded-gaps": "Ready, with recorded decisions",
    "needs-decisions": "Needs decisions", blocked: "Release blocked",
  };
  const CHECK_LABEL = { check_coverage: "Coverage", check_currency: "Currency", check_approval: "Approval", check_consistency: "Consistency" };

  // A sandbox id per browser. Storage can be unavailable; then the sandbox lives for this page view.
  function newId() { return "sb-" + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2) + Date.now().toString(16)); }
  let SID;
  try { SID = localStorage.getItem("aegis-sid") || newId(); localStorage.setItem("aegis-sid", SID); } catch { SID = newId(); }
  let reader = params.get("reader") || "authority";
  if (!READERS.some((r) => r.id === reader)) reader = "authority";
  let data = null, meta = null, busy = false;

  function toast(msg, err = false) {
    const t = $("toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3500);
  }
  async function call(method, path, body) {
    const opt = { method, headers: {} };
    if (body) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    let r;
    try { r = await fetch(API + path, opt); } catch { throw new Error("The service couldn't be reached. It may be starting up; try again in a moment."); }
    if (!r.ok) {
      let d = ""; try { d = (await r.json()).detail; } catch {}
      throw new Error(typeof d === "string" && d ? d : `The service answered ${r.status}.`);
    }
    return r;
  }
  async function act(fn, label) {
    if (busy) return; busy = true;
    const st = $("status"); st.className = "status"; st.innerHTML = `<span class="spinner"></span>${esc(label)}`;
    const slow = setTimeout(() => { st.innerHTML += " The service may be starting; the first call can take about 15 seconds."; }, 5000);
    try { await fn(); st.textContent = ""; }
    catch (e) { st.className = "status err"; st.textContent = e.message; }
    finally { clearTimeout(slow); busy = false; }
  }

  // ---------------------------------------------------------------- readers
  $("readers").innerHTML = READERS.map((r) => `<button class="reader" type="button" data-r="${r.id}" aria-pressed="${r.id === reader}">
    <span class="what">${esc(r.what)}</span><span class="who">${esc(r.who)}</span><span class="set">${esc(r.set)}</span></button>`).join("");
  $("readers").addEventListener("click", (e) => {
    const b = e.target.closest("[data-r]"); if (!b || b.dataset.r === reader) return;
    reader = b.dataset.r;
    document.querySelectorAll(".reader").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.r === reader)));
    const u = new URL(location.href); u.searchParams.set("reader", reader); history.replaceState(null, "", u);
    load();
  });

  async function load() {
    await act(async () => {
      if (!meta) meta = await (await call("GET", "/api/readers")).json();
      data = await (await call("GET", `/api/run?reader=${reader}&sid=${encodeURIComponent(SID)}`)).json();
      render();
      loadRegister();
    }, "Running the four checks on the Gemma 4 source…");
  }
  const run = (method, path, body, label) => act(async () => {
    const r = await (await call(method, path, body)).json();
    data = r.run || r;
    if (r.proposal) {
      toast(r.proposal.outcome === "proposal" ? `Gemini proposed ${r.proposal.candidate} (confidence ${r.proposal.confidence.toFixed(2)}). Review it below.`
        : "Gemini found no topic that states this. A gap note was recorded.");
    }
    render();
  }, label);

  // ---------------------------------------------------------------- render
  function render() {
    const d = data;
    const b = $("status-badge"); b.className = "badge " + d.status; b.textContent = STATUS[d.status] || d.status;
    const s = d.source;
    $("source").innerHTML = `${esc(d.reader_info.pack)} · corpus <a href="${CORPUS}/tree/${esc(s.commit)}">${esc(s.commit)}</a> · profile <code>${esc(s.profile)}</code>
      · ${esc(d.model_version)} version date ${esc(d.version_date)}${d.model_update ? " (simulated update)" : ""} · ${esc(d.summary.built_topics)} topics in the build`;
    renderChecks(d); renderReqs(d); renderFindings(d); renderTools(d); renderBuild(d);
  }

  function renderChecks(d) {
    $("checks").innerHTML = d.checks.map((c) => {
      const blocking = c.findings.some((f) => !f.decidable);
      const cls = c.ok ? "ok" : blocking ? "block" : "bad";
      let detail = c.ok ? "pass" : `${c.findings.length} finding${c.findings.length === 1 ? "" : "s"}`;
      if (c.name === "check_approval" && !c.ok && c.passed === 0) detail += " · awaiting reviewed PRs";
      if (c.name === "check_consistency") detail = c.ok ? `${c.keys} keys · no leaks` : detail + (blocking ? " · leak" : "");
      return `<div class="check ${cls}" data-help="${c.name}"><div class="nm"><span>${CHECK_LABEL[c.name]}</span><code>${c.name}</code></div>
        <div class="v">${c.passed}/${c.total}</div><div class="d">${esc(detail)}</div></div>`;
    }).join("");
  }

  function approvalHtml(e) {
    if (e.approval_ok) return `<span class="ok-t">✓ ${esc(e.approved_by)}</span> · <a href="${esc(e.pr_url)}">PR #${e.pr}</a>`;
    return `<span class="bad-t">not approved</span>`;
  }

  function renderReqs(d) {
    const ov = d.sandbox.overlay;
    const notes = ov.gap_notes || {};
    $("req").querySelector("tbody").innerHTML = d.requirements.map((r) => {
      const pending = ov.links.find((l) => l.requirement === r.id && l.status === "pending");
      const rejected = ov.links.filter((l) => l.requirement === r.id && l.status === "rejected");
      const covF = d.findings.find((f) => f.id === `coverage:${r.id}`);
      const ev = r.evidence.map((e) => `<div class="evi"><span class="t"><a href="${esc(e.url)}">${esc(e.topic)}</a></span>
          <span class="badge ${e.coverage === "conflicting" ? "warn" : e.coverage === "partly" ? "warn" : "gray"}">${esc(e.coverage || "stated")}</span>
          ${e.link.source === "sandbox" ? '<span class="badge sandbox">sandbox link</span>' : ""}
          <span class="small">rev ${esc(e.revised)} · <a href="${CORPUS}/commit/${esc(e.commit)}"><code>${esc(e.commit)}</code></a> · ${approvalHtml(e)}</span></div>`).join("");
      let gap = "";
      if (!r.covered) {
        gap = `<div class="evi"><span class="badge fail">gap</span><span class="small">No evidence topic is linked to this requirement for ${esc(d.model_version)}.</span></div>`;
        if (covF && covF.decision) gap += `<div class="decided">Decision: ${esc(covF.decision.choice)}: ${esc(covF.decision.reason)}</div>`;
        if (pending) {
          const p = pending.proposal;
          gap += `<div class="proposal"><div class="k">propose_mapping · ${esc(p.model)} · confidence ${p.confidence.toFixed(2)}</div>
            <div>Link <b>${esc(r.id)}</b> to <a href="${CORPUS}/blob/main/gemma/evidence/${esc(pending.topic)}.dita"><code>${esc(pending.topic)}</code></a>.</div>
            <div class="small">${esc(p.reason)}</div>
            <div class="actions"><button class="btn good" data-link="approved" data-req="${esc(r.id)}" data-topic="${esc(pending.topic)}">Approve as information architect</button>
            <button class="btn bad" data-link="rejected" data-req="${esc(r.id)}" data-topic="${esc(pending.topic)}">Reject</button></div></div>`;
        } else if (notes[r.id]) {
          gap += `<div class="gapnote"><b>Gap note</b> (${esc(notes[r.id].rule || notes[r.id].outcome)}): ${esc(notes[r.id].gap_note)}</div>`;
        }
        if (rejected.length) gap += `<div class="small">Rejected: ${rejected.map((l) => esc(l.topic)).join(", ")}</div>`;
        const left = d.sandbox.proposals_left_today;
        gap += `<div class="actions">${pending ? "" : `<button class="btn model" data-propose="${esc(r.id)}" ${left ? "" : "disabled"}>Ask Gemini to propose a link</button>`}
          ${covF ? decideButton(covF, "t") : ""}</div>${covF ? decideForm(covF, "t") : ""}`;
      }
      const reqLink = r.topic_file ? `<a href="${CORPUS}/blob/main/${esc(r.topic_file)}">${esc(r.id)}</a>` : esc(r.id);
      return `<tr class="${r.covered ? "" : "gap"}"><td><div class="rid">${reqLink}</div><div class="rtitle">${esc(r.title)}</div>
        ${r.legal_source ? `<div class="small">${esc(r.legal_source)}</div>` : ""}</td><td><div class="ev">${ev}${gap}</div></td></tr>`;
    }).join("");
  }

  function decideButton(f, where = "f") {
    return `<button class="btn" data-open="${where}|${esc(f.id)}">${f.decision ? "Change decision" : "Record a decision"}</button>`;
  }
  function decideForm(f, where = "f") {
    return `<form class="decide" data-form="${where}|${esc(f.id)}"><select aria-label="Decision"><option value="release-with-gap">Release with this recorded</option><option value="hold">Hold the pack</option>${f.decision ? '<option value="clear">Clear the decision</option>' : ""}</select>
      <input aria-label="Reason" maxlength="300" placeholder="Reason, for example: energy estimate due with next release" value="${esc(f.decision ? f.decision.reason : "")}">
      <button class="btn primary" type="submit">Save as compliance lead</button></form>`;
  }

  function renderFindings(d) {
    if (!d.findings.length) { $("findings").innerHTML = '<p class="hint">No findings. Every check passed.</p>'; return; }
    const groups = {};
    d.findings.forEach((f) => (groups[f.check] = groups[f.check] || []).push(f));
    $("findings").innerHTML = Object.entries(groups).map(([check, fs]) => {
      const open = fs.filter((f) => f.decidable && !f.decision);
      const bulk = open.length > 1 ? `<button class="btn" data-open="f|bulk:${check}">Record one decision for all ${open.length}</button>` : "";
      return `<div class="group"><h3><code>${check}</code> ${fs.length} finding${fs.length === 1 ? "" : "s"} ${bulk}</h3>
        ${open.length > 1 ? decideForm({ id: `bulk:${check}`, decision: null }) : ""}
        <div class="findings">${fs.map((f) => `<div class="finding ${f.decidable ? (f.decision ? "done" : "") : "block"}">
          <div class="h">${f.decidable ? (f.decision ? `<span class="badge pass">decided: ${esc(f.decision.choice)}</span>` : '<span class="badge warn">open</span>')
            : '<span class="badge fail">blocks release</span>'}
            ${f.file ? `<a class="meta" href="${CORPUS}/blob/main/${esc(f.file)}${typeof f.line === "number" && f.line > 1 ? "#L" + f.line : ""}">${esc(f.file)}${typeof f.line === "number" && f.line > 1 ? ":" + f.line : f.line === "sandbox" ? " (sandbox)" : ""}</a>` : ""}</div>
          <div>${esc(f.reason)}</div>
          ${f.decision ? `<div class="decided">${esc(f.decision.by || "")}: ${esc(f.decision.reason)}</div>` : ""}
          ${f.decidable ? `<div class="actions">${decideButton(f)}</div>${decideForm(f)}` : ""}</div>`).join("")}</div></div>`;
    }).join("");
  }

  function renderTools(d) {
    if (meta && !$("leak-topic").options.length) {
      $("leak-topic").innerHTML = meta.leak_targets.map((t) => `<option value="${esc(t.id)}">${esc(t.id)}</option>`).join("");
      $("leak-topic").value = "gemma4-training-data";
      $("leak-key").innerHTML = meta.authority_keys.map((k) => `<option value="${esc(k.key)}">${esc(k.key)}</option>`).join("");
    }
    const lk = d.sandbox.overlay.leak;
    const leaks = d.findings.filter((f) => f.kind === "leak");
    $("leak-state").innerHTML = lk ? (leaks.length ? `<span class="bad-t">Planted in ${esc(lk.topic)}: the ${esc(d.reader_info.pack.toLowerCase())} is blocked.</span>`
      : `Planted in ${esc(lk.topic)}. The authority pack may contain authority-only keys, so it isn't a leak here. Pick the public or downstream reader.`) : "No key planted.";
    $("mu-state").textContent = d.sandbox.overlay.model_update ? `Simulated version date ${d.sandbox.overlay.model_update}; currency ${d.checks[1].passed}/${d.checks[1].total}.` : "Using the real version date.";
  }

  function renderBuild(d) {
    const blocked = d.status === "blocked";
    $("build").disabled = blocked;
    $("build-why").innerHTML = blocked ? `<span class="bad-t">Release blocked: ${esc(d.findings.filter((f) => !f.decidable).map((f) => f.reason).join(" "))}</span>`
      : d.status === "needs-decisions" ? `<span class="warn-t">${d.summary.open} open finding${d.summary.open === 1 ? "" : "s"}. You can build now; the manifest records the pack as needing decisions.</span>`
      : `<span class="ok-t">${esc(STATUS[d.status])}.</span>`;
  }

  async function loadRegister() {
    try {
      const r = await (await call("GET", "/api/register")).json();
      $("register").innerHTML = r.packs.length ? r.packs.map((p) => `<div class="finding done"><div class="h"><span class="badge pass">sealed</span>
        <b>${esc(p.pack_id)}</b><span class="meta">released by ${esc(p.released_by)} · ${esc(p.sealed_at)}</span></div>
        <div class="meta">${esc(p.object)} · manifest sha256 ${esc((p.manifest_sha256 || "").slice(0, 16))}… · ${esc(p.status)}</div></div>`).join("")
        : '<p class="hint">No pack has been released yet.</p>';
    } catch { $("register").innerHTML = ""; }
  }

  // ---------------------------------------------------------------- actions
  document.addEventListener("click", (e) => {
    const p = e.target.closest("[data-propose]");
    if (p) return run("POST", "/api/propose", { sid: SID, reader, requirement: p.dataset.propose },
      "propose_mapping: sending the requirement and candidate titles to Gemini…");
    const l = e.target.closest("[data-link]");
    if (l) return run("POST", "/api/link", { sid: SID, reader, requirement: l.dataset.req, topic: l.dataset.topic, status: l.dataset.link },
      "Recording the review and rerunning the checks…");
    const o = e.target.closest("[data-open]");
    if (o) { const f = document.querySelector(`[data-form="${CSS.escape(o.dataset.open)}"]`); if (f) { f.classList.toggle("open"); f.querySelector("input").focus(); } }
  });
  document.addEventListener("submit", (e) => {
    const f = e.target.closest("[data-form]"); if (!f) return;
    e.preventDefault();
    const id = f.dataset.form.split("|").slice(1).join("|");
    const ids = id.startsWith("bulk:") ? data.findings.filter((x) => x.check === id.slice(5) && x.decidable && !x.decision).map((x) => x.id) : [id];
    run("POST", "/api/decision", { sid: SID, reader, findings: ids, choice: f.querySelector("select").value, reason: f.querySelector("input").value },
      "Recording the decision…");
  });
  $("leak-on").onclick = () => run("POST", "/api/leak", { sid: SID, reader, topic: $("leak-topic").value, key: $("leak-key").value }, "Planting the key and rerunning check_consistency…");
  $("leak-off").onclick = () => run("POST", "/api/leak", { sid: SID, reader }, "Removing the key…");
  $("mu-on").onclick = () => run("POST", "/api/model-update", { sid: SID, reader, date: $("mu-date").value }, "Moving the version date and rerunning check_currency…");
  $("mu-off").onclick = () => run("POST", "/api/model-update", { sid: SID, reader, date: null }, "Restoring the version date…");
  $("reset").onclick = () => run("DELETE", `/api/sandbox?sid=${encodeURIComponent(SID)}&reader=${reader}`, null, "Clearing your sandbox…");
  $("build").onclick = () => act(async () => {
    const r = await call("GET", `/api/pack?reader=${reader}&sid=${encodeURIComponent(SID)}`);
    const blob = await r.blob();
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "aegis-pack.zip";
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    $("build-hash").textContent = `${name} · ${(blob.size / 1024).toFixed(0)} KB · manifest sha256 ${r.headers.get("X-Aegis-Manifest-Sha256") || "?"}`;
    toast("Pack built. Check SHA256SUMS inside the zip against its files.");
  }, "build_pack: assembling the DITA-OT output, manifest, report and hashes…");

  load();
})();
