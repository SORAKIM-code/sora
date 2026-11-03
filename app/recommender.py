"""목적 분석과 추천 (PRD F1).

1) 연구 목적에서 조건(대상 분야·분석 목표·자료 유형·기간)을 규칙으로 추출한다.
2) 결과를 바꿀 정보가 빠졌을 때만 추가 질문을 한다.
3) 권한 내 인덱스에서 키워드·의미 검색 점수와 조건 일치도를 합쳐 순위를 정한다.
"""
import re

from .textutil import normalize, tokens

EXTRACTOR_VERSION = "rule-extractor-v1"

TASKS = {
    "예측": ["예측", "예지", "미리", "사전에", "forecast", "predict"],
    "이상탐지": ["이상 징후", "이상징후", "이상 탐지", "이상탐지", "탐지", "조기", "anomaly"],
    "분류": ["분류", "유형별", "classif"],
    "최적화": ["최적화", "효율", "절감", "줄이"],
    "관계분석": ["관계", "영향", "상관", "요인"],
    "추이분석": ["추이", "현황", "통계", "변화", "트렌드"],
}

DATA_HINTS = {
    "시계열": ["센서", "시계열", "진동", "측정값", "계측", "실시간"],
    "이력": ["이력", "정비 기록", "접수"],
    "집계": ["통계", "집계", "월별"],
}

STATUS_SCORE = {"충족": 1.0, "부분": 0.5, "미확인": 0.3, "불충족": 0.0}


def _year(s):
    m = re.match(r"(\d{4})", s or "")
    return int(m.group(1)) if m else None


def parse_period(norm, today_year):
    m = re.search(r"(20\d{2})\s*년?\s*(?:~|-|부터|에서)\s*(20\d{2})", norm)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    m = re.search(r"최근\s*(\d{1,2})\s*년", norm)
    if m:
        return (today_year - int(m.group(1)), today_year)
    m = re.search(r"(20\d{2})\s*년\s*(?:이후|부터)", norm)
    if m:
        return (int(m.group(1)), today_year)
    return None


