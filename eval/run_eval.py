"""평가 시나리오 실행과 기준선 비교 (PRD 13장).

실행: python eval/run_eval.py [--split tune|eval|all]
결과: reports/eval_report.md

주의: 시나리오의 기대 후보는 개발자가 작성한 점검용 값이다. 전문가 사전 판정으로 교체하기 전에는
'추천 적합성' 지표로 보고하지 않는다.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.service import Service  # noqa: E402
from app.textutil import normalize, tokens  # noqa: E402


def baseline(svc, user, purpose, query, k):
    """기존 목록·키워드 검색 흉내: 권한 내 카탈로그 제목에 질의 단어가 들어 있는지만 본다."""
    docs, _ = svc._visible_docs(user, purpose)
    q = tokens(query)
    scored = []
    for d in docs:
        title = normalize(d["values"].get("title") or "")
        hits = sum(1 for t in q if t in title)
        if hits:
            scored.append((-hits, d["id"]))
    return [cid for _, cid in sorted(scored)[:k]]


def grounding(svc, cand):
    """설명의 '사실' 항목이 원문 행과 일치하는지 자동 검사한다(검증 가능한 주장 중 원문 뒷받침 비율)."""
    """근거 문장에 인용한 값(quote)이 연결된 원문 행에 그대로 있는지 검사한다."""
    expl = cand.get("explanation") or {}
    lines = (svc.store.version(cand["catalog_id"], cand["version"])["source_text"] or "").splitlines()
    ok = total = 0
    for f in expl.get("reasons", []) + expl.get("methods", []) + expl.get("checks", []):
        q = f.get("quote")
        if q is None:
            continue
        total += 1
        ln = f.get("source_line")
        if ln and 0 < ln <= len(lines) and str(q)[:40] in lines[ln - 1]:
            ok += 1
    return ok, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["tune", "eval", "all"])
    ap.add_argument("--out", default=os.path.join(BASE, "reports", "eval_report.md"))
    args = ap.parse_args()

    svc = Service(BASE, db_path=":memory:", clock=lambda: datetime(2026, 11, 3, 10, 0, 0))
    k = svc.cfg["top_k"]
    data = json.load(open(os.path.join(BASE, "data", "scenarios.json"), encoding="utf-8"))
    pw = {u["id"]: u["password"] for u in json.load(open(os.path.join(BASE, "data", "users.json"), encoding="utf-8"))["users"]}
    scen = [s for s in data["scenarios"] if args.split == "all" or s["split"] == args.split]

    rows = []
    agg = {"sys_p": [], "sys_r": [], "base_p": [], "base_r": [], "abstain_ok": [], "base_abstain_ok": [],
           "leak": 0, "ground_ok": 0, "ground_total": 0, "lat": [], "clarified": 0}
    for s in scen:
        if s["user"] == svc.cfg["demo_user"]:
            sess = svc.demo_session()
        else:
            sess = svc.session(svc.login(s["user"], pw[s["user"]]))
            svc.set_purpose(sess, s["purpose"])
        t0 = time.perf_counter()
        r = svc.recommend(sess, {"query": s["query"], "answers": s.get("answers"), "skip_clarify": s.get("skip_clarify")})
        clarified = r["status"] == "clarify"
        if clarified:
            agg["clarified"] += 1
            r = svc.recommend(sess, {"query": s["query"], "answers": s.get("answers"), "skip_clarify": True})
        agg["lat"].append((time.perf_counter() - t0) * 1000)
        got = [c["catalog_id"] for c in r.get("candidates", [])]
        base = baseline(svc, sess["user"], s["purpose"], s["query"], k)
        rel = set(s["relevant"])

        visible = {d["id"] for d in svc._visible_docs(sess["user"], s["purpose"])[0]}
        leaks = [c for c in got if c not in visible]
        agg["leak"] += len(leaks)
        for c in r.get("candidates", []):
            a, b = grounding(svc, c)
            agg["ground_ok"] += a
            agg["ground_total"] += b

        if s["expect"] == "ok":
            agg["sys_p"].append(len([g for g in got if g in rel]) / len(got) if got else 0.0)
            agg["sys_r"].append(len([g for g in got if g in rel]) / len(rel))
            agg["base_p"].append(len([g for g in base if g in rel]) / len(base) if base else 0.0)
            agg["base_r"].append(len([g for g in base if g in rel]) / len(rel))
        elif s["expect"] == "abstain":
            agg["abstain_ok"].append(r["status"] == "abstain")
            agg["base_abstain_ok"].append(not base)
        rows.append((s, r["status"], clarified, got, base, leaks))

    def mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    def pct(x):
        return "-" if x != x else f"{x * 100:.1f}%"

    lines = [
        "# 평가 보고서 (자동 생성)", "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 범위: {args.split} ({len(scen)}건) · 후보 수 k={k}",
        f"- 모델·인덱스 버전: `{json.dumps(svc.model_versions(), ensure_ascii=False)}`", "",
        "> 기대 후보는 개발자가 쓴 **점검용 가상 값**입니다. 전문가 2인 이상의 사전 판정(PRD 13-1)으로 바꾸기 전에는",
        "> 아래 수치를 '추천 적합성' 실적으로 보고하지 마세요. 권한 위반 0건도 이 시험 범위 안의 결과일 뿐입니다.", "",
        "## 요약", "",
        "| 지표 | 시제품 | 기준선(제목 키워드) |", "|---|---|---|",
        f"| 상위 {k}건 정밀도(평균) | {pct(mean(agg['sys_p']))} | {pct(mean(agg['base_p']))} |",
        f"| 상위 {k}건 재현율(평균) | {pct(mean(agg['sys_r']))} | {pct(mean(agg['base_r']))} |",
        f"| 답변 보류 정확도(정답 없는 질의) | {pct(mean(agg['abstain_ok']))} | {pct(mean(agg['base_abstain_ok']))} |",
        f"| 권한 밖 후보 노출 | {agg['leak']}건 | - |",
        f"| 근거 일치도(사실 항목 ↔ 원문 행, 자동) | {pct(agg['ground_ok'] / agg['ground_total'] if agg['ground_total'] else float('nan'))} ({agg['ground_ok']}/{agg['ground_total']}) | - |",
        f"| 추가 질문 발생 | {agg['clarified']}건 | - |",
        f"| 처리시간 중앙값(인메모리, 단일 사용자) | {sorted(agg['lat'])[len(agg['lat']) // 2]:.1f} ms | - |",
        "", "## 시나리오별", "",
        "| ID | 분할 | 질의 | 기대 | 결과 | 시제품 후보(●=기대 후보) | 기준선 |", "|---|---|---|---|---|---|---|",
    ]
    for s, status, clar, got, base, leaks in rows:
        rel = set(s["relevant"])
        g = ", ".join(("●" if c in rel else "") + c for c in got) or "(보류)"
        b = ", ".join(("●" if c in rel else "") + c for c in base) or "(없음)"
        st = status + (" · 추가질문" if clar else "") + (f" · 누출 {len(leaks)}" if leaks else "")
        lines.append(f"| {s['id']} | {s['split']} | {s['query']} | {s['expect']} | {st} | {g} | {b} |")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[8:18]))
    print(f"\n보고서: {args.out}")


if __name__ == "__main__":
    main()
