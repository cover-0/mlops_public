#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2-1-parse-api.py
제2장 실습 2.1 — 공개 API 응답(JSON) 파싱과 기본 EDA

한국환경공단 에어코리아 "대기오염정보" 시도별 실시간 측정 응답을
DataFrame으로 변환하고, 측정소 단위의 기본 탐색적 분석(EDA)을 수행한다.
- 결측 표기('-'/'')를 NaN으로 변환해 결측률을 계산한다.
- PM10/PM2.5 등 측정값의 분포 요약을 계산한다.
- 등급(pm10Grade) 분포를 센다.

입력은 저장된 스냅샷 파일(기본값)이거나, --live 로 실제 호출한다.

실행:
    cd practice/chapter2
    pip install -r code/requirements.txt
    python3 code/2-1-parse-api.py            # 저장된 22:00 스냅샷 EDA
    python3 code/2-1-parse-api.py --live --sido 서울   # 실시간 호출 후 EDA
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "input"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
DEFAULT_SNAPSHOT = INPUT_DIR / "airquality_seoul_2200.json"

AIRKOREA_ENDPOINT = (
    "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"
)
MEASURE_COLS = ["pm10Value", "pm25Value", "o3Value", "no2Value", "so2Value", "coValue"]


def load_items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = (payload or {}).get("response", {}).get("body", {})
    items = body.get("items")
    if not isinstance(items, list):
        raise ValueError("response.body.items 가 없습니다. 응답 구조를 확인하세요.")
    return [r for r in items if isinstance(r, dict)]


def fetch_live(sido: str, rows: int) -> dict[str, Any]:
    import requests  # type: ignore

    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    if not api_key:
        raise RuntimeError("DATA_GO_KR_API_KEY 환경변수가 필요합니다(--live).")
    params = {
        "serviceKey": api_key, "returnType": "json", "numOfRows": str(rows),
        "pageNo": "1", "sidoName": sido, "ver": "1.0",
    }
    resp = requests.get(AIRKOREA_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_dataframe(items: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(items)
    # 측정값을 숫자로 변환: '-'/'' 등 결측 표기는 NaN
    for col in MEASURE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace({"-": np.nan, "": np.nan}), errors="coerce")
    return df


def run_eda(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    missing = {
        col: int(df[col].isna().sum()) for col in MEASURE_COLS if col in df.columns
    }

    def num_summary(col: str) -> dict[str, float | None]:
        if col not in df.columns or df[col].notna().sum() == 0:
            return {"min": None, "max": None, "mean": None, "median": None}
        s = df[col].dropna()
        return {
            "min": round(float(s.min()), 3),
            "max": round(float(s.max()), 3),
            "mean": round(float(s.mean()), 3),
            "median": round(float(s.median()), 3),
        }

    grade_counts = {}
    if "pm10Grade" in df.columns:
        grade_counts = {
            str(k): int(v) for k, v in df["pm10Grade"].value_counts(dropna=False).items()
        }

    data_time = None
    if "dataTime" in df.columns and n > 0:
        data_time = str(df["dataTime"].iloc[0])

    return {
        "station_count": n,
        "data_time": data_time,
        "missing_by_field": missing,
        "pm10_summary": num_summary("pm10Value"),
        "pm25_summary": num_summary("pm25Value"),
        "pm10_grade_counts": grade_counts,
    }


GRADE_COLS = ["pm10Grade", "pm25Grade", "khaiGrade"]
RAW_COLS = MEASURE_COLS + ["khaiValue"]


def _is_blank(v: Any) -> bool:
    """API가 쓰는 결측 표기를 한 곳에서 판정한다: None / '' / '-'."""
    return v is None or (isinstance(v, str) and v.strip() in {"", "-"})


def print_field_missing(df: pd.DataFrame, items: list[dict[str, Any]]) -> None:
    """산출물 스키마는 그대로 두고, 화면에만 필드별 결측 대조를 출력한다."""
    times = sorted({str(r.get("dataTime")) for r in items})
    print(f"\n[측정 시각] 서로 다른 dataTime {len(times)}개 — {', '.join(times)}")

    print("[결측 대조] 필드별 결측 건수 (결측 표기: None / '' / '-')")
    for col in RAW_COLS + GRADE_COLS:
        n_blank = sum(1 for r in items if _is_blank(r.get(col)))
        print(f"    {col:<12} 결측 {n_blank}건 / {len(items)}건")

    gap = [
        str(r.get("stationName"))
        for r in items
        if not _is_blank(r.get("pm10Value")) and _is_blank(r.get("pm10Grade"))
    ]
    print(f"[값은 있는데 등급이 없는 측정소] {len(gap)}곳 — {', '.join(gap) if gap else '없음'}")
    for r in items:
        if str(r.get("stationName")) in gap:
            print(
                f"    {r.get('stationName')}  pm10Value={r.get('pm10Value')!r}  "
                f"pm10Grade={r.get('pm10Grade')!r}  khaiValue={r.get('khaiValue')!r}"
            )


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Chapter 2 practice 2.1: parse + EDA")
    parser.add_argument("--input", default=str(DEFAULT_SNAPSHOT), help="스냅샷 JSON 경로")
    parser.add_argument("--live", action="store_true", help="저장 파일 대신 실시간 호출")
    parser.add_argument("--sido", default="서울", help="[--live] 시도명")
    parser.add_argument("--rows", type=int, default=100, help="[--live] 조회 행 수")
    args = parser.parse_args(argv)

    if args.live:
        payload = fetch_live(args.sido, args.rows)
        source = f"live:{args.sido}"
    else:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        source = f"file:{Path(args.input).name}"

    items = load_items_from_payload(payload)
    df = build_dataframe(items)
    summary = run_eda(df)
    summary["source"] = source

    out_path = OUTPUT_DIR / "ch2_eda_summary.json"
    write_json(out_path, summary)
    print(
        f"source={source} stations={summary['station_count']} "
        f"data_time={summary['data_time']} pm10_missing={summary['missing_by_field'].get('pm10Value')} "
        f"output={out_path}"
    )
    print("\n[pm10_summary]", json.dumps(summary["pm10_summary"], ensure_ascii=False))
    print("[pm10_grade_counts]", json.dumps(summary["pm10_grade_counts"], ensure_ascii=False))
    print_field_missing(df, items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
