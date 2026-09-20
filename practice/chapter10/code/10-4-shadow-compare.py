#!/usr/bin/env python3
"""10장 실습: shadow 배포 — 실패 반경을 0으로 두고 후보를 실요청 위에서 재평가한다.

응답은 항상 champion 것만 나가고, challenger는 같은 요청을 받아 로그에만 값을 남긴다.
`10-1-model-api/app.py`가 FastAPI 위에서 하는 일과 같은 동작을 표준 라이브러리로 다시
계산해, 이용자가 받는 값과 로그에만 남는 값이 얼마나 갈리는지 보인다.

입력: practice/chapter9/data/output/ch9_experiment_report.json (훈련 쌍 6개·계수)
출력: practice/chapter10/data/output/ch10_shadow_compare.json

실행: python code/10-4-shadow-compare.py   (cwd: practice/chapter10)
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CH9_REPORT = BASE_DIR.parents[0] / "chapter9" / "data" / "output" / "ch9_experiment_report.json"
PAST_RUN = BASE_DIR / "data" / "output" / "ch10_deploy_report.json"
OUTPUT = BASE_DIR / "data" / "output" / "ch10_shadow_compare.json"

# 강남구의 최신 전일 건수 — 과거 실행이 /predict로 보낸 것과 같은 입력
LATEST_REQUEST = {"lawd_cd": "11680", "x_prev_count": 9}


def fit(pairs: list[dict]) -> tuple[float, float, float]:
    n = len(pairs)
    xs = [float(p["x_prev_count"]) for p in pairs]
    ys = [float(p["y_count"]) for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return my, my - slope * mx, slope


def main() -> int:
    r = json.loads(CH9_REPORT.read_text(encoding="utf-8"))
    pairs = r["training_pairs"]
    mean_y, intercept, slope = fit(pairs)
    champion = lambda x: mean_y                      # noqa: E731
    challenger = lambda x: intercept + slope * x     # noqa: E731

    print(f"[1] 두 모델을 같은 훈련 쌍 {len(pairs)}개로 적합")
    print(f"    champion   v1 평균 예측기      상수 {round(mean_y, 4)}")
    print(f"    challenger v2 선형회귀        절편 {intercept:.4f}  기울기 {slope:.4f}")
    ch9_coef = r["runs"]["linear"]["coef"]
    coef_match = (round(intercept, 4) == ch9_coef["intercept"]
                  and round(slope, 4) == ch9_coef["slope"])
    print(f"    9장이 기록한 계수 {ch9_coef} 와 일치: {'예' if coef_match else '아니오'}")

    print(f"\n[2] shadow 호출 — 훈련 쌍의 전일 건수를 그대로 요청 {len(pairs)}건으로 보낸다")
    print(f"    {'자치구':<8}{'전일':>5}{'이용자가 받는 값':>14}{'로그에만 남는 값':>16}{'차이':>9}")
    log = []
    for p in pairs:
        x = p["x_prev_count"]
        c, s = round(champion(x), 4), round(challenger(x), 4)
        log.append({"lawd_cd": p["lawd_cd"], "x_prev_count": x,
                    "champion_forecast": c, "challenger_forecast": s,
                    "y_true": p["y_count"]})
        print(f"    {p['lawd_cd']:<8}{x:>5}{c:>14}{s:>16}{round(s - c, 4):>9}")
    print(f"    이용자에게 나간 응답 {len(log)}건 전부 champion 값 — challenger는 한 건도 닿지 않았다")

    print("\n[3] 과거 실행이 남긴 shadow 관찰과 대조")
    c9 = round(champion(LATEST_REQUEST["x_prev_count"]), 4)
    s9 = round(challenger(LATEST_REQUEST["x_prev_count"]), 4)
    print(f"    이번 계산  전일 {LATEST_REQUEST['x_prev_count']} → champion {c9} / challenger {s9}")
    past_match = None
    if PAST_RUN.exists():
        past = json.loads(PAST_RUN.read_text(encoding="utf-8"))["shadow_observation"]
        past_match = (past["champion_forecast"] == c9 and past["challenger_forecast"] == s9)
        print(f"    과거 실행  전일 {past['x_prev_count']} → champion {past['champion_forecast']}"
              f" / challenger {past['challenger_forecast']}")
        print(f"    (출처 {PAST_RUN.name} — 일치: {'예' if past_match else '아니오'})")
    print(f"    두 값의 차이 {round(s9 - c9, 4)} 가 이 절의 관찰 자료다")

    print(f"\n[4] 로그만으로 후보를 재평가 — 요청 {len(log)}건의 절대오차 평균")
    # 반올림 전 값으로 센다 — 로그에 적힌 4자리 값으로 세면 마지막 자리가 9장과 갈린다
    mae_c = sum(abs(champion(e["x_prev_count"]) - e["y_true"]) for e in log) / len(log)
    mae_s = sum(abs(challenger(e["x_prev_count"]) - e["y_true"]) for e in log) / len(log)
    print(f"    champion   {round(mae_c, 4)}")
    print(f"    challenger {round(mae_s, 4)}")
    print(f"    9장 기록  champion {r['runs']['baseline_mean']['train_mae']}"
          f" / challenger {r['runs']['linear']['train_mae']}")
    print(f"    후보가 더 낫지 않음 — 승격 보류 판정이 실요청 위에서도 유지된다"
          if mae_s >= mae_c else "    후보가 더 나음 — 승격 검토 대상")

    print("\n[5] challenger가 요청 처리 중 죽으면")
    served, shadow_fail = 0, 0
    for e in log:
        try:
            if e["x_prev_count"] >= 8:
                raise RuntimeError("challenger 예측 실패")
            _ = e["challenger_forecast"]
        except RuntimeError:
            shadow_fail += 1
        served += 1                      # 응답은 shadow와 무관하게 나간다
    print(f"    shadow 실패 {shadow_fail}건 / 이용자에게 나간 응답 {served}건")
    print("    실패 반경 0 — 후보가 무엇을 하든 이용자 응답은 champion 경로로만 만들어진다")

    result = {
        "models": {"champion_constant": round(mean_y, 4),
                   "challenger_intercept": round(intercept, 4),
                   "challenger_slope": round(slope, 4),
                   "coef_matches_ch9": coef_match},
        "shadow_log": log,
        "latest_request": {**LATEST_REQUEST,
                           "champion_forecast": c9, "challenger_forecast": s9,
                           "gap": round(s9 - c9, 4),
                           "matches_past_run": past_match},
        "reevaluation": {"champion_mae": round(mae_c, 4), "challenger_mae": round(mae_s, 4),
                         "challenger_better": mae_s < mae_c},
        "blast_radius": {"shadow_failures": shadow_fail, "responses_served": served,
                         "responses_affected": 0},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\n증거 파일: {OUTPUT}")
    print("CH10_SHADOW_COMPARE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
