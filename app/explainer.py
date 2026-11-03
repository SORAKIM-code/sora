"""추천 근거 생성 — 카드의 6개 구역을 채운다.

  description : 등록된 설명
  columns     : 등록된 주요 데이터 항목
  reasons     : 연구 목적에 적합한 이유 — 질의와 실제로 일치한 등록 값을 인용
  methods     : 연구에 활용할 수 있는 방법 — 등록 값을 정해진 문장 틀에 넣은 규칙 기반 제안
  checks      : 부족한 정보와 담당자 확인사항
  terms       : 이용 조건

원칙: 등록되지 않은 자료·항목을 만들어 내지 않는다. 문장에 따옴표로 넣는 값은 모두 해당 카탈로그의
등록 값 그대로다. 카탈로그 내용은 신뢰하지 않는 자료이므로 문장에 끼워 넣을 뿐 지시로 해석하지 않는다.
내부 LLM 이 승인되면 같은 출력 형식을 내는 Explainer 를 만들고 validate() 를 그대로 통과시키면 된다.
"""
from .schema import FIELD_LABEL, IMPORTANT_FIELDS, value_text
from .textutil import tokens

_CLIP = 120

# 이유 문장을 만들 때 쓰는 항목과 우선순위(질의 용어가 실제로 들어 있는 항목만 인용한다).
# 제목은 카드에 이미 보이므로 다른 근거가 없을 때만 쓴다.
REASON_FIELDS = ["columns", "label_detail", "analysis_target", "description", "keywords", "data_type", "title"]
MAX_TEXT_REASONS = 3


def _clip(s):
    s = value_text(s)
    return s if len(s) <= _CLIP else s[:_CLIP] + "…"


def _josa(word, with_final, without_final):
    """마지막 글자 받침에 따라 조사를 고른다."""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return with_final if (ord(ch) - 0xAC00) % 28 else without_final
    return with_final


