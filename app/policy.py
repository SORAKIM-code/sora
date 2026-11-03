"""인증과 열람 권한 정책.

권한 판단은 생성형 AI 와 무관하게 이 모듈에서만 한다.
설정되지 않은 권한은 접근 거부(deny by default)다.
"""
import hashlib
import hmac
import json
import secrets


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return salt, h


def verify_password(password, salt, expected):
    _, h = hash_password(password, salt)
    return hmac.compare_digest(h, expected or "")


def _grant_row(r):
    r = dict(r)
    r["levels"] = json.loads(r["levels"])
    r["domains"] = json.loads(r["domains"])
    return r


class Policy:
    def __init__(self, db):
        self.db = db

    def grants_for(self, user, today, purpose=None, include_inactive=False):
        rows = self.db.all(
            "SELECT * FROM grants WHERE (subject_type='user' AND subject_id=?) OR (subject_type='org' AND subject_id=?)"
            " ORDER BY id", (user["id"], user["org"]))
        out = []
        for r in map(_grant_row, rows):
            r["active"] = (r["revoked_at"] is None and r["valid_from"] <= today <= r["valid_to"])
            if purpose is not None and r["purpose"] != purpose:
                continue
            if r["active"] or include_inactive:
                out.append(r)
        return out

    def purposes(self, user, today):
        seen = {}
        for g in self.grants_for(user, today):
            seen.setdefault(g["purpose"], []).append(g)
        return [{"purpose": p, "grants": gs} for p, gs in seen.items()]

    @staticmethod
    def grant_allows(grant, values, role):
        if values.get("access_level") not in grant["levels"]:
            return False
        if "*" not in grant["domains"] and values.get("domain") not in grant["domains"]:
            return False
        return role in (values.get("roles") or [])

    def visible(self, user, purpose, values, today, grants=None):
        """이 카탈로그 값을 이 사용자·목적으로 볼 수 있으면 근거가 된 권한 ID 를, 아니면 None."""
        if not user or user["role"] != "researcher" or not purpose:
            return None
        grants = grants if grants is not None else self.grants_for(user, today, purpose)
        for g in grants:
            if self.grant_allows(g, values, user["role"]):
                return g["id"]
        return None
