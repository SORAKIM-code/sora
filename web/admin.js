"use strict";
// 화면 S1~S6. 카탈로그 내용은 신뢰하지 않는 자료이므로 innerHTML 을 쓰지 않고 textContent 로만 넣는다.

const state = { me: null, last: null, lastQuery: null, schema: null };

// ── 공통 ──
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, path, body) {
  const opt = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(path, opt);
  let data = {};
  try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
  if (!res.ok) {
    const err = new Error(data.error || `요청 실패 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) { t = h("div", { class: "toast" }); document.body.append(t); }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2800);
}

const val = (v) => (v === null || v === undefined || (Array.isArray(v) && !v.length))
  ? h("span", { class: "chip unknown-val" }, "미확인")
  : (Array.isArray(v) ? v.join("; ") : String(v));

const statusChip = (s) => h("span", {
  class: "chip " + ({ "충족": "ok", "불충족": "no", "부분": "part", "미확인": "unk" }[s] || "")
}, s);

const STATUS_KO = { draft: "검수 대기", approved: "검수완료·검색 반영", superseded: "이전 버전", withdrawn: "철회" };
const ROLE_KO = { researcher: "연구자", operator: "거점 운영부서", data_owner: "데이터 소관 부서", admin: "서비스 운영자" };

function mount(...nodes) {
  const app = document.getElementById("app");
  app.replaceChildren(...nodes);
  window.scrollTo(0, 0);
}

function errorBox(e) { return h("div", { class: "notice err" }, e.message || String(e)); }

// ── 머리글·라우팅 ──
function renderHeader() {
  const nav = document.getElementById("nav");
  const who = document.getElementById("who");
  nav.replaceChildren();
  who.replaceChildren();
  if (!state.me) return;
  const caps = new Set(state.me.capabilities);
  const links = [];
  links.push(["/", "첫 화면"]);
  if (caps.has("catalog_view")) links.push(["#/admin/catalogs", "카탈로그 관리"]);
  if (caps.has("grant_manage") || caps.has("log_view")) links.push(["#/admin/access", "권한·로그 관리"]);
  const cur = location.hash.split("?")[0];
  for (const [href, label] of links) {
    nav.append(h("a", { href, class: cur.startsWith(href.split("/").slice(0, 3).join("/")) ? "on" : "" }, label));
  }
  who.append(
    h("span", {}, `${state.me.name} · ${ROLE_KO[state.me.role] || state.me.role}`),
    h("button", { onclick: logout }, "로그아웃"),
  );
}

async function logout() {
  try { await api("POST", "/api/logout", {}); } catch (_) { /* 이미 만료 */ }
  state.me = null; state.last = null;
  location.hash = "#/login";
}

async function route() {
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/");
  if (!state.me && parts[0] !== "login") {
    try { state.me = await api("GET", "/api/me"); } catch (_) { location.hash = "#/login"; return; }
  }
  renderHeader();
  try {
    if (parts[0] === "login") return viewLogin();
    if (state.me.role === "researcher") {
      // 첫 버전에서 연구자는 로그인 없이 첫 화면(/)을 쓴다. 이 페이지는 후속 개발용 관리 화면이다.
      return mount(h("div", { class: "panel" }, h("h2", {}, "관리 화면 전용 페이지입니다"),
        h("p", {}, "연구 목적 입력과 카탈로그 추천은 ", h("a", { href: "/" }, "첫 화면"), "에서 로그인 없이 이용합니다.")));
    }
    if (parts[0] === "admin" && parts[1] === "catalogs" && parts[2]) return viewAdminCatalog(decodeURIComponent(parts[2]));
    if (parts[0] === "admin" && parts[1] === "catalogs") return viewAdminCatalogs();
    if (parts[0] === "admin" && parts[1] === "access") return viewAdminAccess(parts[2] || "grants");
    location.hash = "#/admin/catalogs";
  } catch (e) {
    if (e.status === 401) { state.me = null; location.hash = "#/login"; return; }
    mount(errorBox(e));
  }
}
window.addEventListener("hashchange", route);

// ── S1 로그인 ──
function viewLogin() {
  const msg = h("div");
  const user = h("input", { type: "text", autocomplete: "username", required: true });
  const pw = h("input", { type: "password", autocomplete: "current-password", required: true });
  const form = h("form", {
    onsubmit: async (ev) => {
      ev.preventDefault();
      msg.replaceChildren();
      try {
        state.me = await api("POST", "/api/login", { username: user.value, password: pw.value });
        location.hash = "#/admin/catalogs";
      } catch (e) { msg.replaceChildren(errorBox(e)); }
    }
  },
    h("label", { class: "field" }, h("span", {}, "아이디"), user),
    h("label", { class: "field" }, h("span", {}, "비밀번호"), pw),
    msg,
    h("button", { class: "primary", type: "submit" }, "로그인"),
  );
  mount(h("div", { class: "login-wrap" }, h("div", { class: "panel" },
    h("h1", {}, "로그인"),
    h("p", { class: "lead" }, "인증 후 본인의 열람 가능 범위와 유효기간을 확인합니다."),
    form,
    h("p", { class: "muted small" }, "시제품 시연 계정은 data/users.json 에 있습니다. 실운영에서는 기관 인증으로 대체합니다."),
  )));
}

// ── S1 열람 범위 + S2 입력 + S3 결과 ──
function scopePanel() {
  const me = state.me;
  const box = h("div", { class: "panel" }, h("h2", {}, "내 열람 범위"));
  if (!me.purposes.length) {
    box.append(h("div", { class: "notice warn" },
      "현재 유효한 열람 권한이 없습니다. 권한이 설정되지 않은 자료는 조회할 수 없습니다. 거점 운영부서에 문의하세요."));
  } else {
    const sel = h("select", {
      onchange: async (ev) => {
        try {
          state.me = await api("POST", "/api/session/purpose", { purpose: ev.target.value });
          state.last = null;
          viewSearch();
        } catch (e) { toast(e.message); }
      }
    }, h("option", { value: "" }, "— 연구 목적 선택 —"),
      me.purposes.map((p) => h("option", { value: p.purpose, selected: p.purpose === me.purpose }, p.purpose)));
    box.append(h("label", { class: "field" }, h("span", {}, "승인된 연구 목적"), sel));
    const cur = me.purposes.find((p) => p.purpose === me.purpose);
    if (cur) {
      box.append(h("ul", { class: "scope-list" }, cur.grants.map((g) => h("li", {},
        h("div", {}, h("strong", {}, `권한 #${g.id}`), " ", h("span", { class: "chip" }, g.via)),
        h("div", { class: "small" }, "공개 범위: ", g.levels.join(", ")),
        h("div", { class: "small" }, "분야: ", g.domains.includes("*") ? "전체" : g.domains.join(", ")),
        h("div", { class: "small" }, `유효기간: ${g.valid_from} ~ ${g.valid_to}`),
      ))));
      box.append(h("p", { class: "small muted" }, `이 목적으로 열람 가능한 카탈로그: ${me.visible_count}건`));
    }
  }
  if (me.inactive_grants && me.inactive_grants.length) {
    box.append(h("details", {}, h("summary", {}, `사용할 수 없는 권한 ${me.inactive_grants.length}건`),
      me.inactive_grants.map((g) => h("div", { class: "small muted" }, `${g.purpose} — ${g.reason} (~${g.valid_to})`))));
  }
  return box;
}

