"""HTTP 계층. JSON API 와 정적 화면을 제공한다.

실행: python -m app.server   (catalog-recommender 폴더에서)
"""
import json
import mimetypes
import os
import re
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .service import Service, ServiceError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")
MEDIA_DIR = os.path.join(BASE_DIR, "data", "images")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
MEDIA_NAME = re.compile(r"[0-9A-Za-z가-힣_\-. ]{1,100}\.(png|jpg|jpeg|webp|gif)", re.IGNORECASE)
MAX_BODY = 64 * 1024

ROUTES = []


def route(method, pattern, auth=True):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, auth))
        return fn
    return deco


# ── 시연 방문자: 로그인 없이 쓰는 첫 버전 흐름 ──
@route("GET", "/api/public/info", auth=False)
def r_public_info(svc, h, sess, body, q):
    return svc.public_info()


@route("POST", "/api/public/recommend", auth=False)
def r_public_recommend(svc, h, sess, body, q):
    return svc.recommend(svc.demo_session(), body)


# ── 인증 (관리 화면 /admin 용) ──
@route("POST", "/api/login", auth=False)
def r_login(svc, h, sess, body, q):
    token = svc.login(body.get("username"), body.get("password"))
    h.set_cookie = f"sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={svc.cfg['session_ttl_minutes'] * 60}"
    return svc.me(svc.session(token))


@route("POST", "/api/logout")
def r_logout(svc, h, sess, body, q):
    svc.logout(sess)
    h.set_cookie = "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
    return {"ok": True}


@route("GET", "/api/me")
def r_me(svc, h, sess, body, q):
    return svc.me(sess)


@route("POST", "/api/session/purpose")
def r_purpose(svc, h, sess, body, q):
    svc.set_purpose(sess, body.get("purpose"))
    return svc.me(sess)


# ── 연구자 ──
@route("POST", "/api/recommend")
def r_recommend(svc, h, sess, body, q):
    return svc.recommend(sess, body)


@route("GET", "/api/suggest")
def r_suggest(svc, h, sess, body, q):
    return {"items": svc.suggest(sess, (q.get("q") or [""])[0][:50])}


@route("GET", r"/api/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})")
def r_detail(svc, h, sess, body, q, cid):
    return svc.catalog_detail(sess, cid)


@route("POST", "/api/reports")
def r_report(svc, h, sess, body, q):
    return svc.report(sess, body)


# ── 운영자: 카탈로그 ──
@route("GET", "/api/admin/status")
def r_status(svc, h, sess, body, q):
    return svc.status(sess)


@route("GET", "/api/admin/catalogs")
def r_admin_catalogs(svc, h, sess, body, q):
    return {"items": svc.admin_catalogs(sess)}


@route("POST", "/api/admin/catalogs")
def r_admin_create(svc, h, sess, body, q):
    return svc.create_catalog(sess, body)


@route("POST", "/api/admin/extract")
def r_extract(svc, h, sess, body, q):
    return svc.extract(sess, body.get("text"))


@route("GET", r"/api/admin/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})")
def r_admin_catalog(svc, h, sess, body, q, cid):
    return svc.admin_catalog(sess, cid)


@route("POST", r"/api/admin/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})/versions/(?P<v>\d+)")
def r_admin_update(svc, h, sess, body, q, cid, v):
    return svc.update_catalog(sess, cid, v, body.get("values") or {})


@route("POST", r"/api/admin/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})/versions/(?P<v>\d+)/approve")
def r_admin_approve(svc, h, sess, body, q, cid, v):
    return svc.approve_catalog(sess, cid, v, body.get("note"))


@route("POST", r"/api/admin/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})/new-version")
def r_admin_newver(svc, h, sess, body, q, cid):
    return svc.new_version(sess, cid, body.get("from_version"))


@route("POST", r"/api/admin/catalogs/(?P<cid>[A-Za-z0-9\-]{1,40})/withdraw")
def r_admin_withdraw(svc, h, sess, body, q, cid):
    return svc.withdraw_catalog(sess, cid, body.get("reason"))


# ── 운영자: 권한·로그·신고 ──
@route("GET", "/api/admin/users")
def r_users(svc, h, sess, body, q):
    return {"items": svc.users(sess)}


@route("GET", "/api/admin/grants")
def r_grants(svc, h, sess, body, q):
    return {"items": svc.grants(sess)}


@route("POST", "/api/admin/grants")
def r_grant_create(svc, h, sess, body, q):
    return svc.create_grant(sess, body)


@route("POST", r"/api/admin/grants/(?P<gid>\d+)/revoke")
def r_grant_revoke(svc, h, sess, body, q, gid):
    return svc.revoke_grant(sess, gid)


@route("GET", "/api/admin/logs")
def r_logs(svc, h, sess, body, q):
    return svc.logs(sess, min(int((q.get("limit") or ["200"])[0] or 200), 1000), (q.get("event") or [None])[0])


