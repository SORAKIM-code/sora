"use strict";
// 첫 버전 화면: 연구 목적 입력 → 카탈로그 추천 → 추천 근거 확인.
// 카탈로그 내용은 신뢰하지 않는 자료이므로 innerHTML 을 쓰지 않고 textContent 로만 넣는다.

const state = { info: null, payload: null };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(path, opt);
  let data = {};
  try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

const $ = (id) => document.getElementById(id);
const query = $("query");
const result = $("result");

function unknown() { return h("span", { class: "chip unknown-val" }, "미확인"); }
function show(v) {
  if (v === null || v === undefined || (Array.isArray(v) && !v.length)) return unknown();
  return Array.isArray(v) ? v.join("; ") : String(v);
}

// ── 첫 화면 ──
async function init() {
  query.addEventListener("input", () => { $("count").textContent = `${query.value.length} / 1000`; });
  $("ask").addEventListener("submit", (ev) => { ev.preventDefault(); submit({}); });
  try {
    state.info = await api("GET", "/api/public/info");
  } catch (e) {
    result.replaceChildren(h("div", { class: "notice err" }, e.message));
    return;
  }
  const info = state.info;
  $("engine-label").textContent = info.engine.label + ".";
  $("engine-label").classList.remove("hidden");
  $("retention").textContent = `입력한 연구 목적은 시연 품질 점검을 위해 ${info.retention_days}일 동안 보관한 뒤 원문을 삭제합니다. ` +
    `현재 등록된 시연용 가상 카탈로그: ${info.catalog_count}건.`;
  $("examples").replaceChildren(...info.examples.map((ex) => h("button", {
    type: "button", class: "example",
    onclick: () => { query.value = ex; query.dispatchEvent(new Event("input")); query.focus(); },
  }, ex)));
}

