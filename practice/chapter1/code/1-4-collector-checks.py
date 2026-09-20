#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1-4-collector-checks.py
제1장 — 스크립트를 파이프라인으로 만드는 최소 장치, 자동 검사 네 가지.

  C1 업무 코드 검사   response.header.resultCode == "00"
  C2 건수 검사        len(items) == totalCount
  C3 스키마 검사      레코드마다 필수 필드가 전부 있는가
  C4 결측률 검사      핵심 측정값의 결측률이 임계 이하인가

같은 검사를 (가) 원본 응답과 (나) 잘린 응답에 각각 걸어, 검사가 있을 때와
없을 때 무엇이 달라지는지 본다.

인증키 없이 실행된다. 외부 네트워크를 쓰지 않고 저장된 실제 응답
data/output/ch1_airquality_live_raw.json 을 읽기만 한다. 난수를 쓰지 않는다.

실행:
    python3 code/1-4-collector-checks.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
RAW_PATH = OUTPUT_DIR / "ch1_airquality_live_raw.json"
REPORT_PATH = OUTPUT_DIR / "ch1_collector_checks.json"

REQUIRED_FIELDS = ["stationName", "sidoName", "dataTime", "pm10Value", "pm25Value"]
MISSING_RATE_LIMIT = 0.05  # 5%
TRUNCATE_ROWS = 20


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def sha256_of(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_checks(header: dict[str, Any], body: dict[str, Any]) -> list[dict[str, Any]]:
    """네 가지 검사를 돌려 검사 이름·기대·실제·통과 여부를 돌려준다."""
    items: list[dict[str, Any]] = body["items"]
    total_count = body["totalCount"]

    result_code = str(header.get("resultCode"))
    c1 = {
        "id": "C1", "name": "업무 코드",
        "expected": "resultCode == '00'",
        "actual": f"resultCode={result_code}",
        "passed": result_code == "00",
    }

    c2 = {
        "id": "C2", "name": "건수",
        "expected": f"items == totalCount({total_count})",
        "actual": f"items={len(items)}",
        "passed": len(items) == total_count,
    }

    missing_fields = sorted({
        f for rec in items for f in REQUIRED_FIELDS if f not in rec
    })
    c3 = {
        "id": "C3", "name": "스키마",
        "expected": f"필수 {len(REQUIRED_FIELDS)}개 필드 전건 존재",
        "actual": ("모두 존재" if not missing_fields
                   else f"없는 필드 {', '.join(missing_fields)}"),
        "passed": not missing_fields,
    }

    n = len(items) or 1
    pm10_missing = sum(1 for r in items if to_float(r.get("pm10Value")) is None)
    rate = pm10_missing / n
    c4 = {
        "id": "C4", "name": "결측률",
        "expected": f"pm10Value 결측률 <= {MISSING_RATE_LIMIT:.1%}",
        "actual": f"{pm10_missing}/{len(items)} = {rate:.1%}",
        "passed": rate <= MISSING_RATE_LIMIT,
    }
    return [c1, c2, c3, c4]


def print_checks(title: str, checks: list[dict[str, Any]]) -> None:
    print(title)
    for c in checks:
        mark = "통과" if c["passed"] else "실패"
        print(f"    {c['id']} {c['name']:<6} {c['expected']:<34} {c['actual']:<26} {mark}")
    ok = sum(1 for c in checks if c["passed"])
    print(f"    → {ok}/{len(checks)} 통과"
          + ("" if ok == len(checks)
             else f", 실패 {len(checks) - ok}건 — 이 응답은 저장하지 않고 멈춘다"))


def main() -> int:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    header = raw["response"]["header"]
    body = raw["response"]["body"]
    items = body["items"]

    checks_full = run_checks(header, body)
    print_checks("[1] 원본 응답에 검사 네 가지를 적용", checks_full)

    truncated_body = dict(body)
    truncated_body["items"] = items[:TRUNCATE_ROWS]
    checks_trunc = run_checks(header, truncated_body)
    print()
    print_checks(f"[2] 같은 검사를 잘린 응답(앞 {TRUNCATE_ROWS}건)에 적용", checks_trunc)

    print()
    print("[3] 검사가 없으면 무엇이 그대로 지나가는가")
    pm10_all = [v for v in (to_float(r.get("pm10Value")) for r in items) if v is not None]
    pm10_tr = [v for v in (to_float(r.get("pm10Value"))
                           for r in truncated_body["items"]) if v is not None]
    print(f"    잘린 응답도 JSON으로 저장되고 프로그램은 종료 코드 0으로 끝난다")
    print(f"    바뀌는 것은 숫자 하나뿐이다 — pm10 평균 "
          f"{round(sum(pm10_all) / len(pm10_all), 1)} → "
          f"{round(sum(pm10_tr) / len(pm10_tr), 1)}")
    print("    실패한 검사가 C2 하나라는 사실을 기록해 두지 않으면 원인을 되짚을 자리가 없다")

    print()
    print("[4] 원본 보존 — 같은 입력이면 같은 지문")
    h_full = sha256_of(items)
    h_tr = sha256_of(truncated_body["items"])
    print(f"    원본 items SHA-256  {h_full[:16]}…")
    print(f"    잘린 items SHA-256  {h_tr[:16]}…")
    print(f"    두 지문이 같은가: {'예' if h_full == h_tr else '아니오'}")
    print("    원본을 버리고 요약만 남기면 이 대조 자체가 불가능해진다")

    print()
    print("[5] 파이프라인이 실행마다 남겨야 하는 네 줄")
    print("    받은 시각 / 원본 해시 / 검사 4건의 통과 여부 / 실패 시 중단했는지")
    print("    이 네 줄이 있으면 '성공했다'가 아니라 '무엇을 확인하고 성공이라 했다'가 된다")

    report = {
        "source_file": RAW_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "required_fields": REQUIRED_FIELDS,
        "missing_rate_limit": MISSING_RATE_LIMIT,
        "truncate_rows": TRUNCATE_ROWS,
        "checks_full_response": checks_full,
        "checks_truncated_response": checks_trunc,
        "pm10_mean_full": round(sum(pm10_all) / len(pm10_all), 1),
        "pm10_mean_truncated": round(sum(pm10_tr) / len(pm10_tr), 1),
        "items_sha256_full": h_full,
        "items_sha256_truncated": h_tr,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print(f"[6] 산출물 → {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
