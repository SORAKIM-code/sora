"""HTTP 계층 시험: 인증, 역할 검사, CSRF 방어, 정적 경로."""
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import make_handler
from tests.helpers import PASSWORDS, make_service


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = make_service()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.svc))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, method, path, body=None, cookie=None, ctype="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def login(self, user):
        st, body, headers = self.call("POST", "/api/login", {"username": user, "password": PASSWORDS[user]})
        self.assertEqual(st, 200)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        return cookie.split(";")[0]

    def test_unauthenticated_api_is_401(self):
        for path in ("/api/me", "/api/suggest?q=" + urllib.parse.quote("차량"),"/api/catalogs/CAT-VEH-001", "/api/admin/logs"):
            self.assertEqual(self.call("GET", path)[0], 401, path)
        self.assertEqual(self.call("POST", "/api/recommend", {"query": "x"})[0], 401)

    def test_researcher_gets_403_on_admin(self):
        c = self.login("r1")
        self.assertEqual(self.call("GET", "/api/admin/grants", cookie=c)[0], 403)
        self.assertEqual(self.call("POST", "/api/admin/grants", {}, cookie=c)[0], 403)

    def test_form_post_rejected(self):
        c = self.login("r1")
        st, _, _ = self.call("POST", "/api/recommend", {"query": "x"}, cookie=c, ctype="application/x-www-form-urlencoded")
        self.assertEqual(st, 415)

    def test_recommend_round_trip(self):
        c = self.login("r1")
        self.call("POST", "/api/session/purpose", {"purpose": "장비 예지정비 연구"}, cookie=c)
        st, body, headers = self.call("POST", "/api/recommend", {"query": "헬기 엔진 결함 조기 발견"}, cookie=c)
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_static_and_traversal(self):
        req = urllib.request.urlopen(self.base + "/")
        self.assertIn("Content-Security-Policy", req.headers)
        self.assertEqual(self.call("GET", "/static/../config.json")[0], 404)
        self.assertEqual(self.call("GET", "/static/..%2Fconfig.json")[0], 404)


if __name__ == "__main__":
    unittest.main()
