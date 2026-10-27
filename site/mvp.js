(() => {
  const params = new URLSearchParams(location.search);
  const API = (params.get("api") || (window.AEGIS || {}).api || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CORPUS = "https://github.com/siddharthraop/dita-corpus";
  const PACKS = [
    { reader: "authority", name: "Authority pack", who: "AI Office and national authorities", set: "Annex XI, Section 1 · 11 requirements" },
    { reader: "downstream", name: "Downstream pack", who: "Downstream providers", set: "Annex XII · 11 requirements" },
  ];
  const STATUS = {
    ready: "Ready to release", "ready-with-recorded-gaps": "Ready, with recorded decisions",
    "needs-decisions": "Needs decisions", blocked: "Release blocked",
  };
  const CHECK = { check_coverage: "Coverage", check_currency: "Currency", check_approval: "Approval", check_consistency: "Consistency" };
  const BASIS = { measured: "Measured", modeled: "Modeled", "not-in-mvp": "Not in the MVP" };
  const VERDICT = { pass: ["pass", "Meets target"], open: ["warn", "Open"], fail: ["fail", "Fails"], info: ["gray", ""] };

  let busy = false, system = null, lastGen = null;

  function toast(msg, err = false) {
    const t = $("toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3500);
  }
  async function call(path) {
    let r;
    try { r = await fetch(API + path); } catch { throw new Error("The service couldn't be reached. It may be starting up; try again in a moment."); }
    if (!r.ok) {
      let d = ""; try { d = (await r.json()).detail; } catch {}
      throw new Error(typeof d === "string" && d ? d : `The service answered ${r.status}.`);
    }
    return r;
  }
  async function act(fn, label) {
    if (busy) return; busy = true;
    $("go").disabled = true;
    const st = $("status"); st.className = "status"; st.innerHTML = `<span class="spinner"></span>${esc(label)}`;
    const slow = setTimeout(() => { st.innerHTML += " The service may be starting; the first call can take about 15 seconds."; }, 5000);
    try { await fn(); st.textContent = ""; }
    catch (e) { st.className = "status err"; st.textContent = e.message; }
    finally { clearTimeout(slow); busy = false; $("go").disabled = !system; }
  }

  // ---------------------------------------------------------------- systems
  async function loadSystems() {
    await act(async () => {
      const { systems } = await (await call("/api/systems")).json();
      $("system").innerHTML = systems.map((s) =>
        `<option value="${esc(s.id)}" ${s.available ? "" : "disabled"}>${esc(s.name)}${s.available ? "" : " (no evidence set yet)"}</option>`).join("");
      const want = params.get("system");
      const pick = systems.find((s) => s.id === want && s.available) || systems.find((s) => s.available);
      $("system").value = pick.id; system = pick.id;
      $("sys-note").textContent = pick.note;
      window.__systems = systems;
    }, "Loading the systems…");
    if (system && params.get("system")) generate();
  }
  $("system").addEventListener("change", () => {
    system = $("system").value;
    const s = (window.__systems || []).find((x) => x.id === system);
    $("sys-note").textContent = s ? s.note : "";
  });
  $("go").addEventListener("click", generate);

  // ---------------------------------------------------------------- generate
  function generate() {
    if (!system) return;
    return act(async () => {
      lastGen = await (await call(`/api/mvp?system=${encodeURIComponent(system)}`)).json();
      render(lastGen);
      $("out").hidden = false;
      $("out").scrollIntoView({ behavior: "smooth", block: "start" });
    }, "Running the four checks and building both packs…");
  }

  // ---------------------------------------------------------------- render
  function renderChecks(res) {
    return res.checks.map((c) => {
      const blocking = res.findings.some((f) => f.check === c.name && !f.decidable);
      const cls = c.ok ? "ok" : blocking ? "block" : "bad";
      return `<div class="mc ${cls}"><div class="nm">${CHECK[c.name]}</div><div class="v">${c.passed}/${c.total}</div>
        <div class="d">${c.ok ? "pass" : blocking ? "blocked" : "findings"}</div></div>`;
    }).join("");
  }

  function renderPack(p, d) {
    const res = d.results[p.reader], pk = d.packs[p.reader];
    const covered = res.requirements.filter((r) => r.covered);
    const gaps = res.requirements.filter((r) => !r.covered);
    const findings = res.findings;
    const blocked = res.status === "blocked";
    const findHtml = findings.length
      ? `<details><summary>${findings.length} finding${findings.length === 1 ? "" : "s"}</summary><ul class="flist">${findings.map((f) =>
          `<li>${f.decidable ? "" : '<span class="badge fail">blocks release</span> '}<code>${esc(f.check)}</code> ${esc(f.reason)}</li>`).join("")}</ul></details>`
      : '<p class="small">No findings. Every check passed.</p>';
    return `<article class="pack" data-reader="${p.reader}">
      <div><div class="what">${esc(p.name)}</div><h3>${esc(p.who)}</h3><div class="small">${esc(p.set)}</div></div>
      <div><span class="badge ${esc(res.status)}">${esc(STATUS[res.status] || res.status)}</span></div>
      <div class="mini" aria-label="Check results">${renderChecks(res)}</div>
      <p class="small"><b>${covered.length} of ${res.requirements.length}</b> requirements have evidence.
        ${gaps.length ? `Gaps: ${gaps.map((g) => `<code>${esc(g.id)}</code>`).join(", ")}.` : ""}</p>
      ${findHtml}
      <div class="packmeta">
        <div class="meta">${esc(pk.pack_id)} · ${(pk.bytes / 1024).toFixed(0)} KB · ${pk.files.length} files</div>
        <div class="meta" title="${esc(pk.manifest_sha256)}">manifest sha256 ${esc(pk.manifest_sha256.slice(0, 16))}…</div>
        ${pk.has_documentation ? "" : '<div class="small warn-t">No DITA-OT output on this server: this pack holds the manifest and report only.</div>'}
      </div>
      <div class="actions"><button class="btn primary" data-dl="${p.reader}" ${blocked ? "disabled" : ""}>Download ${esc(p.name.toLowerCase())} (.zip)</button></div>
      <p class="small">Holds the DITA-OT HTML5 and PDF built with this reader's profile, <code>manifest.json</code>,
        <code>report.html</code>, <code>coverage.csv</code> and <code>SHA256SUMS</code>.</p>
    </article>`;
  }

  function renderMetrics(d) {
    return d.metrics.map((m) => {
      const [cls, text] = VERDICT[m.status];
      const verdict = text ? `<span class="badge ${cls}">${text}</span>` : "";
      const pct = typeof m.pct === "number" ? ` <span class="small">(${m.pct}%)</span>` : "";
      return `<tr><td><div class="mlabel">${esc(m.label)}</div><div class="small">${esc(m.note)}</div></td>
        <td><div class="mval">${esc(m.value)}${pct}</div>${verdict}</td>
        <td class="small">${esc(m.target)}</td><td><span class="badge ${m.kind === "measured" ? "model" : "gray"}">${esc(BASIS[m.kind])}</span></td></tr>`;
    }).join("");
  }

  function render(d) {
    const s = d.source;
    $("source").innerHTML = `${esc(d.system.name)} · corpus <a href="${CORPUS}/tree/${esc(s.commit)}">${esc(s.commit)}</a> · generated in ${esc(d.seconds)} s`;
    const ap = d.results.authority.checks.find((c) => c.name === "check_approval");
    const note = $("approval-note");
    if (ap && ap.passed === 0 && ap.total > 0) {
      note.hidden = false;
      note.innerHTML = "<b>Approvals read 0.</b> AEGIS trusts Git for approval, and no change to this evidence set has merged " +
        "through a pull request approved by a code owner yet. The packs and metrics below show that honestly. They will change when the review pull requests are merged.";
    } else note.hidden = true;
    $("packs").innerHTML = PACKS.map((p) => renderPack(p, d)).join("");
    $("metrics").querySelector("tbody").innerHTML = renderMetrics(d);
  }

  // ---------------------------------------------------------------- download
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-dl]"); if (!b) return;
    const reader = b.dataset.dl;
    act(async () => {
      const r = await call(`/api/mvp/pack?system=${encodeURIComponent(system)}&reader=${reader}`);
      const blob = await r.blob();
      const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "aegis-pack.zip";
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
      document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      const shown = lastGen && lastGen.packs[reader].manifest_sha256, got = r.headers.get("X-Aegis-Manifest-Sha256");
      toast(shown && got && shown !== got ? "Downloaded, but the manifest hash differs from the one shown. Generate again."
        : "Downloaded. The manifest hash matches the one on this page; check SHA256SUMS inside the zip against its files.", shown !== got);
    }, "Building the pack…");
  });

  loadSystems();
})();