@route("POST", "/api/admin/logs/purge")
def r_purge(svc, h, sess, body, q):
    return svc.purge(sess)


@route("GET", "/api/admin/reports")
def r_reports(svc, h, sess, body, q):
    return {"items": svc.reports(sess)}


@route("POST", r"/api/admin/reports/(?P<rid>\d+)/resolve")
def r_resolve(svc, h, sess, body, q, rid):
    return svc.resolve_report(sess, rid, body.get("resolution"))


def make_handler(svc):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CatalogRecommender/0.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

        def _headers(self, status, ctype, length):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                             "frame-ancestors 'none'")

        def _json(self, status, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(data))
            self.send_header("Cache-Control", "no-store")
            if getattr(self, "set_cookie", None):
                self.send_header("Set-Cookie", self.set_cookie)
            self.end_headers()
            self.wfile.write(data)

        def _media(self, path):
            """카탈로그 대표 이미지: data/images 안의 그림 파일만, 정해진 확장자만 내준다."""
            name = unquote(path[len("/media/"):])
            if not MEDIA_NAME.fullmatch(name):
                return self._json(404, {"error": "없는 경로입니다."})
            full = os.path.realpath(os.path.join(MEDIA_DIR, name))
            if not full.startswith(os.path.realpath(MEDIA_DIR) + os.sep) or not os.path.isfile(full) \
                    or os.path.getsize(full) > 5 * 1024 * 1024:
                return self._json(404, {"error": "없는 경로입니다."})
            with open(full, "rb") as f:
                data = f.read()
            self._headers(200, MEDIA_TYPES[name.rsplit(".", 1)[1].lower()], len(data))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, path):
            pages = {"/": "index.html", "/index.html": "index.html", "/admin": "admin.html"}
            rel = pages.get(path) or (path[len("/static/"):] if path.startswith("/static/") else None)
            if rel is None:
                return self._json(404, {"error": "없는 경로입니다."})
            full = os.path.realpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
                return self._json(404, {"error": "없는 경로입니다."})
            with open(full, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._headers(200, ctype, len(data))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method):
            self.set_cookie = None
            url = urlparse(self.path)
            if method == "GET" and url.path.startswith("/media/"):
                return self._media(url.path)
            if method == "GET" and not url.path.startswith("/api/"):
                return self._static(url.path)
            for m, rx, fn, auth in ROUTES:
                if m != method:
                    continue
                match = rx.match(url.path)
                if not match:
                    continue
                try:
                    body = {}
                    if method == "POST":
                        # JSON 만 받는다: 다른 사이트의 단순 form 전송(CSRF)을 막는다.
                        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                            raise ServiceError(415, "application/json 요청만 받습니다.")
                        n = int(self.headers.get("Content-Length") or 0)
                        if n > MAX_BODY:
                            raise ServiceError(413, "요청이 너무 큽니다.")
                        raw = self.rfile.read(n) if n else b"{}"
                        try:
                            body = json.loads(raw.decode("utf-8") or "{}")
                        except (ValueError, UnicodeDecodeError):
                            raise ServiceError(400, "JSON 형식이 올바르지 않습니다.")
                        if not isinstance(body, dict):
                            raise ServiceError(400, "JSON 객체를 보내세요.")
                    sess = None
                    if auth:
                        c = SimpleCookie(self.headers.get("Cookie") or "")
                        sess = svc.session(c["sid"].value if "sid" in c else None)
                    result = fn(svc, self, sess, body, parse_qs(url.query), **match.groupdict())
                    return self._json(200, result)
                except ServiceError as e:
                    return self._json(e.status, {"error": e.message})
                except Exception as e:  # 내부 오류 내용은 응답에 싣지 않는다
                    self.log_message("internal error: %r", e)
                    return self._json(500, {"error": "서버 내부 오류가 발생했습니다."})
            return self._json(404, {"error": "없는 경로입니다."})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def main():
    svc = Service(BASE_DIR)
    host, port = svc.cfg["host"], int(os.environ.get("PORT", svc.cfg["port"]))
    httpd = ThreadingHTTPServer((host, port), make_handler(svc))
    imp = svc.last_import
    if imp is None:
        print("카탈로그: 엑셀 파일이 없어 data/catalogs.json 의 가상 카탈로그를 사용합니다.", flush=True)
    elif imp["status"] == "failed":
        print(f"[주의] 엑셀 카탈로그를 읽지 못해 이전 카탈로그를 그대로 씁니다: {imp['error']}", flush=True)
    else:
        print(f"카탈로그: {svc.excel_path} ({'변경 없음' if imp['status'] == 'unchanged' else '반영함'}) {imp.get('counts')}", flush=True)
        for e in imp.get("errors", []):
            print("  [오류]", e, flush=True)
    print(f"군 데이터 카탈로그 추천 서비스(시제품): http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
