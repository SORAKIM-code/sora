"""엑셀 카탈로그 목록 반영 시험."""
import os
import shutil
import tempfile
import unittest

from app.excel_catalog import headers, parse_workbook
from app.service import Service, ServiceError
from app.xlsx import read_xlsx, write_xlsx
from tests.helpers import BASE, Clock, ids, make_service

SAMPLE = os.path.join(BASE, "data", "catalogs.xlsx")


def sample_rows():
    """견본 엑셀의 카탈로그 시트 행(머리글 포함)을 목록으로."""
    return [cells for _, cells in read_xlsx(SAMPLE)["카탈로그"]]


def save(path, rows, shared=False):
    write_xlsx(path, [{"name": "카탈로그", "rows": rows}], shared_strings=shared)


class Excel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.tmp, name)

    def test_sample_matches_virtual_json_catalogs(self):
        from_json = Service(BASE, db_path=":memory:", clock=Clock(), config_overrides={"catalog_excel": None})
        from_excel = make_service()
        a = {c["id"]: c["values"] for c in from_json.store.approved()}
        b = {c["id"]: c["values"] for c in from_excel.store.approved()}
        self.assertEqual(a, b)
        self.assertEqual(from_excel.last_import["status"], "imported")
        self.assertIsNotNone(from_excel.store.approved_one("CAT-VEH-001")["origin"])

    def test_recommendation_cites_excel_cell(self):
        svc = make_service()
        r = svc.recommend(svc.demo_session(), {"query": "차량 정비 이력을 활용해서 고장 예측 AI를 개발하고 싶습니다."})
        o = r["candidates"][0]["availability"]["origin"]
        self.assertEqual((o["file"], o["sheet"]), ("catalogs.xlsx", "카탈로그"))
        rows = sample_rows()
        hdr = rows[0]
        row = rows[o["row"] - 1]
        col = ord(o["cols"]["title"]) - 65
        self.assertEqual(row[col], r["candidates"][0]["title"])
        self.assertEqual(hdr[col], "제목")

    def test_sync_edit_withdraw_remove_and_add(self):
        rows = sample_rows()
        hdr = rows[0]
        ci = {h: i for i, h in enumerate(hdr)}
        by_id = {r[0]: r for r in rows[1:]}
        by_id["CAT-VEH-002"][ci["제목"]] = "차량 운행 이력(개정)"
        by_id["CAT-VEH-005"][ci["상태"]] = "철회"
        by_id["CAT-VEH-003"][ci["상태"]] = "검수대기"
        del by_id["CAT-FOD-002"]
        new = [""] * len(hdr)
        new[ci["카탈로그 ID"]], new[ci["상태"]], new[ci["제목"]] = "NEW-001", "검수완료", "전술차량 타이어 교체 기록"
        new[ci["분야"]], new[ci["공개 범위"]], new[ci["주제어"]] = "차량", "공개", "타이어; 교체; 9종"
        path = self.p("edited.xlsx")
        save(path, [hdr] + list(by_id.values()) + [new])

        svc = make_service()
        demo = svc.demo_session()
        before = svc.recommend(demo, {"query": "잔반 발생량을 줄이기 위한 급식 식단 분석", "skip_clarify": True})
        self.assertIn("CAT-FOD-002", ids(before))
        res = svc.sync_excel(path)
        self.assertEqual(res["counts"]["added"], 1)
        self.assertEqual(res["counts"]["updated"], 1)
        self.assertEqual(res["counts"]["withdrawn"], 2)  # 철회 표시 1 + 목록에서 빠짐 1
        self.assertEqual(res["counts"]["draft"], 3)      # 검수대기로 바꾼 1 + 원래 검수대기 2

        self.assertEqual(svc.store.approved_one("CAT-VEH-002")["values"]["title"], "차량 운행 이력(개정)")
        self.assertEqual(svc.store.approved_one("CAT-VEH-002")["version"], 2)
        for gone in ("CAT-VEH-005", "CAT-VEH-003", "CAT-FOD-002"):
            self.assertIsNone(svc.store.approved_one(gone), gone)
        after = svc.recommend(demo, {"query": "잔반 발생량을 줄이기 위한 급식 식단 분석", "skip_clarify": True})
        self.assertNotIn("CAT-FOD-002", ids(after))
        self.assertIn("NEW-001", ids(svc.recommend(demo, {"query": "전술차량 타이어 교체", "skip_clarify": True})))
        hashtag = svc.recommend(demo, {"query": "전술차량 타이어 교체", "skip_clarify": True})["candidates"][0]
        self.assertIn("#9종", [t["tag"] for t in hashtag["explanation"]["hashtags"]])

    def test_bad_rows_are_reported_and_skipped(self):
        hdr = headers()
        ci = {h: i for i, h in enumerate(hdr)}

        def row(**kw):
            r = [""] * len(hdr)
            for k, v in kw.items():
                r[ci[k]] = v
            return r
        path = self.p("bad.xlsx")
        save(path, [hdr,
                    row(**{"카탈로그 ID": "A-1", "상태": "검수완료", "제목": "정상", "분야": "차량", "공개 범위": "공개"}),
                    row(**{"카탈로그 ID": "A-1", "상태": "검수완료", "제목": "중복", "분야": "차량", "공개 범위": "공개"}),
                    row(**{"카탈로그 ID": "A-2", "상태": "검수완료", "제목": "등급 오류", "분야": "차량", "공개 범위": "비밀"}),
                    row(**{"카탈로그 ID": "A-3", "상태": "검수완료", "제목": "분야 없음", "공개 범위": "공개"}),
                    row(**{"카탈로그 ID": "A-4", "제목": "상태 없음", "분야": "차량", "공개 범위": "공개"}),
                    row(**{"제목": "ID 없음", "분야": "차량", "공개 범위": "공개"})])
        p = parse_workbook(path)
        got = {r["id"]: r["status"] for r in p["rows"]}
        self.assertEqual(got, {"A-1": "approved", "A-3": "draft", "A-4": "draft"})
        self.assertEqual(len(p["errors"]), 4)  # 중복·등급·분야 누락(검수대기 강등)·ID 없음
        self.assertTrue(any("상태가 비어" in w for w in p["warnings"]))

    def test_alias_headers_dates_and_shared_strings(self):
        path = self.p("alias.xlsx")
        save(path, [
            ["안내: 이 표는 시험용입니다"],
            ["ID", "자료명", "분류", "공개구분", "키워드", "데이터 항목", "수집시작", "최종확인일", "검수상태", "비고"],
            ["X-1", "급식 잔반 월별 집계", "급식", "공개", "#잔반 #1종", "연월\n잔반량(kg)", "43101", "2026.9.30", "검수완료", "무시"],
        ], shared=True)
        p = parse_workbook(path)
        self.assertIsNone(p["fatal"])
        v = p["rows"][0]["values"]
        self.assertEqual(v["title"], "급식 잔반 월별 집계")
        self.assertEqual(v["keywords"], ["잔반", "1종"])
        self.assertEqual(v["columns"], ["연월", "잔반량(kg)"])
        self.assertEqual(v["period_start"], "2018-01")
        self.assertEqual(v["last_checked"], "2026-09-30")
        self.assertEqual(v["roles"], ["researcher"])
        self.assertIn("alias.xlsx", v["source_doc"])
        self.assertEqual(p["rows"][0]["origin"]["row"], 3)
        self.assertTrue(any("비고" in w for w in p["warnings"]))

    def test_structure_and_preprocessing_columns(self):
        path = self.p("shape.xlsx")
        save(path, [
            ["ID", "자료명", "분야", "공개범위", "정형/비정형", "전처리 여부", "전처리 방법", "상태"],
            ["S-1", "가", "차량", "공개", "정형 데이터", "O", "결측 보정", "검수완료"],
            ["S-2", "나", "차량", "공개", "비정형", "무", "", "검수완료"],
            ["S-3", "다", "차량", "공개", "표", "몰라", "", "검수완료"],
            ["S-4", "라", "차량", "공개", "", "", "", "검수완료"],
        ])
        p = parse_workbook(path)
        got = {r["id"]: (r["values"]["structure"], r["values"]["preprocessed"], r["values"]["preprocess_detail"])
               for r in p["rows"]}
        self.assertEqual(got, {"S-1": ("정형", "있음", "결측 보정"), "S-2": ("비정형", "없음", None),
                               "S-3": (None, None, None), "S-4": (None, None, None)})
        self.assertEqual(sum("미확인으로 둡니다" in w for w in p["warnings"]), 2)
        # 견본 엑셀에 새 열과 드롭다운이 들어 있다
        hdr = sample_rows()[0]
        for col in ("데이터 구조", "전처리 유무", "전처리 내용"):
            self.assertIn(col, hdr)

    def test_structure_and_preprocessing_on_card(self):
        svc = make_service()
        r = svc.recommend(svc.demo_session(), {"query": "차량 정비 이력을 활용해서 고장 예측 AI를 개발하고 싶습니다."})
        c = r["candidates"][0]
        self.assertEqual((c["metadata"]["structure"], c["metadata"]["preprocessed"]), ("정형", "없음"))
        self.assertTrue(any(x["field"] == "preprocessed" for x in c["explanation"]["checks"]))
        r = svc.recommend(svc.demo_session(), {"query": "온열질환 발생 통계", "skip_clarify": True})
        c = next(c for c in r["candidates"] if c["catalog_id"] == "CAT-MED-002")
        self.assertEqual(c["metadata"]["preprocess_detail"], "비식별화 후 집계")
        self.assertFalse(any(x["field"] == "preprocessed" for x in c["explanation"]["checks"]))
        self.assertEqual(c["metadata"]["size"], "약 0.3MB")

    def test_size_column(self):
        path = self.p("size.xlsx")
        save(path, [["ID", "자료명", "분야", "공개범위", "파일 크기", "파일 갯수", "상태"],
                    ["Z-1", "가", "차량", "공개", "약 2GB", "12", "검수완료"],
                    ["Z-2", "나", "차량", "공개", "1500", "약 3만 개", "검수완료"],
                    ["Z-3", "다", "차량", "공개", "", "", "검수완료"]])
        p = parse_workbook(path)
        self.assertEqual([r["values"]["size"] for r in p["rows"]], ["약 2GB", "1500", None])
        self.assertEqual([r["values"]["file_count"] for r in p["rows"]], ["12개", "약 3만 개", None])
        self.assertTrue(any("단위" in w and "1500" in w for w in p["warnings"]))
        self.assertIn("데이터 용량", sample_rows()[0])
        self.assertIn("파일 개수", sample_rows()[0])

    def test_missing_required_header_is_fatal(self):
        path = self.p("nohdr.xlsx")
        save(path, [["카탈로그 ID", "제목"], ["A", "B"]])
        svc = make_service()
        with self.assertRaises(ServiceError):
            svc.sync_excel(path)
        self.assertTrue(svc.store.approved())  # 기존 카탈로그는 그대로

    def test_not_an_xlsx(self):
        path = self.p("fake.xlsx")
        with open(path, "w", encoding="utf-8") as f:
            f.write("a,b,c")
        from app.xlsx import XlsxError
        with self.assertRaises(XlsxError):
            parse_workbook(path)

    def test_auto_reimport_when_file_changes(self):
        os.makedirs(self.p("data"))
        shutil.copy(os.path.join(BASE, "config.json"), self.p("config.json"))
        for f in ("glossary.json", "clarify_rules.json", "users.json", "grants.json", "examples.json", "catalogs.json"):
            shutil.copy(os.path.join(BASE, "data", f), self.p(os.path.join("data", f)))
        xlsx = self.p(os.path.join("data", "catalogs.xlsx"))
        shutil.copy(SAMPLE, xlsx)
        db = self.p("t.db")
        s1 = Service(self.tmp, db_path=db, clock=Clock())
        self.assertEqual(s1.last_import["status"], "imported")
        s1.db.conn.close()
        s2 = Service(self.tmp, db_path=db, clock=Clock())
        self.assertEqual(s2.last_import["status"], "unchanged")
        s2.db.conn.close()
        rows = sample_rows()
        save(xlsx, rows[:1] + [r for r in rows[1:] if r[0] != "CAT-WTH-001"])
        s3 = Service(self.tmp, db_path=db, clock=Clock())
        self.assertEqual(s3.last_import["status"], "imported")
        self.assertIsNone(s3.store.approved_one("CAT-WTH-001"))
        s3.db.conn.close()


if __name__ == "__main__":
    unittest.main()
