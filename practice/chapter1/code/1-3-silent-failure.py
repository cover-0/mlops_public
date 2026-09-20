#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1-3-silent-failure.py
제1장 — 침묵 실패 세 가지를 실제 응답 위에서 재현한다.

  (1) 결측을 0으로 채우면 무엇이 뒤집히는가
  (2) 페이지네이션을 빠뜨리면 몇 건이 조용히 사라지는가
  (3) HTTP 상태만 보고 판단하면 무엇을 놓치는가

인증키 없이 실행된다. 외부 네트워크를 쓰지 않고, 이미 저장된 실제 응답
data/output/ch1_airquality_live_raw.json 과 요약본
data/output/ch1_api_summary.json 을 읽기만 한다. 두 파일을 바꾸지 않는다.

난수를 쓰지 않는다. (2)의 '잘린 응답'은 응답에 적힌 순서대로 앞에서 n건만
남기는 고정 규칙으로 만든다.

실행:
    python3 code/1-3-silent-failure.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
RAW_PATH = OUTPUT_DIR / "ch1_airquality_live_raw.json"
SUMMARY_PATH = OUTPUT_DIR / "ch1_api_summary.json"
REPORT_PATH = OUTPUT_DIR / "ch1_silent_failure.json"

# 페이지네이션 누락을 재현할 때 한 페이지로 가정할 건수(구성값).
TRUNCATE_ROWS = 20


