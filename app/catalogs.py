"""카탈로그 등록·검수·버전·철회 (PRD F3).

상태: draft(검수 대기) → approved(검색 반영) → superseded(새 버전으로 대체) / withdrawn(철회)
검색에는 catalog_id 별 approved 버전 하나만 쓰인다.
"""
import json
import re

from .schema import (FIELD_KIND, FIELD_LABEL, FIELD_SCHEMA, LABEL_TO_KEY, REQUIRED_FOR_REVIEW,
                     ACCESS_LEVELS, clean_values, value_text)
from .textutil import injection_flags

ID_RE = re.compile(r"^CAT-[A-Z]{3}-\d{3}$")


class CatalogError(Exception):
    pass


def render_spec(values):
    """메타데이터 → '항목: 값' 형식 원문과 항목별 원문 행 번호."""
    lines = [f"[자료 명세서] {values.get('title') or ''}".strip()]
    sources = {}
    for key, label, _group, _kind in FIELD_SCHEMA:
        v = values.get(key)
        if v in (None, "", []):
            continue
        lines.append(f"{label}: {value_text(v)}")
        sources[key] = len(lines)
    return "\n".join(lines), sources


def parse_spec(text):
    """'항목: 값' 형식 문서에서 메타데이터 초안을 뽑는다. 알 수 없는 값은 비워 둔다(추정 금지)."""
    raw, sources, warnings = {}, {}, []
    for i, line in enumerate((text or "").splitlines(), 1):
        if ":" not in line:
            continue
        label, _, val = line.partition(":")
        key = LABEL_TO_KEY.get(label.strip())
        if not key:
            warnings.append(f"{i}행: 알 수 없는 항목 '{label.strip()[:30]}' — 무시함")
            continue
        raw[key] = val.strip()
        sources[key] = i
    values = clean_values(raw)
    sources = {k: v for k, v in sources.items() if values.get(k) is not None}
    return values, sources, warnings


def review_warnings(values):
    """검수자에게 보여 줄 경고. 지시문처럼 보이는 문구는 자료로만 다루되 검수 시 확인하게 한다."""
    out = []
    for key in REQUIRED_FOR_REVIEW:
        if values.get(key) in (None, []):
            out.append(f"필수 항목 '{FIELD_LABEL[key]}'이(가) 비어 있습니다.")
    if values.get("access_level") and values["access_level"] not in ACCESS_LEVELS:
        out.append(f"공개 범위는 {', '.join(ACCESS_LEVELS)} 중 하나여야 합니다.")
    for key, v in values.items():
        if v is not None and injection_flags(value_text(v)):
            out.append(f"'{FIELD_LABEL[key]}'에 지시문으로 보이는 문구가 있습니다. 자료로만 취급되며 실행되지 않지만 내용을 확인하세요.")
    return out


def _row(r):
    d = json.loads(r["data"])
    return {
        "id": r["catalog_id"], "version": r["version"], "status": r["status"],
        "values": d["values"], "sources": {k: int(v) for k, v in d.get("sources", {}).items()},
        "source_text": r["source_text"], "created_by": r["created_by"], "created_at": r["created_at"],
        "reviewed_by": r["reviewed_by"], "reviewed_at": r["reviewed_at"], "note": r["note"],
        "origin": d.get("origin"),
    }


