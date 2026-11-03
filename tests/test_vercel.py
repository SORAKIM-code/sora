"""Vercel 진입점(api/index.py) 시험: rewrite 된 경로와 원래 경로 모두 같은 화면·API 를 준다."""
import json
import os
import tempfile
import threading
import unittest
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

    def test_rewritten_post_recommend(self):
        req = urllib.request.Request(self.base + "/api/index?path=/api/public/recommend", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"query": "차량 정비 이력을 활용해서 고장 예측 AI를 개발하고 싶습니다."}).encode())
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.loads(r.read())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