def to_float(value: Any) -> float | None:
    """'21', '-', '', None 이 섞인 측정값을 float 또는 None으로 바꾼다."""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def main() -> int:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    body = raw["response"]["body"]
    header = raw["response"]["header"]
    items: list[dict[str, Any]] = body["items"]
    total_count = body["totalCount"]

    # ---------------------------------------------------------------- [1]
    nulls = Counter()
    dashes = Counter()
    for rec in items:
        for key, value in rec.items():
            if value is None:
                nulls[key] += 1
            elif str(value).strip() == "-":
                dashes[key] += 1

    print(f"[1] 이 응답의 결측 — 레코드 {len(items)}건")
    print(f"    문자열 '-'  {sum(dashes.values())}건: "
          f"{', '.join(f'{k} {v}건' for k, v in sorted(dashes.items()))}")
    print(f"    null       {sum(nulls.values())}건")
    for k, v in sorted(nulls.items()):
        print(f"      {k:<12} {v}건")
    dash_station = [r["stationName"] for r in items
                    if str(r.get("khaiValue")).strip() == "-"]
    print(f"    khaiValue가 '-'인 측정소: {', '.join(dash_station)}")
    print("    pm10Flag는 40건 모두 null인데 khaiValue는 '-'로 온다 — 결측 표기가 필드마다 다르다")

    # ---------------------------------------------------------------- [2]
    khai_all = [str(r.get("khaiValue")).strip() for r in items]
    khai_ok = [to_float(v) for v in khai_all]
    kept = [v for v in khai_ok if v is not None]
    zero_filled = [(v if v is not None else 0.0) for v in khai_ok]

    print()
    print("[2] 결측을 0으로 채우면 — khaiValue(통합대기환경지수)")
    print(f"    결측 제외   건수 {len(kept):>3}  평균 {mean(kept)}  "
          f"최소 {min(kept):.0f}  최대 {max(kept):.0f}")
    print(f"    0으로 채움  건수 {len(zero_filled):>3}  평균 {mean(zero_filled)}  "
          f"최소 {min(zero_filled):.0f}  최대 {max(zero_filled):.0f}")
    print(f"    평균은 {mean(kept)} → {mean(zero_filled)}로 조금 움직인다")
    print(f"    그런데 {dash_station[0]}의 값은 '측정 실패'에서 0, 곧 이 응답에서 가장 좋은 값이 된다")
    print(f"    최솟값이 {min(kept):.0f}에서 {min(zero_filled):.0f}으로 바뀐 것이 그 자리다")

    # ---------------------------------------------------------------- [3]
    pm10_all = [v for v in (to_float(r.get("pm10Value")) for r in items) if v is not None]
    truncated = items[:TRUNCATE_ROWS]
    pm10_trunc = [v for v in (to_float(r.get("pm10Value")) for r in truncated) if v is not None]

    print()
    print(f"[3] 페이지네이션을 빠뜨리면 — 한 페이지를 {TRUNCATE_ROWS}건으로 가정해 재현")
    print(f"    totalCount {total_count}  저장한 건수 {len(truncated)}  "
          f"조용히 빠진 건수 {total_count - len(truncated)}")
    print(f"    pm10 평균   전체 {mean(pm10_all)}  →  앞 {TRUNCATE_ROWS}건만 {mean(pm10_trunc)}")
    print("    검사를 넣지 않으면 이 실행도 예외 없이 끝나고 JSON 파일도 만들어진다")
    print(f"    막는 검사는 한 줄이다: len(items) == totalCount  "
          f"({len(truncated)} == {total_count} → {len(truncated) == total_count})")

    # ---------------------------------------------------------------- [4]
    print()
    print("[4] HTTP 상태만 검사하면")
    print(f"    이 응답의 업무 코드  resultCode={header['resultCode']}  "
          f"resultMsg={header['resultMsg']}")
    print("    업무 코드는 HTTP 상태와 별개로 response.header 안에 들어 있다")
    print("    HTTP 200만 확인하고 저장하는 코드는 이 자리를 아예 읽지 않는다")
    print(f"    막는 검사도 한 줄이다: resultCode == '00'  "
          f"(현재 {header['resultCode']!r} → {header['resultCode'] == '00'})")

    # ---------------------------------------------------------------- [5]
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    print()
    print("[5] 이번 호출에 결측이 없다는 것과 이 API에 결측이 없다는 것은 다르다")
    print(f"    {sorted({str(r['dataTime']) for r in items})[0]} 호출  "
          f"측정소 {len(items)}개  pm10 결측 "
          f"{sum(1 for r in items if to_float(r.get('pm10Value')) is None)}건   "
          f"(ch1_airquality_live_raw.json)")
    print(f"    {summary['data_time_min']} 호출  "
          f"측정소 {summary['station_count']}개  pm10 결측 {summary['pm10_missing']}건   "
          f"(ch1_api_summary.json)")
    print("    같은 코드가 같은 API를 불렀는데 한쪽은 0건, 다른 쪽은 3건이다")

    report = {
        "source_files": [
            RAW_PATH.relative_to(PROJECT_ROOT).as_posix(),
            SUMMARY_PATH.relative_to(PROJECT_ROOT).as_posix(),
        ],
        "record_count": len(items),
        "null_counts": dict(sorted(nulls.items())),
        "dash_counts": dict(sorted(dashes.items())),
        "dash_stations": dash_station,
        "khai_excluding_missing": {
            "count": len(kept), "mean": mean(kept),
            "min": min(kept), "max": max(kept),
        },
        "khai_zero_filled": {
            "count": len(zero_filled), "mean": mean(zero_filled),
            "min": min(zero_filled), "max": max(zero_filled),
        },
        "pagination": {
            "truncate_rows": TRUNCATE_ROWS,
            "total_count": total_count,
            "saved": len(truncated),
            "dropped": total_count - len(truncated),
            "pm10_mean_all": mean(pm10_all),
            "pm10_mean_truncated": mean(pm10_trunc),
            "count_check_passes": len(truncated) == total_count,
        },
        "business_code": {
            "result_code": header["resultCode"],
            "result_msg": header["resultMsg"],
            "check_passes": header["resultCode"] == "00",
        },
        "missing_across_two_calls": {
            "raw_snapshot": {
                "data_time": sorted({str(r["dataTime"]) for r in items})[0],
                "station_count": len(items),
                "pm10_missing": sum(
                    1 for r in items if to_float(r.get("pm10Value")) is None
                ),
            },
            "summary_snapshot": {
                "data_time": summary["data_time_min"],
                "station_count": summary["station_count"],
                "pm10_missing": summary["pm10_missing"],
            },
        },
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print(f"[6] 산출물 → {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
