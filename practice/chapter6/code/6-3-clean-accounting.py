#!/usr/bin/env python3
"""6주차 실습 6-3: 표준 코드로 키를 바꾸고, 모든 레코드의 행방을 적는다.

6-1 DAG의 clean_and_map 태스크와 같은 규칙(중복 제거 → 공백 보정 → 약칭 보정 →
표준 코드 매핑)을 Airflow 없이 그대로 적용해, 두 가지를 화면으로 보인다.

  (1) 지역명을 키로 쓰면 같은 자치구가 여러 줄로 쪼개진다.
  (2) 정제한 레코드는 네 갈래(매핑/미기재/미매핑/중복제거) 중 하나로 가고,
      그 합이 입력과 같은지 검사하는 식이 총계 보존식이다.
  (3) 매핑 실패를 조용히 건너뛰면 총계가 줄어든 사실이 어디에도 남지 않는다.

입력은 6주차 원천(data/input/complaints/*.jsonl)과 표준 코드 사전
(data/input/lawd_cd_seoul.csv)뿐이다. 파일을 쓰지 않고 표준 라이브러리만 쓴다.

실행:
    python code/6-3-clean-accounting.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
DATES = ("2026-07-01", "2026-07-02", "2026-07-03")

# 약칭 보정 사전 — 6-1 DAG의 ALIASES와 같은 값이다.
ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}


def load_mapping() -> dict[str, str]:
    with open(INPUT_DIR / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def read_day(ds: str) -> list[dict]:
    with open(INPUT_DIR / "complaints" / f"{ds}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def clean_day(recs: list[dict], mapping: dict[str, str]) -> dict:
    """중복 제거 → 표기 정규화 → 표준 코드 매핑. 네 갈래를 모두 기록한다."""
    seen: set[str] = set()
    dup_removed: list[str] = []
    valid: list[dict] = []
    for rec in recs:
        cid = rec["complaint_id"]
        if cid in seen:
            dup_removed.append(cid)
            continue
        seen.add(cid)
        valid.append(rec)

    mapped: list[dict] = []
    missing: list[str] = []
    unmapped: list[dict] = []
    ws_stripped = alias_fixed = 0
    for rec in valid:
        raw = rec.get("region_raw")
        name = (raw or "").strip()
        if raw is not None and name != raw:
            ws_stripped += 1
        if not name:
            missing.append(rec["complaint_id"])
            continue
        if name in ALIASES:
            alias_fixed += 1
        name = ALIASES.get(name, name)
        if name in mapping:
            mapped.append({**rec, "region_std": name, "lawd_cd": mapping[name]})
        else:
            unmapped.append({"complaint_id": rec["complaint_id"], "region_raw": raw})

    return {
        "physical": len(recs),
        "dup_removed": len(dup_removed),
        "valid": len(valid),
        "mapped": len(mapped),
        "missing": len(missing),
        "unmapped": len(unmapped),
        "ws_stripped": ws_stripped,
        "alias_fixed": alias_fixed,
        "preservation_ok": len(recs)
        == len(mapped) + len(missing) + len(unmapped) + len(dup_removed),
        "mapped_records": mapped,
        "unmapped_raw": [u["region_raw"] for u in unmapped],
        "missing_ids": missing,
        "dup_ids": dup_removed,
    }


def main() -> int:
    mapping = load_mapping()
    print(f"[1] 표준 코드 사전 — {len(mapping)}개 자치구")
    for name, code in mapping.items():
        print(f"    {name} → {code}")

    raw_recs = {ds: read_day(ds) for ds in DATES}

    print("\n[2] 지역명을 그대로 키로 쓰면 — 사흘치 원문 표기 기준")
    raw_key: Counter = Counter()
    for recs in raw_recs.values():
        for r in recs:
            raw_key[r["region_raw"] if r["region_raw"] is not None else "(미기재)"] += 1
    print(f"    집계 줄 수 {len(raw_key)}줄")
    gangnam = {k: v for k, v in raw_key.items() if "강남" in k}
    print(f"    강남 계열만 {len(gangnam)}줄로 쪼개짐: "
          + ", ".join(f"{k!r} {v}건" for k, v in sorted(gangnam.items())))
    print(f"    강남 계열 합 {sum(gangnam.values())}건 — 어느 줄도 단독으로는 이 수를 보이지 못함")

    print("\n[3] 정규화 후 표준 코드를 키로 쓰면")
    results = {ds: clean_day(raw_recs[ds], mapping) for ds in DATES}
    code_key: Counter = Counter()
    for res in results.values():
        for rec in res["mapped_records"]:
            code_key[(rec["lawd_cd"], rec["region_std"])] += 1
    print(f"    집계 줄 수 {len(code_key)}줄")
    for (code, name), cnt in sorted(code_key.items()):
        print(f"    {code} {name}: {cnt}건")
    print(f"    강남구 {code_key[('11680', '강남구')]}건 — [2]의 강남 계열 합보다 "
          f"{sum(gangnam.values()) - code_key[('11680', '강남구')]}건 적음(중복 접수 제거분)")

    print("\n[4] 일별 정제 회계 — physical = mapped + missing + unmapped + dup_removed")
    print("    날짜          physical  dup  valid  mapped  missing  unmapped  보존")
    for ds in DATES:
        r = results[ds]
        print(f"    {ds}  {r['physical']:>8}  {r['dup_removed']:>3}  {r['valid']:>5}  "
              f"{r['mapped']:>6}  {r['missing']:>7}  {r['unmapped']:>8}  "
              f"{'OK' if r['preservation_ok'] else 'FAIL'}")
        print(f"        검산 {r['physical']} = {r['mapped']} + {r['missing']} + "
              f"{r['unmapped']} + {r['dup_removed']}   "
              f"공백 보정 {r['ws_stripped']}건, 약칭 보정 {r['alias_fixed']}건")

    tot = {k: sum(results[ds][k] for ds in DATES)
           for k in ("physical", "dup_removed", "valid", "mapped", "missing", "unmapped")}
    ok = tot["physical"] == tot["mapped"] + tot["missing"] + tot["unmapped"] + tot["dup_removed"]
    print(f"\n[5] 사흘 합계 — {tot['physical']} = {tot['mapped']} + {tot['missing']} + "
          f"{tot['unmapped']} + {tot['dup_removed']}  보존 {'OK' if ok else 'FAIL'}")
    print("    미기재 " + ", ".join(sum((results[ds]["missing_ids"] for ds in DATES), [])))
    print("    미매핑 " + ", ".join(
        f"{raw!r}" for raw in sum((results[ds]["unmapped_raw"] for ds in DATES), [])))
    print("    중복제거 " + ", ".join(sum((results[ds]["dup_ids"] for ds in DATES), [])))

    print("\n[6] 조용히 건너뛰는 코드와 대조 — 매핑 실패를 기록하지 않으면")
    silent_total = tot["mapped"]
    print(f"    보고서에 적히는 총계   {silent_total}건")
    print(f"    원천 물리 레코드      {tot['physical']}건")
    print(f"    설명되지 않는 차이    {tot['physical'] - silent_total}건")
    print("    예외 없음, 종료 코드 0 — 차이가 로그에도 산출물에도 남지 않음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
