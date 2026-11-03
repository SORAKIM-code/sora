"""카탈로그 메타데이터 항목 정의 (PRD 9-1).

값이 None 이면 '미확인'으로 취급하며, 시스템은 이를 추정해 채우지 않는다.
"""

# (key, 표시명, 영역, 형태)
FIELD_SCHEMA = [
    ("title", "제목", "식별과 관리", "text"),
    ("description", "설명", "식별과 관리", "text"),
    ("department", "소관 부서", "식별과 관리", "text"),
    ("contact", "담당자", "식별과 관리", "text"),
    ("last_checked", "최종 확인일", "식별과 관리", "text"),
    ("domain", "분야", "식별과 관리", "text"),
    ("keywords", "주제어", "식별과 관리", "list"),
    ("image", "대표 이미지", "식별과 관리", "text"),
    ("analysis_target", "분석 대상", "데이터 내용", "text"),
    ("columns", "항목 정의", "데이터 내용", "list"),
    ("unit", "단위", "데이터 내용", "text"),
    ("format", "형식", "데이터 내용", "text"),
    ("period_start", "수집 기간(시작)", "데이터 내용", "text"),
    ("period_end", "수집 기간(종료)", "데이터 내용", "text"),
    ("update_cycle", "갱신 주기", "데이터 내용", "text"),
    ("data_type", "자료 유형", "데이터 내용", "text"),
    ("structure", "데이터 구조", "데이터 내용", "text"),
    ("preprocessed", "전처리 유무", "데이터 내용", "text"),
    ("preprocess_detail", "전처리 내용", "데이터 내용", "text"),
    ("size", "데이터 용량", "데이터 내용", "text"),
    ("analysis_unit", "분석 단위", "연구 적합성", "text"),
    ("label_available", "정답표시 유무", "연구 적합성", "text"),
    ("label_detail", "정답표시 내용", "연구 적합성", "text"),
    ("join_keys", "결합 식별자", "연구 적합성", "list"),
    ("quality", "품질 정보", "연구 적합성", "text"),
    ("quality_status", "품질 확인 상태", "연구 적합성", "text"),
    ("access_level", "공개 범위", "이용 조건", "text"),
    ("roles", "열람 가능 역할", "이용 조건", "list"),
    ("procedure", "신청 절차", "이용 조건", "text"),
    ("place_restriction", "사용 장소 제한", "이용 조건", "text"),
    ("purpose_restriction", "사용 목적 제한", "이용 조건", "text"),
    ("source_doc", "원문 문서", "근거 추적", "text"),
]

FIELD_KEYS = [f[0] for f in FIELD_SCHEMA]
FIELD_LABEL = {f[0]: f[1] for f in FIELD_SCHEMA}
FIELD_KIND = {f[0]: f[3] for f in FIELD_SCHEMA}
LABEL_TO_KEY = {f[1]: f[0] for f in FIELD_SCHEMA}

ACCESS_LEVELS = ["공개", "거점승인", "제한"]
ROLES = ["researcher", "operator", "data_owner", "admin"]

# 값을 정해진 선택지 중 하나로 받는 항목. 흔한 다른 표기는 표준 값으로 바꾼다.
CHOICES = {
    "structure": ["정형", "반정형", "비정형"],
    "preprocessed": ["있음", "없음"],
    "label_available": ["있음", "없음"],
}
_YES = ["유", "예", "o", "y", "yes", "완료", "실시", "적용"]
_NO = ["무", "아니오", "x", "n", "no", "미실시", "미적용"]
CHOICE_ALIASES = {
    "structure": {**{s + "데이터": s for s in CHOICES["structure"]}, **{s + "자료": s for s in CHOICES["structure"]}},
    "preprocessed": {**{a: "있음" for a in _YES}, **{a: "없음" for a in _NO}},
}


def normalize_choice(key, v):
    """선택지 항목의 값을 표준 값으로. 알 수 없는 값은 그대로 돌려준다(호출한 쪽이 경고)."""
    if v is None or key not in CHOICES:
        return v
    t = str(v).replace(" ", "").lower()
    for c in CHOICES[key]:
        if t == c:
            return c
    return CHOICE_ALIASES.get(key, {}).get(t, v)

# 검수 승인 전에 반드시 채워져야 하는 항목
REQUIRED_FOR_REVIEW = ["title", "domain", "access_level", "roles", "source_doc"]

# 검색에 쓰는 항목과 가중치
SEARCH_FIELDS = [
    ("title", 3.0),
    ("keywords", 2.0),
    ("domain", 1.5),
    ("analysis_target", 1.5),
    ("description", 1.0),
    ("columns", 1.0),
    ("label_detail", 1.0),
    ("data_type", 1.0),
    ("structure", 0.5),
    ("analysis_unit", 0.5),
]

# 연구 판단에 중요해서, 비어 있으면 '부족한 정보'로 표시하는 항목
IMPORTANT_FIELDS = [
    "analysis_target", "columns", "period_start", "period_end", "update_cycle",
    "data_type", "structure", "preprocessed", "size", "analysis_unit", "label_available", "quality", "quality_status",
]

# 역할별 권한. 서버의 모든 관리 API는 이 표로 검사한다.
CAPABILITIES = {
    "researcher": {"search"},
    "data_owner": {"catalog_view", "catalog_edit", "catalog_review"},
    "operator": {"catalog_view", "catalog_withdraw", "grant_manage", "log_view", "report_manage"},
    "admin": {"catalog_view", "catalog_edit", "catalog_review", "catalog_withdraw",
              "grant_manage", "log_view", "log_raw", "report_manage", "purge", "catalog_excel"},
}


def empty_values():
    return {k: None for k in FIELD_KEYS}


def clean_values(raw):
    """입력값을 스키마에 맞춰 정리한다. 빈 값·'미확인'은 None 으로 둔다."""
    out = empty_values()
    for key in FIELD_KEYS:
        v = (raw or {}).get(key)
        if v is None:
            continue
        if FIELD_KIND[key] == "list":
            if isinstance(v, str):
                v = [x.strip() for x in v.split(";")]
            v = [str(x).strip() for x in v if str(x).strip() and str(x).strip() != "미확인"]
            out[key] = v or None
        else:
            v = str(v).strip()
            out[key] = None if v in ("", "미확인", "-") else normalize_choice(key, v)
    return out


def value_text(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(v)
    return str(v)
