"use strict";

const $ = (s) => document.querySelector(s);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const googleHref = (u) => (/^https:\/\/www\.google\.com\//.test(String(u || "")) ? esc(u) : null);
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
  $("#live").classList.remove("hidden", "collapsed"); $("#trail-toggle")?.remove();
  $("#trail").innerHTML = ""; $("#notices").innerHTML = ""; $("#trail-meta").textContent = "";
  $("#result").classList.add("hidden"); $("#result").innerHTML = "";
  $("#go").disabled = true; $("#go").textContent = "Reading reviews…";
  es = new EventSource("/api/compare/stream?" + new URLSearchParams(q));
  let gotResult = false;
  const on = (name, fn) => es.addEventListener(name, (ev) => { try { fn(JSON.parse(ev.data)); } catch (err) { console.warn(err); } });
  on("step", step);
  on("serp_call", serpCall);
  on("notice", (n) => $("#notices").insertAdjacentHTML("beforeend", `<div class="notice ${n.level === "info" ? "info" : ""}">${esc(n.text)}</div>`));
  on("result", (r) => { gotResult = true; render(r); });
  on("done", (d) => { meta(d.ms); finish(); });
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

/* ---------- rendering ---------- */
function count(c, key) { return `${c.complete ? "" : "≥"}${c[key]}`; }

function quoteHtml(q) {
  const href = googleHref(q.link);
  return `<blockquote class="quote">“${esc(q.excerpt)}”
    <cite>${esc(q.stars)}★ · ${fmtDate(q.date)}${q.edited ? ` (edited ${fmtDate(q.edited)})` : ""} · a Google review${q.replied ? " · hospital replied" : ""}${href ? ` · <a href="${href}" target="_blank" rel="noopener nofollow">read on Google</a>` : ""}</cite></blockquote>`;
}

function card(c, r) {
  const months = r.recent_months;
  if (c.status !== "ok") {
    return `<article class="card hcard"><div><div class="hname">${esc(short(c.title))}</div>
      <div class="hmeta"><span class="stars">${esc(c.rating ?? "–")}★</span> · ${esc((c.reviews || 0).toLocaleString("en-IN"))} Google reviews</div></div>
      <div class="unknown">${c.status === "no_reviews" ? `Google's review filter returned no reviews mentioning “${esc(r.keyword)}” here. That means <b>unknown</b>, not “no complaints”.` : "The review search failed for this hospital."}</div></article>`;
  }
  const n = c.complaints_recent_procedure;
  const themeChips = Object.entries(c.themes).filter(([, v]) => v).sort((a, b) => b[1] - a[1])
    .map(([t, v]) => `<span class="tchip">${esc(r.themes[t])} · ${v}</span>`).join("") || `<span class="tchip zero">no recurring theme</span>`;
  const quotes = c.excerpts.slice(0, 2).map(quoteHtml).join("")
    || `<p class="muted" style="margin:0;font-size:13px">No 1–2★ review mentioning “${esc(r.keyword)}” in the last ${months} months.${c.newest_complaint ? ` The newest is from ${fmtDate(c.newest_complaint)}.` : ""}</p>`;
  return `<article class="card hcard">
    <div><div class="hname" title="${esc(c.title)}">${esc(short(c.title))}</div>
      <div class="hmeta"><span class="stars">${esc(c.rating ?? "–")}★</span> · ${esc((c.reviews || 0).toLocaleString("en-IN"))} Google reviews</div></div>
    <div class="stat ${n ? "warn" : "calm"}"><b>${c.complete ? "" : "≥"}${n}</b>
      <span>1–2★ reviews about the ${esc(r.procedure.toLowerCase())} or the stay, last ${months} months</span>
      <span class="sub">${count(c, "complaints_recent")} recent 1–2★ “${esc(r.keyword)}” reviews in all · ${count(c, "complaints")} ever${c.complete ? "" : " (Google shows 20 at a time, so “≥”)"}</span></div>
    <div class="stat"><b>${c.replied}/${c.complaints}</b><span>complaints the hospital replied to</span></div>
    <div class="stat"><b>${c.new_critical}/${c.new_read}</b><span>of the newest “${esc(r.keyword)}” reviews are 1–2★</span>
      ${c.new_span ? `<span class="sub">covering ${fmtDate(c.new_span[0])} – ${fmtDate(c.new_span[1])}</span>` : ""}</div>
    <div class="tchips">${themeChips}</div>
    ${quotes}
  </article>`;
}

function render(r) {
  const out = [];
  const hs = r.hospitals || [];
  if (!hs.length) {
    $("#result").innerHTML = `<article class="card"><p>No hospitals with enough Google reviews were found. Try the city without an area.</p></article>`;
    $("#result").classList.remove("hidden");
    return;
  }
  const ratings = hs.map((c) => c.rating).filter((x) => typeof x === "number");
  const lo = Math.min(...ratings), hi = Math.max(...ratings);
  const starTxt = ratings.length ? (lo === hi ? `${lo}★` : `${lo}–${hi}★`) : "";
  out.push(`<article class="card"><p class="headline">${hs.length} hospitals for ${esc(r.procedure.toLowerCase())} near ${esc(r.place)}${starTxt ? `, all rated ${starTxt} on Google` : ""}. Here is what patients who mentioned “${esc(r.keyword)}” complained about.
    <small>We read each hospital's lowest-rated “${esc(r.keyword)}” reviews first, then its newest ones. Counts are computed by code from Google reviews as of ${fmtDate(r.as_of)}; nothing here is a rating of the hospital or medical advice.</small></p></article>`);
  out.push(`<div class="cards">${hs.map((c) => card(c, r)).join("")}</div>`);

  if (r.asks?.length) {
    out.push(`<article class="card"><h2>Ask before you admit</h2>
      <p class="muted" style="margin:4px 0 0">Turned from what recent patients complained about — worth asking any of these hospitals.</p>
      <ol class="asks">${r.asks.map((a) => `<li><div>${esc(a.question)}<span class="why">${esc(a.label)}: raised in ${plural(a.count, "recent complaint")} (${a.hospitals.map(esc).join(", ")})</span></div></li>`).join("")}</ol></article>`);
  }

  const themeKeys = Object.keys(r.themes);
  out.push(`<details class="card more"><summary>Complaint themes by hospital (last ${r.recent_months} months, about the ${esc(r.procedure.toLowerCase())} or the stay)</summary>
    <div class="grid-wrap"><table class="tgrid"><thead><tr><th>Hospital</th>${themeKeys.map((t) => `<th>${esc(r.themes[t])}</th>`).join("")}</tr></thead>
    <tbody>${hs.map((c) => `<tr><td>${esc(short(c.title))}</td>${themeKeys.map((t) => { const v = c.themes?.[t] || 0; return `<td class="${v ? "hot" : ""}">${v || "·"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="muted" style="font-size:13px">A review can raise several themes. Themes were labelled by ${r.label_source === "llm" ? "Gemini 2.5 Flash (labels only)" : "keyword rules"}; every number is counted by code.</p></details>`);

  const more = hs.map((c) => (c.excerpts || []).slice(2).map(quoteHtml).join("") ? `<h3>${esc(short(c.title))}</h3>${c.excerpts.slice(2).map(quoteHtml).join("")}` : "").join("");
  if (more) out.push(`<details class="card more"><summary>More recent complaints</summary><div style="display:grid;gap:8px;margin-top:10px">${more}</div></details>`);

  out.push(`<details class="card more"><summary>How this was checked</summary><div class="how">
    <ol><li>Google Maps search for “${esc(r.procedure.toLowerCase())}” hospitals near ${esc(r.place)} (SerpApi). Doctors' own listings, clinics, places with under 200 reviews and extra branches of the same group are skipped; the ${hs.length} most-reviewed hospitals are compared.</li>
    <li>For each hospital, two Google Maps review searches with the <b>same keyword “${esc(r.keyword)}”</b>: lowest-rated first, and newest first (20 reviews each — Google's page size, so counts that hit 20 are shown as “≥”).</li>
    <li>Every 1–2★ review is labelled — about the procedure/stay or only an OPD visit, and which complaint themes it raises — by ${r.label_source === "llm" ? "Gemini 2.5 Flash, which returns labels only" : "keyword rules"}. Code counts everything. Dates are when the review was first posted.</li>
    <li>Names of doctors and staff are removed from excerpts. Reviews are individual experiences and may be outdated or unrepresentative.</li></ol>
    ${r.skipped?.length ? `<p><b>Skipped places</b></p><ul class="skips">${r.skipped.slice(0, 12).map((s) => `<li>${esc(s.title)} — ${esc(s.why)}</li>`).join("")}</ul>` : ""}
    <p class="muted">${plural(r.searches, "search")} · ${r.credits_spent} credit${r.credits_spent === 1 ? "" : "s"} spent · ${(r.ms / 1000).toFixed(1)} s</p></div></details>`);

  $("#result").innerHTML = out.join("");
  $("#result").classList.remove("hidden");
  $("#live").classList.add("collapsed");
  if (!$("#trail-toggle")) {
    $(".trail-head").insertAdjacentHTML("beforeend", '<button id="trail-toggle" type="button" class="trail-toggle">Show trail</button>');
    $("#trail-toggle").addEventListener("click", () => {
      const c = $("#live").classList.toggle("collapsed");
      $("#trail-toggle").textContent = c ? "Show trail" : "Hide trail";
    });
  }
  $("#live").scrollIntoView({ behavior: "smooth", block: "start" });
}

boot();
