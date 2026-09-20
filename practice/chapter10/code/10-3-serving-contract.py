#!/usr/bin/env python3
"""10장 실습: 서빙 API가 지켜야 할 계약 — 신원 응답·예측·입력 검증.

`10-1-model-api/app.py`는 FastAPI와 pydantic으로 이 계약을 집행한다. 이 스크립트는
같은 규칙(자치구 코드 5자리 숫자, 전일 건수 0 이상 정수)을 표준 라이브러리로 다시
써서, 어떤 요청이 모델에 닿고 어떤 요청이 닿기 전에 거절되는지 눈으로 보인다.

입력: practice/chapter9/data/output/ch9_experiment_report.json (champion 신원·훈련 쌍)
출력: practice/chapter10/data/output/ch10_serving_contract.json

실행: python code/10-3-serving-contract.py   (cwd: practice/chapter10)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CH9_REPORT = BASE_DIR.parents[0] / "chapter9" / "data" / "output" / "ch9_experiment_report.json"
OUTPUT = BASE_DIR / "data" / "output" / "ch10_serving_contract.json"

MODEL_NAME = "complaint_daily_forecaster"
LAWD_CD = re.compile(r"^\d{5}$")        # app.py의 pydantic Field(pattern=...)과 같은 규칙

# 실제 서울 자치구 코드(practice/chapter6/data/input/lawd_cd_seoul.csv에 있는 값)
KNOWN_DISTRICTS = {"11440", "11620", "11680"}

# 요청 사례는 고정이다 — 난수를 쓰지 않는다. 앞의 셋은 test_app.py가 검증하는 사례와 같다.
CASES = [
    {"label": "정상 — 강남구, 전일 9건", "body": {"lawd_cd": "11680", "x_prev_count": 9}},
    {"label": "정상 — 마포구, 전일 0건", "body": {"lawd_cd": "11440", "x_prev_count": 0}},
    {"label": "음수 건수", "body": {"lawd_cd": "11680", "x_prev_count": -1}},
    {"label": "코드 자리에 한글", "body": {"lawd_cd": "강남구", "x_prev_count": 9}},
    {"label": "필드 누락", "body": {"x_prev_count": 9}},
    {"label": "코드 4자리", "body": {"lawd_cd": "1168", "x_prev_count": 9}},
    {"label": "형식은 맞지만 없는 자치구", "body": {"lawd_cd": "99999", "x_prev_count": 9}},
]


def load_identity() -> dict:
    """9장 레지스트리 판정에서 champion 신원을 가져온다."""
    r = json.loads(CH9_REPORT.read_text(encoding="utf-8"))
    return {"model_name": MODEL_NAME,
            "model_version": str(r["registry"]["champion_version"]),
            "model_source": "registry-alias"}


def validate(body: dict) -> list[str]:
    """모델에 닿기 전 스키마 계약. 위반 사유 목록을 돌려준다(빈 목록이면 통과)."""
    errs = []
    if "lawd_cd" not in body:
        errs.append("lawd_cd 필드 누락")
    elif not isinstance(body["lawd_cd"], str) or not LAWD_CD.match(body["lawd_cd"]):
        errs.append("lawd_cd는 5자리 숫자 문자열이어야 함")
    if "x_prev_count" not in body:
        errs.append("x_prev_count 필드 누락")
    elif not isinstance(body["x_prev_count"], int) or body["x_prev_count"] < 0:
        errs.append("x_prev_count는 0 이상 정수여야 함")
    return errs


def main() -> int:
    r = json.loads(CH9_REPORT.read_text(encoding="utf-8"))
    identity = load_identity()
    mean_y = sum(p["y_count"] for p in r["training_pairs"]) / len(r["training_pairs"])

    print("[1] GET /health — 살아 있는가가 아니라 무엇을 서빙 중인가")
    health = {"status": "ok", **identity, "shadow_enabled": True}
    for k, v in health.items():
        print(f"    {k:<16} {v}")
    print(f"    model_version {identity['model_version']} 은 9장이 champion으로 승격한 버전이다")

    print(f"\n[2] POST /predict — 요청 {len(CASES)}건을 계약에 통과시킨다")
    results, ok_n, rejected_n = [], 0, 0
    for c in CASES:
        errs = validate(c["body"])
        if errs:
            rejected_n += 1
            row = {"label": c["label"], "body": c["body"], "status": 422,
                   "reason": errs, "forecast": None}
            print(f"    422  {c['label']:<22} {c['body']}")
            print(f"         └ {'; '.join(errs)}")
        else:
            ok_n += 1
            row = {"label": c["label"], "body": c["body"], "status": 200,
                   "reason": [], "forecast": round(mean_y, 4), **identity}
            print(f"    200  {c['label']:<22} {c['body']} → forecast {round(mean_y, 4)}")
        results.append(row)
    print(f"    통과 {ok_n}건 / 거절 {rejected_n}건")

    print("\n[3] 스키마 계약이 보는 것과 보지 않는 것")
    unknown = [x for x in results
               if x["status"] == 200 and x["body"]["lawd_cd"] not in KNOWN_DISTRICTS]
    print(f"    형식을 어겨 거절된 요청 {rejected_n}건")
    print(f"    형식은 맞지만 사전에 없는 자치구 코드가 통과한 요청 {len(unknown)}건"
          f" — {[x['body']['lawd_cd'] for x in unknown]}")
    print("    스키마는 값의 모양만 본다. 그 코드가 실제로 있는지는 표준 코드 사전(6주차 실습 입력)이 판정한다")

    print("\n[4] 응답에 신원을 실을 때와 싣지 않을 때")
    with_id = results[0]
    without_id = {"forecast": with_id["forecast"]}
    print(f"    신원 있음 {len([k for k in with_id if k in ('forecast', *identity)])}개 필드"
          f" — forecast {with_id['forecast']}, {identity['model_name']} v{identity['model_version']},"
          f" 출처 {identity['model_source']}")
    print(f"    신원 없음 {len(without_id)}개 필드 — forecast {without_id['forecast']}")
    print("    '이 예측을 만든 모델이 무엇인가'에 답할 수 있는 쪽은 앞의 응답뿐이다")

    result = {
        "health": health,
        "cases": results,
        "summary": {"total": len(CASES), "accepted": ok_n, "rejected_422": rejected_n,
                    "accepted_but_unknown_district": len(unknown)},
        "identity_fields": sorted(identity),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\n증거 파일: {OUTPUT}")
    print("CH10_SERVING_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
