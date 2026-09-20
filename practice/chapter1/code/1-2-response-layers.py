#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1-2-response-layers.py
제1장 — 공공 API 응답의 두 계층과 레코드 구조를 읽는다.

인증키 없이 실행된다. 외부 네트워크를 쓰지 않고, 이미 저장된 실제 응답
data/output/ch1_airquality_live_raw.json 을 그대로 읽는다.
이 파일은 에어코리아 "시도별 실시간 측정정보"를 실제로 한 번 호출해 받은
원본 응답이며, 이 스크립트는 그 값을 바꾸지 않는다.

표준 라이브러리만 사용한다.

실행:
    python3 code/1-2-response-layers.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
RAW_PATH = OUTPUT_DIR / "ch1_airquality_live_raw.json"
REPORT_PATH = OUTPUT_DIR / "ch1_response_layers.json"

# 측정 항목 접두어 — 필드 이름이 {항목}Value / {항목}Grade / {항목}Flag 로 반복된다.
POLLUTANTS = ["so2", "co", "o3", "no2", "pm10", "pm25"]


def load_raw() -> dict[str, Any]:
    return json.loads(RAW_PATH.read_text(encoding="utf-8"))


def main() -> int:
    raw = load_raw()
    response = raw["response"]
    header = response["header"]
    body = response["body"]
    items: list[dict[str, Any]] = body["items"]

    total_count = body["totalCount"]
    num_of_rows = body["numOfRows"]
    page_no = body["pageNo"]
    received = len(items)

    print("[1] 응답의 두 계층")
    print(f"    response.header   resultCode={header['resultCode']}  "
          f"resultMsg={header['resultMsg']}")
    print(f"    response.body     totalCount={total_count}  pageNo={page_no}  "
          f"numOfRows={num_of_rows}  items={received}건")
    print("    header는 '요청 처리가 업무적으로 성공했는가', body는 '무엇이 몇 건 왔는가'를 담는다")

    first = items[0]
    fields = sorted(first.keys())

    print()
    print(f"[2] 레코드 하나의 필드 {len(fields)}개")
    triple = [p for p in POLLUTANTS
              if all(f"{p}{suffix}" in first for suffix in ("Value", "Grade", "Flag"))]
    print(f"    값·등급·플래그가 한 묶음인 측정 항목 {len(triple)}종: {', '.join(triple)}")
    print(f"      → {len(triple)}종 x 3 = {len(triple) * 3}개")
    rest = [f for f in fields
            if not any(f.startswith(p) for p in triple)]
    print(f"    나머지 {len(rest)}개: {', '.join(rest)}")
    print("    값만 저장하고 Grade·Flag를 버리면 결측이 왜 생겼는지 되짚을 근거가 사라진다")

    print()
    print("[3] 첫 레코드")
    for key in ("stationName", "sidoName", "dataTime",
                "pm10Value", "pm10Grade", "pm10Flag",
                "khaiValue", "khaiGrade"):
        print(f"    {key:<12} {first.get(key)!r}")

    print()
    print("[4] 숫자처럼 보이는 값의 자료형")
    str_numeric = [f for f in fields
                   if isinstance(first.get(f), str) and _looks_numeric(first[f])]
    print(f"    문자열로 온 숫자 필드 {len(str_numeric)}개: {', '.join(str_numeric)}")
    print(f"    JSON 숫자로 온 필드: totalCount={total_count!r}, "
          f"pageNo={page_no!r}, numOfRows={num_of_rows!r}")
    print("    items 안의 측정값은 전부 문자열이므로 숫자로 바꾸는 단계가 반드시 끼어든다")

    print()
    print("[5] 건수를 세는 자리가 셋이다")
    print(f"    totalCount {total_count:>4}  서버가 가진 전체 건수")
    print(f"    numOfRows  {num_of_rows:>4}  이번 요청이 허용한 한 페이지 최대 건수")
    print(f"    items      {received:>4}  이번 응답으로 실제 받은 건수")
    fits = received == total_count
    print(f"    받은 건수 == 전체 건수: {'예' if fits else '아니오'}  "
          f"(한 페이지에 {'다 들어옴' if fits else '다 들어오지 못함'})")

    print()
    print("[6] 측정 시각")
    times = Counter(str(r.get("dataTime")) for r in items)
    for t, c in sorted(times.items()):
        print(f"    {t}  {c}건")
    print("    한 응답 안의 측정 시각이 모두 같다 — 이 API는 '지금 이 시각의 전 측정소'를 준다")

    report = {
        "source_file": RAW_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "header": {"resultCode": header["resultCode"], "resultMsg": header["resultMsg"]},
        "total_count": total_count,
        "num_of_rows": num_of_rows,
        "page_no": page_no,
        "items_received": received,
        "field_count": len(fields),
        "fields": fields,
        "pollutants_with_triple": triple,
        "non_triple_fields": rest,
        "string_numeric_fields": str_numeric,
        "data_times": dict(sorted(times.items())),
        "first_station": first.get("stationName"),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print(f"[7] 산출물 → {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
