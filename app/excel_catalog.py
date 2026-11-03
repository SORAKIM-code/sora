"""엑셀 카탈로그 목록 ↔ 카탈로그 메타데이터.

엑셀 한 행 = 카탈로그 하나. 첫 행은 열 이름이다. 열 이름은 표준 이름(FIELD_SCHEMA 표시명) 외에
자주 쓰는 다른 이름도 알아본다(HEADER_ALIASES). 값이 빈 칸이면 '미확인'으로 두고 추정하지 않는다.
"""
import os
import re
from datetime import date, timedelta

from .schema import ACCESS_LEVELS, FIELD_SCHEMA, clean_values, value_text
from .xlsx import col_letter, read_xlsx, write_xlsx

SHEET = "카탈로그"
GUIDE_SHEET = "작성 안내"
ID_HEADER = "카탈로그 ID"
STATUS_HEADER = "상태"
STATUS = {"검수완료": "approved", "검수대기": "draft", "철회": "withdrawn"}
STATUS_KO = {v: k for k, v in STATUS.items()}
ID_RE = re.compile(r"^[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-.]{0,39}$")
REQUIRED = ["title", "domain", "access_level"]
DATE_KEYS = {"period_start": "month", "period_end": "month", "last_checked": "day"}

HEADER_ALIASES = {
    "id": ["카탈로그id", "카탈로그번호", "id", "번호", "자료id", "자료번호", "관리번호"],
    "status": ["상태", "검수상태", "검수", "승인상태"],
    "title": ["제목", "카탈로그명", "자료명", "데이터명", "데이터셋명", "명칭"],
    "description": ["설명", "자료설명", "개요", "내용"],
    "department": ["소관부서", "부서", "관리부서", "보유부서"],
    "contact": ["담당자", "담당"],
    "last_checked": ["최종확인일", "확인일", "갱신일", "수정일"],
    "domain": ["분야", "분류", "대분류", "도메인"],
    "keywords": ["주제어", "키워드", "해시태그", "태그"],
    "image": ["대표이미지", "이미지", "사진", "대표사진", "썸네일", "그림"],
    "analysis_target": ["분석대상", "대상"],
    "columns": ["항목정의", "데이터항목", "주요데이터항목", "항목", "컬럼", "필드"],
    "unit": ["단위"],
    "format": ["형식", "파일형식", "포맷"],
    "period_start": ["수집기간(시작)", "수집시작", "시작", "수집기간시작", "시작일"],
    "period_end": ["수집기간(종료)", "수집종료", "종료", "수집기간종료", "종료일"],
    "update_cycle": ["갱신주기", "주기", "업데이트주기"],
    "data_type": ["자료유형", "데이터유형", "유형"],
    "analysis_unit": ["분석단위"],
    "label_available": ["정답표시유무", "정답표시", "라벨유무", "레이블유무"],
    "label_detail": ["정답표시내용", "라벨내용", "레이블내용"],
    "join_keys": ["결합식별자", "식별자", "연계키"],
    "quality": ["품질정보", "품질"],
    "quality_status": ["품질확인상태"],
    "access_level": ["공개범위", "공개구분", "공개여부", "등급"],
    "roles": ["열람가능역할", "역할"],
    "procedure": ["신청절차", "이용절차", "절차"],
    "place_restriction": ["사용장소제한", "장소제한"],
    "purpose_restriction": ["사용목적제한", "목적제한"],
    "source_doc": ["원문문서", "원문", "근거문서", "출처"],
}

GUIDE = {
    "id": ("필수", "카탈로그마다 겹치지 않는 번호. 영문·숫자·한글·-·_ 40자 이내", "CAT-VEH-001"),
    "status": ("필수", "검수완료 = 검색에 나옴 / 검수대기 = 나오지 않음 / 철회 = 나오지 않음. 비우면 검수대기", "검수완료"),
    "title": ("필수", "카탈로그 이름", "차량 정비 이력"),
    "domain": ("필수", "분야. 용어사전 분야(차량·항공기·함정·통신·보급·에너지·시설·기상·교육훈련·급식·보건·공통)와 같게 쓰면 조건 일치도에 반영", "차량"),
    "access_level": ("필수", "공개 / 거점승인 / 제한. '제한'은 시연 화면에 나오지 않음", "거점승인"),
    "keywords": ("권장", "해시태그로 보이는 주제어. 세미콜론(;)·쉼표·#으로 구분", "정비; 고장; 1종"),
    "columns": ("권장", "포함된 데이터 항목. 세미콜론(;) 또는 줄바꿈으로 구분", "정비일자: 정비 완료일; 고장유형코드"),
    "roles": ("선택", "비우면 researcher", "researcher"),
    "image": ("선택", "data/images 폴더에 넣은 그림 파일 이름(png·jpg·webp·gif). 비우면 분야·자료 유형으로 그림을 자동 생성", "veh001.png"),
    "label_available": ("선택", "있음 / 없음. 비우면 미확인", "있음"),
    "period_start": ("선택", "YYYY-MM", "2018-01"),
    "period_end": ("선택", "YYYY-MM", "2025-12"),
    "last_checked": ("선택", "YYYY-MM-DD", "2026-09-30"),
    "source_doc": ("선택", "비우면 '엑셀 파일명 N행'으로 기록", "(가상) 정비자료 명세서 v1"),
}


