#!/usr/bin/env python3
"""6주차 실습 6-5: 재실행 재현성과 주간 롤업.

세 가지를 화면으로 확인한다.

  (1) 보고서 내용이 입력만의 함수이면 같은 날짜를 다시 계산해도 바이트가 같다.
      생성 시각 같은 비결정 요소를 한 줄 넣으면 그 성질이 깨진다.
  (2) 주간 롤업은 원천을 다시 읽지 않고 _SUCCESS 마커가 있는 날짜의 일별 확정
      산출물만 합산한다. 마커가 없는 날짜는 조용히 넘기지 않고 결측으로 적는다.
  (3) 상위 집계가 원천을 다시 정제하면, 정제 규칙이 한쪽만 바뀌는 순간 일별 합과
      주간 값이 갈린다.

입력은 6주차 원천(data/input/)과 기존 일별 산출물(data/output/daily/)이다.
기존 산출물은 읽기만 한다. 새로 만든 파일은 임시 폴더에 쓰고 지운다.

실행:
    python code/6-5-rerun-rollup.py
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
DAILY_DIR = BASE_DIR / "data" / "output" / "daily"
ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}
WINDOW_END = "2026-07-05"  # 주간 창의 끝 날짜(7일 창)


def load_mapping() -> dict[str, str]:
    with open(INPUT_DIR / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def clean(ds: str, aliases: dict[str, str]) -> dict:
    """중복 제거 → 표기 정규화 → 표준 코드 매핑(6-3과 같은 규칙)."""
    mapping = load_mapping()
    with open(INPUT_DIR / "complaints" / f"{ds}.jsonl", encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    seen: set[str] = set()
    dup = 0
    valid = []
    for rec in recs:
        if rec["complaint_id"] in seen:
            dup += 1
            continue
        seen.add(rec["complaint_id"])
        valid.append(rec)
    mapped, missing, unmapped = [], 0, 0
    for rec in valid:
        name = (rec.get("region_raw") or "").strip()
        if not name:
            missing += 1
            continue
        name = aliases.get(name, name)
        if name in mapping:
            mapped.append({**rec, "region_std": name, "lawd_cd": mapping[name]})
        else:
            unmapped += 1
    return {"physical": len(recs), "dup_removed": dup, "mapped_records": mapped,
            "mapped": len(mapped), "missing": missing, "unmapped": unmapped}


def render_report(ds: str, res: dict, with_clock: bool = False) -> str:
    """보고서 본문을 만든다. with_clock=True면 생성 시각 한 줄을 더 넣는다."""
    by_region = Counter((r["lawd_cd"], r["region_std"]) for r in res["mapped_records"])
    lines = [f"# 일별 민원 요약 보고서 — {ds}", ""]
    if with_clock:
        lines.append(f"- 생성 시각: {dt.datetime.now().isoformat()}")
    lines += [
        f"- 원천 접수: {res['physical']}건 (중복 제거 {res['dup_removed']}건)",
        f"- 매핑 {res['mapped']}건 / 미기재 {res['missing']}건 / 미매핑 {res['unmapped']}건",
        "",
        "| 코드 | 지역 | 건수 |",
        "|---|---|---|",
    ]
    for (code, name), cnt in sorted(by_region.items()):
        lines.append(f"| {code} | {name} | {cnt} |")
    return "\n".join(lines) + "\n"


def write_and_hash(path: Path, text: str) -> str:
    """덮어쓰기로 저장하고 파일 바이트의 SHA-256을 낸다(이어 붙이지 않는다)."""
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ds = "2026-07-01"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print(f"[1] {ds} 보고서를 두 번 만들어 파일 해시를 비교 — 입력만의 함수일 때")
        h1 = write_and_hash(tmp / "report.md", render_report(ds, clean(ds, ALIASES)))
        h2 = write_and_hash(tmp / "report.md", render_report(ds, clean(ds, ALIASES)))
        print(f"    1회차 {h1[:16]}…")
        print(f"    2회차 {h2[:16]}…")
        print(f"    같은 바이트인가: {'예' if h1 == h2 else '아니오'}")

        print(f"\n[2] 같은 보고서에 생성 시각 한 줄을 넣으면")
        g1 = write_and_hash(tmp / "report_clock.md",
                            render_report(ds, clean(ds, ALIASES), with_clock=True))
        g2 = write_and_hash(tmp / "report_clock.md",
                            render_report(ds, clean(ds, ALIASES), with_clock=True))
        print("    달라진 줄: '- 생성 시각: …' 한 줄 (실행할 때마다 값이 바뀜)")
        print(f"    같은 바이트인가: {'예' if g1 == g2 else '아니오'}")
        print("    → 집계 결과가 같아도 해시 비교로는 '재현됐다'를 보일 수 없게 됨")

    end = dt.date.fromisoformat(WINDOW_END)
    window = [(end - dt.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    print(f"\n[3] 주간 창 {window[0]} ~ {window[-1]} — _SUCCESS 마커로 확정 여부를 판별")
    days, absent = [], []
    for d in window:
        marked = (DAILY_DIR / d / "_SUCCESS").exists()
        has_file = (DAILY_DIR / d / "daily_summary.json").exists()
        (days if marked else absent).append(d)
        print(f"    {d}  마커 {'있음' if marked else '없음':<4}  "
              f"일별 요약 파일 {'있음' if has_file else '없음'}")
    print(f"    합산 대상 {len(days)}일, 결측 {len(absent)}일: {', '.join(absent)}")

    print("\n[4] 일별 확정 산출물만 합산한 주간 값 — 원천을 다시 읽지 않음")
    totals: Counter = Counter()
    region_total: Counter = Counter()
    category_total: Counter = Counter()
    for d in days:
        summary = json.loads((DAILY_DIR / d / "daily_summary.json").read_text(encoding="utf-8"))
        check = json.loads((DAILY_DIR / d / "quality_check.json").read_text(encoding="utf-8"))
        for key in ("physical", "dup_removed", "mapped", "missing", "unmapped"):
            totals[key] += check[key]
        for row in summary["by_region"]:
            region_total[(row["lawd_cd"], row["region"])] += row["count"]
        for cat, cnt in summary["by_category"].items():
            category_total[cat] += cnt
    ok = totals["physical"] == (totals["mapped"] + totals["missing"]
                                + totals["unmapped"] + totals["dup_removed"])
    print(f"    총계 보존  {totals['physical']} = {totals['mapped']} + {totals['missing']} + "
          f"{totals['unmapped']} + {totals['dup_removed']}  {'OK' if ok else 'FAIL'}")
    print("    지역별  " + ", ".join(f"{n} {v}" for (_, n), v in sorted(region_total.items())))
    print("    유형별  " + ", ".join(f"{c} {v}" for c, v in sorted(category_total.items())))
    print(f"    검산  지역별 합 {sum(region_total.values())} / "
          f"유형별 합 {sum(category_total.values())} / 매핑 {totals['mapped']}")

    print("\n[5] 주간 쪽이 원천을 다시 정제하는데 정제 규칙만 구버전이면")
    old_aliases = {k: v for k, v in ALIASES.items() if k != "관악"}
    print(f"    구버전 사전: 약칭 {sorted(old_aliases)} — '관악' 항목이 아직 없음")
    rescan = Counter()
    for d in days:
        res = clean(d, old_aliases)
        for key in ("physical", "dup_removed", "mapped", "missing", "unmapped"):
            rescan[key] += res[key]
    print(f"    원천 재정제 결과  매핑 {rescan['mapped']}건 / 미매핑 {rescan['unmapped']}건")
    print(f"    일별 합산 결과    매핑 {totals['mapped']}건 / 미매핑 {totals['unmapped']}건")
    print(f"    같은 주에 대해 두 보고서가 매핑 {abs(rescan['mapped'] - totals['mapped'])}건 차이")
    print("    두 계산 모두 총계 보존은 성립함 — 각자 안에서는 합이 맞아 오류로 잡히지 않음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
