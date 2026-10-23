#!/usr/bin/env python3
"""중간 미니 프로젝트 m-3 (B3): 확정 통계와 피처 — 일 배치, 품질 게이트, 시점 조인.

입력: data/input/b3/complaints/2026-07-01.jsonl ~ 2026-07-04.jsonl,
      data/input/b3/lawd_cd_seoul.csv, data/input/b3/samples.csv
산출: data/output/b3_reports/<날짜>.json  (게이트를 통과한 날만)
      data/output/b3_report.json

일 배치 규칙 (6주차 6-1·6-3과 같은 순서에 '마감 밖' 갈래를 하나 더한다)
  1. 중복 제거   complaint_id가 이미 나왔으면 dup
  2. 마감 범위   created_at(+09:00)의 날짜가 파일 날짜와 다르면 out_of_scope
  3. 표기 정규화 region_raw 앞뒤 공백 제거 → 비면 missing
                 약칭(강남·마포·관악)은 '구'를 붙인다
  4. 표준 코드   사전에 있으면 mapped, 없으면 unmapped
  총계 보존식: physical = dup + out_of_scope + missing + unmapped + mapped
  품질 게이트: 총계 보존식 성립 AND unmapped_rate = unmapped / (missing + unmapped + mapped) <= 0.10
               통과한 날만 보고서 파일을 쓴다

피처 규칙 (7주차 7-4와 같은 시점 조인)
  피처 행: 게이트를 통과한 날의 (lawd_cd, 그날 mapped 건수). 알려진 시각 = 다음 날 00:00(+09:00)
  시점 조인: 기준 시점 이전에 알려진 값 중 가장 최근 값. 3일(TTL)보다 오래됐으면 붙이지 않는다
  최신값 조인: 기준 시점과 상관없이 그 lawd_cd의 마지막 값
  future_leak: 최신값의 알려진 시각이 기준 시점보다 뒤

실행:
    python code/m-3-batch-feature.py
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]
ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}
UNMAPPED_RATE_LIMIT = 0.10
TTL = timedelta(days=3)


# ------------------------------------------------------------------ 제공 함수
def load_mapping(input_dir: Path) -> dict[str, str]:
    with open(input_dir / "b3" / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def read_day(input_dir: Path, ds: str) -> list[dict]:
    path = input_dir / "b3" / "complaints" / f"{ds}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def report_text(report: dict) -> str:
    """보고서를 파일로 쓸 글자열. 이 형식을 바꾸면 해시가 달라진다."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ 일 배치
def clean_day(recs: list[dict], ds: str, mapping: dict[str, str]) -> dict:
    seen: set[str] = set()
    dup = out_of_scope = missing = unmapped = 0
    mapped: list[str] = []
    for rec in recs:
        cid = rec["complaint_id"]
        if cid in seen:
            dup += 1
            continue
        seen.add(cid)
        if rec["created_at"][:10] != ds:
            out_of_scope += 1
            continue
        name = (rec.get("region_raw") or "").strip()
        if not name:
            missing += 1
            continue
        name = ALIASES.get(name, name)
        if name in mapping:
            mapped.append(mapping[name])
        else:
            unmapped += 1
    return {"physical": len(recs), "dup": dup, "out_of_scope": out_of_scope,
            "missing": missing, "unmapped": unmapped, "mapped": len(mapped),
            "by_region": dict(sorted(Counter(mapped).items()))}


def gate(acc: dict) -> tuple[bool, float]:
    in_scope = acc["missing"] + acc["unmapped"] + acc["mapped"]
    rate = round(acc["unmapped"] / in_scope, 4) if in_scope else 0.0
    preserved = acc["physical"] == (acc["dup"] + acc["out_of_scope"] + acc["missing"]
                                    + acc["unmapped"] + acc["mapped"])
    return preserved and rate <= UNMAPPED_RATE_LIMIT, rate


def build_report(ds: str, acc: dict) -> dict:
    return {
        "date": ds,
        "by_region": [{"lawd_cd": cd, "count": n} for cd, n in acc["by_region"].items()],
        "accounting": {k: acc[k] for k in ("physical", "dup", "out_of_scope", "missing", "unmapped", "mapped")},
    }


