"""Vercel Python 함수 진입점. 기존 서버(app/server.py)의 요청 처리기를 그대로 쓴다.

vercel.json 이 모든 경로를 이 함수로 보낸다(/api/index?path=/원래경로).
Vercel 에서는 파일을 오래 저장할 수 없으므로 DB 는 임시 폴더(/tmp)에 두고,
함수가 새로 뜰 때마다 data/catalogs.xlsx 를 다시 읽는다.
→ 첫 화면(연구 목적 입력 → 추천 → 근거)은 그대로 동작한다.
→ 관리 화면(/admin)과 로그인·관리 API 는 기본으로 닫는다. 공개 저장소의 시연 계정 비밀번호로
  누구나 들어올 수 있고, 로그인·업로드도 인스턴스가 바뀌면 사라지기 때문이다.
  꼭 열어야 하면 Vercel 환경변수 MILMATCH_ENABLE_ADMIN=1 (시연 계정 비밀번호를 바꾼 뒤에만).
"""
import os
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.server import make_handler  # noqa: E402
from app.service import Service  # noqa: E402

DB_PATH = os.environ.get("CATALOG_DB") or os.path.join(tempfile.gettempdir(), "catalog-recommender.db")
ADMIN_ENABLED = os.environ.get("MILMATCH_ENABLE_ADMIN") == "1"
_svc = Service(BASE, db_path=DB_PATH, config_overrides={"admin_enabled": ADMIN_ENABLED})


def original_path(path):
    """rewrite 로 들어온 /api/index?path=/x&q=1 을 /x?q=1 로 되돌린다. 원래 경로가 그대로 오면 손대지 않는다."""
    url = urlparse(path)
    if url.path.rstrip("/") not in ("/api/index", "/api/index.py"):
        return path
    params = parse_qsl(url.query, keep_blank_values=True)
    orig = next((v for k, v in params if k == "path"), "/") or "/"
    if not orig.startswith("/"):
        orig = "/" + orig
    rest = [(k, v) for k, v in params if k != "path"]
    return orig + ("?" + urlencode(rest) if rest else "")


class handler(make_handler(_svc)):
    def _dispatch(self, method):
        self.path = original_path(self.path)
        return super()._dispatch(method)