function viewSearch() {
  const me = state.me;
  const ready = !!me.purpose;
  const q = state.lastQuery || {};
  const query = h("textarea", { rows: 3, maxlength: 1000, placeholder: "예) 군용 차량의 고장을 사전에 예측하고 싶다", disabled: !ready }, q.query || "");
  const target = h("input", { type: "text", maxlength: 200, value: q.target || "", placeholder: "예) 전술차량" });
  const method = h("input", { type: "text", maxlength: 200, value: q.method || "", placeholder: "예) 시계열 이상 탐지" });
  const period = h("input", { type: "text", maxlength: 200, value: q.period || "", placeholder: "예) 2020~2024" });
  const output = h("input", { type: "text", maxlength: 200, value: q.output || "", placeholder: "예) 고장 예측 모델" });
  const sug = h("div", { class: "suggest hidden" });
  const result = h("div", { id: "result" });

  let sugTimer;
  query.addEventListener("input", () => {
    clearTimeout(sugTimer);
    const words = query.value.split(/\s+/);
    const last = words[words.length - 1];
    if (last.length < 2) { sug.classList.add("hidden"); return; }
    sugTimer = setTimeout(async () => {
      try {
        const r = await api("GET", "/api/suggest?q=" + encodeURIComponent(last));
        sug.replaceChildren(...r.items.map((t) => h("div", {
          onclick: () => { words[words.length - 1] = t; query.value = words.join(" ") + " "; sug.classList.add("hidden"); query.focus(); }
        }, t)));
        sug.classList.toggle("hidden", !r.items.length);
      } catch (_) { sug.classList.add("hidden"); }
    }, 200);
  });
  query.addEventListener("blur", () => setTimeout(() => sug.classList.add("hidden"), 200));

  async function submit(extra) {
    const payload = {
      query: query.value.trim(), target: target.value, method: method.value, period: period.value,
      output: output.value, ...(extra || {}),
    };
    if (!payload.query) { toast("연구 목적을 입력하세요."); return; }
    state.lastQuery = payload;
    result.replaceChildren(h("div", { class: "panel muted" }, "권한 내 카탈로그를 검색하는 중…"));
    try {
      const r = await api("POST", "/api/recommend", payload);
      state.last = r;
      renderResult(result, r, payload, submit);
    } catch (e) { result.replaceChildren(errorBox(e)); }
  }

  const form = h("form", { onsubmit: (ev) => { ev.preventDefault(); submit(); } },
    h("label", { class: "field rel" }, h("span", {}, "연구 목적 (필수)"), query, sug),
    h("details", {}, h("summary", {}, "세부 조건 (선택) — 연구 대상·분석 방법·기간·산출물"),
      h("div", { class: "grid2" },
        h("label", { class: "field" }, h("span", {}, "연구 대상"), target),
        h("label", { class: "field" }, h("span", {}, "분석 방법"), method),
        h("label", { class: "field" }, h("span", {}, "필요 기간·범위"), period),
        h("label", { class: "field" }, h("span", {}, "원하는 산출물"), output),
      )),
    h("div", { class: "notice warn" },
      h("strong", {}, "입력 주의 "), "비공개 작전정보, 개인정보, 기업의 영업비밀은 입력하지 마세요. 연구 목적을 일반적인 표현으로 적어도 추천이 동작합니다."),
    h("div", { class: "notice small" },
      "입력 내용 저장 안내 — 목적: 감사 추적과 추천 품질 점검 · 원문 보관: 30일 후 원문 삭제(해시만 유지) · 열람: 서비스 운영자로 제한"),
    h("div", { class: "row end" }, h("button", { class: "primary", type: "submit", disabled: !ready }, "권한 내 카탈로그 추천 받기")),
  );

  mount(
    h("h1", {}, "연구 목적으로 카탈로그 찾기"),
    h("p", { class: "lead" }, "군 용어를 몰라도 연구 목적을 적으면, 열람 권한 안의 카탈로그를 추천하고 근거와 활용 한계를 함께 보여 드립니다."),
    h("div", { class: "grid-side" }, scopePanel(), h("div", {}, h("div", { class: "panel" }, h("h2", {}, "연구 목적 입력"), form), result)),
  );
  if (state.last && state.lastQuery) renderResult(result, state.last, state.lastQuery, submit);
}