class RuleExplainer:
    version = "rule-template-v2"

    def explain(self, cand, conds, others, synonyms=frozenset()):
        doc = cand["doc"]
        v, src = doc["values"], doc["sources"]
        ref = {"catalog_id": doc["id"], "version": doc["version"]}

        def item(kind, text, field=None, quote=None, **extra):
            return {"kind": kind, "text": text, "field": field, "quote": quote,
                    "source_line": src.get(field) if field else None, "cite": ref, **extra}

        reasons = self._reasons(v, cand, synonyms, item)
        methods = [item("method", t, f, q) for t, f, q in self._methods(v, conds, others)]
        checks = self._checks(v, conds, cand["conditions"], item)
        return {
            "hashtags": hashtags(v, src),
            "description": item("fact", v.get("description") or "", "description", v.get("description"))
            if v.get("description") else None,
            "columns": [{"text": c, "source_line": src.get("columns")} for c in (v.get("columns") or [])],
            "reasons": reasons, "methods": methods, "checks": checks,
            "missing": [{"field": k, "label": FIELD_LABEL[k]} for k in IMPORTANT_FIELDS if v.get(k) is None],
            "terms": {k: v.get(k) for k in ("access_level", "procedure", "place_restriction", "purpose_restriction")},
        }

    # ── 적합한 이유 ──
    def _reasons(self, v, cand, synonyms, item):
        out = []
        matched = cand["matched_fields"]
        cond_ok = {c["key"] for c in cand["conditions"] if c["status"] == "충족"}
        keys = [k for k in REASON_FIELDS if k in matched and v.get(k) is not None]
        keys = [k for k in keys if not (k == "data_type" and "data_type" in cond_ok)
                and not (k == "label_detail" and "label_available" in cond_ok)]
        if len(keys) > 1 and "title" in keys:
            keys.remove("title")
        for key in keys:
            if len(out) >= MAX_TEXT_REASONS:
                break
            terms = sorted(set(matched[key]))
            direct = [t for t in terms if t not in synonyms]
            via = [t for t in terms if t in synonyms]
            if key in ("columns", "keywords"):
                # 목록형은 실제로 용어가 들어 있는 원소만 인용한다.
                hits = [x for x in v[key] if set(tokens(x)) & set(terms)]
                if not hits:
                    continue
                quoted = ", ".join(f"'{_clip(x)}'" for x in hits[:3])
                head = "등록된 데이터 항목 " if key == "columns" else "등록된 주제어 "
                text = f"{head}{quoted}{_josa(hits[min(len(hits), 3) - 1], '이', '가')} 연구 목적과 관련됩니다"
                quote = hits[0]
            else:
                quote = v[key]
                text = f"등록된 {FIELD_LABEL[key]} '{_clip(quote)}'에 연구 목적과 같은 내용이 있습니다"
            words = []
            if direct:
                words.append("일치한 말: " + ", ".join(direct))
            if via:
                words.append("승인 용어사전 대응어: " + ", ".join(via))
            out.append(item("reason", f"{text} ({' / '.join(words)}).", key, quote))
        for c in cand["conditions"]:
            if c["status"] != "충족":
                continue
            if c["key"] == "label_available":
                detail = v.get("label_detail")
                text = (f"정답표시가 '있음'으로 등록되어 있어({_clip(detail)}) 예측·분류 연구의 조건에 맞습니다."
                        if detail else "정답표시가 '있음'으로 등록되어 있어 예측·분류 연구의 조건에 맞습니다.")
                out.append(item("reason", text, "label_available", v.get("label_available")))
            elif c["key"] == "period":
                out.append(item("reason", f"등록된 수집 기간 {c['actual']}이 요청 기간 {c['wanted']}을 포함합니다.",
                                "period_start", v.get("period_start")))
            elif c["key"] == "data_type":
                out.append(item("reason", f"자료 유형이 '{v['data_type']}'으로 등록되어 있어 요청한 분석 방식과 맞습니다.",
                                "data_type", v.get("data_type")))
        return out

    # ── 활용 방법 ──
    def _methods(self, v, conds, others):
        """(문장, 근거 항목, 인용 값). 문장 속 따옴표 값은 모두 등록 값이다."""
        out = []
        tasks = conds["tasks"]
        label = v.get("label_available") or ""
        unit = v.get("analysis_unit")
        unit_txt = f"'{unit}' 단위로 " if unit else ""
        if "예측" in tasks or "분류" in tasks:
            goal = "예측" if "예측" in tasks else "분류"
            if label.startswith("있음") and v.get("label_detail"):
                out.append((f"'{_clip(v['label_detail'])}'을(를) 정답표시로 두고 {unit_txt}{goal} 모델을 학습하는 방안을 검토할 수 있습니다.",
                            "label_detail", v["label_detail"]))
            elif label.startswith("있음"):
                out.append((f"등록된 정답표시를 이용해 {unit_txt}{goal} 모델을 학습하는 방안을 검토할 수 있습니다.",
                            "label_available", v["label_available"]))
            elif label.startswith("없음"):
                out.append(("정답표시가 '없음'으로 등록되어 있어 이 자료만으로 지도학습을 하기는 어렵습니다. "
                            "다른 자료의 정답표시와 연결하거나 설명변수로 쓰는 방안을 검토할 수 있습니다.",
                            "label_available", v["label_available"]))
            else:
                out.append(("정답표시 유무가 등록되어 있지 않아 예측·분류에 바로 쓸 수 있는지는 판단할 수 없습니다.",
                            "label_available", None))
        if "이상탐지" in tasks:
            if "시계열" in (v.get("data_type") or ""):
                cols = [c for c in (v.get("columns") or []) if "시각" not in c and "번호" not in c and "코드" not in c][:3]
                what = ", ".join(f"'{_clip(c)}'" for c in cols) if cols else "측정값"
                out.append((f"{what}의 시간에 따른 변화를 보고 평소 범위를 벗어나는 구간을 찾는 이상 탐지를 검토할 수 있습니다.",
                            "columns", cols[0] if cols else None))
            else:
                out.append((f"자료 유형이 '{v.get('data_type') or '미확인'}'이므로 실시간 이상 탐지보다는 사후 기록 분석에 가깝게 활용됩니다.",
                            "data_type", v.get("data_type")))
        if "관계분석" in tasks and v.get("columns"):
            cols = v["columns"][:3]
            out.append((f"{', '.join(repr_q(c) for c in cols)} 항목을 변수로 두고 다른 요인과의 관계를 분석할 수 있습니다.",
                        "columns", cols[0]))
        if ("최적화" in tasks or "추이분석" in tasks) and v.get("update_cycle"):
            out.append((f"'{v['update_cycle']}' 주기로 쌓인 기록의 추이를 먼저 살펴보는 현황 분석부터 시작할 수 있습니다.",
                        "update_cycle", v["update_cycle"]))
        if v.get("join_keys") and others:
            partners = [o["doc"]["id"] for o in others
                        if set(o["doc"]["values"].get("join_keys") or []) & set(v["join_keys"])]
            if partners:
                out.append((f"등록된 결합 식별자 '{_clip(v['join_keys'][0])}'이(가) 함께 추천된 {', '.join(partners)}에도 있어 "
                            "자료를 서로 연결해 분석하는 방안을 검토할 수 있습니다. 실제 연결 가능 여부는 확인되지 않았습니다.",
                            "join_keys", v["join_keys"][0]))
        if not out and v.get("analysis_target"):
            out.append((f"등록된 분석 대상 '{_clip(v['analysis_target'])}'에 대한 기초 현황 분석부터 검토할 수 있습니다.",
                        "analysis_target", v["analysis_target"]))
        return out

    # ── 부족한 정보와 담당자 확인사항 ──
    def _checks(self, v, conds, cond_items, item):
        owner = f"데이터 소관 부서({v.get('department') or '미확인'})"
        hub = "거점 운영부서"
        out = []
        missing = [FIELD_LABEL[k] for k in IMPORTANT_FIELDS if v.get(k) is None]
        if missing:
            out.append(item("missing", f"카탈로그에 등록되지 않은 정보: {', '.join(missing)}. 실제 값은 담당자에게 확인해야 합니다.",
                            confirmer=owner))
        for c in cond_items:
            if c["status"] == "부분" and c["key"] == "period":
                out.append(item("check", f"요청 기간({c['wanted']}) 중 일부만 수집되어 있습니다(등록 기간 {c['actual']}). 추가 기간 자료가 있나요?",
                                "period_start", confirmer=owner))
            elif c["status"] == "불충족" and c["key"] == "label_available":
                out.append(item("check", "정답표시가 '없음'으로 등록되어 있습니다. 연결할 수 있는 정답표시 자료가 있나요?",
                                "label_available", confirmer=owner))
        cols = " ".join(v.get("columns") or [])
        if "예측" in conds["tasks"] and v.get("columns") and "발생" not in cols:
            out.append(item("check", "등록된 항목에 사건(고장 등) 발생 시점이 따로 없습니다. 발생 시점과 기록 시점이 구분되어 있나요?",
                            "columns", confirmer=owner))
        if "이상탐지" in conds["tasks"] and "시계열" in (v.get("data_type") or "") and not v.get("unit"):
            out.append(item("check", "측정 단위와 주기가 등록되어 있지 않습니다. 측정 주기를 확인할 수 있나요?",
                            "unit", confirmer=owner))
        for k in v.get("join_keys") or []:
            out.append(item("check", f"결합 식별자 '{_clip(k)}'의 제공 가능 범위와 다른 자료와의 대응 관계를 확인해 주세요.",
                            "join_keys", k, confirmer=owner))
        if v.get("preprocessed") == "없음":
            out.append(item("check", "전처리 유무가 '없음'으로 등록되어 있습니다. 결측·이상값 정제나 비식별화를 연구자가 직접 해야 하는지 확인해 주세요.",
                            "preprocessed", v["preprocessed"], confirmer=owner))
        if v.get("structure") in ("반정형", "비정형"):
            out.append(item("check", f"데이터 구조가 '{v['structure']}'으로 등록되어 있습니다. 제공 형식(파일 형태·분량)과 분석 전 변환 방법을 확인해 주세요.",
                            "structure", v["structure"], confirmer=owner))
        if v.get("quality_status") is None and v.get("quality") is not None:
            out.append(item("check", f"품질 정보('{_clip(v['quality'])}')의 확인 상태가 등록되어 있지 않습니다.",
                            "quality", v["quality"], confirmer=owner))
        if v.get("purpose_restriction"):
            out.append(item("check", f"연구 목적이 사용 목적 제한('{_clip(v['purpose_restriction'])}')에 해당하는지 확인이 필요합니다.",
                            "purpose_restriction", v["purpose_restriction"], confirmer=hub))
        if v.get("place_restriction"):
            out.append(item("check", f"사용 장소 제한('{_clip(v['place_restriction'])}')에 맞는 분석 환경을 확인해 주세요.",
                            "place_restriction", v["place_restriction"], confirmer=hub))
        return out


