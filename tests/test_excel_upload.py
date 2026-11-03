"""관리자 화면의 카탈로그 엑셀 내려받기·검사·올리기 시험."""
import base64
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import make_handler
from app.service import Service, ServiceError
from app.xlsx import read_xlsx, write_xlsx
from tests.helpers import BASE, PASSWORDS, Clock, ids, login

SAMPLE = os.path.join(BASE, "data", "catalogs.xlsx")


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def copy_base(tmp):
    """실제 data/catalogs.xlsx 를 건드리지 않도록 서비스 폴더를 임시 폴더에 복사한다."""
    os.makedirs(os.path.join(tmp, "data"))
    shutil.copy(os.path.join(BASE, "config.json"), os.path.join(tmp, "config.json"))
    for f in ("glossary.json", "clarify_rules.json", "users.json", "grants.json", "examples.json", "catalogs.json",
              "catalogs.xlsx"):
        shutil.copy(os.path.join(BASE, "data", f), os.path.join(tmp, "data", f))


def edited_workbook(path):
    """견본에 새 카탈로그 한 행을 추가하고 한 행을 지운 파일."""
    rows = [cells for _, cells in read_xlsx(SAMPLE)["카탈로그"]]
    hdr = rows[0]
    ci = {h: i for i, h in enumerate(hdr)}
    new = [""] * len(hdr)
    new[ci["카탈로그 ID"]], new[ci["상태"]], new[ci["제목"]] = "NEW-777", "검수완료", "전술차량 배터리 교체 기록"
    new[ci["분야"]], new[ci["공개 범위"]], new[ci["주제어"]] = "차량", "공개", "배터리; 교체"
    body = [r for r in rows[1:] if r[0] != "CAT-WTH-001"] + [new]
    write_xlsx(path, [{"name": "카탈로그", "rows": [hdr] + body}])


class ExcelUpload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        copy_base(self.tmp)
        self.svc = Service(self.tmp, db_path=":memory:", clock=Clock())
        self.adm = login(self.svc, "adm1")
        self.edited = os.path.join(self.tmp, "edited.xlsx")
        edited_workbook(self.edited)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_download_is_the_file_in_use(self):
        res = self.svc.excel_download(self.adm)
        with open(SAMPLE, "rb") as f:
            self.assertEqual(res.data, f.read())
        self.assertTrue(res.name.endswith(".xlsx"))

    def test_only_admin_can_use_excel(self):
        for user in ("op1", "own1", "r1"):
            sess = login(self.svc, user)
            with self.assertRaises(ServiceError) as cm:
                self.svc.excel_download(sess)
            self.assertEqual(cm.exception.status, 403, user)
            with self.assertRaises(ServiceError):
                self.svc.excel_upload(sess, {"data": b64(self.edited)})

    def test_check_does_not_change_anything_and_matches_upload(self):
        before = {c["id"] for c in self.svc.store.approved()}
        chk = self.svc.excel_check(self.adm, {"data": b64(self.edited)})
        self.assertTrue(chk["ok"])
        self.assertEqual(chk["lists"]["added"], ["NEW-777"])
        self.assertEqual(chk["lists"]["withdrawn"], ["CAT-WTH-001"])
        self.assertEqual({c["id"] for c in self.svc.store.approved()}, before)
        with open(SAMPLE, "rb") as a, open(self.svc.excel_path, "rb") as b:
            self.assertEqual(a.read(), b.read())

        up = self.svc.excel_upload(self.adm, {"data": b64(self.edited)})
        self.assertEqual(up["status"], "imported")
        self.assertEqual(up["counts"], chk["counts"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "var", "excel_backups", up["backup"])))
        with open(self.edited, "rb") as a, open(self.svc.excel_path, "rb") as b:
            self.assertEqual(a.read(), b.read())
        demo = self.svc.demo_session()
        r = self.svc.recommend(demo, {"query": "전술차량 배터리 교체", "skip_clarify": True})
        self.assertIn("NEW-777", ids(r))
        self.assertEqual(r["candidates"][0]["availability"]["origin"]["file"], "catalogs.xlsx")
        self.assertIsNone(self.svc.store.approved_one("CAT-WTH-001"))
        # 같은 파일을 다시 올리면 바뀌는 것이 없다
        self.assertEqual(self.svc.excel_upload(self.adm, {"data": b64(self.edited)})["status"], "unchanged")

    def test_bad_files_are_rejected_and_old_file_kept(self):
        nohdr = os.path.join(self.tmp, "nohdr.xlsx")
        write_xlsx(nohdr, [{"name": "카탈로그", "rows": [["카탈로그 ID", "제목"], ["A", "B"]]}])
        self.assertFalse(self.svc.excel_check(self.adm, {"data": b64(nohdr)})["ok"])
        bad = [{"data": b64(nohdr)}, {"data": base64.b64encode(b"a,b,c").decode()}, {"data": "!!!"}, {"data": ""},
               {"data": base64.b64encode(b"PK" + b"x" * 100).decode()}]
        for body in bad:
            with self.assertRaises(ServiceError):
                self.svc.excel_upload(self.adm, body)
        with open(SAMPLE, "rb") as a, open(self.svc.excel_path, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertIsNotNone(self.svc.store.approved_one("CAT-WTH-001"))


class ExcelUploadHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        copy_base(cls.tmp)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Service(cls.tmp, db_path=":memory:", clock=Clock())))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def cookie(self, user):
        req = urllib.request.Request(self.base + "/api/login", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"username": user, "password": PASSWORDS[user]}).encode())
        with urllib.request.urlopen(req) as r:
            return r.headers["Set-Cookie"].split(";")[0]

    def test_download_and_upload_over_http(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/admin/excel/download")
        self.assertEqual(cm.exception.code, 401)
        ck = self.cookie("adm1")
        req = urllib.request.Request(self.base + "/api/admin/excel/download", headers={"Cookie": ck})
        with urllib.request.urlopen(req) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("application/vnd.openxmlformats"))
            self.assertIn("attachment", r.headers["Content-Disposition"])
            data = r.read()
        self.assertTrue(data.startswith(b"PK"))
        path = os.path.join(self.tmp, "dl.xlsx")
        with open(path, "wb") as f:
            f.write(data)
        edited_workbook(path)
        req = urllib.request.Request(self.base + "/api/admin/excel/upload", method="POST",
                                     headers={"Content-Type": "application/json", "Cookie": ck},
                                     data=json.dumps({"data": b64(path)}).encode())
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.loads(r.read())["status"], "imported")
        req = urllib.request.Request(self.base + "/api/admin/excel/download", headers={"Cookie": self.cookie("op1")})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