function condChips(c) {
  const out = [];
  if (c.domains.length) out.push(h("span", { class: "chip" }, "대상 분야: " + c.domains.join(", ")));
  if (c.tasks.length) out.push(h("span", { class: "chip" }, "분석 목표: " + c.tasks.join(", ")));
  if (c.data_hints.length) out.push(h("span", { class: "chip" }, "자료 유형: " + c.data_hints.join(", ")));
  if (c.period) out.push(h("span", { class: "chip" }, `기간: ${c.period[0]}~${c.period[1]}`));
  if (c.need_label) out.push(h("span", { class: "chip" }, "정답표시 필요"));
  if (c.output) out.push(h("span", { class: "chip" }, "산출물: " + c.output));
  return out.length ? out : [h("span", { class: "muted small" }, "추출된 조건 없음")];
}

function renderResult(box, r, payload, submit) {
  box.replaceChildren();
  if (r.status === "clarify") {
    const panel = h("div", { class: "panel" }, h("h2", {}, "추가 질문"),
      h("p", { class: "muted small" }, "결과를 바꿀 수 있는 정보가 빠져 있어 먼저 여쭙습니다."));
    for (const q of r.questions) {
      panel.append(h("p", {}, h("strong", {}, q.question)));
      panel.append(h("div", { class: "row" }, q.options.map((o) => h("button", {
        onclick: () => submit({ answers: { ...(payload.answers || {}), [q.id]: o.value } })
      }, o.label))));
    }
    panel.append(h("div", { class: "row end" }, h("button", { class: "link", onclick: () => submit({ answers: payload.answers, skip_clarify: true }) }, "답하지 않고 추천 보기")));
    box.append(panel);
    return;
  }
  const head = h("div", { class: "panel" },
    h("div", { class: "row" }, h("h2", {}, r.status === "ok" ? `추천 후보 ${r.candidates.length}건` : "추천 보류"),
      h("span", { class: "spacer" }), h("span", { class: "small muted" }, `질의 기록 #${r.query_id}`)),
    h("div", {}, h("span", { class: "small muted" }, "추출한 조건: "), condChips(r.conditions)));
  if (r.status === "abstain") {
    head.append(h("div", { class: "notice warn" }, r.message));
    box.append(head);
    return;
  }
  head.append(h("div", { class: "notice small" }, r.notice));
  if (r.comparison.columns.length) {
    head.append(h("h3", {}, "후보 간 조건 비교"), h("div", { class: "scroll" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, h("th", {}, "후보"), r.comparison.columns.map((c) => h("th", {}, c)), h("th", {}, "결합 식별자"))),
      h("tbody", {}, r.comparison.rows.map((row) => h("tr", {},
        h("td", {}, row.title, h("div", { class: "small muted" }, row.catalog_id)),
        r.comparison.columns.map((c) => h("td", {}, row.cells[c] ? [statusChip(row.cells[c].status), h("div", { class: "small muted" }, row.cells[c].actual || "미확인")] : "—")),
        h("td", { class: "small" }, row.join_keys ? row.join_keys.join("; ") : h("span", { class: "chip unknown-val" }, "없음/미확인")),
      ))))));
  }
  box.append(head);
  r.candidates.forEach((c, i) => box.append(candidateCard(c, i + 1)));
}

function srcLink(c, line) {
  if (!line) return h("span", { class: "src muted" }, "(원문 위치 미기재)");
  return h("a", { class: "src", href: `#/catalog/${encodeURIComponent(c.catalog_id)}/${line}` }, `원문 ${line}행`);
}

function candidateCard(c, rank) {
  const band = { "높음": "high", "보통": "mid", "낮음": "low" }[c.relevance];
  const e = c.explanation;
  const av = c.availability;
  const card = h("div", { class: "cand" },
    h("div", { class: "cand-head" },
      h("div", { class: "cand-rank" }, rank),
      h("div", {},
        h("div", { class: "cand-title" }, c.title),
        h("div", { class: "cand-meta" }, `${c.catalog_id} · v${c.version} · ${c.domain}`),
        h("div", {}, h("span", { class: "small" }, "연구 관련성 "), h("span", { class: "badge " + band }, c.relevance),
          h("span", { class: "small muted" }, ` (검색 일치 정도 ${c.score.toFixed(2)})`)),
      ),
      h("div", { class: "avail" },
        h("strong", {}, "이용 가능 여부"),
        h("div", {}, `공개 범위: ${av.access_level}`),
        h("div", {}, av.catalog),
        h("div", {}, av.raw_data),
        h("div", {}, "승인 상태: ", av.approval_status),
        h("div", {}, "확인 주체: ", av.confirmer),
        h("div", { class: "muted" }, `메타데이터 검수: ${av.reviewed_by || "미확인"} · 최종 확인 ${av.last_checked || "미확인"}`),
      ),
    ));
  if (!e) {
    card.append(h("div", { class: "cand-sec full" }, h("div", { class: "notice err" }, c.explanation_error),
      metaTable(c.metadata, c.sources, c)));
  } else {
    card.append(h("div", { class: "cand-body" },
      h("div", { class: "cand-sec sec-fact" },
        h("div", { class: "sec-title" }, h("span", { class: "tag" }, "① 사실"), "카탈로그에서 확인된 내용"),
        h("ul", {}, e.facts.map((f) => h("li", {}, f.text, srcLink(c, f.source_line)))),
        e.basis.length ? h("div", { class: "small" }, h("strong", {}, "추천 근거 항목: "),
          e.basis.map((b) => h("span", { class: "chip ok" }, b.label + (b.terms.length ? ` (${b.terms.join(", ")})` : "") + (b.condition ? " · 조건 충족" : "")))) : null,
      ),
      h("div", { class: "cand-sec sec-ai" },
        h("div", { class: "sec-title" }, h("span", { class: "tag" }, "② AI 제안"), "확인되지 않은 활용 제안"),
        h("ul", {}, e.suggestions.map((s) => h("li", {}, s.text))),
        h("div", { class: "small muted" }, "제안은 연구 가능성이나 승인을 보장하지 않습니다."),
      ),
      h("div", { class: "cand-sec sec-check full" },
        h("div", { class: "sec-title" }, h("span", { class: "tag" }, "③ 확인 필요"), "담당자에게 확인할 사항"),
        h("ul", {}, e.checks.map((k) => h("li", {}, k.text, h("span", { class: "who" }, "· " + k.confirmer)))),
      ),
      h("div", { class: "cand-sec" },
        h("div", { class: "sec-title" }, "부족한 정보"),
        e.missing.length ? e.missing.map((m) => h("span", { class: "chip unk" }, m.label + " 미확인")) : h("span", { class: "small muted" }, "주요 항목이 모두 기재됨"),
      ),
      h("div", { class: "cand-sec" },
        h("div", { class: "sec-title" }, "이용 조건"),
        h("div", { class: "small" }, "신청 절차: ", val(e.terms.procedure)),
        h("div", { class: "small" }, "사용 장소 제한: ", val(e.terms.place_restriction)),
        h("div", { class: "small" }, "사용 목적 제한: ", val(e.terms.purpose_restriction)),
      ),
    ));
  }
  card.append(h("div", { class: "cand-sec full row" },
    h("a", { href: `#/catalog/${encodeURIComponent(c.catalog_id)}` }, "상세·원문 확인"),
    h("span", { class: "spacer" }),
    h("button", { class: "link", onclick: () => location.hash = `#/catalog/${encodeURIComponent(c.catalog_id)}/report` }, "잘못된 근거 신고"),
  ));
  return card;
}