def run_batch(input_dir: Path) -> list[dict]:
    mapping = load_mapping(input_dir)
    days = []
    for ds in DAYS:
        acc = clean_day(read_day(input_dir, ds), ds, mapping)
        passed, rate = gate(acc)
        text = report_text(build_report(ds, acc)) if passed else None
        days.append({
            "date": ds,
            **{k: acc[k] for k in ("physical", "dup", "out_of_scope", "missing", "unmapped", "mapped")},
            "unmapped_rate": rate,
            "gate_passed": passed,
            "by_region": acc["by_region"],
            "report_text": text,
        })
    return days


# ------------------------------------------------------------------ 피처
def feature_rows(days: list[dict]) -> list[dict]:
    rows = []
    for d in days:
        if not d["gate_passed"]:
            continue
        known_at = datetime.fromisoformat(d["date"] + "T00:00:00+09:00") + timedelta(days=1)
        for cd, n in d["by_region"].items():
            rows.append({"lawd_cd": cd, "covers": d["date"], "known_at": known_at, "value": n})
    return rows


def join_samples(rows: list[dict], input_dir: Path) -> list[dict]:
    with open(input_dir / "b3" / "samples.csv", encoding="utf-8") as f:
        samples = list(csv.DictReader(f))
    out = []
    for s in samples:
        as_of = datetime.fromisoformat(s["as_of"])
        mine = [r for r in rows if r["lawd_cd"] == s["lawd_cd"]]
        known = [r for r in mine if r["known_at"] <= as_of]
        pit = max(known, key=lambda r: r["known_at"]) if known else None
        if pit is not None and as_of - pit["known_at"] > TTL:
            pit = None
        latest = max(mine, key=lambda r: r["known_at"]) if mine else None
        out.append({
            "sample_id": s["sample_id"], "lawd_cd": s["lawd_cd"], "as_of": s["as_of"],
            "pit_covers": pit and pit["covers"], "pit_value": pit and pit["value"],
            "latest_covers": latest and latest["covers"], "latest_value": latest and latest["value"],
            "future_leak": bool(latest and latest["known_at"] > as_of),
        })
    return out


def compute(input_dir: Path) -> dict:
    days = run_batch(input_dir)
    days_out = []
    for d in days:
        first = d["report_text"]
        second = run_batch(input_dir)[DAYS.index(d["date"])]["report_text"]  # 같은 입력으로 다시 실행
        row = {k: v for k, v in d.items() if k not in ("by_region", "report_text")}
        row["report_sha256"] = first and sha256_text(first)
        row["rerun_sha256"] = second and sha256_text(second)
        days_out.append(row)
    return {"days": days_out, "features": join_samples(feature_rows(days), input_dir), "_days_raw": days}


def main() -> int:
    result = compute(INPUT_DIR)
    days_raw = result.pop("_days_raw")
    reports_dir = OUTPUT_DIR / "b3_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for old in reports_dir.glob("*.json"):
        old.unlink()
    print("[1] 일 배치 — 총계 보존식과 품질 게이트")
    for d, raw in zip(result["days"], days_raw):
        print(f"    {d['date']}  {d['physical']} = 중복 {d['dup']} + 마감밖 {d['out_of_scope']} + "
              f"미기재 {d['missing']} + 미매핑 {d['unmapped']} + 매핑 {d['mapped']}  "
              f"미매핑률 {d['unmapped_rate']:.4f}  게이트 {'통과' if d['gate_passed'] else '차단'}")
        if raw["report_text"]:
            (reports_dir / f"{d['date']}.json").write_text(raw["report_text"], encoding="utf-8")
    print(f"    보고서 파일 {len(list(reports_dir.glob('*.json')))}개")
    print("[2] 재실행 해시")
    for d in result["days"]:
        if d["report_sha256"]:
            same = "같음" if d["report_sha256"] == d["rerun_sha256"] else "다름"
            print(f"    {d['date']}  {d['report_sha256'][:16]}… / {d['rerun_sha256'][:16]}…  {same}")
    print("[3] 시점 조인 대 최신값 조인")
    for s in result["features"]:
        print(f"    {s['sample_id']} {s['lawd_cd']} 기준 {s['as_of'][:16]}  "
              f"시점 {s['pit_covers']}={s['pit_value']}  최신 {s['latest_covers']}={s['latest_value']}  "
              f"미래 누출 {'예' if s['future_leak'] else '아니오'}")
    out = OUTPUT_DIR / "b3_report.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[4] 산출물 → {out.relative_to(BASE_DIR.parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
