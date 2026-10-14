#!/usr/bin/env python3
"""중간 미니 프로젝트 m-1 (B1): 침묵 실패 탐지기.

입력: data/input/b1/resp_01.json ~ resp_06.json (m-0이 학번으로 만든 파일)
산출: data/output/b1_checks.json

할 일
  (1) 응답 6개 각각에 검사 다섯 가지를 걸고, 실패한 검사 id를 적는다.
        C1 업무 코드   header.resultCode == "00"
        C2 건수        len(items) == totalCount
        C3 스키마      모든 레코드에 필수 필드 5개가 있다
        C4 결측률      pm10Value 결측('-'·빈칸·null·필드 없음) 비율 <= 5%
        C5 0 값        pm10Value가 정확히 0인 레코드가 0건이다
      C1~C4는 1주차 1-4-collector-checks.py와 같은 규칙이다. C5는 이번에 새로 만든다.
  (2) resp_01(기준)과 resp_06(현재)의 pm10 분포를 KS 검정으로 비교한다(2주차 2-2와 같은 방법).

실행:
    python code/m-1-silent-failure-checks.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scipy import stats  # noqa: F401 — drift_test에서 쓴다

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_PATH = BASE_DIR / "data" / "output" / "b1_checks.json"

REQUIRED_FIELDS = ["stationName", "sidoName", "dataTime", "pm10Value", "pm25Value"]
MISSING_RATE_LIMIT = 0.05
ALPHA = 0.05


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


def load(path: Path) -> tuple[dict, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["response"]["header"], raw["response"]["body"]


def run_checks(header: dict, body: dict) -> dict[str, bool]:
    """검사 다섯 가지의 통과 여부를 {"C1": True, ...} 로 돌려준다.

    TODO — 1주차 1-4-collector-checks.py의 run_checks를 참고해 C1~C4를 채우고 C5를 새로 만든다.
      · items가 0건이면 결측률 분모를 1로 둔다 (1-4와 같은 규칙)
      · C4의 결측은 to_float(r.get("pm10Value"))가 None인 경우다 — 필드가 아예 없어도 None이다
      · C5는 to_float 값이 0.0인 레코드 수가 0이면 통과다
    """
    raise NotImplementedError("run_checks를 완성한다")


def pm10_values(body: dict) -> list[float]:
    return [v for v in (to_float(r.get("pm10Value")) for r in body["items"]) if v is not None]


def drift_test(baseline: list[float], current: list[float]) -> dict:
    """2주차와 같은 2표본 KS 검정.

    TODO — 2주차 2-2-drift-visualize.py처럼 stats.ks_2samp로 통계량과 p-value를 구하고,
    아래 형식의 딕셔너리를 돌려준다. 키 이름은 바꾸지 않는다(채점이 이 키를 읽는다).
        {
            "baseline_n": 기준 표본 수,
            "current_n": 현재 표본 수,
            "statistic": 통계량 (소수 6자리 반올림),
            "p_value": p-value (소수 6자리 반올림),
            "alpha": ALPHA,
            "drift_detected": p-value < ALPHA,
        }
    """
    raise NotImplementedError("drift_test를 완성한다")


def compute(input_dir: Path) -> dict:
    files = sorted((input_dir / "b1").glob("resp_*.json"))
    responses = []
    for path in files:
        header, body = load(path)
        checks = run_checks(header, body)
        responses.append({
            "file": path.name,
            "items": len(body["items"]),
            "total_count": body["totalCount"],
            "failed": sorted(k for k, ok in checks.items() if not ok),
        })
    _, base = load(input_dir / "b1" / "resp_01.json")
    _, curr = load(input_dir / "b1" / "resp_06.json")
    return {"responses": responses, "drift": drift_test(pm10_values(base), pm10_values(curr))}


def main() -> int:
    result = compute(INPUT_DIR)
    print("[1] 응답별 검사 결과 (실패한 검사만 적는다)")
    for r in result["responses"]:
        failed = ", ".join(r["failed"]) or "없음 — 저장"
        print(f"    {r['file']}  items {r['items']:>2} / totalCount {r['total_count']:>2}  실패: {failed}")
    d = result["drift"]
    print("[2] resp_01 대 resp_06 pm10 분포 비교 (KS 검정)")
    print(f"    n {d['baseline_n']} 대 {d['current_n']}, D = {d['statistic']}, p = {d['p_value']}, "
          f"alpha = {d['alpha']} → drift_detected = {d['drift_detected']}")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[3] 산출물 → {OUTPUT_PATH.relative_to(BASE_DIR.parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