function metaTable(values, sources, c, onSource) {
  const schema = state.schema || [];
  const groups = {};
  for (const [key, label, group] of schema) (groups[group] = groups[group] || []).push([key, label]);
  if (!schema.length) {
    return h("table", { class: "tbl" }, h("tbody", {}, Object.entries(values).map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, val(v))))));
  }
  return h("table", { class: "tbl" }, h("tbody", {}, Object.entries(groups).map(([g, fields]) => [
    h("tr", {}, h("th", { colspan: 3 }, g)),
    fields.map(([key, label]) => h("tr", { "data-key": key },
      h("td", {}, label), h("td", {}, val(values[key])),
      h("td", { class: "small" }, sources && sources[key]
        ? (onSource ? h("button", { class: "link", onclick: () => onSource(sources[key]) }, `원문 ${sources[key]}행`) : srcLink(c, sources[key]))
        : h("span", { class: "muted" }, values[key] == null ? "—" : "직접 입력")),
    )),
  ])));
}

function sourceDoc(text, hl) {
  return h("div", { class: "srcdoc" }, (text || "").split("\n").map((line, i) =>
    h("div", { class: i + 1 === hl ? "hl" : "", id: `L${i + 1}` }, h("span", {}, i + 1), h("span", {}, line))));
}

// ── S4 후보 상세 ──
async function viewDetail(id, extra) {
  const d = await api("GET", `/api/catalogs/${encodeURIComponent(id)}`);
  state.schema = d.schema;
  const hl = /^\d+$/.test(extra || "") ? Number(extra) : null;
  const docBox = h("div");
  const showLine = (n) => {
    docBox.replaceChildren(sourceDoc(d.source_text, n));
    const el = docBox.querySelector(`#L${n}`);
    if (el) el.scrollIntoView({ block: "center" });
  };
  docBox.append(sourceDoc(d.source_text, hl));

  const last = state.last && state.last.candidates && state.last.candidates.find((c) => c.catalog_id === d.catalog_id);
  const fieldSel = h("select", {},
    h("option", { value: "general" }, "전반"), h("option", { value: "suggestion" }, "AI 제안"), h("option", { value: "check" }, "확인 필요사항"),
    d.schema.map(([k, label]) => h("option", { value: k }, label)));
  const msg = h("textarea", { rows: 3, maxlength: 1000, placeholder: "어떤 근거가 왜 잘못되었는지 적어 주세요." });
  const reportForm = h("form", {
    id: "report",
    onsubmit: async (ev) => {
      ev.preventDefault();
      try {
        const r = await api("POST", "/api/reports", { catalog_id: d.catalog_id, field: fieldSel.value, message: msg.value });
        msg.value = "";
        toast(`신고가 접수되었습니다 (#${r.report_id}). 거점 운영부서가 확인합니다.`);
      } catch (e) { toast(e.message); }
    }
  }, h("h3", {}, "잘못된 근거 신고"),
    h("label", { class: "field" }, h("span", {}, "항목"), fieldSel),
    h("label", { class: "field" }, h("span", {}, "내용"), msg),
    h("div", { class: "row end" }, h("button", { class: "primary", type: "submit" }, "신고")));

  mount(
    h("div", { class: "row" }, h("a", { href: "#/search" }, "← 추천 결과로")),
    h("h1", {}, d.values.title),
    h("p", { class: "lead" }, `${d.catalog_id} · v${d.version} · 승인 상태: ${d.approval_status} (검수자 ${d.reviewed_by || "미확인"}, ${d.reviewed_at || "미확인"}) · 확인 주체: 데이터 소관 부서(${d.values.department || "미확인"})`),
    h("div", { class: "notice small" }, "이 화면은 카탈로그(메타데이터)입니다. 원본 데이터 이용 여부는 별도 신청·승인 절차에서 결정됩니다."),
    h("div", { class: "grid2" },
      h("div", { class: "panel" }, h("h2", {}, "메타데이터와 항목별 출처"), metaTable(d.values, d.sources, d, showLine)),
      h("div", {},
        h("div", { class: "panel" }, h("h2", {}, "원문 확인"), h("p", { class: "small muted" }, d.values.source_doc || ""), docBox),
        last && last.explanation ? h("div", { class: "panel" }, h("h2", {}, "담당자 확인사항"),
          h("ul", {}, last.explanation.checks.map((k) => h("li", {}, k.text, h("span", { class: "who" }, "· " + k.confirmer))))) : null,
        h("div", { class: "panel" }, reportForm),
      )),
  );
  if (hl) showLine(hl);
  if (extra === "report") document.getElementById("report").scrollIntoView();
}

