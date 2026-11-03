"use strict";
// 카탈로그 대표 이미지(자동 생성). 등록된 분야·자료 유형으로 그림을 고르고, 카탈로그 ID 로 배치를 조금씩 달리한다.
// 실제 데이터 값을 그린 그래프가 아니라 분위기를 나타내는 그림이다.

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  for (const kid of kids.flat(Infinity)) if (kid) el.append(kid);
  return el;
}

// 분야별 색(위→아래 그라디언트)과 선 그림(64×64 기준)
const COVER_THEMES = {
  "차량": ["#4f8cff", "#1b2f6b", [
    "M6 22h30v20H6z", "M36 29h12l9 9v4H36z", "M12 48a5 5 0 1 0 10 0a5 5 0 1 0-10 0", "M42 48a5 5 0 1 0 10 0a5 5 0 1 0-10 0"]],
  "항공기": ["#38bdf8", "#0b3a5c", [
    "M32 6c2 0 3 2 3 5v14l21 11v5l-21-7v12l7 5v4l-10-3-10 3v-4l7-5V34l-21 7v-5l21-11V11c0-3 1-5 3-5z"]],
  "함정": ["#22d3ee", "#0d3b4a", [
    "M6 38h52l-7 12H13z", "M18 38V28h18v10", "M25 28v-8h7v8", "M4 57q5-4 10 0t10 0t10 0t10 0t10 0t10 0"]],
  "통신": ["#a78bfa", "#33206b", [
    "M32 24v34", "M22 58l10-34 10 34", "M25 47h14", "M24 12a11 11 0 0 0 0 16", "M40 12a11 11 0 0 1 0 16",
    "M17 6a20 20 0 0 0 0 28", "M47 6a20 20 0 0 1 0 28"]],
  "보급": ["#f5a524", "#5c3006", [
    "M32 8l22 11v26L32 56 10 45V19z", "M10 19l22 11 22-11", "M32 30v26", "M21 13.5l22 11"]],
  "에너지": ["#facc15", "#5a4206", ["M37 4L14 36h16l-4 24 24-34H34z"]],
  "시설": ["#9fb1c7", "#2a3545", [
    "M10 58V18l22-10 22 10v40", "M5 58h54", "M20 26h7v7h-7z", "M37 26h7v7h-7z", "M20 40h7v7h-7z", "M37 40h7v7h-7z", "M28 58V49h8v9"]],
  "기상": ["#7aa8ff", "#2a2f7a", [
    "M14 22a8 8 0 1 0 16 0a8 8 0 1 0-16 0", "M22 6v4", "M22 34v4", "M6 22h4", "M8.7 8.7l2.8 2.8", "M32.5 11.5l2.8-2.8",
    "M20 54h28a9 9 0 0 0-1-18 12 12 0 0 0-23 3 8 8 0 0 0-4 15z"]],
  "교육훈련": ["#34d399", "#0b4a39", [
    "M8 32a24 24 0 1 0 48 0a24 24 0 1 0-48 0", "M18 32a14 14 0 1 0 28 0a14 14 0 1 0-28 0", "M28 32a4 4 0 1 0 8 0a4 4 0 1 0-8 0",
    "M32 2v12", "M32 50v12", "M2 32h12", "M50 32h12"]],
  "급식": ["#fb8c4a", "#5a1e08", [
    "M8 32h48a24 18 0 0 1-48 0z", "M24 54h16", "M24 10q-4 5 0 10", "M32 8q-4 5 0 10", "M40 10q-4 5 0 10"]],
  "보건": ["#f87171", "#5c1414", [
    "M26 8h12v16h16v12H38v16H26V36H10V24h16z", "M4 58h12l4-6 5 10 5-14 4 10h26"]],
  "군수": ["#c2b04a", "#3d3a10", [
    "M6 30h34v18H6z", "M40 36h10l8 8v4H40z", "M12 52a4 4 0 1 0 8 0a4 4 0 1 0-8 0", "M44 52a4 4 0 1 0 8 0a4 4 0 1 0-8 0",
    "M10 30V18h12v12", "M24 30V12h12v18", "M16 18v-4", "M30 12V8"]],
  "작전": ["#ef6f6c", "#4a1220", [
    "M32 6l6 14h15l-12 9 5 15-14-9-14 9 5-15-12-9h15z", "M12 58h40", "M32 44v14"]],
  "정보": ["#2dd4bf", "#0b3d3a", [
    "M4 32q28-26 56 0q-28 26-56 0z", "M24 32a8 8 0 1 0 16 0a8 8 0 1 0-16 0", "M44 50l12 10", "M38 44a10 10 0 1 0 0.1 0"]],
  "인사": ["#f472b6", "#521638", [
    "M24 18a8 8 0 1 0 16 0a8 8 0 1 0-16 0", "M14 46a18 14 0 0 1 36 0v4H14z", "M6 30a5 5 0 1 0 10 0a5 5 0 1 0-10 0",
    "M48 30a5 5 0 1 0 10 0a5 5 0 1 0-10 0", "M2 50a9 8 0 0 1 14-7", "M62 50a9 8 0 0 0-14-7"]],
  "공통": ["#a1a1aa", "#27272a",["M10 10h18v18H10z", "M36 10h18v18H36z", "M10 36h18v18H10z", "M36 36h18v18H36z"]],
};
const DEFAULT_THEME = ["#64748b", "#1e293b", [
  "M12 14a20 7 0 1 0 40 0a20 7 0 1 0-40 0", "M12 14v36a20 7 0 0 0 40 0V14", "M12 26a20 7 0 0 0 40 0", "M12 38a20 7 0 0 0 40 0"]];

