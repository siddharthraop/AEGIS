(() => {
  const params = new URLSearchParams(location.search);
  const API = (params.get("api") || (window.AEGIS || {}).api || "").replace(/\/$/, "");
  const CORPUS = "https://github.com/siddharthraop/dita-corpus";
  const SAMPLES = [
    "Is the training compute for Gemma 4 documented anywhere?",
    "What licence is Gemma 4 released under?",
    "What does Annex XII 1(e) ask for, and is there evidence for it?",
    "How many tokens was Gemma 3 trained on, and what is its knowledge cutoff?",
    "Which requirements does the Gemma 4 limitations topic answer?",
  ];
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  SAMPLES.forEach((q) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = q;
    b.onclick = () => { $("q").value = q; ask(q); };
    $("samples").appendChild(b);
  });
  const qp = params.get("q");
  $("q").value = qp || SAMPLES[0];
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask").requestSubmit(); } });
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); ask($("q").value); });
  let busy = false;
  if (qp) ask(qp);

  async function ask(q) {
    q = (q || "").trim();
    if (q.length < 3 || busy) return;
    busy = true; $("go").disabled = true;
    const st = $("status"); st.className = "status";
    st.innerHTML = '<span class="spinner"></span>Searching the topics, composing and checking each point…';
    const slow = setTimeout(() => { st.innerHTML += " The service may be starting; the first question can take about 20 seconds."; }, 6000);
    try {
      const r = await fetch(API + "/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
      if (!r.ok) throw new Error(r.status === 429 ? "Too many questions this minute. Try again shortly." : `The service answered ${r.status}.`);
      render(await r.json());
      st.textContent = "";
      const u = new URL(location.href); u.searchParams.set("q", q); history.replaceState(null, "", u);
    } catch (e) {
      st.className = "status err";
      st.textContent = e instanceof TypeError ? "The service couldn't be reached. Try again in a moment." : e.message;
    } finally { clearTimeout(slow); busy = false; $("go").disabled = false; }
  }

  function trace(s) {
    if (s.kind === "requirement") {
      if (s.gap) return `<dt>Trace</dt><dd><span class="bad-t">Gap:</span> no evidence topic is linked to <code>${esc(s.requirement)}</code>.</dd>`;
      return `<dt>Trace</dt><dd>Evidence: ${s.linked_evidence.map((l) => `<code>${esc(l.topic)}</code> (${esc(l.coverage)})`).join(", ")}</dd>`;
    }
    const ev = s.evidence_for || [];
    return `<dt>Answers</dt><dd>${ev.length ? ev.map((e) => `<code>${esc(e.requirement)}</code> (${esc(e.coverage)})`).join(", ") : "no requirement in the trace"}</dd>`;
  }

  function render(d) {
    $("result").hidden = false;
    $("summary").textContent = d.summary || "";
    const num = {}; d.sources.forEach((s, i) => { num[s.id] = i + 1; });
    $("points").innerHTML = d.points.map((p) => `<li class="point"><span class="num">${num[p.topic] || "?"}</span>
      <p>${esc(p.text)}</p><blockquote>${esc(p.quote)}</blockquote></li>`).join("");
    const nc = $("notcovered"); nc.hidden = !d.not_covered; nc.innerHTML = d.not_covered ? "<b>Not in these topics:</b> " + esc(d.not_covered) : "";
    const dr = $("dropped"); dr.hidden = !d.dropped.length;
    dr.innerHTML = d.dropped.length ? `<b>Dropped by the checks (${d.dropped.length}):</b> ` +
      d.dropped.map((x) => `<s>${esc(x.text)}</s> (${esc(x.why)})`).join(" · ") : "";
    $("sources").innerHTML = d.sources.map((s, i) => `<div class="src"><h3><span class="num">${i + 1}</span><a href="${esc(s.url)}">${esc(s.title)}</a></h3>
      <dl><dt>Topic</dt><dd><code>${esc(s.id)}</code> · ${esc(s.kind)}${s.model_version ? " · " + esc(s.model_version) : ""}</dd>
      <dt>File</dt><dd><a href="${esc(s.url)}">${esc(s.file)}</a></dd>
      <dt>Revised</dt><dd>${esc(s.revised || "?")}</dd>
      <dt>Commit</dt><dd><a href="${CORPUS}/commit/${esc(s.commit)}"><code>${esc(s.commit)}</code></a></dd>
      <dt>Approved</dt><dd>${s.approved ? `<span class="ok-t">✓ ${esc(s.approved_by)}</span> · <a href="${esc(s.pr_url)}">PR #${s.pr}</a>` : `<span class="bad-t">not yet</span> · ${esc(s.approval)}`}</dd>
      ${trace(s)}</dl></div>`).join("");
    const m = d.model || {};
    $("meta").textContent = `${m.name || "?"} ${m.id && m.id !== "none" ? m.id : ""} · retrieved ${(d.retrieved || []).join(", ")} · ${d.ms} ms`
      + (m.error ? ` · ${m.error}` : "");
  }
})();