// ── S5 카탈로그 관리 ──
async function viewAdminCatalogs() {
  const [list, status] = await Promise.all([api("GET", "/api/admin/catalogs"), api("GET", "/api/admin/status")]);
  state.schema = status.schema;
  let filter = "all";
  const tableBox = h("div", { class: "scroll" });
  const draw = () => {
    const items = list.items.filter((c) => filter === "all" || c.state === filter || (filter === "draft" && c.has_draft));
    tableBox.replaceChildren(h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ["ID", "제목", "분야", "공개 범위", "소관 부서", "상태", "버전"].map((t) => h("th", {}, t)))),
      h("tbody", {}, items.map((c) => h("tr", {},
        h("td", {}, h("a", { href: `#/admin/catalogs/${encodeURIComponent(c.id)}` }, c.id)),
        h("td", {}, c.title), h("td", {}, c.domain || "—"), h("td", {}, c.access_level || "—"),
        h("td", { class: "small" }, c.department || "—"),
        h("td", {}, h("span", { class: "status-" + c.state }, STATUS_KO[c.state]), c.has_draft && c.state !== "draft" ? h("span", { class: "chip part" }, "새 버전 검수 대기") : null),
        h("td", { class: "small" }, c.versions.map((v) => `v${v.version}(${STATUS_KO[v.status]})`).join(", ")),
      )))));
  };
  const tabs = h("div", { class: "tabs" }, [["all", "전체"], ["approved", "검색 반영"], ["draft", "검수 대기"], ["withdrawn", "철회"]].map(([k, label]) =>
    h("button", { class: k === filter ? "on" : "", onclick: (ev) => { filter = k; tabs.querySelectorAll("button").forEach((b) => b.classList.remove("on")); ev.target.classList.add("on"); draw(); } }, label)));
  draw();
  const canEdit = state.me.capabilities.includes("catalog_edit");
  mount(
    h("h1", {}, "카탈로그 관리"),
    h("p", { class: "lead" }, "등록 · 검수 · 버전 관리 · 철회. 검수되지 않은 메타데이터는 검색에 나오지 않고, 알 수 없는 값은 '미확인'으로 둡니다."),
    state.me.capabilities.includes("catalog_excel") ? excelPanel() : null,
    canEdit ? extractPanel() : null,
    h("div", { class: "panel" }, tabs, tableBox),
    h("div", { class: "panel small" }, h("h3", {}, "모델·인덱스 버전"),
      h("div", { class: "mono" }, Object.entries(status.model).map(([k, v]) => `${k}=${v}`).join(" · ")),
      status.unapproved_glossary.length ? h("div", { class: "muted" }, "미승인 용어(검색에 쓰지 않음): " + status.unapproved_glossary.join(", ")) : null),
  );
}

// 카탈로그 엑셀: 지금 쓰는 파일을 받아 행을 추가·수정한 뒤 다시 올린다. 올리기 전에 검사 결과를 보여 준다.
function excelPanel() {
  const file = h("input", { type: "file", accept: ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  const out = h("div");
  const applyBtn = h("button", { class: "primary", disabled: true }, "이 파일로 반영");
  let data = null;

  const readFile = (f) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] || "");
    r.onerror = () => reject(new Error("파일을 읽지 못했습니다."));
    r.readAsDataURL(f);
  });
  const ids = (label, list, cls) => list && list.length
    ? h("div", { class: "small" }, h("strong", {}, `${label} ${list.length}건: `), list.map((x) => h("span", { class: "chip " + (cls || "") }, x)))
    : null;
  const msgs = (r) => [
    r.errors && r.errors.length ? h("div", { class: "notice err small" }, h("strong", {}, "건너뛰는 행"), r.errors.map((x) => h("div", {}, x))) : null,
    r.warnings && r.warnings.length ? h("details", { class: "small" }, h("summary", {}, `주의 사항 ${r.warnings.length}건`), r.warnings.map((x) => h("div", {}, x))) : null,
  ];
  const countLine = (c) => `새로 추가 ${c.added} · 내용 변경 ${c.updated} · 그대로 ${c.unchanged} · 검수대기 ${c.draft} · 철회 ${c.withdrawn} · 건너뜀 ${c.skipped}`;

  file.addEventListener("change", async () => {
    data = null;
    applyBtn.disabled = true;
    out.replaceChildren();
    const f = file.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { out.replaceChildren(errorBox(new Error("엑셀 파일은 5MB 이하만 올릴 수 있습니다."))); return; }
    out.replaceChildren(h("p", { class: "small muted" }, "검사하는 중…"));
    try {
      const b64 = await readFile(f);
      const r = await api("POST", "/api/admin/excel/check", { data: b64 });
      if (!r.ok) {
        out.replaceChildren(h("div", {}, h("div", { class: "notice err" }, h("strong", {}, "반영할 수 없는 파일입니다. "), r.fatal), msgs(r)));
        return;
      }
      data = b64;
      applyBtn.disabled = false;
      out.replaceChildren(h("div", {},
        h("div", { class: "notice small" }, h("strong", {}, `검사 결과 (${r.rows}행) `), countLine(r.counts)),
        ids("새로 추가", r.lists.added, "ok"), ids("내용 변경", r.lists.updated, "part"),
        ids("검색에서 빠짐(철회)", r.lists.withdrawn, "no"), ids("검수대기로 바뀜(검색에서 빠짐)", r.lists.to_draft, "no"),
        r.lists.withdrawn.length ? h("div", { class: "notice warn small" }, "엑셀에 없는 카탈로그는 철회됩니다. 받은 파일에 행을 추가해서 올리세요.") : null,
        msgs(r)));
    } catch (e) { out.replaceChildren(errorBox(e)); }
  });

  applyBtn.addEventListener("click", async () => {
    if (!data) return;
    applyBtn.disabled = true;
    try {
      const r = await api("POST", "/api/admin/excel/upload", { data });
      data = null;
      file.value = "";
      toast(r.status === "unchanged" ? "지금 쓰는 파일과 같아 바뀐 것이 없습니다." : `반영했습니다. 검색에 나오는 카탈로그 ${r.catalog_count}건.`);
      viewAdminCatalogs();
    } catch (e) { out.append(errorBox(e)); applyBtn.disabled = false; }
  });

  return h("div", { class: "panel" }, h("h2", {}, "카탈로그 엑셀"),
    h("p", { class: "small muted" }, "검색에 쓰는 카탈로그 목록 파일입니다. 내려받아 행을 추가·수정한 뒤 올리면 바로 검색에 반영됩니다. ",
      "한 행이 카탈로그 하나이고, 상태가 '검수완료'인 행만 검색에 나옵니다. 작성 방법은 파일의 '작성 안내' 시트를 보세요."),
    h("div", { class: "row" },
      h("a", { class: "button", href: "/api/admin/excel/download", download: "" }, "지금 쓰는 엑셀 내려받기"),
      h("span", { class: "spacer" }),
      h("label", { class: "row small" }, "고친 엑셀 올리기", file),
      applyBtn),
    out,
    h("p", { class: "small muted" }, "반영하기 전 파일은 서버의 var/excel_backups 폴더에 남습니다."));
}

