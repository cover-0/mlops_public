#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1-5-feature-rule-skew.py
제1장 — 같은 이름의 피처를 두 경로가 다른 규칙으로 계산하면 어떻게 갈라지는가.

피처 pm10_bad("이 측정소의 PM10이 나쁜 상태인가")를 두 경로로 만든다.
  학습 경로: API가 함께 준 pm10Grade를 그대로 쓴다(2 이상이면 나쁨).
  서빙 경로: pm10Value 하나만 받아 임계로 등급을 다시 계산한다.
두 경로 모두 오류 없이 끝나지만 같은 측정소를 다르게 판정한다.

끝으로 두 시점의 실제 호출 결과를 나란히 놓아, 코드를 고치지 않아도
입력 분포가 달라진다는 사실(드리프트)을 확인한다.

인증키 없이 실행된다. 외부 네트워크를 쓰지 않고 저장된 실제 산출물
data/output/ch1_airquality_live_raw.json 과 ch1_api_summary.json 을 읽기만 한다.
난수를 쓰지 않는다.

실행:
    python3 code/1-5-feature-rule-skew.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
RAW_PATH = OUTPUT_DIR / "ch1_airquality_live_raw.json"
SUMMARY_PATH = OUTPUT_DIR / "ch1_api_summary.json"
REPORT_PATH = OUTPUT_DIR / "ch1_feature_skew.json"

# 서빙 경로가 값에서 등급을 다시 만들 때 쓰는 임계(구성값).
SERVING_THRESHOLD = 30
# 임계를 바꿔 가며 시험할 범위(구성값).
THRESHOLD_SCAN = range(10, 35)


def label_from_grade(grade: Any) -> int | None:
    """학습 경로 — API가 준 등급으로 나쁨 여부를 정한다."""
    if grade is None:
        return None
    try:
        return 1 if int(str(grade).strip()) >= 2 else 0
    except ValueError:
        return None


def label_from_value(value: Any, threshold: int) -> int | None:
    """서빙 경로 — 값 하나에 임계를 걸어 나쁨 여부를 정한다."""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-"):
        return None
    try:
        return 1 if float(s) >= threshold else 0
    except ValueError:
        return None


