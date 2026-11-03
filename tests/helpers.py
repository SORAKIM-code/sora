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


class Clock:
    def __init__(self, dt=datetime(2026, 11, 3, 10, 0, 0)):
        self.dt = dt

    def __call__(self):
        return self.dt


def make_service(clock=None):
    return Service(BASE, db_path=":memory:", clock=clock or Clock())


def login(svc, user, purpose=None):
    sess = svc.session(svc.login(user, PASSWORDS[user]))
    if purpose:
        svc.set_purpose(sess, purpose)
    return sess


def ids(result):
    return [c["catalog_id"] for c in result.get("candidates", [])]