async function submit(extra) {
  const text = query.value.trim();
  if (!text) { query.focus(); return; }
  state.payload = { query: text, ...extra };
  $("submit").disabled = true;
  result.replaceChildren(h("div", { class: "panel muted" }, "등록된 카탈로그를 검색하는 중입니다…"));
  try {
    const r = await api("POST", "/api/public/recommend", state.payload);
    render(r);
  } catch (e) {
    result.replaceChildren(h("div", { class: "notice err" }, e.message));
  } finally {
    $("submit").disabled = false;
  }
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── 추천 결과 ──
function render(r) {
  if (r.status === "clarify") return renderClarify(r);
  const engine = h("div", { class: "demo-strip small" },
    h("strong", {}, "시연용 추천"), h("span", {}, r.engine.label), h("span", { class: "muted" }, r.engine.detail));
  if (r.status === "abstain") {
    result.replaceChildren(h("div", { class: "panel" }, h("h2", {}, "추천할 카탈로그를 찾지 못했습니다"),
      h("p", {}, r.message), engine));
    return;
  }
  result.replaceChildren(
    h("div", { class: "result-head" },
      h("h2", {}, `추천 카탈로그 ${r.candidates.length}건`),
      h("p", { class: "small muted" }, r.notice), engine),
    ...r.candidates.map((c, i) => card(c, i + 1)),
  );
}

function renderClarify(r) {
  const box = h("div", { class: "panel clarify" }, h("h2", {}, "조금 더 알려 주세요"),
    h("p", { class: "small muted" }, "추천 결과가 달라질 수 있는 정보가 빠져 있어 먼저 여쭙습니다."));
  for (const q of r.questions) {
    box.append(h("p", {}, h("strong", {}, q.question)),
      h("div", { class: "row" }, q.options.map((o) => h("button", {
        type: "button", onclick: () => submit({ answers: { ...(state.payload.answers || {}), [q.id]: o.value } }),
      }, o.label))));
  }
  box.append(h("div", { class: "row end" }, h("button", {
    type: "button", class: "link", onclick: () => submit({ answers: state.payload.answers, skip_clarify: true }),
  }, "답하지 않고 추천 보기")));
  result.replaceChildren(box);
}

// 근거 위치: 엑셀에서 온 카탈로그면 '파일 N행 X열', 아니면 등록 정보 행 번호
function srcNote(origin, field, line) {
  if (origin && field && origin.cols && origin.cols[field]) {
    return h("span", { class: "src muted" }, `${origin.file} ${origin.row}행 ${origin.cols[field]}열`);
  }
  return line ? h("span", { class: "src muted" }, `등록 정보 ${line}행`) : null;
}

function fieldPlace(origin, key, line) {
  if (origin && origin.cols && origin.cols[key]) return `${origin.cols[key]}${origin.row}`;
  return line ? `${line}행` : "—";
}

function section(cls, title, ...body) {
  return h("div", { class: "cand-sec " + cls }, h("div", { class: "sec-title" }, title), ...body);
}

function card(c, rank) {
  const e = c.explanation;
  const v = c.metadata;
  const band = { "높음": "high", "보통": "mid", "낮음": "low" }[c.relevance];
  const detail = h("div", { class: "cand-sec full hidden" });
  const toggle = h("button", {
    type: "button", class: "link", onclick: () => {
      const open = detail.classList.toggle("hidden");
      toggle.textContent = open ? "등록 정보 전체 보기" : "등록 정보 접기";
      if (!detail.childNodes.length) detail.append(metaTable(v, c.sources, c.availability.origin));
    },
  }, "등록 정보 전체 보기");

  const head = h("div", { class: "cand-head" },
    h("div", { class: "cand-rank" }, rank),
    h("div", { class: "grow" },
      h("div", { class: "row" }, h("span", { class: "cand-title" }, c.title), h("span", { class: "demo-badge sm" }, "시연용 가상 카탈로그")),
      h("div", { class: "cand-meta" }, `${c.catalog_id} · v${c.version} · ${c.domain} · `,
        v.size ? h("span", { class: "size-tag", title: "등록된 데이터 용량" }, v.size) : null, v.size ? " · " : null, "관련도 ",
        h("span", { class: "badge " + band }, c.relevance)),
      h("p", { class: "cand-desc" }, e && e.description ? e.description.text : show(v.description)),
      e && e.hashtags.length ? h("div", { class: "hashtags", title: "등록된 주제어·분야·자료 유형에서 가져온 키워드" },
        e.hashtags.map((t) => h("span", { class: "hashtag" }, t.tag))) : null,
    ),
    coverFor(c));

  if (!e) {
    return h("div", { class: "cand" }, head,
      h("div", { class: "cand-sec full" }, h("div", { class: "notice err" }, c.explanation_error), metaTable(v, c.sources)));
  }

  const pre = v.preprocessed ? (v.preprocessed + (v.preprocess_detail ? ` (${v.preprocess_detail})` : "")) : null;
  const body = h("div", { class: "cand-body" },
    section("full", "포함된 주요 데이터 항목",
      h("div", { class: "data-shape" },
        h("span", { class: "shape-item" }, h("span", { class: "muted" }, "데이터 구조 "), v.structure ? h("strong", {}, v.structure) : unknown(),
          srcNote(c.availability.origin, "structure")),
        h("span", { class: "shape-item" }, h("span", { class: "muted" }, "전처리 "), pre ? h("strong", {}, pre) : unknown(),
          srcNote(c.availability.origin, "preprocessed")),
        h("span", { class: "shape-item" }, h("span", { class: "muted" }, "데이터 용량 "), v.size ? h("strong", {}, v.size) : unknown(),
          srcNote(c.availability.origin, "size"))),
      e.columns.length ? h("ul", { class: "cols" }, e.columns.map((x) => h("li", {}, x.text))) : h("p", {}, "등록된 데이터 항목이 없습니다 (미확인).")),
    section("sec-fact left", "연구 목적에 적합한 이유",
      h("ul", {}, e.reasons.map((x) => h("li", {}, x.text, srcNote(c.availability.origin, x.field, x.source_line))))),
    section("sec-ai", "연구에 활용할 수 있는 방법",
      h("ul", {}, e.methods.map((x) => h("li", {}, x.text))),
      h("div", { class: "small muted" }, "규칙으로 만든 시연용 제안입니다. 연구 가능성이나 자료 제공 승인을 보장하지 않습니다.")),
    section("sec-check full", "부족한 정보 · 담당자 확인사항",
      e.checks.length ? h("ul", {}, e.checks.map((x) => h("li", {}, x.text, x.confirmer ? h("span", { class: "who" }, " · 확인: " + x.confirmer) : null)))
        : h("p", { class: "small" }, "추가로 확인할 사항이 등록 정보에서 발견되지 않았습니다.")),
    section("full", "이용 조건",
      h("table", { class: "tbl terms" }, h("tbody", {},
        h("tr", {}, h("th", {}, "공개 범위"), h("td", {}, show(e.terms.access_level))),
        h("tr", {}, h("th", {}, "신청 절차"), h("td", {}, show(e.terms.procedure))),
        h("tr", {}, h("th", {}, "사용 장소 제한"), h("td", {}, e.terms.place_restriction || "등록된 제한 없음")),
        h("tr", {}, h("th", {}, "사용 목적 제한"), h("td", {}, e.terms.purpose_restriction || "등록된 제한 없음")),
        h("tr", {}, h("th", {}, "승인 상태"), h("td", {}, c.availability.approval_status)),
        h("tr", {}, h("th", {}, "확인 주체"), h("td", {}, c.availability.confirmer)),
      ))),
  );
  return h("div", { class: "cand" }, head, body,
    h("div", { class: "cand-sec full row" }, toggle, h("span", { class: "spacer" }),
      h("span", { class: "small muted" }, c.availability.origin
        ? `출처 ${c.availability.origin.file} · ${c.availability.origin.sheet} 시트 ${c.availability.origin.row}행 · 최종 확인 ${c.availability.last_checked || "미확인"}`
        : `메타데이터 검수 ${c.availability.reviewed_by || "미확인"} · 최종 확인 ${c.availability.last_checked || "미확인"}`)),
    detail);
}

function metaTable(values, sources, origin) {
  const schema = (state.info && state.info.schema) || [];
  const groups = {};
  for (const [key, label, group] of schema) (groups[group] = groups[group] || []).push([key, label]);
  return h("table", { class: "tbl" }, h("tbody", {}, Object.entries(groups).map(([g, fields]) => [
    h("tr", {}, h("th", { colspan: 2 }, g), h("th", {}, origin ? "엑셀 셀" : "위치")),
    fields.filter(([key]) => key !== "image" || values.image).map(([key, label]) => h("tr", {},
      h("td", {}, label), h("td", {}, show(values[key])),
      h("td", { class: "small muted" }, fieldPlace(origin, key, sources[key])))),
  ])));
}

init();