HASHTAG_FIELDS = ["keywords", "domain", "data_type"]
HASHTAG_COUNT = 5


def hashtags(v, src):
    """등록된 주제어 → 분야 → 자료 유형 순으로 최대 5개. 등록 값이 모자라면 더 만들지 않는다."""
    out, seen = [], set()
    for key in HASHTAG_FIELDS:
        vals = v.get(key) or []
        for val in (vals if isinstance(vals, list) else [vals]):
            tag = "".join(ch for ch in val if ch.isalnum())
            if not tag or tag.lower() in seen or val == "공통":
                continue
            if key == "keywords" and val == v.get("domain"):
                continue  # 주제어에 분야 이름을 또 적은 경우 분야 태그 자리로 미룬다
            seen.add(tag.lower())
            out.append({"tag": "#" + tag, "value": val, "field": key, "source_line": src.get(key)})
            if len(out) == HASHTAG_COUNT:
                return out
    return out


def repr_q(s):
    return f"'{_clip(s)}'"


def validate(expl, allowed_refs):
    """설명에 들어간 모든 인용이 이번에 검색된 ID·버전인지 확인하고, 아니면 그 항목을 버린다."""
    dropped = 0
    for part in ("reasons", "methods", "checks"):
        kept = []
        for it in expl.get(part, []):
            c = it.get("cite") or {}
            if (c.get("catalog_id"), c.get("version")) in allowed_refs:
                kept.append(it)
            else:
                dropped += 1
        expl[part] = kept
    d = expl.get("description")
    if d and ((d.get("cite") or {}).get("catalog_id"), (d.get("cite") or {}).get("version")) not in allowed_refs:
        expl["description"] = None
        dropped += 1
    expl["dropped_citations"] = dropped
    return expl