class CatalogStore:
    def __init__(self, db, now):
        self.db = db
        self.now = now

    # ── 조회 ──
    def approved(self):
        return [_row(r) for r in self.db.all(
            "SELECT * FROM catalog_versions WHERE status='approved' ORDER BY catalog_id")]

    def approved_one(self, catalog_id):
        r = self.db.one("SELECT * FROM catalog_versions WHERE catalog_id=? AND status='approved'", (catalog_id,))
        return _row(r) if r else None

    def versions(self, catalog_id):
        return [_row(r) for r in self.db.all(
            "SELECT * FROM catalog_versions WHERE catalog_id=? ORDER BY version", (catalog_id,))]

    def version(self, catalog_id, version):
        r = self.db.one("SELECT * FROM catalog_versions WHERE catalog_id=? AND version=?", (catalog_id, version))
        return _row(r) if r else None

    def summary(self, department=None):
        rows = self.db.all("SELECT * FROM catalog_versions ORDER BY catalog_id, version")
        by_id = {}
        for r in map(_row, rows):
            if department and r["values"].get("department") != department:
                continue
            e = by_id.setdefault(r["id"], {"id": r["id"], "versions": []})
            e["versions"].append({"version": r["version"], "status": r["status"],
                                  "title": r["values"].get("title"), "reviewed_by": r["reviewed_by"]})
            e["title"] = r["values"].get("title")
            e["domain"] = r["values"].get("domain")
            e["access_level"] = r["values"].get("access_level")
            e["department"] = r["values"].get("department")
        for e in by_id.values():
            st = [v["status"] for v in e["versions"]]
            e["state"] = ("approved" if "approved" in st else "withdrawn" if "withdrawn" in st else "draft")
            e["has_draft"] = "draft" in st
        return list(by_id.values())

    # ── 변경 ──
    def _next_id(self, domain_code):
        rows = self.db.all("SELECT DISTINCT catalog_id FROM catalog_versions WHERE catalog_id LIKE ?",
                           (f"CAT-{domain_code}-%",))
        n = max([int(r["catalog_id"][-3:]) for r in rows] or [0]) + 1
        return f"CAT-{domain_code}-{n:03d}"

    def create_draft(self, values, sources, source_text, by, catalog_id=None, domain_code="NEW"):
        values = clean_values(values)
        if catalog_id:
            if not ID_RE.match(catalog_id):
                raise CatalogError("카탈로그 ID 형식은 CAT-XXX-000 입니다.")
            if self.versions(catalog_id):
                raise CatalogError("이미 있는 카탈로그 ID 입니다. 새 버전을 만드세요.")
        else:
            code = re.sub(r"[^A-Z]", "", (domain_code or "NEW").upper())[:3].ljust(3, "X")
            catalog_id = self._next_id(code)
        if not source_text:
            source_text, sources = render_spec(values)
        self._insert(catalog_id, 1, values, sources, source_text, by)
        return catalog_id, 1

    def _insert(self, catalog_id, version, values, sources, source_text, by, note=None, origin=None):
        data = json.dumps({"values": values, "sources": sources or {}, "origin": origin}, ensure_ascii=False)
        self.db.run("INSERT INTO catalog_versions(catalog_id,version,status,data,source_text,created_by,created_at,note)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (catalog_id, version, "draft", data, source_text, by, self.now(), note))

    def replace_draft(self, catalog_id, version, values, sources, source_text, note, origin=None):
        data = json.dumps({"values": values, "sources": sources or {}, "origin": origin}, ensure_ascii=False)
        self.db.run("UPDATE catalog_versions SET data=?, source_text=?, note=? WHERE catalog_id=? AND version=? AND status='draft'",
                    (data, source_text, note, catalog_id, version))

    def set_origin(self, catalog_id, version, origin):
        """값은 그대로이고 엑셀 위치(행·열)만 바뀐 경우."""
        cur = self.version(catalog_id, version)
        data = json.dumps({"values": cur["values"], "sources": cur["sources"], "origin": origin}, ensure_ascii=False)
        self.db.run("UPDATE catalog_versions SET data=? WHERE catalog_id=? AND version=?", (data, catalog_id, version))

    def mark_withdrawn(self, catalog_id, version, note):
        self.db.run("UPDATE catalog_versions SET status='withdrawn', note=? WHERE catalog_id=? AND version=?",
                    (note, catalog_id, version))

    def update_draft(self, catalog_id, version, values, by):
        cur = self.version(catalog_id, version)
        if not cur or cur["status"] != "draft":
            raise CatalogError("검수 대기(draft) 버전만 수정할 수 있습니다.")
        values = clean_values(values)
        source_text, sources = cur["source_text"], cur["sources"]
        changed = [k for k in values if values[k] != cur["values"].get(k)]
        for k in changed:
            # 운영자가 직접 고친 값은 원문 행과 더 이상 대응하지 않는다.
            sources.pop(k, None)
        data = json.dumps({"values": values, "sources": sources}, ensure_ascii=False)
        self.db.run("UPDATE catalog_versions SET data=?, note=? WHERE catalog_id=? AND version=?",
                    (data, f"{by} 수정: {', '.join(FIELD_LABEL[k] for k in changed) or '변경 없음'}",
                     catalog_id, version))
        return changed

    def new_version(self, catalog_id, by, from_version=None):
        vs = self.versions(catalog_id)
        if not vs:
            raise CatalogError("카탈로그가 없습니다.")
        if any(v["status"] == "draft" for v in vs):
            raise CatalogError("이미 검수 대기 버전이 있습니다.")
        base = next((v for v in vs if v["version"] == from_version), None) if from_version else \
            next((v for v in reversed(vs) if v["status"] in ("approved", "superseded", "withdrawn")), vs[-1])
        if not base:
            raise CatalogError("기준 버전이 없습니다.")
        nv = vs[-1]["version"] + 1
        self._insert(catalog_id, nv, base["values"], base["sources"], base["source_text"], by,
                     note=f"v{base['version']} 기반 새 버전")
        return nv

    def approve(self, catalog_id, version, by, note=None):
        cur = self.version(catalog_id, version)
        if not cur or cur["status"] != "draft":
            raise CatalogError("검수 대기(draft) 버전만 승인할 수 있습니다.")
        missing = [FIELD_LABEL[k] for k in REQUIRED_FOR_REVIEW if cur["values"].get(k) in (None, [])]
        if missing:
            raise CatalogError("필수 항목이 비어 있습니다: " + ", ".join(missing))
        if cur["values"]["access_level"] not in ACCESS_LEVELS:
            raise CatalogError("공개 범위 값이 올바르지 않습니다.")
        with self.db.lock:
            self.db.run("UPDATE catalog_versions SET status='superseded' WHERE catalog_id=? AND status='approved'",
                        (catalog_id,))
            self.db.run("UPDATE catalog_versions SET status='approved', reviewed_by=?, reviewed_at=?, note=?"
                        " WHERE catalog_id=? AND version=?", (by, self.now(), note, catalog_id, version))
            self.db.bump_generation()

    def withdraw(self, catalog_id, by, reason):
        cur = self.approved_one(catalog_id)
        if not cur:
            raise CatalogError("검색에 반영된(approved) 버전이 없습니다.")
        with self.db.lock:
            self.db.run("UPDATE catalog_versions SET status='withdrawn', note=? WHERE catalog_id=? AND version=?",
                        (f"{by} 철회: {reason}", catalog_id, cur["version"]))
            self.db.bump_generation()
        return cur["version"]
