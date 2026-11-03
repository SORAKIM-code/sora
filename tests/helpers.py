import json
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.service import Service  # noqa: E402

with open(os.path.join(BASE, "data", "users.json"), encoding="utf-8") as f:
    PASSWORDS = {u["id"]: u["password"] for u in json.load(f)["users"]}

RESTRICTED = {"CAT-AMM-001", "CAT-CYB-001", "CAT-PER-001"}

# 시험은 data/catalogs.xlsx(운영자가 바꾸는 실제 목록) 대신 고정된 견본(가상 카탈로그 44건)을 쓴다.
# 견본 다시 만들기: python tools/catalog_excel.py export tests/fixtures/catalogs.xlsx
FIXTURE_XLSX = os.path.join(BASE, "tests", "fixtures", "catalogs.xlsx")
FIXTURE = {"catalog_excel": os.path.relpath(FIXTURE_XLSX, BASE)}


class Clock:
    def __init__(self, dt=datetime(2026, 11, 3, 10, 0, 0)):
        self.dt = dt

    def __call__(self):
        return self.dt


def make_service(clock=None):
    return Service(BASE, db_path=":memory:", clock=clock or Clock(), config_overrides=FIXTURE)


def login(svc, user, purpose=None):
    sess = svc.session(svc.login(user, PASSWORDS[user]))
    if purpose:
        svc.set_purpose(sess, purpose)
    return sess


def ids(result):
    return [c["catalog_id"] for c in result.get("candidates", [])]
