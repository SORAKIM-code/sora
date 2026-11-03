"""엑셀 카탈로그 도구.

  python tools/catalog_excel.py export 파일.xlsx            가상 카탈로그(data/catalogs.json)로 견본 엑셀 만들기
  python tools/catalog_excel.py export 파일.xlsx --current  지금 서비스 DB 의 카탈로그를 엑셀로 내보내기
  python tools/catalog_excel.py check  파일.xlsx            반영하지 않고 검사만
  python tools/catalog_excel.py import 파일.xlsx            서비스 DB 에 반영(실행 중인 서버에도 바로 적용)
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.excel_catalog import parse_workbook  # noqa: E402
from app.service import Service, ServiceError  # noqa: E402
from app.xlsx import XlsxError  # noqa: E402


def report(errors, warnings):
    for e in errors:
        print("  [오류]", e)
    for w in warnings:
        print("  [주의]", w)


def main():
    ap = argparse.ArgumentParser(description="엑셀 카탈로그 도구")
    ap.add_argument("command", choices=["export", "check", "import"])
    ap.add_argument("path")
    ap.add_argument("--current", action="store_true", help="export: 서비스 DB 기준으로 내보내기")
    a = ap.parse_args()
    try:
        if a.command == "export":
            if a.current:
                svc = Service(BASE)
            else:
                svc = Service(BASE, db_path=":memory:", config_overrides={"catalog_excel": None})
            n = svc.export_excel(a.path)
            print(f"{n}건을 {a.path} 에 저장했습니다.")
        elif a.command == "check":
            p = parse_workbook(a.path)
            if p["fatal"]:
                print("읽을 수 없습니다:", p["fatal"])
                return 1
            st = {}
            for r in p["rows"]:
                st[r["status"]] = st.get(r["status"], 0) + 1
            print(f"'{p['sheet']}' 시트 · 읽은 카탈로그 {len(p['rows'])}건 "
                  f"(검수완료 {st.get('approved', 0)} · 검수대기 {st.get('draft', 0)} · 철회 {st.get('withdrawn', 0)}) · "
                  f"건너뛴 행 {len(p['errors'])}건")
            report(p["errors"], p["warnings"])
            return 1 if p["errors"] else 0
        else:
            svc = Service(BASE, config_overrides={"catalog_excel": None})
            r = svc.sync_excel(a.path)
            print(f"반영 완료: {r['counts']}")
            report(r["errors"], r["warnings"])
            print("주의: config.json 의 catalog_excel 파일이 이 파일과 다르면, 서비스를 다시 시작할 때 그 파일 기준으로 되돌아갑니다.")
    except (ServiceError, XlsxError) as e:
        print("실패:", getattr(e, "message", str(e)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