def _norm_header(h):
    return re.sub(r"[\s*·_\-]", "", (h or "")).lower()


_ALIAS = {}
for _key, _names in HEADER_ALIASES.items():
    for _n in _names:
        _ALIAS[_norm_header(_n)] = _key
for _key, _label, _g, _k in FIELD_SCHEMA:
    _ALIAS[_norm_header(_label)] = _key


def headers():
    return [ID_HEADER, STATUS_HEADER] + [label for _, label, _, _ in FIELD_SCHEMA]


def _excel_date(s, kind):
    """엑셀이 날짜로 바꿔 저장한 일련번호(예: 43101)를 되돌린다."""
    s = (s or "").strip()
    if re.fullmatch(r"\d+(\.\d+)?", s) and 20000 < float(s) < 80000:
        d = date(1899, 12, 30) + timedelta(days=int(float(s)))
        return d.strftime("%Y-%m") if kind == "month" else d.isoformat()
    m = re.fullmatch(r"(\d{4})[./년\s-]*(\d{1,2})(?:[./월\s-]*(\d{1,2}))?[일\s]*", s)
    if m:
        y, mo, dd = m.group(1), int(m.group(2)), m.group(3)
        if kind == "month" or not dd:
            return f"{y}-{mo:02d}"
        return f"{y}-{mo:02d}-{int(dd):02d}"
    return s


def _split_list(key, s):
    seps = r"[;\n,#]+" if key == "keywords" else r"[;\n]+"
    return [x.strip() for x in re.split(seps, s or "") if x.strip()]


