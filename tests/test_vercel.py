"""Vercel 진입점(api/index.py) 시험: rewrite 된 경로와 원래 경로 모두 같은 화면·API 를 준다."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import quote

from tests.helpers import BASE


class VercelEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CATALOG_DB"] = os.path.join(cls.tmp, "v.db")
        try:
            import api.index as entry
        finally:
            del os.environ["CATALOG_DB"]
        cls.entry = entry
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), entry.handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.entry._svc.db.conn.close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.headers["Content-Type"], r.read()

    def test_original_path(self):
        op = self.entry.original_path
        self.assertEqual(op("/api/index?path=/"), "/")
        self.assertEqual(op("/api/index?path=/api/suggest&q=a"), "/api/suggest?q=a")
        self.assertEqual(op("/api/index?path=/static/style.css"), "/static/style.css")
        self.assertEqual(op("/api/public/info"), "/api/public/info")

    def test_rewritten_requests_serve_page_static_and_api(self):
        st, ct, body = self.get("/api/index?path=/")
        self.assertEqual(st, 200)
        self.assertIn("밀매치", body.decode("utf-8"))
        st, ct, _ = self.get("/api/index?path=/static/style.css")
        self.assertTrue(ct.startswith("text/css"))
        st, ct, body = self.get("/api/index?path=" + quote("/api/public/info"))
        self.assertGreater(json.loads(body)["catalog_count"], 0)

    def test_admin_closed_by_default(self):
        """공개 배포에서는 관리 화면·로그인·관리 API 를 닫고, 첫 화면 흐름만 연다."""
        _, _, body = self.get("/api/index?path=/api/public/info")
        self.assertIs(json.loads(body)["admin_enabled"], False)
        for path in ("/admin", "/api/me", "/api/admin/logs", "/api/admin/excel/download", "/api/suggest?q=정비",
                     "/api/catalogs/CAT-VEH-001", "/data/users.json", "/config.json"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as cm:
                urllib.request.urlopen(self.base + "/api/index?path=" + quote(path, safe="/?=&"))
            self.assertEqual(cm.exception.code, 404, path)
        req = urllib.request.Request(self.base + "/api/index?path=/api/login", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"username": "adm1", "password": "x"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 404)

    def test_vercel_sends_every_path_to_function(self):
        """rewrites 는 저장소 파일이 있으면 그 파일을 먼저 내준다. routes 로 모든 경로를 함수에 보내야 파일이 노출되지 않는다."""
        with open(os.path.join(BASE, "vercel.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertNotIn("rewrites", cfg)
        self.assertEqual(cfg["routes"], [{"src": "/(.*)", "dest": "/api/index?path=/$1"}])
        self.assertFalse(any("handle" in r for r in cfg["routes"]))  # filesystem 단계를 넣지 않는다

    def test_rewritten_post_recommend(self):
        req = urllib.request.Request(self.base + "/api/index?path=/api/public/recommend", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"query": "차량 정비 이력을 활용해서 고장 예측 AI를 개발하고 싶습니다."}).encode())
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.loads(r.read())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
