"use strict";

const $ = (s) => document.querySelector(s);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const googleHref = (u) => (/^https:\/\/www\.google\.com\/maps\//.test(String(u || "")) ? esc(u) : null);
const short = (t) => String(t || "").split(",")[0].split(" - ")[0].split(" | ")[0].slice(0, 48);
const fmtDate = (d) => {
  if (!d) return "undated";
  const x = new Date(d + "T00:00:00Z");
  return isNaN(x) ? esc(d) : x.toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "UTC" });
};
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

let es = null;
let state = {};

(function theme() {
  try { const t = localStorage.getItem("bm-theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("bm-theme", next); } catch {}
  });
})();

async function boot() {
  try {
    const st = await (await fetch("/api/status")).json();
    const m = $("#mode");
    m.textContent = st.mode === "replay" ? "Replay · recorded examples" : `Live · ${st.account?.searches_left ?? "?"} searches left`;
    m.className = "pill " + (st.mode === "replay" ? "replay" : "live");
    $("#procedure").innerHTML = (st.procedures || []).map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("");
    $("#city").innerHTML = (st.cities || ["Bengaluru"]).map((c) => `<option>${esc(c)}</option>`).join("");
  } catch {}
  try {
    const ex = await (await fetch("/api/examples")).json();
    $("#examples").innerHTML = ex.map((e, i) =>
      `<button type="button" class="chip" data-i="${i}">${esc(e.label)}<small>${esc(e.hint)}</small></button>`).join("");
    $("#examples").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      const e = ex[+b.dataset.i];
      $("#procedure").value = e.procedure; $("#area").value = e.area || ""; $("#city").value = e.city;
      start();
    }));
  } catch {}
  const p = new URLSearchParams(location.search);  // a shared link pre-fills the form; the visitor clicks Compare
  if (p.get("procedure")) {
    $("#procedure").value = p.get("procedure"); $("#area").value = p.get("area") || "";
    if (p.get("city")) $("#city").value = p.get("city");
  }
}

$("#form").addEventListener("submit", (e) => { e.preventDefault(); start(); });

function start() {
  if (es) es.close();
  state = { calls: 0, credits: 0, steps: {} };
  const q = { procedure: $("#procedure").value, area: $("#area").value.trim(), city: $("#city").value };
  history.replaceState(null, "", "?" + new URLSearchParams(q));
  $("#live").classList.remove("hidden", "collapsed", "done"); $("#trail-toggle")?.remove();
  $("#trail").innerHTML = ""; $("#notices").innerHTML = ""; $("#trail-meta").textContent = "";
  $("#result").classList.add("hidden"); $("#result").innerHTML = "";
  $("#go").disabled = true; $("#go").textContent = "Reading reviews…";
  es = new EventSource("/api/compare/stream?" + new URLSearchParams(q));
  let gotResult = false;
  const on = (name, fn) => es.addEventListener(name, (ev) => { try { fn(JSON.parse(ev.data)); } catch (err) { console.warn(err); } });
  on("step", step);
  on("serp_call", serpCall);
  on("notice", (n) => $("#notices").insertAdjacentHTML("beforeend", `<div class="notice ${n.level === "info" ? "info" : ""}">${esc(n.text)}</div>`));
  on("result", (r) => {
    gotResult = true;
    try { render(r); } catch (err) {
      console.warn(err);
      $("#notices").insertAdjacentHTML("beforeend", `<div class="notice">The results arrived but couldn't be displayed. Please try again.</div>`);
    }
  });
  on("failure", (d) => { gotResult = true; $("#notices").insertAdjacentHTML("beforeend", `<div class="notice">${esc(d.text || "Something went wrong.")}</div>`); finish(); });
  on("done", (d) => { meta(d.ms); $("#live").classList.add("done"); finish(); });
  es.onerror = () => {
    if (!gotResult) $("#notices").insertAdjacentHTML("beforeend", `<div class="notice">The comparison couldn't run or was interrupted. Please try again.</div>`);
    finish();
  };
}