function extractPanel() {
  const text = h("textarea", { class: "mono", rows: 8, placeholder: "제목: 차량 타이어 교체 기록\n분야: 차량\n설명: ...\n항목 정의: 교체일자; 차량관리번호; 타이어규격\n공개 범위: 거점승인\n열람 가능 역할: researcher\n원문 문서: (가상) 명세서 v1" });
  const code = h("input", { type: "text", maxlength: 3, placeholder: "VEH" });
  const preview = h("div");
  return h("details", { class: "panel" }, h("summary", {}, "새 카탈로그 등록 — 명세서 원문에서 추출"),
    h("p", { class: "small muted" }, "'항목명: 값' 형식의 원문을 붙여 넣으면 항목을 추출합니다. 추출 결과는 검수 대기 상태로 저장되며, 원문 행 번호가 출처로 연결됩니다. 없는 항목은 추정하지 않고 비워 둡니다."),
    h("label", { class: "field" }, h("span", {}, "원문"), text),
    h("div", { class: "row" },
      h("button", { onclick: async () => {
        try {
          const r = await api("POST", "/api/admin/extract", { text: text.value });
          preview.replaceChildren(
            r.warnings.length ? h("div", { class: "notice warn" }, r.warnings.map((w) => h("div", {}, w))) : null,
            metaTable(r.values, r.sources, null, () => {}));
        } catch (e) { preview.replaceChildren(errorBox(e)); }
      } }, "추출 미리보기"),
      h("label", { class: "row small" }, "ID 분야 코드", code),
      h("button", { class: "primary", onclick: async () => {
        try {
          const r = await api("POST", "/api/admin/catalogs", { text: text.value, domain_code: code.value || "NEW" });
          toast(`${r.catalog_id} v${r.version} 초안이 저장되었습니다(검수 대기).`);
          location.hash = `#/admin/catalogs/${encodeURIComponent(r.catalog_id)}`;
        } catch (e) { toast(e.message); }
      } }, "검수 대기로 저장"),
    ),
    preview,
  );
}

async function viewAdminCatalog(id) {
  const d = await api("GET", `/api/admin/catalogs/${encodeURIComponent(id)}`);
  state.schema = d.schema;
  const caps = new Set(state.me.capabilities);
  const versions = d.versions;
  let sel = versions.find((v) => v.status === "draft") || versions.find((v) => v.status === "approved") || versions[versions.length - 1];
  const body = h("div");
  const reload = () => viewAdminCatalog(id);
  const act = async (fn, okMsg) => { try { await fn(); toast(okMsg); reload(); } catch (e) { toast(e.message); } };

  const draw = () => {
    const v = sel;
    const docBox = h("div", {}, sourceDoc(v.source_text));
    const showLine = (n) => { docBox.replaceChildren(sourceDoc(v.source_text, n)); const el = docBox.querySelector(`#L${n}`); if (el) el.scrollIntoView({ block: "center" }); };
    const editable = v.status === "draft" && caps.has("catalog_edit");
    const inputs = {};
    const formTable = h("table", { class: "tbl" }, h("tbody", {}, d.schema.map(([key, label, group, kind]) => {
      const cur = v.values[key];
      const text = cur == null ? "" : (Array.isArray(cur) ? cur.join("; ") : cur);
      let input;
      if (key === "access_level") {
        input = h("select", {}, h("option", { value: "" }, "미확인"), d.access_levels.map((a) => h("option", { value: a, selected: a === cur }, a)));
      } else {
        input = h("input", { type: "text", value: text, placeholder: kind === "list" ? "세미콜론(;)으로 구분 · 비우면 미확인" : "비우면 미확인" });
      }
      inputs[key] = input;
      return h("tr", {}, h("td", { class: "small" }, group), h("td", {}, label),
        h("td", {}, editable ? input : val(cur)),
        h("td", { class: "small" }, v.sources[key] ? h("button", { class: "link", onclick: () => showLine(v.sources[key]) }, `원문 ${v.sources[key]}행`) : h("span", { class: "muted" }, cur == null ? "—" : "직접 입력")));
    })));
    const note = h("input", { type: "text", placeholder: "검수 의견(선택)" });
    const reason = h("input", { type: "text", placeholder: "철회 사유(필수)" });
    const actions = h("div", { class: "row" });
    if (editable) {
      actions.append(h("button", { onclick: () => act(() => api("POST", `/api/admin/catalogs/${encodeURIComponent(id)}/versions/${v.version}`,
        { values: Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value])) }), "저장했습니다. 직접 고친 항목은 원문 출처 연결이 해제됩니다.") }, "초안 저장"));
    }
    if (v.status === "draft" && caps.has("catalog_review")) {
      actions.append(note, h("button", { class: "primary", onclick: () => act(() => api("POST", `/api/admin/catalogs/${encodeURIComponent(id)}/versions/${v.version}/approve`, { note: note.value }), "검수 승인했습니다. 검색 인덱스와 캐시에 즉시 반영됩니다.") }, "검수 승인 → 검색 반영"));
    }
    if (v.status !== "draft" && caps.has("catalog_edit") && !versions.some((x) => x.status === "draft")) {
      actions.append(h("button", { onclick: () => act(() => api("POST", `/api/admin/catalogs/${encodeURIComponent(id)}/new-version`, { from_version: v.version }), `v${v.version} 기반 새 버전(검수 대기)을 만들었습니다.`) },
        v.status === "approved" ? "이 버전으로 새 버전 만들기" : `v${v.version}로 복구(새 버전 생성)`));
    }
    if (v.status === "approved" && caps.has("catalog_withdraw")) {
      actions.append(reason, h("button", { class: "danger", onclick: () => act(() => api("POST", `/api/admin/catalogs/${encodeURIComponent(id)}/withdraw`, { reason: reason.value }), "철회했습니다. 더 이상 추천되지 않습니다.") }, "철회"));
    }
    body.replaceChildren(
      v.warnings.length ? h("div", { class: "notice warn" }, v.warnings.map((w) => h("div", {}, w))) : null,
      h("div", { class: "small muted" }, `상태: ${STATUS_KO[v.status]} · 작성 ${v.created_by} ${v.created_at} · 검수 ${v.reviewed_by || "—"} ${v.reviewed_at || ""} · ${v.note || ""}`),
      h("div", { class: "grid2" },
        h("div", { class: "panel" }, h("h2", {}, `v${v.version} 메타데이터`), formTable, actions),
        h("div", { class: "panel" }, h("h2", {}, "원문"), docBox)),
    );
  };
  const vtabs = h("div", { class: "tabs" }, versions.map((v) => h("button", {
    class: v === sel ? "on" : "",
    onclick: (ev) => { sel = v; vtabs.querySelectorAll("button").forEach((b) => b.classList.remove("on")); ev.target.classList.add("on"); draw(); }
  }, `v${v.version} · ${STATUS_KO[v.status]}`)));
  draw();
  mount(h("div", { class: "row" }, h("a", { href: "#/admin/catalogs" }, "← 카탈로그 목록")),
    h("h1", {}, `${id} ${sel.values.title || ""}`), vtabs, body);
}

