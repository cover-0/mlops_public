#!/usr/bin/env python3
"""10장 실습: 배치 추론과 온라인 추론은 실패의 형태가 다르다.

`10-1-model-api/`는 mlflow·FastAPI·Docker가 있어야 돌아간다. 이 스크립트는 같은
모델 두 개(9장 champion=평균 예측기, challenger=선형회귀)를 표준 라이브러리만으로
다시 만들어, **예측을 언제 계산하는가**가 실패를 어떤 모양으로 만드는지 보인다.

입력: practice/chapter9/data/output/ch9_experiment_report.json 의 훈련 쌍 6개
      (8장 피처 스냅숏에서 만든 (전일 건수 → 당일 건수) 쌍. 난수 없음)
출력: practice/chapter10/data/output/ch10_batch_vs_online.json

실행: python code/10-2-batch-vs-online.py   (cwd: practice/chapter10)
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]          # practice/chapter10
CH9_REPORT = BASE_DIR.parents[0] / "chapter9" / "data" / "output" / "ch9_experiment_report.json"
OUTPUT = BASE_DIR / "data" / "output" / "ch10_batch_vs_online.json"

EXPECTED_FP = "96f6b6b3ce9dcdd1da62e0284e0ceea1ec2afec24c522f6df3221ad0ab31f49e"
# 조회가 일어나는 날짜는 구성값이다 — 원자료에 조회 시각이 없다. 난수를 쓰지 않고 고정한다.
D_MINUS_1 = "2026-07-02"
D_TODAY = "2026-07-03"


def load_pairs() -> list[dict]:
    """9장이 남긴 훈련 쌍을 읽는다. 지문이 다르면 다른 데이터이므로 즉시 멈춘다."""
    report = json.loads(CH9_REPORT.read_text(encoding="utf-8"))
    if report["data_fingerprint_sha256"] != EXPECTED_FP:
        raise SystemExit("지문 불일치 — 9장 스냅숏과 다른 데이터다")
    return report["training_pairs"]


def fit_mean(pairs: list[dict]) -> float:
    """champion(v1) — 입력을 보지 않고 훈련 y의 평균을 답한다."""
    return sum(p["y_count"] for p in pairs) / len(pairs)


def fit_linear(pairs: list[dict]) -> tuple[float, float]:
    """challenger(v2) — 최소제곱 직선. 9장 계수(3.6818, 0.4091)와 같아야 한다."""
    n = len(pairs)
    xs = [float(p["x_prev_count"]) for p in pairs]
    ys = [float(p["y_count"]) for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return my - slope * mx, slope


def daily_inputs(pairs: list[dict]) -> tuple[dict, dict]:
    """자치구별로 첫 쌍의 x를 어제 입력, 둘째 쌍의 x를 오늘 입력으로 쓴다."""
    prev, today = {}, {}
    for p in pairs:
        cd = p["lawd_cd"]
        (prev if cd not in prev else today)[cd] = p["x_prev_count"]
    return prev, today


def batch_table(inputs: dict, predict, as_of: str) -> dict:
    """밤 배치 — 자치구 전부의 익일 예측을 미리 계산해 표에 넣어 둔다."""
    return {"as_of": as_of,
            "rows": {cd: round(predict(x), 4) for cd, x in sorted(inputs.items())}}


def main() -> int:
    pairs = load_pairs()
    prev_in, today_in = daily_inputs(pairs)
    mean_y = fit_mean(pairs)
    intercept, slope = fit_linear(pairs)

    champion = lambda x: mean_y                      # noqa: E731 — 평균 예측기
    challenger = lambda x: intercept + slope * x     # noqa: E731 — 선형회귀

    print(f"[1] 입력 — 9장 훈련 쌍 {len(pairs)}개, 자치구 {len(prev_in)}개")
    print(f"    지문 {EXPECTED_FP[:16]}… (9장 산출물과 동일)")
    print(f"    champion(평균 예측기) 훈련 y 평균 {sum(p['y_count'] for p in pairs)}/{len(pairs)} = {mean_y}")
    print(f"    challenger(선형회귀) 절편 {intercept:.4f}  기울기 {slope:.4f}")
    print(f"    자치구별 전일 건수  어제({D_MINUS_1}) {prev_in}  오늘({D_TODAY}) {today_in}")

    tables = {}
    for name, fn in (("champion", champion), ("challenger", challenger)):
        tables[name] = {"prev": batch_table(prev_in, fn, D_MINUS_1),
                        "today": batch_table(today_in, fn, D_TODAY)}

    print("\n[2] 배치 추론 — 밤에 자치구 전부를 미리 계산해 표로 저장")
    for name in ("champion", "challenger"):
        t = tables[name]
        print(f"    {name:<11} 어제 표 {t['prev']['rows']}")
        print(f"    {'':<11} 오늘 표 {t['today']['rows']}")

    print(f"\n[3] 오늘 밤 배치가 죽었다 — 낮의 조회 {len(prev_in)}건은 어제 표를 그대로 읽는다")
    stale_gap = {}
    for name in ("champion", "challenger"):
        served = tables[name]["prev"]["rows"]
        correct = tables[name]["today"]["rows"]
        gaps = {cd: round(correct[cd] - served[cd], 4) for cd in served if correct[cd] != served[cd]}
        stale_gap[name] = gaps
        print(f"    {name:<11} 조회 {len(served)}건 전부 성공, 오류 0건, 응답 코드 200")
        print(f"    {'':<11} 낸 값 {served}")
        print(f"    {'':<11} 오늘 값과 어긋난 자치구 {len(gaps)}개 {gaps if gaps else '(없음)'}")

    print("\n[4] 온라인 추론이 같은 이유로 죽으면")
    online_errors = 0
    for cd in sorted(today_in):
        try:
            raise RuntimeError("모델 로드 실패")
        except RuntimeError as e:
            online_errors += 1
            print(f"    {cd} 요청 → 즉시 실패: {e}")
    print(f"    조회 {len(today_in)}건 중 실패 {online_errors}건 — 아무도 모르고 지나갈 수 없다")

    print("\n[5] 배치의 낡음을 조회가 판정하려면 — 표에 기준일을 함께 저장한다")
    served_as_of = tables["champion"]["prev"]["as_of"]
    stale = served_as_of != D_TODAY
    print(f"    표의 기준일 {served_as_of} / 조회한 날 {D_TODAY} → 낡음 판정 {'예' if stale else '아니오'}")
    print(f"    기준일이 없으면 같은 조회 {len(prev_in)}건이 전부 정상으로 보인다")

    result = {
        "inputs": {"pairs": len(pairs), "districts": sorted(prev_in),
                   "prev_day": {"as_of": D_MINUS_1, "x_prev_count": prev_in},
                   "today": {"as_of": D_TODAY, "x_prev_count": today_in},
                   "note": "조회 날짜는 구성값 — 원자료에 조회 시각이 없다"},
        "models": {"champion_mean": round(mean_y, 4),
                   "challenger_intercept": round(intercept, 4),
                   "challenger_slope": round(slope, 4)},
        "batch_tables": tables,
        "batch_failure": {"queries": len(prev_in), "errors": 0, "status_code": 200,
                          "stale_gap": stale_gap},
        "online_failure": {"queries": len(today_in), "errors": online_errors},
        "staleness_detectable_by_as_of": stale,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(f"\n증거 파일: {OUTPUT}")
    print("CH10_BATCH_VS_ONLINE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