function finish() {
  if (es) es.close();
  $("#go").disabled = false; $("#go").textContent = "Compare hospitals";
}

function meta(ms) {
  const parts = [plural(state.calls, "SerpApi search"), `${state.credits} credit${state.credits === 1 ? "" : "s"} spent`];
  if (ms) parts.push(ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  $("#trail-meta").textContent = parts.join(" · ");
}

function step(s) {
  let li = state.steps[s.id];
  if (!li) { li = document.createElement("li"); li.className = "step"; state.steps[s.id] = li; $("#trail").appendChild(li); }
  li.innerHTML = `${s.status === "done" ? '<span class="tick">✓</span>' : '<span class="spin"></span>'}<span>${esc(s.label)}</span>`;
}

function serpCall(c) {
  state.calls += 1; if (c.credit) state.credits += 1;
  const cost = !c.ok ? `<span class="cost bad">failed · free</span>`
    : c.source === "live" ? `<span class="cost live">live · 1 credit · ${c.ms} ms</span>`
    : `<span class="cost">${c.source === "fixture" ? "recorded" : "cached"} · free</span>`;
  const eng = c.engine === "google_maps" ? "google_maps" : "google";
  $("#trail").insertAdjacentHTML("beforeend",
    `<li><span class="eng ${eng}">${esc(c.engine)}</span><span class="purpose" title="${esc(c.purpose)}">${esc(c.purpose)}</span>${cost}</li>`);
  meta();
}

/* ---------- rendering: the chart ---------- */
function count(c, key) { return `${c.complete ? "" : "≥"}${c[key]}`; }

function quoteHtml(q) {
  const href = googleHref(q.link);
  return `<blockquote class="quote">“${esc(q.excerpt)}”
    <cite>${esc(q.stars)}★ · ${fmtDate(q.date)}${q.edited ? ` (edited ${fmtDate(q.edited)})` : ""} · a Google review${q.replied ? " · hospital replied" : ""}${href ? ` · <a href="${href}" target="_blank" rel="noopener nofollow">read on Google</a>` : ""}</cite></blockquote>`;
}

// Handwritten margin notes: plain observations computed from the counts — never a verdict on the hospital.
function noteFor(c, r) {
  const top = Object.entries(c.themes || {}).filter(([, v]) => v >= 2).sort((a, b) => b[1] - a[1])[0];
  if (top) return `mostly ${r.themes[top[0]].toLowerCase()}`;
  if (c.complaints_recent_procedure === 0) return "nothing recent on this";
  return "";
}
function replyNote(c) {
  if (!c.complaints) return "";
  if (c.replied === c.complaints) return "replied to every one we read";
  if (c.replied === 0) return "no replies to these";
  return "";
}

function card(c, r) {
  const months = r.recent_months;
  const head = `<div class="hcard-top"><div class="hname" title="${esc(c.title)}">${esc(short(c.title))}</div>
      <div class="hmeta"><span class="stars">${esc(c.rating ?? "–")}★</span> · ${esc((c.reviews || 0).toLocaleString("en-IN"))} Google reviews</div></div>`;
  if (c.status !== "ok") {
    return `<article class="hcard">${head}
      <div class="unknown" style="margin-bottom:16px">${c.status === "no_reviews" ? `Google's review filter returned no reviews mentioning “${esc(r.keyword)}” here. That means <b>unknown</b>, not “no complaints”.` : "The review search failed for this hospital."}</div></article>`;
  }
  const n = c.complaints_recent_procedure;
  const note = noteFor(c, r);
  const rnote = replyNote(c);
  const tabs = Object.entries(c.themes).filter(([, v]) => v).sort((a, b) => b[1] - a[1])
    .map(([t, v]) => `<span class="tab" data-t="${esc(t)}">${esc(r.themes[t])} · ${v}</span>`).join("")
    || `<span class="tab zero">no recurring theme</span>`;
  const quotes = c.excerpts.slice(0, 2).map(quoteHtml).join("")
    || `<p class="empty-note">${c.complete ? `No complaint mentioning “${esc(r.keyword)}” in the last ${months} months.` : `None from the last ${months} months among the 20 lowest-rated and 20 newest “${esc(r.keyword)}” reviews we read.`}${c.newest_complaint ? ` The newest complaint we read is from ${fmtDate(c.newest_complaint)}.` : ""}</p>`;
  return `<article class="hcard">${head}
    <dl class="vitals">
      <div class="vital"><dt>${c.complete ? "" : "≥"}${n}</dt>
        <dd>complaints about the ${esc(r.procedure.toLowerCase())} or the stay, last ${months} months</dd>
        <span class="sub">${count(c, "complaints_recent")} recent “${esc(r.keyword)}” complaints in all · ${count(c, "complaints")} ever${c.complete ? "" : " (Google shows 20 at a time, so “≥”)"}${c.low_stars_no_issue ? ` · ${c.low_stars_no_issue} more 1–2★ without a stated problem` : ""}</span>
        ${note ? `<span class="hand">${esc(note)}</span>` : ""}</div>
      ${c.complaints ? `<div class="vital"><dt>${c.replied}/${c.complaints}</dt><dd>of the complaints we read have a reply from the hospital</dd>
        ${rnote ? `<span class="hand">${esc(rnote)}</span>` : ""}</div>`
        : `<div class="vital"><dt>—</dt><dd>no complaints in what we read, so no replies to count</dd></div>`}
      ${c.new_read ? `<div class="vital"><dt>${c.new_critical}/${c.new_read}</dt><dd>of the newest “${esc(r.keyword)}” reviews are 1–2★</dd>
        ${c.new_span ? `<span class="sub">covering ${fmtDate(c.new_span[0])} – ${fmtDate(c.new_span[1])}</span>` : ""}</div>` : ""}
    </dl>
    ${c.new_read ? "" : `<div class="unknown">Google's filter returned no <i>newest</i> “${esc(r.keyword)}” reviews for this hospital — unknown, not zero.</div>`}
    <div class="tabs">${tabs}</div>
    <div class="quotes">${quotes}</div>
  </article>`;
}

function render(r) {
  const out = [];
  const hs = r.hospitals || [];
  if (!hs.length) {
    $("#result").innerHTML = `<article class="chart-head"><p class="headline">No hospitals with enough Google reviews were found.</p><small>Try the city without an area.</small></article>`;
    $("#result").classList.remove("hidden");
    $("#live").classList.add("done");
    return;
  }
  const ratings = hs.map((c) => c.rating).filter((x) => typeof x === "number");
  const lo = Math.min(...ratings), hi = Math.max(...ratings);
  const starTxt = ratings.length ? (lo === hi ? `${lo}★` : `${lo}–${hi}★`) : "";
  const close = ratings.length && hi - lo <= 0.2;
  out.push(`<article class="chart-head">
    <div class="chart-meta"><span>Chart · <b>${esc(r.procedure)}</b></span><span>Near · <b>${esc(r.place)}</b></span><span>Keyword · <b>“${esc(r.keyword)}”</b></span><span>Data as of · <b>${fmtDate(r.as_of)}</b></span></div>
    <p class="headline">${hs.length} hospitals for ${esc(r.procedure.toLowerCase())} near ${esc(r.place)}${starTxt ? `, all rated ${starTxt} on Google` : ""}. Here is what patients who mentioned “${esc(r.keyword)}” complained about.</p>
    <small>We read each hospital's lowest-rated “${esc(r.keyword)}” reviews first, then its newest ones. Counts are computed by code from Google reviews; nothing here is a rating of the hospital or medical advice.</small>
    ${close ? `<span class="margin-note hand">same stars — read the chart ↓</span>` : ""}</article>`);
  out.push(`<div class="cards">${hs.map((c) => card(c, r)).join("")}</div>`);

  if (r.asks?.length) {
    out.push(`<article class="checklist"><h2>Pre-admission checklist <span class="hand">— ask before you admit</span></h2>
      <p class="muted" style="margin:4px 0 0">Turned from what recent patients complained about. Worth asking any of these hospitals — tick them off as you go.</p>
      <ul class="checks">${r.asks.map((a, i) => `<li><label><input type="checkbox" aria-label="Asked: ${esc(a.label)}" data-i="${i}"><span>${esc(a.question)}<span class="why">${esc(a.label)}: raised in ${plural(a.count, "recent complaint")} (${a.hospitals.map(esc).join(", ")})</span></span></label></li>`).join("")}</ul></article>`);
  }

  const themeKeys = Object.keys(r.themes);
  out.push(`<details class="page"><summary>Complaint themes by hospital (last ${r.recent_months} months, about the ${esc(r.procedure.toLowerCase())} or the stay)</summary>
    <div class="grid-wrap"><table class="tgrid"><thead><tr><th>Hospital</th>${themeKeys.map((t) => `<th>${esc(r.themes[t])}</th>`).join("")}</tr></thead>
    <tbody>${hs.map((c) => `<tr><td>${esc(short(c.title))}</td>${themeKeys.map((t) => { const v = c.themes?.[t] || 0; return `<td class="${v ? "hot" : ""}">${v || "·"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="muted" style="font-size:13px">A review can raise several themes. Themes were labelled by ${r.label_source === "llm" ? `${esc(r.label_model)} (labels only)` : "keyword rules"}; every number is counted by code.</p></details>`);

  const more = hs.map((c) => (c.excerpts || []).slice(2).map(quoteHtml).join("") ? `<h3>${esc(short(c.title))}</h3><div class="quotes" style="padding:0">${c.excerpts.slice(2).map(quoteHtml).join("")}</div>` : "").join("");
  if (more) out.push(`<details class="page"><summary>More recent complaints</summary>${more}</details>`);

  out.push(`<details class="page"><summary>How this chart was made</summary><div class="how">
    <ol><li>Google Maps search for “${esc(r.procedure.toLowerCase())}” hospitals near ${esc(r.place)} (SerpApi). Doctors' own listings, clinics, places with under 200 reviews and extra branches of the same group are skipped; the ${hs.length} most-reviewed hospitals are compared.</li>
    <li>For each hospital, two Google Maps review searches with the <b>same keyword “${esc(r.keyword)}”</b>: lowest-rated first, and newest first (20 reviews each — Google's page size, so counts that hit 20 are shown as “≥”).</li>
    <li>Every 1–2★ review is labelled — about the procedure/stay or only an OPD visit, and which complaint themes it raises — by ${r.label_source === "llm" ? `${esc(r.label_model)}, which returns labels only` : "keyword rules"}. Code counts everything. Dates are when the review was first posted.</li>
    <li>Names of doctors and staff are removed from excerpts. Reviews are individual experiences and may be outdated or unrepresentative.</li></ol>
    ${r.skipped?.length ? `<p><b>Skipped places</b></p><ul class="skips">${r.skipped.slice(0, 12).map((s) => `<li>${esc(s.title)} — ${esc(s.why)}</li>`).join("")}</ul>` : ""}
    <p class="muted">${plural(r.searches, "search")} · ${r.credits_spent} credit${r.credits_spent === 1 ? "" : "s"} spent · ${(r.ms / 1000).toFixed(1)} s</p></div></details>`);

  $("#result").innerHTML = out.join("");
  $("#result").classList.remove("hidden");
  $("#live").classList.add("collapsed", "done");
  if (!$("#trail-toggle")) {
    $(".trail-head").insertAdjacentHTML("beforeend", '<button id="trail-toggle" type="button" class="trail-toggle">Show case notes</button>');
    $("#trail-toggle").addEventListener("click", () => {
      const c = $("#live").classList.toggle("collapsed");
      $("#trail-toggle").textContent = c ? "Show case notes" : "Hide case notes";
    });
  }
  $("#live").scrollIntoView({ behavior: "smooth", block: "start" });
}

boot();
