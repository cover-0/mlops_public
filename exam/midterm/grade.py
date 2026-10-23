#!/usr/bin/env python3
"""중간 미니 프로젝트 채점 — '실행 증거와 값 일치' 40점 부분만 자동으로 매긴다.

학번으로 입력 데이터를 다시 만들고(practice/midterm/code/m-0-make-dataset.py의 generate),
정답 풀이(exam/midterm/solution/)로 정답 값을 계산한 뒤, 학생이 낸 JSON 세 개와 항목별로 대조한다.
서술(원인 설명 30·감지 지점 20·문서 10)은 사람이 채점한다.

실행:
    python exam/midterm/grade.py --student-id 20231234 --submission <제출물 폴더>
    python exam/midterm/grade.py --student-id 20231234 --submission <폴더> --json  # 결과를 JSON으로

제출물 폴더 안에서 b1_checks.json·b2_accounting.json·b3_report.json·manifest.json을
하위 폴더까지 찾는다. 없는 파일은 그 소주제 점수를 0으로 매기고 '파일 없음'으로 적는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN_PATH = ROOT / "practice" / "midterm" / "code" / "m-0-make-dataset.py"
SOL_DIR = Path(__file__).resolve().parent / "solution"
P_TOL = 1e-4  # KS p-value 허용 오차 (SciPy 버전에 따른 반올림 차이)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find(sub: Path, name: str) -> dict | None:
    hits = sorted(sub.rglob(name))
    if not hits:
        return None
    return json.loads(hits[0].read_text(encoding="utf-8"))


class Sheet:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, part: str, item: str, points: float, ok: bool, note: str = "") -> None:
        self.rows.append({"part": part, "item": item, "max": points,
                          "score": points if ok else 0.0, "ok": ok, "note": note})

    def missing(self, part: str, points: float, name: str) -> None:
        self.rows.append({"part": part, "item": f"{name} 제출", "max": points, "score": 0.0,
                          "ok": False, "note": "파일 없음"})

    def total(self) -> tuple[float, float]:
        return sum(r["score"] for r in self.rows), sum(r["max"] for r in self.rows)


# ------------------------------------------------------------------ B1 (12점)
def grade_b1(sheet: Sheet, ans: dict, got: dict | None) -> None:
    if got is None:
        return sheet.missing("B1", 12, "b1_checks.json")
    by_file = {r.get("file"): r for r in got.get("responses", [])}
    for r in ans["responses"]:
        g = by_file.get(r["file"], {})
        ok = sorted(g.get("failed", [])) == r["failed"]
        sheet.add("B1", f"{r['file']} 실패 검사", 1.5, ok,
                  "" if ok else f"제출 {sorted(g.get('failed', []))} / 정답 {r['failed']}")
    a, g = ans["drift"], got.get("drift", {})
    ok_n = g.get("baseline_n") == a["baseline_n"] and g.get("current_n") == a["current_n"]
    sheet.add("B1", "drift 표본 수", 1, ok_n)
    try:
        ok_p = abs(float(g.get("p_value")) - a["p_value"]) <= P_TOL
    except (TypeError, ValueError):
        ok_p = False
    sheet.add("B1", "drift p_value", 1, ok_p, "" if ok_p else f"제출 {g.get('p_value')} / 정답 {a['p_value']}")
    sheet.add("B1", "drift_detected", 1, g.get("drift_detected") == a["drift_detected"])


# ------------------------------------------------------------------ B2 (14점)
def grade_b2(sheet: Sheet, ans: dict, got: dict | None) -> None:
    if got is None:
        return sheet.missing("B2", 14, "b2_accounting.json")
    runs = {r.get("watermark_delay_minutes"): r for r in got.get("runs", [])}
    for a in ans["runs"]:
        d = a["watermark_delay_minutes"]
        g = runs.get(d, {})
        tag = f"지연 {d}분"
        for key in ("received", "duplicates", "accepted", "dropped_late"):
            ok = g.get(key) == a[key]
            sheet.add("B2", f"{tag} {key}", 1, ok, "" if ok else f"제출 {g.get(key)} / 정답 {a[key]}")
        ok = sorted(g.get("dropped_event_ids", [])) == a["dropped_event_ids"]
        sheet.add("B2", f"{tag} 폐기 event_id", 1.5, ok)
        norm = sorted((w.get("window_start"), w.get("district"), w.get("count"))
                      for w in g.get("window_counts", []))
        want = sorted((w["window_start"], w["district"], w["count"]) for w in a["window_counts"])
        sheet.add("B2", f"{tag} 창별 집계", 1.5, norm == want,
                  "" if norm == want else f"일치하지 않는 행 {len(set(norm) ^ set(want))}개")


# ------------------------------------------------------------------ B3 (14점)
def grade_b3(sheet: Sheet, ans: dict, got: dict | None) -> None:
    if got is None:
        return sheet.missing("B3", 14, "b3_report.json")
    days = {d.get("date"): d for d in got.get("days", [])}
    keys = ("physical", "dup", "out_of_scope", "missing", "unmapped", "mapped")
    for a in ans["days"]:
        g = days.get(a["date"], {})
        ok = all(g.get(k) == a[k] for k in keys)
        diff = [f"{k} {g.get(k)}≠{a[k]}" for k in keys if g.get(k) != a[k]]
        sheet.add("B3", f"{a['date']} 총계 6항", 1.5, ok, ", ".join(diff))
        sheet.add("B3", f"{a['date']} 게이트 판정", 0.5, g.get("gate_passed") == a["gate_passed"])
        ok_h = g.get("report_sha256") == a["report_sha256"] and g.get("rerun_sha256") == a["rerun_sha256"]
        sheet.add("B3", f"{a['date']} 보고서 해시", 0.5, ok_h)
    feats = {f.get("sample_id"): f for f in got.get("features", [])}
    fkeys = ("pit_covers", "pit_value", "latest_covers", "latest_value", "future_leak")
    per = 4.0 / len(ans["features"])
    for a in ans["features"]:
        g = feats.get(a["sample_id"], {})
        ok = all(g.get(k) == a[k] for k in fkeys)
        sheet.add("B3", f"{a['sample_id']} 시점 조인", round(per, 4), ok,
                  ", ".join(f"{k} {g.get(k)}≠{a[k]}" for k in fkeys if g.get(k) != a[k]))


def grade(student_id: str, submission: Path) -> dict:
    gen = load_module(GEN_PATH)
    sols = [load_module(SOL_DIR / f"{n}.py") for n in
            ("m-1-silent-failure-checks", "m-2-event-accounting", "m-3-batch-feature")]
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "input"
        manifest = gen.generate(student_id, data)
        ans_b1 = sols[0].compute(data)
        ans_b2 = sols[1].compute(data)
        ans_b3 = sols[2].compute(data)
        ans_b3.pop("_days_raw", None)

    sheet = Sheet()
    sub_manifest = find(submission, "manifest.json")
    ok_m = bool(sub_manifest) and sub_manifest.get("seed") == manifest["seed"] \
        and sub_manifest.get("files") == manifest["files"]
    notes = []
    if not sub_manifest:
        notes.append("manifest.json 없음 — 본인 학번 데이터로 실행했는지 확인할 수 없다")
    elif not ok_m:
        notes.append(f"manifest 불일치 — 제출 학번 {sub_manifest.get('student_id')}, "
                     f"제출 시드 {sub_manifest.get('seed')} / 정답 시드 {manifest['seed']}")
    grade_b1(sheet, ans_b1, find(submission, "b1_checks.json"))
    grade_b2(sheet, ans_b2, find(submission, "b2_accounting.json"))
    grade_b3(sheet, ans_b3, find(submission, "b3_report.json"))
    score, full = sheet.total()
    return {"student_id": student_id, "seed": manifest["seed"], "manifest_ok": ok_m, "notes": notes,
            "score": round(score, 2), "max": round(full, 2), "rows": sheet.rows}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="중간 미니 프로젝트 자동 채점(값 일치 40점)")
    p.add_argument("--student-id", required=True)
    p.add_argument("--submission", required=True, type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = grade(args.student_id, args.submission)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"학번 {result['student_id']}  시드 {result['seed']}  manifest 일치 {result['manifest_ok']}")
    for n in result["notes"]:
        print(f"  ! {n}")
    for part in ("B1", "B2", "B3"):
        rows = [r for r in result["rows"] if r["part"] == part]
        s, m = sum(r["score"] for r in rows), sum(r["max"] for r in rows)
        print(f"\n[{part}] {s:g} / {m:g}")
        for r in rows:
            mark = "O" if r["ok"] else "X"
            print(f"  {mark} {r['item']:<28} {r['score']:g}/{r['max']:g}  {r['note']}")
    print(f"\n합계 {result['score']:g} / {result['max']:g}  → 25점 환산 {result['score'] * 25 / 40:.2f}")
    if not result["manifest_ok"]:
        print("규정: manifest가 본인 학번과 맞지 않으면 재택 산출물 점수는 0점 (lecture/midterm-project.md 6절)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
