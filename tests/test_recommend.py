"""추천·근거 표시 기능 시험 (PRD F1, F2)."""
import unittest

from app import explainer
from app.catalogs import parse_spec, render_spec
from tests.helpers import ids, login, make_service

R1 = "장비 예지정비 연구"


class Recommend(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()
        self.s = login(self.svc, "r1", R1)

    def test_purpose_only_input_works(self):
        r = self.svc.recommend(self.s, {"query": "헬기 엔진 결함을 조기에 발견하는 모델"})
        self.assertEqual(r["status"], "ok")
        self.assertIn("CAT-AIR-003", ids(r))

    def test_clarify_first_for_ambiguous_prediction(self):
        r = self.svc.recommend(self.s, {"query": "군용 차량의 고장을 사전에 예측하고 싶다"})
        self.assertEqual(r["status"], "clarify")
        self.assertEqual(r["questions"][0]["id"], "data_hint")
        a = self.svc.recommend(self.s, {"query": "군용 차량의 고장을 사전에 예측하고 싶다", "answers": {"data_hint": "시계열"}})
        b = self.svc.recommend(self.s, {"query": "군용 차량의 고장을 사전에 예측하고 싶다", "answers": {"data_hint": "이력"}})
        self.assertEqual(ids(a)[0], "CAT-VEH-003")
        self.assertEqual(ids(b)[0], "CAT-VEH-001")

    def test_abstain_when_no_answer(self):
        r = self.svc.recommend(self.s, {"query": "주식 시장 가격 예측", "skip_clarify": True})
        self.assertEqual(r["status"], "abstain")
        self.assertEqual(r["candidates"], [])
        self.assertTrue(r["message"])

    def test_every_candidate_has_required_display_items(self):
        r = self.svc.recommend(self.s, {"query": "통신장비 고장 유형을 분류하는 연구"})
        self.assertTrue(r["candidates"])
        self.assertEqual(r["engine"]["type"], "rule")
        self.assertIn("AI 미연결", r["engine"]["label"])
        for c in r["candidates"]:
            for k in ("catalog_id", "title", "version", "availability", "relevance"):
                self.assertTrue(c[k], k)
            e = c["explanation"]
            # 카드 6구역: 이름·설명 / 주요 항목 / 적합한 이유 / 활용 방법 / 부족한 정보·확인사항 / 이용 조건
            self.assertEqual(e["description"]["text"], c["metadata"]["description"])
            self.assertEqual([x["text"] for x in e["columns"]], c["metadata"]["columns"])
            self.assertTrue(e["reasons"] and e["methods"] and e["checks"])
            self.assertIn("procedure", e["terms"])
            self.assertIn("approval_status", c["availability"])
            self.assertNotIn("%", c["relevance"])

    def test_explanations_cite_only_retrieved_ids_and_versions(self):
        r = self.svc.recommend(self.s, {"query": "군용 차량 고장 예측", "answers": {"data_hint": "이력"}})
        refs = {(c["catalog_id"], c["version"]) for c in r["candidates"]}
        for c in r["candidates"]:
            for part in ("reasons", "methods", "checks"):
                for item in c["explanation"][part]:
                    self.assertIn((item["cite"]["catalog_id"], item["cite"]["version"]), refs)

    def test_validator_drops_foreign_citations(self):
        expl = {"reasons": [{"cite": {"catalog_id": "CAT-AMM-001", "version": 1}}],
                "methods": [{"cite": {"catalog_id": "CAT-VEH-001", "version": 1}}], "checks": []}
        out = explainer.validate(expl, {("CAT-VEH-001", 1)})
        self.assertEqual(out["reasons"], [])
        self.assertEqual(out["dropped_citations"], 1)

    def test_explainer_failure_still_returns_candidates_with_metadata(self):
        class Broken:
            version = "broken"

            def explain(self, *a):
                raise RuntimeError("boom")
        self.svc.explainer = Broken()
        r = self.svc.recommend(self.s, {"query": "통신장비 고장 유형 분류"})
        self.assertTrue(r["candidates"])
        for c in r["candidates"]:
            self.assertIsNone(c["explanation"])
            self.assertTrue(c["explanation_error"])
            self.assertTrue(c["metadata"]["title"])

    def test_unknown_values_are_not_filled(self):
        r = self.svc.recommend(self.s, {"query": "차량 센서 시계열 진동", "skip_clarify": True})
        c = next(c for c in r["candidates"] if c["catalog_id"] == "CAT-VEH-003")
        self.assertIsNone(c["metadata"]["label_available"])
        self.assertIn("정답표시 유무", [m["label"] for m in c["explanation"]["missing"]])

    def test_reasons_point_to_source_lines(self):
        r = self.svc.recommend(self.s, {"query": "통신장비 고장 유형 분류"})
        for c in r["candidates"]:
            lines = self.svc.store.version(c["catalog_id"], c["version"])["source_text"].splitlines()
            for f in c["explanation"]["reasons"]:
                self.assertIn(str(f["quote"])[:40], lines[f["source_line"] - 1])

    def test_period_condition(self):
        r = self.svc.recommend(self.s, {"query": "2015~2024 항공기 비행시간 기록 분석"})
        c = next(c for c in r["candidates"] if c["catalog_id"] == "CAT-AIR-002")
        period = next(i for i in c["conditions"] if i["key"] == "period")
        self.assertEqual(period["status"], "부분")

    def test_report_wrong_evidence(self):
        rid = self.svc.report(self.s, {"catalog_id": "CAT-VEH-001", "field": "period_end", "message": "실제 종료는 2024-12"})
        op = login(self.svc, "op1")
        self.assertEqual(self.svc.reports(op)[0]["id"], rid["report_id"])
        self.svc.resolve_report(op, rid["report_id"], "소관 부서 확인 후 v2에서 수정")
        self.assertEqual(self.svc.reports(op)[0]["status"], "resolved")


class Catalogs(unittest.TestCase):
    def test_spec_round_trip(self):
        values = {"title": "시험", "domain": "차량", "columns": ["a", "b"], "access_level": "공개", "label_available": None}
        text, sources = render_spec(values)
        parsed, psrc, warnings = parse_spec(text)
        self.assertEqual(parsed["columns"], ["a", "b"])
        self.assertIsNone(parsed["label_available"])
        self.assertEqual(psrc, sources)
        self.assertEqual(warnings, [])

    def test_extract_marks_unknown_and_create_draft(self):
        svc = make_service()
        own = login(svc, "own1")
        text = "제목: 차량 타이어 교체 기록\n분야: 차량\n정답표시 유무: 미확인\n공개 범위: 거점승인\n열람 가능 역할: researcher\n원문 문서: (가상) 명세서\n이상한항목: x"
        ex = svc.extract(own, text)
        self.assertIsNone(ex["values"]["label_available"])
        self.assertTrue(any("알 수 없는 항목" in w for w in ex["warnings"]))
        r = svc.create_catalog(own, {"text": text, "domain_code": "VEH"})
        self.assertEqual(r["catalog_id"], "CAT-VEH-008")
        v = svc.store.version(r["catalog_id"], 1)
        self.assertEqual(v["status"], "draft")
        self.assertEqual(v["values"]["department"], "(가상) 군수정비부서")
        self.assertEqual(v["sources"]["title"], 1)

    def test_approve_requires_required_fields(self):
        svc = make_service()
        adm = login(svc, "adm1")
        r = svc.create_catalog(adm, {"values": {"title": "필수 누락"}, "domain_code": "TST"})
        from app.service import ServiceError
        with self.assertRaises(ServiceError):
            svc.approve_catalog(adm, r["catalog_id"], 1)


if __name__ == "__main__":
    unittest.main()