function hashSeed(s) {
  let h = 2166136261;
  for (const ch of String(s)) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function rng(seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 자료 유형 무늬: 시계열=선, 이력·텍스트=기록 줄, 집계·통계=막대, 코드표=격자, 이미지·영상=사진 틀, 음성=파형, 공간=등고선
function motif(dataType, rand) {
  const g = svg("g", { fill: "none", stroke: "#fff", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", opacity: ".75" });
  const x0 = 18, y0 = 96, w = 108, h = 50;
  const t = dataType || "";
  if (t.includes("이미지") || t.includes("영상")) {
    for (let i = 0; i < 3; i++) {
      const x = x0 + i * 36, y = y0 - h + 8 + (i % 2) * 6;
      g.append(svg("rect", { x, y, width: 30, height: 26, rx: 3, fill: "#fff", "fill-opacity": ".12" }),
        svg("path", { d: `M${x + 3} ${y + 22}l8-9 6 6 4-4 6 7`, opacity: ".8" }),
        svg("circle", { cx: x + 22, cy: y + 7, r: 2.5, fill: "#fff", "fill-opacity": ".6", stroke: "none" }));
    }
  } else if (t.includes("음성")) {
    for (let i = 0; i < 18; i++) {
      const bh = h * (0.15 + 0.7 * rand()) / 2;
      const x = x0 + i * 6;
      g.append(svg("path", { d: `M${x} ${y0 - h / 2 - bh}V${y0 - h / 2 + bh}`, "stroke-width": "3" }));
    }
  } else if (t.includes("공간")) {
    for (let i = 0; i < 4; i++) {
      const rx = 14 + i * 12, ry = 8 + i * 6;
      g.append(svg("ellipse", { cx: x0 + w / 2 + rand() * 6, cy: y0 - h / 2, rx, ry, opacity: (0.9 - i * 0.18).toFixed(2) }));
    }
  } else if (t.includes("시계열")) {
    let d = "";
    for (let i = 0; i <= 12; i++) {
      const x = x0 + (w / 12) * i;
      const y = y0 - h * (0.35 + 0.3 * Math.sin(i * 0.9 + rand() * 2) + 0.2 * rand());
      d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    g.append(svg("path", { d }), svg("path", { d: `M${x0} ${y0}H${x0 + w}`, opacity: ".35" }));
  } else if (t.includes("집계") || t.includes("통계") || t.includes("현황")) {
    for (let i = 0; i < 6; i++) {
      const bh = h * (0.3 + 0.7 * rand());
      g.append(svg("rect", { x: x0 + i * 18, y: y0 - bh, width: 11, height: bh, rx: 2, fill: "#fff", "fill-opacity": ".22" }));
    }
  } else if (t.includes("코드") || t.includes("참조")) {
    for (let r = 0; r < 3; r++) for (let c = 0; c < 5; c++) {
      g.append(svg("rect", { x: x0 + c * 21, y: y0 - h + r * 17, width: 16, height: 12, rx: 2, "fill-opacity": ".15", fill: "#fff" }));
    }
  } else {
    for (let i = 0; i < 4; i++) {
      const y = y0 - h + 6 + i * 14;
      g.append(svg("path", { d: `M${x0} ${y}h6`, "stroke-width": "4" }),
        svg("path", { d: `M${x0 + 14} ${y}h${(40 + 50 * rand()).toFixed(0)}`, opacity: ".6" }));
    }
  }
  return g;
}

function makeCover(c) {
  const v = c.metadata || {};
  const [top, bottom, icon] = COVER_THEMES[v.domain] || DEFAULT_THEME;
  const rand = rng(hashSeed(c.catalog_id));
  const gid = "cg-" + String(c.catalog_id).replace(/[^A-Za-z0-9_-]/g, "_") + "-" + Math.floor(rand() * 1e6);
  const angle = 20 + Math.floor(rand() * 50);
  const blobs = [0, 1, 2].map(() => svg("circle", {
    cx: (rand() * 240).toFixed(0), cy: (rand() * 150).toFixed(0), r: (30 + rand() * 60).toFixed(0), fill: "#fff", "fill-opacity": (0.04 + rand() * 0.06).toFixed(2),
  }));
  const label = [v.domain, v.data_type].filter(Boolean).join(" · ");
  // 카탈로그마다 구별되도록 첫 해시태그(등록된 주제어)를 크게 쓴다. 너무 길면 줄인다.
  const tags = (c.explanation && c.explanation.hashtags) || [];
  let keyword = tags.length ? tags[0].tag.slice(1) : "";
  if (keyword.length > 9) keyword = keyword.slice(0, 8) + "…";
  const el = svg("svg", { viewBox: "0 0 240 150", preserveAspectRatio: "xMidYMid slice", class: "cover-svg", role: "img", "aria-label": `${c.title} 대표 이미지` },
    svg("defs", {}, svg("linearGradient", { id: gid, gradientTransform: `rotate(${angle} .5 .5)` },
      svg("stop", { offset: "0", "stop-color": top }), svg("stop", { offset: "1", "stop-color": bottom }))),
    svg("rect", { width: 240, height: 150, fill: `url(#${gid})` }),
    blobs,
    svg("g", { stroke: "#fff", "stroke-opacity": ".06" },
      [1, 2, 3, 4, 5].map((i) => svg("path", { d: `M${i * 40} 0V150` })), [1, 2, 3].map((i) => svg("path", { d: `M0 ${i * 37.5}H240` }))),
    motif(v.data_type, rand),
    svg("g", { transform: "translate(150 26) scale(1.25)", fill: "none", stroke: "#fff", "stroke-width": "2.4",
      "stroke-linecap": "round", "stroke-linejoin": "round", opacity: ".95" }, icon.map((d) => svg("path", { d }))),
    svg("text", { x: 16, y: 26, fill: "#fff", "fill-opacity": ".6", "font-size": "11", "font-weight": "600" }, document.createTextNode(c.catalog_id)),
    keyword ? svg("text", { x: 16, y: 122, fill: "#fff", "font-size": "17", "font-weight": "800" }, document.createTextNode("#" + keyword)) : null,
    svg("text", { x: 16, y: 140, fill: "#fff", "fill-opacity": ".75", "font-size": "11.5", "font-weight": "600" }, document.createTextNode(label)),
  );
  return el;
}

// 엑셀 '대표 이미지' 칸에 파일이 있으면 그 이미지를, 없거나 열리지 않으면 자동 생성 그림을 쓴다.
function coverFor(c) {
  const box = document.createElement("div");
  box.className = "cover";
  const img = c.metadata && c.metadata.image;
  if (img) {
    const el = document.createElement("img");
    el.src = "/media/" + encodeURIComponent(img);
    el.alt = `${c.title} 대표 이미지`;
    el.addEventListener("error", () => { el.remove(); box.append(makeCover(c)); box.title = "대표 이미지를 열 수 없어 자동 생성 그림을 보여 줍니다"; });
    box.append(el);
  } else {
    box.append(makeCover(c));
    box.title = "분야·자료 유형으로 만든 그림(실제 데이터 아님)";
  }
  return box;
}