def main() -> int:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = raw["response"]["body"]["items"]

    rows = []
    for rec in items:
        rows.append({
            "station": rec.get("stationName"),
            "value": rec.get("pm10Value"),
            "grade": rec.get("pm10Grade"),
            "train": label_from_grade(rec.get("pm10Grade")),
        })
    comparable = [r for r in rows if r["train"] is not None]

    print("[1] 피처 정의 — pm10_bad: 이 측정소의 PM10이 나쁜 상태인가(1/0)")
    print(f"    측정소 {len(rows)}곳 중 pm10Grade가 있는 곳 {len(comparable)}곳")
    no_grade = [r["station"] for r in rows if r["train"] is None]
    print(f"    등급이 비어 있어 비교에서 빠진 곳: {', '.join(no_grade) or '없음'}")

    train_bad = sum(r["train"] for r in comparable)
    print()
    print("[2] 학습 경로 — API가 준 pm10Grade를 그대로 사용")
    print(f"    나쁨(등급 2 이상) {train_bad}곳 / {len(comparable)}곳")

    print()
    print(f"[3] 서빙 경로 — pm10Value에 임계 {SERVING_THRESHOLD}을 걸어 등급을 다시 계산")
    serve = [label_from_value(r["value"], SERVING_THRESHOLD) for r in comparable]
    serve_bad = sum(v for v in serve if v is not None)
    mismatch = [(r["station"], int(str(r["value"])), r["grade"], r["train"], s)
                for r, s in zip(comparable, serve) if s != r["train"]]
    print(f"    나쁨 {serve_bad}곳 / {len(comparable)}곳")
    print(f"    학습 경로와 어긋난 측정소 {len(mismatch)}곳")
    for station, value, grade, t, s in mismatch[:5]:
        print(f"      {station:<8} pm10Value={value:<3} pm10Grade={grade}  "
              f"학습={t} 서빙={s}")
    if len(mismatch) > 5:
        print(f"      … 외 {len(mismatch) - 5}곳")
    print("    두 경로 모두 예외를 내지 않는다. 어긋난 것은 오류가 아니라 값이다")

    print()
    print("[4] 임계를 바꾸면 맞출 수 있는가 — 10부터 34까지 전부 시험")
    scan = []
    for t in THRESHOLD_SCAN:
        labels = [label_from_value(r["value"], t) for r in comparable]
        mm = sum(1 for r, s in zip(comparable, labels) if s != r["train"])
        scan.append({"threshold": t, "mismatch": mm})
    best = min(scan, key=lambda d: d["mismatch"])
    print(f"    어긋남이 가장 적은 임계 {best['threshold']}  그래도 {best['mismatch']}곳이 어긋남")
    print(f"    임계 {SERVING_THRESHOLD}일 때 {len(mismatch)}곳, "
          f"임계 {best['threshold']}일 때 {best['mismatch']}곳 — 0이 되는 임계는 없다")

    g1 = [int(str(r["value"])) for r in comparable if r["train"] == 0]
    g2 = [int(str(r["value"])) for r in comparable if r["train"] == 1]
    print()
    print("[5] 0이 되는 임계가 없는 이유 — 값의 범위가 겹친다")
    print(f"    학습 라벨 0(등급 1)  {len(g1)}곳  pm10Value {min(g1)}~{max(g1)}")
    print(f"    학습 라벨 1(등급 2)  {len(g2)}곳  pm10Value {min(g2)}~{max(g2)}")
    overlap = sorted(set(g1) & set(g2))
    print(f"    두 범위가 겹치는 값: {', '.join(map(str, overlap))}")
    print("    같은 21이 어떤 측정소에서는 라벨 0, 다른 측정소에서는 라벨 1이다")
    print("    값 하나만으로는 등급을 되만들 수 없다 — 두 필드가 같은 규칙으로 만들어지지 않았다")

    print()
    print("[6] 규칙을 맞춰도 남는 것 — 입력 자체가 시간이 지나면 달라진다")
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    raw_time = sorted({str(r["dataTime"]) for r in items})[0]
    pm10_vals = [float(r["pm10Value"]) for r in items
                 if str(r["pm10Value"]).strip() not in ("", "-")]
    raw_mean = round(sum(pm10_vals) / len(pm10_vals), 1)
    print(f"    {raw_time}  측정소 {len(items)}개  pm10 평균 {raw_mean}  "
          f"결측 {len(items) - len(pm10_vals)}건   (ch1_airquality_live_raw.json)")
    print(f"    {summary['data_time_min']}  측정소 {summary['station_count']}개  "
          f"pm10 평균 {summary['pm10_avg']}  결측 {summary['pm10_missing']}건   "
          f"(ch1_api_summary.json)")
    print("    코드는 한 줄도 바뀌지 않았다. 계절과 시각이 모두 달라 원인을 하나로 지목할 수는 없다")
    print("    지목할 수 있는 사실은 하나다 — 같은 코드가 받는 값이 시간이 지나면 달라진다")

    report = {
        "source_files": [
            RAW_PATH.relative_to(PROJECT_ROOT).as_posix(),
            SUMMARY_PATH.relative_to(PROJECT_ROOT).as_posix(),
        ],
        "feature": "pm10_bad",
        "station_count": len(rows),
        "comparable_count": len(comparable),
        "stations_without_grade": no_grade,
        "train_path_bad": train_bad,
        "serving_threshold": SERVING_THRESHOLD,
        "serving_path_bad": serve_bad,
        "mismatch_count": len(mismatch),
        "mismatch_stations": [
            {"station": s, "pm10Value": v, "pm10Grade": g, "train": t, "serving": sv}
            for s, v, g, t, sv in mismatch
        ],
        "threshold_scan": scan,
        "best_threshold": best,
        "value_range_label0": {"count": len(g1), "min": min(g1), "max": max(g1)},
        "value_range_label1": {"count": len(g2), "min": min(g2), "max": max(g2)},
        "overlapping_values": overlap,
        "two_calls": {
            "raw": {"data_time": raw_time, "station_count": len(items),
                    "pm10_avg": raw_mean,
                    "pm10_missing": len(items) - len(pm10_vals)},
            "summary": {"data_time": summary["data_time_min"],
                        "station_count": summary["station_count"],
                        "pm10_avg": summary["pm10_avg"],
                        "pm10_missing": summary["pm10_missing"]},
        },
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print(f"[7] 산출물 → {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
