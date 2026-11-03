"""서비스 계층: 인증·권한·카탈로그·검색·설명·로그를 묶는다.

웹 계층(server.py)은 이 클래스의 메서드만 부르고, 모든 권한 검사는 여기서 서버 측으로 한다.
"""
import copy
import hashlib
import json
import os
import secrets
from collections import OrderedDict
from datetime import date, datetime, timedelta

from . import explainer as explainer_mod
from .audit import AuditLog
from .catalogs import CatalogError, CatalogStore, parse_spec, render_spec, review_warnings
from .db import DB
from .glossary import Glossary
from .policy import Policy, hash_password, verify_password
from .recommender import EXTRACTOR_VERSION, Recommender
from .schema import ACCESS_LEVELS, CAPABILITIES, FIELD_KEYS, FIELD_SCHEMA, clean_values
from .search import INDEX_VERSION, SearchIndex, SemanticEncoder
from .textutil import injection_flags, normalize

ABSTAIN_MESSAGE = ("열람 권한 범위 안에서 연구 목적에 맞는 카탈로그를 확인할 수 없습니다. "
                   "연구 목적을 더 구체적으로 적어 다시 시도하거나 거점 담당자와 상담하세요.")
SCORE_NOTICE = "관련도는 연구 목적과 카탈로그 기재 내용의 일치 정도이며, 연구 성공이나 승인 가능성을 뜻하지 않습니다."


class ServiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Service:
    def __init__(self, base_dir, db_path=None, clock=None, config_overrides=None):
        self.base_dir = base_dir
        self.cfg = _load_json(os.path.join(base_dir, "config.json"))
        self.cfg.update(config_overrides or {})
        data_dir = os.path.join(base_dir, "data")
        db_path = db_path or os.path.join(base_dir, self.cfg["db_path"])
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._clock = clock or datetime.now
        self.db = DB(db_path)
        self.glossary = Glossary(_load_json(os.path.join(data_dir, "glossary.json")))
        self.clarify_rules = _load_json(os.path.join(data_dir, "clarify_rules.json"))
        self.policy = Policy(self.db)
        self.store = CatalogStore(self.db, self.now)
        self.audit = AuditLog(self.db, self.now)
        self.recommender = Recommender(self.cfg, self.glossary, self.clarify_rules)
        self.explainer = explainer_mod.RuleExplainer()
        self._index_cache = OrderedDict()
        self._result_cache = OrderedDict()
        if not self.db.one("SELECT id FROM users LIMIT 1"):
            self._seed(data_dir)

    # ── 공통 ──
    def now(self):
        return self._clock().isoformat(timespec="seconds")

    def today(self):
        return self._clock().date().isoformat()

    def model_versions(self):
        return {"index": INDEX_VERSION, "semantic": SemanticEncoder.version,
                "extractor": EXTRACTOR_VERSION, "explainer": self.explainer.version,
                "glossary": self.glossary.version, "clarify_rules": self.clarify_rules.get("version"),
                "weights": self.cfg.get("weights_version"), "catalog_generation": self.db.generation()}

    def _invalidate(self):
        self._index_cache.clear()
        self._result_cache.clear()

    # ── 초기 자료 ──
    def _seed(self, data_dir):
        for u in _load_json(os.path.join(data_dir, "users.json"))["users"]:
            # 비밀번호가 없는 계정(시연 방문자)은 로그인할 수 없도록 임의 값으로 막는다.
            salt, h = hash_password(u.get("password") or secrets.token_urlsafe(32))
            self.db.run("INSERT INTO users(id,name,org,role,department,pw_salt,pw_hash) VALUES(?,?,?,?,?,?,?)",
                        (u["id"], u["name"], u["org"], u["role"], u.get("department"), salt, h))
        for g in _load_json(os.path.join(data_dir, "grants.json"))["grants"]:
            self.db.run("INSERT INTO grants(subject_type,subject_id,purpose,levels,domains,valid_from,valid_to,created_by,created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (g["subject_type"], g["subject_id"], g["purpose"], json.dumps(g["levels"], ensure_ascii=False),
                         json.dumps(g["domains"], ensure_ascii=False), g["valid_from"], g["valid_to"], "seed", self.now()))
        cat = _load_json(os.path.join(data_dir, "catalogs.json"))
        defaults = cat.get("defaults", {})
        dept = cat.get("departments", {})
        for c in cat["catalogs"]:
            raw = dict(defaults)
            raw["department"] = dept.get(c.get("domain"), defaults.get("department"))
            raw.update({k: v for k, v in c.items() if k in FIELD_KEYS})
            raw["source_doc"] = c.get("source_doc") or f"(가상) {c['title']} 자료 명세서 v1"
            values = clean_values(raw)
            text, sources = render_spec(values)
            self.store._insert(c["id"], 1, values, sources, text, "seed", note="초기 등록(가상 자료)")
            status = c.get("status", "approved")
            if status in ("approved", "withdrawn"):
                self.store.approve(c["id"], 1, "seed-reviewer", note="초기 검수(가상 자료)")
            if status == "withdrawn":
                self.store.withdraw(c["id"], "seed", c.get("withdraw_reason", "초기 자료 철회"))

    # ── 인증 ──
    @staticmethod
    def _th(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def login(self, username, password):
        username = (username or "").strip()[:64]
        fail = self.db.one("SELECT * FROM login_failures WHERE username=?", (username,))
        if fail and fail["count"] >= self.cfg["login_max_failures"]:
            until = datetime.fromisoformat(fail["last_at"]) + timedelta(minutes=self.cfg["login_lock_minutes"])
            if self._clock() < until:
                raise ServiceError(429, "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.")
        u = self.db.one("SELECT * FROM users WHERE id=? AND active=1", (username,))
        if not u or not verify_password(password or "", u["pw_salt"], u["pw_hash"]):
            cnt = (fail["count"] if fail else 0) + 1
            self.db.run("INSERT INTO login_failures(username,count,last_at) VALUES(?,?,?) ON CONFLICT(username)"
                        " DO UPDATE SET count=excluded.count, last_at=excluded.last_at", (username, cnt, self.now()))
            self.audit.write("login_fail", user_id=username, outcome="deny")
            raise ServiceError(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        self.db.run("DELETE FROM login_failures WHERE username=?", (username,))
        token = secrets.token_urlsafe(32)
        purposes = self.policy.purposes(u, self.today()) if u["role"] == "researcher" else []
        purpose = purposes[0]["purpose"] if len(purposes) == 1 else None
        exp = (self._clock() + timedelta(minutes=self.cfg["session_ttl_minutes"])).isoformat(timespec="seconds")
        self.db.run("INSERT INTO sessions(token_hash,user_id,purpose,created_at,expires_at) VALUES(?,?,?,?,?)",
                    (self._th(token), u["id"], purpose, self.now(), exp))
        self.audit.write("login", user_id=u["id"], purpose=purpose, outcome="allow")
        return token

    def session(self, token):
        if not token:
            raise ServiceError(401, "로그인이 필요합니다.")
        s = self.db.one("SELECT * FROM sessions WHERE token_hash=?", (self._th(token),))
        if not s or s["expires_at"] < self.now():
            raise ServiceError(401, "로그인이 필요합니다.")
        u = self.db.one("SELECT * FROM users WHERE id=? AND active=1", (s["user_id"],))
        if not u:
            raise ServiceError(401, "로그인이 필요합니다.")
        return {"token_hash": s["token_hash"], "user": u, "purpose": s["purpose"]}

    def logout(self, sess):
        self.db.run("DELETE FROM sessions WHERE token_hash=?", (sess["token_hash"],))

    def set_purpose(self, sess, purpose):
        if purpose not in [p["purpose"] for p in self.policy.purposes(sess["user"], self.today())]:
            raise ServiceError(403, "유효한 열람 권한이 없는 목적입니다.")
        self.db.run("UPDATE sessions SET purpose=? WHERE token_hash=?", (purpose, sess["token_hash"]))
        sess["purpose"] = purpose

    def me(self, sess):
        u = sess["user"]
        out = {"id": u["id"], "name": u["name"], "org": u["org"], "role": u["role"],
               "department": u["department"], "capabilities": sorted(CAPABILITIES.get(u["role"], [])),
               "purpose": sess["purpose"], "purposes": [], "visible_count": 0, "today": self.today()}
        if u["role"] == "researcher":
            for p in self.policy.purposes(u, self.today()):
                out["purposes"].append({"purpose": p["purpose"], "grants": [
                    {"id": g["id"], "via": "개인" if g["subject_type"] == "user" else f"기관({g['subject_id']})",
                     "levels": g["levels"], "domains": g["domains"], "valid_from": g["valid_from"],
                     "valid_to": g["valid_to"]} for g in p["grants"]]})
            inactive = [g for g in self.policy.grants_for(u, self.today(), include_inactive=True) if not g["active"]]
            out["inactive_grants"] = [{"purpose": g["purpose"], "valid_to": g["valid_to"],
                                       "reason": "회수됨" if g["revoked_at"] else "유효기간 아님"} for g in inactive]
            if sess["purpose"]:
                out["visible_count"] = len(self._visible_docs(u, sess["purpose"])[0])
        return out

    # ── 시연 방문자 (로그인 없이 쓰는 첫 버전 흐름) ──
    def demo_session(self):
        """고정된 시연 방문자 범위(공개·거점승인, '제한' 제외)의 서버 측 세션. 권한 검사는 그대로 거친다."""
        u = self.db.one("SELECT * FROM users WHERE id=? AND active=1", (self.cfg["demo_user"],))
        if not u:
            raise ServiceError(503, "시연 방문자 설정이 없습니다. var/ 폴더를 지우고 다시 시작하세요.")
        return {"token_hash": None, "user": u, "purpose": self.cfg["demo_purpose"]}

    def engine_info(self):
        rule = self.explainer.version.startswith("rule")
        return {
            "type": "rule" if rule else "model",
            "label": "정해진 규칙으로 추천을 계산합니다 (AI 미연결)" if rule else "AI가 추천 근거 문장을 생성합니다",
            "detail": ("연구 목적의 낱말과 카탈로그에 등록된 제목·설명·항목을 비교해 점수를 매기고, "
                       "등록된 값만 정해진 문장 틀에 넣어 근거를 보여 줍니다."),
            "version": self.explainer.version,
        }

    def public_info(self):
        examples = _load_json(os.path.join(self.base_dir, "data", "examples.json"))["examples"]
        docs, _ = self._visible_docs(self.demo_session()["user"], self.cfg["demo_purpose"])
        return {"examples": examples, "catalog_count": len(docs), "engine": self.engine_info(),
                "max_query_chars": self.cfg["max_query_chars"], "schema": FIELD_SCHEMA,
                "retention_days": self.cfg["raw_query_retention_days"]}

    def require(self, sess, cap):
        if cap not in CAPABILITIES.get(sess["user"]["role"], set()):
            raise ServiceError(403, "이 기능을 사용할 권한이 없습니다.")

    # ── 권한 내 문서와 인덱스 ──
    def _visible_docs(self, user, purpose):
        today = self.today()
        grants = self.policy.grants_for(user, today, purpose)
        docs = []
        for d in self.store.approved():
            gid = self.policy.visible(user, purpose, d["values"], today, grants)
            if gid is not None:
                d["grant_id"] = gid
                docs.append(d)
        return docs, grants

    def _index(self, docs):
        key = (self.db.generation(), tuple((d["id"], d["version"]) for d in docs))
        idx = self._index_cache.get(key)
        if idx is None:
            b = self.cfg["bm25"]
            idx = SearchIndex(docs, k1=b["k1"], b=b["b"])
            self._index_cache[key] = idx
            while len(self._index_cache) > 32:
                self._index_cache.popitem(last=False)
        return idx

    def _search_session(self, sess):
        self.require(sess, "search")
        if not sess["purpose"]:
            raise ServiceError(409, "연구 목적(열람 권한)을 먼저 선택하세요.")
        return sess["user"], sess["purpose"]

    # ── F1/F2 추천 ──
    def recommend(self, sess, payload):
        user, purpose = self._search_session(sess)
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ServiceError(400, "연구 목적을 입력하세요.")
        if len(query) > self.cfg["max_query_chars"]:
            raise ServiceError(400, f"연구 목적은 {self.cfg['max_query_chars']}자 이내로 입력하세요.")
        form = {k: str(payload.get(k) or "").strip()[:200] for k in ("target", "method", "period", "output")}
        rule_ids = {r["id"] for r in self.clarify_rules["rules"]}
        answers = {k: str(v)[:50] for k, v in (payload.get("answers") or {}).items() if k in rule_ids and v}
        skip = bool(payload.get("skip_clarify"))
        flags = ["injection_suspected"] if injection_flags(" ".join([query] + list(form.values()))) else []

        docs, grants = self._visible_docs(user, purpose)
        today = self.today()
        conds = self.recommender.extract(query, form, answers, int(today[:4]))
        public_conds = {k: conds[k] for k in ("domains", "tasks", "data_hints", "period", "need_label", "output")}
        permission = {"decision": "allow", "grant_ids": [g["id"] for g in grants], "visible_count": len(docs)}

        if not skip:
            visible_domains = sorted({d["values"]["domain"] for d in docs if d["values"].get("domain")})
            qs = self.recommender.clarifications(conds, answers, visible_domains)
            if qs:
                qid = self.audit.write("clarify", user["id"], purpose, query, [], permission,
                                       self.model_versions(), "clarify", flags)
                return {"status": "clarify", "query_id": qid, "questions": qs, "conditions": public_conds}

        ckey = json.dumps([user["id"], purpose, today, self.db.generation(), normalize(query), form, answers, skip],
                          ensure_ascii=False, sort_keys=True)
        cached = self._result_cache.get(ckey)
        if cached is not None:
            candidates = copy.deepcopy(cached)
            flags.append("cache_hit")
        else:
            candidates = self._build_candidates(docs, conds)
            self._result_cache[ckey] = copy.deepcopy(candidates)
            while len(self._result_cache) > self.cfg["cache_size"]:
                self._result_cache.popitem(last=False)

        # 응답 반환 직전 권한·버전 재확인 (캐시 결과 포함)
        final = []
        for c in candidates:
            fresh = self.store.approved_one(c["catalog_id"])
            if fresh and fresh["version"] == c["version"] and \
                    self.policy.visible(user, purpose, fresh["values"], today) is not None:
                final.append(c)
            else:
                flags.append("recheck_dropped")
        status = "ok" if final else "abstain"
        qid = self.audit.write(
            "recommend", user["id"], purpose, query,
            [{"catalog_id": c["catalog_id"], "version": c["version"], "score": c["score"]} for c in final],
            permission, self.model_versions(), status, flags)
        labels = []
        for c in final:
            for item in c["conditions"]:
                if item["label"] not in labels:
                    labels.append(item["label"])
        return {
            "status": status, "query_id": qid, "conditions": public_conds, "candidates": final,
            "comparison": {"columns": labels, "rows": [
                {"catalog_id": c["catalog_id"], "title": c["title"],
                 "cells": {i["label"]: {"status": i["status"], "actual": i["actual"]} for i in c["conditions"]},
                 "join_keys": c["metadata"].get("join_keys")} for c in final]},
            "message": ABSTAIN_MESSAGE if status == "abstain" else None,
            "notice": SCORE_NOTICE,
            "engine": self.engine_info(),
            "model": self.model_versions(),
        }

    def _build_candidates(self, docs, conds):
        ranked, weighted = self.recommender.rank(self._index(docs), conds)
        synonyms = {t for t, w in weighted.items() if w < 1}
        refs = {(r["doc"]["id"], r["doc"]["version"]) for r in ranked}
        out = []
        for r in ranked:
            d = r["doc"]
            expl, err = None, None
            try:
                others = [o for o in ranked if o is not r]
                expl = explainer_mod.validate(self.explainer.explain(r, conds, others, synonyms), refs)
            except Exception:  # 설명이 실패해도 후보와 원문 메타데이터는 보여 준다(PRD F2)
                err = "추천 근거를 만들지 못했습니다. 아래 등록 정보를 직접 확인하세요."
            v = d["values"]
            out.append({
                "catalog_id": d["id"], "version": d["version"], "title": v.get("title"), "domain": v.get("domain"),
                "score": r["score"], "relevance": self.recommender.relevance_band(r["score"]),
                "scores": r["scores"], "conditions": r["conditions"],
                "explanation": expl, "explanation_error": err,
                "availability": {
                    "catalog": "열람 가능(카탈로그 메타데이터)",
                    "raw_data": "원본 이용은 별도 활용 신청·승인 필요",
                    "approval_status": "미신청 — 이 서비스는 승인을 대신하지 않습니다",
                    "access_level": v.get("access_level"),
                    "procedure": v.get("procedure"),
                    "confirmer": f"데이터 소관 부서({v.get('department') or '미확인'}) · 거점 운영부서",
                    "reviewed_by": d["reviewed_by"], "reviewed_at": d["reviewed_at"],
                    "last_checked": v.get("last_checked"),
                },
                "metadata": v, "sources": d["sources"],
            })
        return out

    def suggest(self, sess, q):
        user, purpose = self._search_session(sess)
        q = normalize(q).strip()
        if not q:
            return []
        docs, _ = self._visible_docs(user, purpose)
        seen, out = set(), []
        for d in docs:
            for term in [d["values"].get("title") or ""] + (d["values"].get("keywords") or []):
                if q in normalize(term) and term not in seen:
                    seen.add(term)
                    out.append(term)
        return sorted(out, key=lambda t: (not normalize(t).startswith(q), len(t)))[:8]

    def catalog_detail(self, sess, catalog_id):
        user, purpose = self._search_session(sess)
        d = self.store.approved_one(str(catalog_id))
        gid = self.policy.visible(user, purpose, d["values"], self.today()) if d else None
        if gid is None:
            # 없는 자료와 권한 밖 자료를 같은 응답으로 돌려 존재 여부를 드러내지 않는다.
            self.audit.write("view_detail", user["id"], purpose, None, [{"catalog_id": str(catalog_id)[:40]}],
                             {"decision": "deny"}, self.model_versions(), "deny")
            raise ServiceError(404, "카탈로그를 찾을 수 없습니다.")
        self.audit.write("view_detail", user["id"], purpose, None,
                         [{"catalog_id": d["id"], "version": d["version"]}],
                         {"decision": "allow", "grant_ids": [gid]}, self.model_versions(), "allow")
        return {"catalog_id": d["id"], "version": d["version"], "values": d["values"], "sources": d["sources"],
                "source_text": d["source_text"], "reviewed_by": d["reviewed_by"], "reviewed_at": d["reviewed_at"],
                "approval_status": "검수완료", "schema": FIELD_SCHEMA}

    def report(self, sess, payload):
        user, purpose = self._search_session(sess)
        cid = str(payload.get("catalog_id") or "")
        d = self.store.approved_one(cid)
        if not d or self.policy.visible(user, purpose, d["values"], self.today()) is None:
            raise ServiceError(404, "카탈로그를 찾을 수 없습니다.")
        field = str(payload.get("field") or "general")
        if field not in FIELD_KEYS and field not in ("general", "suggestion", "check"):
            raise ServiceError(400, "알 수 없는 항목입니다.")
        msg = str(payload.get("message") or "").strip()
        if not msg or len(msg) > 1000:
            raise ServiceError(400, "신고 내용은 1~1000자로 입력하세요.")
        rid = self.db.run("INSERT INTO reports(ts,user_id,catalog_id,version,field,message) VALUES(?,?,?,?,?,?)",
                          (self.now(), user["id"], d["id"], d["version"], field, msg))
        self.audit.write("report", user["id"], purpose, None, [{"catalog_id": d["id"], "version": d["version"],
                                                                "field": field}], {"decision": "allow"},
                         self.model_versions(), "open")
        return {"report_id": rid}

    # ── F3 카탈로그 관리 ──
    def _dept_guard(self, sess, values):
        u = sess["user"]
        if u["role"] == "data_owner" and (values or {}).get("department") != u["department"]:
            raise ServiceError(403, "소관 부서의 카탈로그만 다룰 수 있습니다.")

    def admin_catalogs(self, sess):
        self.require(sess, "catalog_view")
        u = sess["user"]
        return self.store.summary(u["department"] if u["role"] == "data_owner" else None)

    def admin_catalog(self, sess, catalog_id):
        self.require(sess, "catalog_view")
        vs = self.store.versions(catalog_id)
        if not vs:
            raise ServiceError(404, "카탈로그를 찾을 수 없습니다.")
        self._dept_guard(sess, vs[-1]["values"])
        for v in vs:
            v["warnings"] = review_warnings(v["values"])
        return {"catalog_id": catalog_id, "versions": vs, "schema": FIELD_SCHEMA, "access_levels": ACCESS_LEVELS}

    def extract(self, sess, text):
        self.require(sess, "catalog_edit")
        if len(text or "") > 20000:
            raise ServiceError(400, "원문은 20,000자 이내로 붙여 넣으세요.")
        values, sources, warnings = parse_spec(text)
        return {"values": values, "sources": sources, "warnings": warnings + review_warnings(values)}

    def create_catalog(self, sess, payload):
        self.require(sess, "catalog_edit")
        text = payload.get("text")
        if text:
            values, sources, _ = parse_spec(text)
        else:
            values, sources = clean_values(payload.get("values")), None
        if sess["user"]["role"] == "data_owner" and not values.get("department"):
            values["department"] = sess["user"]["department"]
        self._dept_guard(sess, values)
        try:
            cid, ver = self.store.create_draft(values, sources, text, sess["user"]["id"],
                                               catalog_id=payload.get("catalog_id") or None,
                                               domain_code=payload.get("domain_code") or "NEW")
        except CatalogError as e:
            raise ServiceError(400, str(e))
        self.audit.write("catalog_create", sess["user"]["id"], evidence=[{"catalog_id": cid, "version": ver}],
                         outcome="draft")
        return {"catalog_id": cid, "version": ver}

    def _catalog_op(self, sess, cap, catalog_id, fn, event, **evidence):
        self.require(sess, cap)
        vs = self.store.versions(catalog_id)
        if not vs:
            raise ServiceError(404, "카탈로그를 찾을 수 없습니다.")
        self._dept_guard(sess, vs[-1]["values"])
        try:
            result = fn()
        except CatalogError as e:
            raise ServiceError(400, str(e))
        self._invalidate()
        self.audit.write(event, sess["user"]["id"], evidence=[dict(catalog_id=catalog_id, **evidence)],
                         model=self.model_versions(), outcome="ok")
        return result

    def update_catalog(self, sess, catalog_id, version, values):
        self._dept_guard(sess, values)
        changed = self._catalog_op(sess, "catalog_edit", catalog_id,
                                   lambda: self.store.update_draft(catalog_id, int(version), values, sess["user"]["id"]),
                                   "catalog_update", version=int(version))
        return {"changed": changed}

    def new_version(self, sess, catalog_id, from_version=None):
        nv = self._catalog_op(sess, "catalog_edit", catalog_id,
                              lambda: self.store.new_version(catalog_id, sess["user"]["id"],
                                                             int(from_version) if from_version else None),
                              "catalog_new_version", from_version=from_version)
        return {"version": nv}

    def approve_catalog(self, sess, catalog_id, version, note=None):
        self._catalog_op(sess, "catalog_review", catalog_id,
                         lambda: self.store.approve(catalog_id, int(version), sess["user"]["id"], note),
                         "catalog_approve", version=int(version))
        return {"ok": True}

    def withdraw_catalog(self, sess, catalog_id, reason):
        if not (reason or "").strip():
            raise ServiceError(400, "철회 사유를 입력하세요.")
        v = self._catalog_op(sess, "catalog_withdraw", catalog_id,
                             lambda: self.store.withdraw(catalog_id, sess["user"]["id"], reason.strip()[:300]),
                             "catalog_withdraw", reason=reason.strip()[:300])
        return {"withdrawn_version": v}

    # ── F3 권한 관리 ──
    def users(self, sess):
        self.require(sess, "grant_manage")
        return self.db.all("SELECT id,name,org,role,department,active FROM users ORDER BY role,id")

    def grants(self, sess):
        self.require(sess, "grant_manage")
        rows = self.db.all("SELECT * FROM grants ORDER BY id")
        today = self.today()
        for r in rows:
            r["levels"] = json.loads(r["levels"])
            r["domains"] = json.loads(r["domains"])
            r["active"] = r["revoked_at"] is None and r["valid_from"] <= today <= r["valid_to"]
        return rows

    def create_grant(self, sess, p):
        self.require(sess, "grant_manage")
        st, sid = p.get("subject_type"), str(p.get("subject_id") or "").strip()
        if st == "user":
            if not self.db.one("SELECT id FROM users WHERE id=? AND role='researcher'", (sid,)):
                raise ServiceError(400, "연구자 계정을 찾을 수 없습니다.")
        elif st == "org":
            if not self.db.one("SELECT id FROM users WHERE org=?", (sid,)):
                raise ServiceError(400, "등록된 기관이 아닙니다.")
        else:
            raise ServiceError(400, "대상 유형은 user 또는 org 입니다.")
        levels = [x for x in (p.get("levels") or []) if x in ACCESS_LEVELS]
        domains = [str(x).strip() for x in (p.get("domains") or []) if str(x).strip()]
        purpose = str(p.get("purpose") or "").strip()[:100]
        vf, vt = str(p.get("valid_from") or ""), str(p.get("valid_to") or "")
        try:
            date.fromisoformat(vf), date.fromisoformat(vt)
        except ValueError:
            raise ServiceError(400, "유효기간은 YYYY-MM-DD 형식입니다.")
        if not (levels and domains and purpose and vf <= vt):
            raise ServiceError(400, "목적·공개 범위·분야·유효기간을 모두 올바르게 입력하세요.")
        gid = self.db.run("INSERT INTO grants(subject_type,subject_id,purpose,levels,domains,valid_from,valid_to,created_by,created_at)"
                          " VALUES(?,?,?,?,?,?,?,?,?)",
                          (st, sid, purpose, json.dumps(levels, ensure_ascii=False), json.dumps(domains, ensure_ascii=False),
                           vf, vt, sess["user"]["id"], self.now()))
        self.db.bump_generation()
        self._invalidate()
        self.audit.write("grant_create", sess["user"]["id"], permission={"grant_id": gid, "subject": f"{st}:{sid}"},
                         outcome="ok")
        return {"grant_id": gid}

    def revoke_grant(self, sess, grant_id):
        self.require(sess, "grant_manage")
        g = self.db.one("SELECT * FROM grants WHERE id=?", (int(grant_id),))
        if not g or g["revoked_at"]:
            raise ServiceError(404, "회수할 권한이 없습니다.")
        self.db.run("UPDATE grants SET revoked_at=?, revoked_by=? WHERE id=?", (self.now(), sess["user"]["id"], g["id"]))
        self.db.bump_generation()
        self._invalidate()
        self.audit.write("grant_revoke", sess["user"]["id"], permission={"grant_id": g["id"]}, outcome="ok")
        return {"ok": True}

    # ── 로그·신고 ──
    def logs(self, sess, limit=200, event=None):
        self.require(sess, "log_view")
        raw = "log_raw" in CAPABILITIES.get(sess["user"]["role"], set())
        return {"raw_visible": raw, "logs": self.audit.list(limit, raw=raw, event=event or None),
                "retention": {"raw_query_days": self.cfg["raw_query_retention_days"],
                              "log_days": self.cfg["log_retention_days"]}}

    def purge(self, sess):
        self.require(sess, "purge")
        r = self.audit.purge(self.cfg["raw_query_retention_days"], self.cfg["log_retention_days"])
        self.audit.write("purge", sess["user"]["id"], outcome=json.dumps(r))
        return r

    def reports(self, sess):
        self.require(sess, "report_manage")
        return self.db.all("SELECT * FROM reports ORDER BY status DESC, id DESC")

    def resolve_report(self, sess, report_id, resolution):
        self.require(sess, "report_manage")
        if not (resolution or "").strip():
            raise ServiceError(400, "처리 내용을 입력하세요.")
        r = self.db.one("SELECT * FROM reports WHERE id=?", (int(report_id),))
        if not r:
            raise ServiceError(404, "신고를 찾을 수 없습니다.")
        self.db.run("UPDATE reports SET status='resolved', resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
                    (resolution.strip()[:500], sess["user"]["id"], self.now(), r["id"]))
        self.audit.write("report_resolve", sess["user"]["id"], evidence=[{"report_id": r["id"]}], outcome="resolved")
        return {"ok": True}

    def status(self, sess):
        self.require(sess, "catalog_view")
        return {"model": self.model_versions(), "schema": FIELD_SCHEMA,
                "unapproved_glossary": [g["canonical"] for g in self.glossary.unapproved],
                "counts": {r["status"]: r["n"] for r in self.db.all(
                    "SELECT status, COUNT(*) n FROM catalog_versions GROUP BY status")}}