class Recommender:
    def __init__(self, config, glossary, clarify_rules):
        self.cfg = config
        self.glossary = glossary
        self.rules = clarify_rules

    # ── 1. 조건 추출 ──
    def extract(self, query, form, answers, today_year):
        form = form or {}
        answers = answers or {}
        text = " ".join([query] + [str(form.get(k) or "") for k in ("target", "method", "period", "output")])
        norm = normalize(text)
        domains = self.glossary.domains_in(text)
        if answers.get("target"):
            domains = [answers["target"]]
        tasks = [t for t, kws in TASKS.items() if any(k in norm for k in kws)]
        hints = [h for h, kws in DATA_HINTS.items() if any(k in norm for k in kws)]
        add_terms = []
        for rule in self.rules["rules"]:
            val = answers.get(rule["id"])
            if val and isinstance(rule.get("options"), list):
                for opt in rule["options"]:
                    if opt["value"] == val:
                        add_terms += opt.get("add_terms", [])
                if rule["id"] == "data_hint":
                    hints = [val]
        return {
            "text": text,
            "domains": domains,
            "tasks": tasks,
            "data_hints": hints,
            "period": parse_period(norm, today_year),
            "need_label": any(t in ("예측", "분류") for t in tasks),
            "add_terms": add_terms,
            "output": (form.get("output") or "").strip() or None,
        }

    # ── 2. 추가 질문 ──
    def clarifications(self, conds, answers, visible_domains):
        out = []
        for rule in self.rules["rules"]:
            if rule["id"] in (answers or {}):
                continue
            w = rule.get("when", {})
            if w.get("task_any") and not set(w["task_any"]) & set(conds["tasks"]):
                continue
            if w.get("domain_any") and not set(w["domain_any"]) & set(conds["domains"]):
                continue
            missing = w.get("missing")
            if missing == "data_hint" and conds["data_hints"]:
                continue
            if missing == "domain" and conds["domains"]:
                continue
            options = rule["options"]
            if options == "visible_domains":
                # 권한 내 분야만 선택지로 보여 준다(권한 밖 분야 존재를 드러내지 않음).
                options = [{"value": d, "label": d} for d in visible_domains if d != "공통"]
            out.append({"id": rule["id"], "question": rule["question"], "options": options,
                        "allow_free_text": rule.get("allow_free_text", False)})
        return out

    # ── 3. 조건 일치도 ──
    def match_conditions(self, conds, values):
        items = []
        if conds["domains"]:
            dom = values.get("domain")
            st = "충족" if dom in conds["domains"] else ("부분" if dom == "공통" else "불충족")
            items.append({"key": "domain", "label": "대상 분야", "wanted": ", ".join(conds["domains"]),
                          "actual": dom, "status": st})
        if conds["data_hints"]:
            dt = values.get("data_type")
            st = "미확인" if not dt else ("충족" if any(h in dt for h in conds["data_hints"]) else "불충족")
            items.append({"key": "data_type", "label": "자료 유형", "wanted": ", ".join(conds["data_hints"]),
                          "actual": dt, "status": st})
        if conds["need_label"]:
            la = values.get("label_available")
            st = "미확인" if not la else ("충족" if la.startswith("있음") else "불충족")
            items.append({"key": "label_available", "label": "정답표시", "wanted": "필요(예측·분류)",
                          "actual": la, "status": st})
        if conds["period"]:
            a, b = conds["period"]
            s, e = _year(values.get("period_start")), _year(values.get("period_end"))
            if s is None or e is None:
                st = "미확인"
            elif s <= a and e >= b:
                st = "충족"
            elif e < a or s > b:
                st = "불충족"
            else:
                st = "부분"
            items.append({"key": "period", "label": "수집 기간", "wanted": f"{a}~{b}",
                          "actual": f"{values.get('period_start') or '미확인'}~{values.get('period_end') or '미확인'}",
                          "status": st})
        return items

    # ── 4. 순위 ──
    def rank(self, index, conds):
        qtoks = tokens(conds["text"]) + [t for term in conds["add_terms"] for t in tokens(term)]
        weighted = self.glossary.expand(qtoks, domain_term_weight=self.cfg["domain_term_weight"])
        if not weighted or not index.docs:
            return [], weighted
        w = self.cfg["weights"]
        sat = self.cfg["bm25"]["saturation"]
        kws = index.keyword(weighted)
        sems = index.semantic(weighted)
        results = []
        for doc, (kw_raw, matched), sem in zip(index.docs, kws, sems):
            if kw_raw <= 0 and sem < self.cfg["min_semantic_without_keyword"]:
                continue
            kw = kw_raw / (kw_raw + sat)
            cond_items = self.match_conditions(conds, doc["values"])
            if cond_items:
                cond = sum(STATUS_SCORE[c["status"]] for c in cond_items) / len(cond_items)
                # 내용 일치가 약한 자료가 분야만 맞아서 올라오지 않도록 조건 점수를 내용 일치도로 제한한다.
                text_rel = min(1.0, kw / self.cfg["condition_gate_keyword"])
                final = w["keyword"] * kw + w["semantic"] * sem + w["condition"] * cond * text_rel
            else:
                cond = None
                final = (w["keyword"] * kw + w["semantic"] * sem) / (w["keyword"] + w["semantic"])
            if conds["domains"] and doc["values"].get("domain") not in conds["domains"] + ["공통"]:
                final *= self.cfg["domain_mismatch_factor"]
            results.append({
                "doc": doc, "score": round(final, 4),
                "scores": {"keyword": round(kw, 4), "semantic": round(sem, 4),
                           "condition": None if cond is None else round(cond, 4)},
                "matched_fields": matched, "conditions": cond_items,
            })
        results.sort(key=lambda r: (-r["score"], r["doc"]["id"]))
        kept = [r for r in results if r["score"] >= self.cfg["abstain_threshold"]]
        return kept[: self.cfg["top_k"]], weighted

    def relevance_band(self, score):
        bands = self.cfg["relevance_bands"]
        return "높음" if score >= bands["high"] else ("보통" if score >= bands["medium"] else "낮음")