// ── S6 권한·로그 관리 ──
async function viewAdminAccess(tab) {
  const caps = new Set(state.me.capabilities);
  const tabs = [["grants", "열람 권한", "grant_manage"], ["logs", "감사로그", "log_view"], ["reports", "근거 신고", "report_manage"]].filter((t) => caps.has(t[2]));
  if (!tabs.some((t) => t[0] === tab)) tab = tabs.length ? tabs[0][0] : "";
  const content = h("div");
  mount(h("h1", {}, "권한·로그 관리"),
    h("p", { class: "lead" }, "권한은 사용자·기관·목적·유효기간별로 설정합니다. 설정되지 않은 권한은 접근 거부이며, 변경 즉시 검색 결과와 캐시에 반영됩니다."),
    h("div", { class: "tabs" }, tabs.map(([k, label]) => h("button", { class: k === tab ? "on" : "", onclick: () => location.hash = `#/admin/access/${k}` }, label))),
    content);
  if (tab === "grants") return grantsTab(content);
  if (tab === "logs") return logsTab(content);
  if (tab === "reports") return reportsTab(content);
}

async function grantsTab(box) {
  const [g, u] = await Promise.all([api("GET", "/api/admin/grants"), api("GET", "/api/admin/users")]);
  const st = h("select", {}, h("option", { value: "user" }, "사용자"), h("option", { value: "org" }, "기관"));
  const researchers = u.items.filter((x) => x.role === "researcher");
  const orgs = [...new Set(researchers.map((x) => x.org))];
  const sid = h("select");
  const fillSid = () => sid.replaceChildren(...(st.value === "user"
    ? researchers.map((x) => h("option", { value: x.id }, `${x.id} · ${x.name} · ${x.org}`))
    : orgs.map((o) => h("option", { value: o }, o))));
  st.addEventListener("change", fillSid);
  fillSid();
  const purpose = h("input", { type: "text", maxlength: 100, placeholder: "예) 장비 예지정비 연구" });
  const levels = ["공개", "거점승인", "제한"].map((l) => h("label", { class: "row small" }, h("input", { type: "checkbox", value: l, checked: l === "공개" }), l));
  const domains = h("input", { type: "text", placeholder: "쉼표로 구분 · 전체는 *  예) 차량, 항공기" });
  const vf = h("input", { type: "date", value: state.me.today });
  const vt = h("input", { type: "date" });
  box.append(
    h("div", { class: "panel" }, h("h2", {}, "권한 추가"),
      h("div", { class: "grid2" },
        h("label", { class: "field" }, h("span", {}, "대상 유형"), st),
        h("label", { class: "field" }, h("span", {}, "대상"), sid),
        h("label", { class: "field" }, h("span", {}, "연구 목적"), purpose),
        h("label", { class: "field" }, h("span", {}, "분야"), domains),
        h("div", { class: "field" }, h("span", { class: "small" }, h("strong", {}, "공개 범위")), h("div", { class: "row" }, levels)),
        h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "유효 시작"), vf), h("label", { class: "field" }, h("span", {}, "유효 종료"), vt)),
      ),
      h("div", { class: "row end" }, h("button", { class: "primary", onclick: async () => {
        try {
          await api("POST", "/api/admin/grants", {
            subject_type: st.value, subject_id: sid.value, purpose: purpose.value,
            levels: levels.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value),
            domains: domains.value.split(",").map((s) => s.trim()).filter(Boolean), valid_from: vf.value, valid_to: vt.value,
          });
          toast("권한을 추가했습니다."); viewAdminAccess("grants");
        } catch (e) { toast(e.message); }
      } }, "권한 추가"))),
    h("div", { class: "panel scroll" }, h("h2", {}, "권한 목록"), h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ["#", "대상", "목적", "공개 범위", "분야", "유효기간", "상태", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, g.items.map((x) => h("tr", {},
        h("td", {}, x.id), h("td", {}, `${x.subject_type === "user" ? "사용자" : "기관"} ${x.subject_id}`), h("td", {}, x.purpose),
        h("td", {}, x.levels.join(", ")), h("td", {}, x.domains.includes("*") ? "전체" : x.domains.join(", ")),
        h("td", { class: "small" }, `${x.valid_from} ~ ${x.valid_to}`),
        h("td", {}, x.revoked_at ? h("span", { class: "chip no" }, `회수 ${x.revoked_at.slice(0, 10)}`) : x.active ? h("span", { class: "chip ok" }, "유효") : h("span", { class: "chip unk" }, "기간 외")),
        h("td", {}, !x.revoked_at ? h("button", { class: "danger", onclick: async () => {
          try { await api("POST", `/api/admin/grants/${x.id}/revoke`, {}); toast("회수했습니다. 즉시 반영됩니다."); viewAdminAccess("grants"); } catch (e) { toast(e.message); }
        } }, "회수") : null),
      ))))),
  );
}

