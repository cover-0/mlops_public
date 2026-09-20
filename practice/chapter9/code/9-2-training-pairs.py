#!/usr/bin/env python3
"""9장 9-2: 훈련 데이터를 만들고 지문(sha256)을 찍는다.

무엇을 보이는가
---------------
- 7주차 확정 집계(3일 × 3지역)에서 (전일 건수 → 당일 건수) 훈련 쌍 6개를 만든다.
- 그 쌍을 정규화 CSV로 직렬화해 sha256 지문을 계산한다.
- 계산한 지문을 9-1(MLflow 실습)이 남긴 산출물의 지문과 대조한다.
- 원천 한 칸만 바뀌면 지문이 어떻게 달라지는지 보인다.

의존성: 표준 라이브러리만. Docker·MLflow 없이 실행된다.
실행:   python code/9-2-training-pairs.py
산출물: data/output/ch9_training_pairs.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "output"
# 원천은 7주차 실습이 입력으로 쓰는 6주차 배치 확정 산출물이다.
SOURCE_DIR = BASE_DIR.parent / "chapter7" / "data" / "input" / "ch6_daily"

REGION_NAME = {"11440": "마포구", "11620": "관악구", "11680": "강남구"}


def load_daily_counts() -> tuple[list[str], dict[str, dict[str, int]]]:
    """일자별·지역별 확정 건수를 읽는다. {lawd_cd: {date: count}}."""
    days = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_dir())
    table: dict[str, dict[str, int]] = {}
    for day in days:
        summary = json.loads((SOURCE_DIR / day / "daily_summary.json").read_text(encoding="utf-8"))
        for row in summary["by_region"]:
            table.setdefault(row["lawd_cd"], {})[day] = int(row["count"])
    return days, table


def build_pairs(table: dict[str, dict[str, int]]) -> list[dict]:
    """(전일 건수 → 당일 건수) 쌍. 지역 코드·전일 건수 순으로 정렬한다."""
    pairs = []
    for cd in sorted(table):
        days = sorted(table[cd])
        for i in range(len(days) - 1):
            pairs.append(
                {
                    "lawd_cd": cd,
                    "x_prev_count": table[cd][days[i]],
                    "y_count": table[cd][days[i + 1]],
                    "x_day": days[i],
                    "y_day": days[i + 1],
                }
            )
    pairs.sort(key=lambda p: (p["lawd_cd"], p["x_prev_count"]))
    return pairs


def canonical_csv(pairs: list[dict]) -> str:
    """지문을 찍을 정규화 형식. 열 순서·행 순서·줄바꿈을 고정한다."""
    head = "lawd_cd,x_prev_count,y_count\n"
    body = "".join(f"{p['lawd_cd']},{p['x_prev_count']},{p['y_count']}\n" for p in pairs)
    return head + body


def fingerprint(pairs: list[dict]) -> str:
    return hashlib.sha256(canonical_csv(pairs).encode("utf-8")).hexdigest()


def common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def main() -> int:
    days, table = load_daily_counts()
    pairs = build_pairs(table)
    fp = fingerprint(pairs)

    print(f"[1] 원천 — 7주차 확정 집계 {len(days)}일 × 지역 {len(table)}개")
    print(f"    경로 practice/chapter7/data/input/ch6_daily/")
    header = "    일자          " + "".join(f"{REGION_NAME[cd]}({cd})  " for cd in sorted(table))
    print(header)
    for day in days:
        line = f"    {day}  "
        for cd in sorted(table):
            line += f"{table[cd][day]:>11}  "
        print(line)

    print(f"\n[2] 훈련 쌍 — (전일 건수 → 당일 건수) {len(pairs)}개")
    print("    지역               전일 → 당일      전일 건수  당일 건수")
    for p in pairs:
        print(
            f"    {REGION_NAME[p['lawd_cd']]}({p['lawd_cd']})  "
            f"{p['x_day']} → {p['y_day']}  "
            f"{p['x_prev_count']:>9}  {p['y_count']:>9}"
        )

    print("\n[3] 정규화 CSV와 지문")
    print(f"    첫 줄        {canonical_csv(pairs).splitlines()[0]}")
    print(f"    행 수        {len(pairs)}행 + 머리글 1행")
    print(f"    sha256       {fp}")

    # 9-1(MLflow 실습)이 남긴 산출물과 대조한다. 없으면 대조를 건너뛴다.
    report_path = OUTPUT_DIR / "ch9_experiment_report.json"
    if report_path.exists():
        recorded = json.loads(report_path.read_text(encoding="utf-8"))["data_fingerprint_sha256"]
        print(f"    9-1 기록값   {recorded}")
        print(f"    일치 여부    {'예 — 같은 데이터다' if recorded == fp else '아니오'}")
    else:
        print("    9-1 기록값   없음(ch9_experiment_report.json 미생성)")

    # 원천 한 칸만 고쳐 지문의 민감도를 본다. 난수를 쓰지 않고 고정된 한 건만 바꾼다.
    changed_cd, changed_day = "11440", days[-1]
    before = table[changed_cd][changed_day]
    table[changed_cd][changed_day] = before + 1
    pairs_alt = build_pairs(table)
    fp_alt = fingerprint(pairs_alt)
    table[changed_cd][changed_day] = before

    print(f"\n[4] 원천 한 칸만 바뀌면 — {REGION_NAME[changed_cd]} {changed_day} 건수 {before} → {before + 1}")
    print(f"    바뀐 쌍       (5,{before}) → (5,{before + 1})   나머지 5쌍은 그대로")
    print(f"    sha256        {fp_alt}")
    print(f"    앞에서부터 일치하는 글자 수  {common_prefix_len(fp, fp_alt)}")
    print("    한 건이 바뀌면 지문 전체가 달라진다 — 부분 일치로 '조금 다르다'를 말할 수 없다")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "source_dir": "practice/chapter7/data/input/ch6_daily",
        "source_days": days,
        "pairs": [
            {k: p[k] for k in ("lawd_cd", "x_prev_count", "y_count", "x_day", "y_day")}
            for p in pairs
        ],
        "canonical_csv_header": canonical_csv(pairs).splitlines()[0],
        "data_fingerprint_sha256": fp,
        "one_cell_changed": {
            "lawd_cd": changed_cd,
            "day": changed_day,
            "count_before": before,
            "count_after": before + 1,
            "data_fingerprint_sha256": fp_alt,
            "common_prefix_len": common_prefix_len(fp, fp_alt),
        },
    }
    (OUTPUT_DIR / "ch9_training_pairs.json").write_text(
        json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n증거 파일: {OUTPUT_DIR / 'ch9_training_pairs.json'}")
    print("CH9_2_" + ("PASS" if len(pairs) == 6 else "FAIL"))
    return 0 if len(pairs) == 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