def parse_workbook(path):
    """엑셀 → {"rows": [...], "errors": [...], "warnings": [...], "fatal": 문자열|None}"""
    fname = os.path.basename(path)
    sheets = read_xlsx(path)
    if not sheets:
        return {"rows": [], "errors": [], "warnings": [], "fatal": "시트가 없습니다."}
    sheet_name = SHEET if SHEET in sheets else next(iter(sheets))
    rows = sheets[sheet_name]
    header_at = next((i for i, (_, cells) in enumerate(rows)
                      if sum(1 for c in cells if _ALIAS.get(_norm_header(c)) in ("id", "title")) >= 2), None)
    if header_at is None:
        return {"rows": [], "errors": [], "warnings": [],
                "fatal": f"'{sheet_name}' 시트에서 '{ID_HEADER}'와 '제목' 열이 있는 머리글 행을 찾지 못했습니다."}
    hdr_row, hdr = rows[header_at]
    colmap, warnings, errors = {}, [], []
    for ci, h in enumerate(hdr):
        if not str(h).strip():
            continue
        key = _ALIAS.get(_norm_header(h))
        if key is None:
            warnings.append(f"{col_letter(ci)}열 '{h}': 알 수 없는 열이라 읽지 않습니다.")
        elif key in colmap:
            warnings.append(f"{col_letter(ci)}열 '{h}': '{hdr[colmap[key]]}' 열과 같은 항목이라 읽지 않습니다.")
        else:
            colmap[key] = ci
    missing = [n for k, n in (("id", ID_HEADER), ("title", "제목"), ("domain", "분야"), ("access_level", "공개 범위"))
               if k not in colmap]
    if missing:
        return {"rows": [], "errors": [], "warnings": warnings, "fatal": "필수 열이 없습니다: " + ", ".join(missing)}

    out, seen = [], {}
    for rnum, cells in rows[header_at + 1:]:
        get = lambda k: str(cells[colmap[k]]).strip() if k in colmap and colmap[k] < len(cells) else ""  # noqa: E731
        if not any(str(c).strip() for c in cells):
            continue
        cid = get("id")
        where = f"{rnum}행"
        if not cid:
            errors.append(f"{where}: 카탈로그 ID 가 비어 있어 건너뜁니다.")
            continue
        if not ID_RE.match(cid):
            errors.append(f"{where}: 카탈로그 ID '{cid[:40]}' 형식이 올바르지 않아 건너뜁니다.")
            continue
        if cid in seen:
            errors.append(f"{where}: 카탈로그 ID '{cid}'가 {seen[cid]}행과 겹쳐 건너뜁니다.")
            continue
        seen[cid] = rnum
        st_txt = get("status")
        status = STATUS.get(st_txt.replace(" ", ""))
        if status is None:
            if st_txt:
                warnings.append(f"{where}: 상태 '{st_txt}'를 알 수 없어 검수대기로 둡니다.")
            else:
                warnings.append(f"{where}: 상태가 비어 있어 검수대기로 둡니다(검색에 나오지 않음).")
            status = "draft"
        raw = {}
        for key, _label, _g, kind in FIELD_SCHEMA:
            v = get(key)
            if key in DATE_KEYS and v:
                v = _excel_date(v, DATE_KEYS[key])
            raw[key] = _split_list(key, v) if kind == "list" else v
        values = clean_values(raw)
        if not values.get("roles"):
            values["roles"] = ["researcher"]
        if not values.get("source_doc"):
            values["source_doc"] = f"{fname} {sheet_name} 시트 {rnum}행"
        lack = [n for k, n in (("title", "제목"), ("domain", "분야"), ("access_level", "공개 범위")) if not values.get(k)]
        if values.get("access_level") and values["access_level"] not in ACCESS_LEVELS:
            errors.append(f"{where}: 공개 범위 '{values['access_level']}'는 {'/'.join(ACCESS_LEVELS)} 중 하나여야 합니다. 건너뜁니다.")
            continue
        if lack and status == "approved":
            errors.append(f"{where}: 필수 값({', '.join(lack)})이 비어 검수완료로 올릴 수 없습니다. 검수대기로 둡니다.")
            status = "draft"
        out.append({
            "id": cid, "status": status, "values": values,
            "origin": {"file": fname, "sheet": sheet_name, "row": rnum,
                       "cols": {k: col_letter(ci) for k, ci in colmap.items()}},
        })
    return {"rows": out, "errors": errors, "warnings": warnings, "fatal": None, "sheet": sheet_name,
            "header_row": hdr_row}


def write_workbook(path, catalogs):
    """catalogs: [{"id", "status", "values"}] → 견본·내보내기 엑셀."""
    hdr = headers()
    keys = ["id", "status"] + [k for k, _, _, _ in FIELD_SCHEMA]
    rows = [hdr]
    for c in catalogs:
        rows.append([c["id"], STATUS_KO.get(c["status"], "검수대기")] +
                    [value_text(c["values"].get(k)) for k, _, _, _ in FIELD_SCHEMA])
    widths = [14, 10] + [{"title": 26, "description": 48, "columns": 52, "keywords": 26, "procedure": 34,
                          "department": 20, "analysis_target": 24}.get(k, 14) for k, _, _, _ in FIELD_SCHEMA]
    required = {"id", "status"} | set(REQUIRED)
    styles = {(0, i): 3 for i, k in enumerate(keys) if k in required}
    status_col = keys.index("status")
    level_col = keys.index("access_level")
    label_col = keys.index("label_available")
    guide = [["열 이름", "구분", "설명", "예시"]]
    for k, label in zip(keys, hdr):
        g = GUIDE.get(k, ("선택", "비우면 '미확인'으로 표시하고 추정하지 않음", ""))
        guide.append([label, g[0], g[1], g[2]])
    guide += [[], ["안내", "", "주황색 머리글은 필수 열입니다. 목록형 항목은 세미콜론(;)으로 구분합니다.", ""],
              ["안내", "", "파일을 바꾼 뒤 서비스를 다시 시작하면 자동으로 반영됩니다. 목록에서 지운 카탈로그는 철회됩니다.", ""],
              ["안내", "", "다른 열 이름도 알아봅니다(예: 카탈로그명·자료명 → 제목, 키워드·해시태그 → 주제어).", ""]]
    write_xlsx(path, [
        {"name": SHEET, "rows": rows, "widths": widths, "freeze": True, "styles": styles,
         "validations": [(status_col, list(STATUS)), (level_col, ACCESS_LEVELS), (label_col, ["있음", "없음"])]},
        {"name": GUIDE_SHEET, "rows": guide, "widths": [18, 8, 80, 30], "freeze": True},
    ])