async function logsTab(box) {
  const event = h("select", {}, ["", "recommend", "clarify", "view_detail", "report", "login", "login_fail", "grant_create", "grant_revoke",
    "catalog_create", "catalog_update", "catalog_approve", "catalog_withdraw", "catalog_new_version", "purge"].map((e) => h("option", { value: e }, e || "전체 이벤트")));
  const tbl = h("div", { class: "scroll" });
  const load = async () => {
    const r = await api("GET", "/api/admin/logs?limit=300" + (event.value ? "&event=" + encodeURIComponent(event.value) : ""));
    tbl.replaceChildren(
      h("p", { class: "small muted" }, `원문 질의 ${r.raw_visible ? "열람 가능(서비스 운영자)" : "가림 처리됨"} · 원문 보관 ${r.retention.raw_query_days}일 · 로그 보관 ${r.retention.log_days}일`),
      h("table", { class: "tbl" },
        h("thead", {}, h("tr", {}, ["#", "시각", "사용자", "이벤트", "목적", "질의", "근거(ID·버전)", "권한 판정", "모델", "결과"].map((t) => h("th", {}, t)))),
        h("tbody", {}, r.logs.map((l) => h("tr", {},
          h("td", {}, l.id), h("td", { class: "small" }, l.ts), h("td", {}, l.user_id || "—"), h("td", {}, l.event),
          h("td", { class: "small" }, l.purpose || "—"),
          h("td", { class: "small" }, l.query_text == null ? (l.query_hash ? h("span", { class: "muted" }, `#${l.query_hash}`) : "—") : l.query_text),
          h("td", { class: "small" }, (l.evidence || []).map((e) => e.catalog_id ? `${e.catalog_id}${e.version ? " v" + e.version : ""}` : JSON.stringify(e)).join(", ") || "—"),
          h("td", { class: "small" }, l.permission && l.permission.decision ? `${l.permission.decision}${l.permission.grant_ids ? " · 권한 " + l.permission.grant_ids.join(",") : ""}` : (l.permission && l.permission.grant_id ? `권한 #${l.permission.grant_id}` : "—")),
          h("td", { class: "small mono" }, l.model && l.model.explainer ? `${l.model.explainer} / gen ${l.model.catalog_generation}` : "—"),
          h("td", { class: "small" }, l.outcome || "", (l.flags || []).map((f) => h("span", { class: "chip " + (f === "injection_suspected" ? "no" : "") }, f))),
        )))));
  };
  event.addEventListener("change", load);
  box.append(h("div", { class: "panel" }, h("div", { class: "row" }, event, h("span", { class: "spacer" }),
    state.me.capabilities.includes("purge") ? h("button", { class: "danger", onclick: async () => {
      try { const r = await api("POST", "/api/admin/logs/purge", {}); toast(`원문 삭제 ${r.raw_queries_cleared}건 · 로그 삭제 ${r.logs_deleted}건`); load(); } catch (e) { toast(e.message); }
    } }, "보존기간 지난 기록 정리") : null), tbl));
  await load();
}

async function reportsTab(box) {
  const r = await api("GET", "/api/admin/reports");
  box.append(h("div", { class: "panel scroll" }, h("h2", {}, "잘못된 근거 신고"),
    r.items.length ? h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ["#", "접수", "신고자", "카탈로그", "항목", "내용", "상태", "처리"].map((t) => h("th", {}, t)))),
      h("tbody", {}, r.items.map((x) => {
        const res = h("input", { type: "text", placeholder: "처리 내용" });
        return h("tr", {},
          h("td", {}, x.id), h("td", { class: "small" }, x.ts), h("td", {}, x.user_id),
          h("td", {}, h("a", { href: `#/admin/catalogs/${encodeURIComponent(x.catalog_id)}` }, `${x.catalog_id} v${x.version}`)),
          h("td", {}, x.field), h("td", {}, x.message),
          h("td", {}, x.status === "open" ? h("span", { class: "chip part" }, "접수") : h("span", { class: "chip ok" }, "처리됨")),
          h("td", {}, x.status === "open" ? h("div", { class: "row" }, res, h("button", { onclick: async () => {
            try { await api("POST", `/api/admin/reports/${x.id}/resolve`, { resolution: res.value }); toast("처리했습니다."); viewAdminAccess("reports"); } catch (e) { toast(e.message); }
          } }, "처리 완료")) : h("span", { class: "small" }, `${x.resolution} (${x.resolved_by})`)));
      }))) : h("p", { class: "muted" }, "접수된 신고가 없습니다.")));
}

route();
