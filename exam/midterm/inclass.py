#!/usr/bin/env python3
"""중간 미니 프로젝트 — 현장 지필 예측 문항 생성기 (코딩 에이전트 없이 수업 시간에 푼다).

학번마다 입력 데이터가 다르므로 문항의 정답도 학생마다 다르다. 문항은 모두
「설정값 하나를 바꾸면 본인 결과가 어떻게 달라지는가」를 묻고, 문제지에 그 학생 데이터의
발췌 표를 함께 인쇄한다. 학생은 코드를 돌리지 않고 표와 규칙만으로 답한다.

실행:
    python exam/midterm/inclass.py --student-id 20231234
    python exam/midterm/inclass.py --roster exam/midterm/roster.csv   # 첫 열 student_id

산출:
    exam/midterm/sheets/<학번>.md   문제지 (인쇄용)
    exam/midterm/keys/<학번>.json   정답 키 (채점용)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GEN_PATH = ROOT / "practice" / "midterm" / "code" / "m-0-make-dataset.py"
SOL_DIR = HERE / "solution"
SHEET_DIR = HERE / "sheets"
KEY_DIR = HERE / "keys"

Q1_LIMIT = 0.20       # 결측률 임계 5% → 20%
Q2_DELAY = 10         # 지연 허용 5분 → 10분
Q4_LIMIT = 0.35       # 미매핑률 임계 0.10 → 0.35 (생성기의 차단일 최대 미매핑률 약 0.32보다 크게)


def load_module(path: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = load_module(GEN_PATH)
S1 = load_module(SOL_DIR / "m-1-silent-failure-checks.py")
S2 = load_module(SOL_DIR / "m-2-event-accounting.py")
S3 = load_module(SOL_DIR / "m-3-batch-feature.py")


# ------------------------------------------------------------------ Q1 (B1)
def q1(data: Path) -> tuple[str, dict]:
    rows, answer = [], {}
    for path in sorted((data / "b1").glob("resp_*.json")):
        header, body = S1.load(path)
        items = body["items"]
        pm10 = [S1.to_float(r.get("pm10Value")) for r in items]
        missing = sum(1 for v in pm10 if v is None)
        zeros = sum(1 for v in pm10 if v == 0.0)
        fields_ok = all(f in r for r in items for f in S1.REQUIRED_FIELDS)
        before = S1.run_checks(header, body)
        old = S1.MISSING_RATE_LIMIT
        S1.MISSING_RATE_LIMIT = Q1_LIMIT
        after = S1.run_checks(header, body)
        S1.MISSING_RATE_LIMIT = old
        fb = sorted(k for k, ok in before.items() if not ok)
        fa = sorted(k for k, ok in after.items() if not ok)
        rows.append(f"| {path.name} | {header.get('resultCode')} | {len(items)} | {body['totalCount']} | "
                    f"{'예' if fields_ok else '아니오'} | {missing} | {zeros} | {', '.join(fb) or '없음'} |")
        if fa != fb:
            answer[path.name] = {"before": fb, "after": fa}
    only_c5_files = []
    for path in sorted((data / "b1").glob("resp_*.json")):
        h, b = S1.load(path)
        c = S1.run_checks(h, b)
        if [k for k, ok in c.items() if not ok] == ["C5"]:
            only_c5_files.append(path.name)
    text = f"""### 문항 1 (B1 · 15점)

본인 응답 6개의 요약이다. 결측은 pm10Value가 '-'·빈칸·null이거나 필드가 없는 경우다.

| 파일 | resultCode | items | totalCount | 필수 필드 5개 모두 있음 | pm10 결측 | pm10 = 0 | 본인 실행의 실패 검사 |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

(1) C4의 결측률 임계를 5%에서 {Q1_LIMIT:.0%}로 올린다. 실패 검사 목록이 **바뀌는** 파일을 모두 적고, 바뀐 뒤의 목록을 적는다. 바뀌는 파일이 없으면 「없음」이라 쓰고 이유를 쓴다. (8점)

(2) C5(0 값 검사)를 빼면 다섯 검사를 모두 통과해 저장되는 파일이 있는가. 있으면 파일 이름을 적고, 그 파일을 저장했을 때 1주차에서 본 어떤 일이 생기는지 두 문장 이내로 쓴다. 없으면 「없음」이라 쓰고, 본인 데이터에 0 채움이 들어왔다면 무엇이 잡았을지 쓴다. (7점)
"""
    return text, {"q1_1_changed": answer, "q1_2_only_c5": only_c5_files}


# ------------------------------------------------------------------ Q2·Q3 (B2)
def q2_q3(data: Path) -> tuple[str, dict]:
    batches = S2.load_batches(data)
    r5 = S2.run(batches, 5)
    r10 = S2.run(batches, Q2_DELAY)
    times = {}
    arrive = {}
    for name, rows in batches:
        for r in rows:
            times.setdefault(r["event_id"], r["event_time"][11:16])
            arrive.setdefault(r["event_id"], name)
    wm_rows = "\n".join(f"| {b['batch']} | {b['watermark'] or '없음'} |" for b in r5["per_batch"])
    drop_rows = "\n".join(f"| {e} | {times[e]} | {arrive[e]} |" for e in r5["dropped_event_ids"]) or "| (없음) | | |"
    recovered = sorted(set(r5["dropped_event_ids"]) - set(r10["dropped_event_ids"]))
    newly = sorted(set(r10["dropped_event_ids"]) - set(r5["dropped_event_ids"]))

    # Q3: 중복 제거를 빼면 — 중복 행이 수용 판정을 그대로 받는다
    def run_no_dedup(delay_min: int) -> int:
        delay = timedelta(minutes=delay_min)
        max_seen = None
        accepted = 0
        for _, rows in batches:
            wm = None if max_seen is None else max_seen - delay
            for row in rows:
                _, w_end = S2.window_of(row["t"])
                if wm is None or w_end > wm:
                    accepted += 1
            m = max(r["t"] for r in rows)
            max_seen = m if max_seen is None else max(max_seen, m)
        return accepted
    nodedup = run_no_dedup(5)

    text = f"""### 문항 2 (B2 · 20점)

지연 허용 5분 실행에서 배치별 적용 watermark와 폐기된 이벤트다. 창은 10분(:00·:10·:20 …에서 시작)이다.

| 배치 | 적용 watermark (지연 5분) |
|---|---|
{wm_rows}

| 폐기된 event_id | event_time | 도착 배치 |
|---|---|---|
{drop_rows}

(1) 지연 허용을 5분에서 {Q2_DELAY}분으로 바꾸면 각 배치의 watermark는 몇 시 몇 분인가. (4점)

(2) 위 표의 폐기 이벤트 중 {Q2_DELAY}분에서는 **수용**으로 바뀌는 것을 모두 적고, 각각 창의 끝과 watermark를 비교해 근거를 쓴다. (10점)

(3) 지연 허용을 늘리면 폐기가 줄어든다. 그 대가로 운영에서 무엇이 늦어지는지, 본인 수치(창 크기·지연 허용)를 넣어 두 문장 이내로 쓴다. (6점)

### 문항 3 (B2 · 10점)

본인 지연 5분 실행의 합계는 받음 {r5['received']} = 중복 {r5['duplicates']} + 수용 {r5['accepted']} + 지연 폐기 {r5['dropped_late']}이다.

(1) 중복 제거 단계를 빼고(같은 event_id도 매번 새 이벤트로 보고) 같은 규칙으로 돌리면 수용 건수는 최소 몇에서 최대 몇 사이인가. 계산 근거를 쓴다. (5점)

(2) 이 상태에서 「창별 민원 건수」 대시보드가 보여 주는 값과 4주차 at-least-once 실험의 관계를 두 문장 이내로 쓴다. (5점)
"""
    key = {
        "q2_1_watermarks_delay10": [b["watermark"] for b in r10["per_batch"]],
        "q2_2_recovered": recovered,
        "q2_2_newly_dropped_note": newly,
        "q3_1_range": [r5["accepted"], r5["accepted"] + r5["duplicates"]],
        "q3_1_actual_rule_result": nodedup,
    }
    return text, key


# ------------------------------------------------------------------ Q4 (B3)
def q4(data: Path) -> tuple[str, dict]:
    days = S3.run_batch(data)
    day_rows = "\n".join(
        f"| {d['date']} | {d['physical']} | {d['dup']} | {d['out_of_scope']} | {d['missing']} | "
        f"{d['unmapped']} | {d['mapped']} | {'통과' if d['gate_passed'] else '차단'} |" for d in days)
    blocked = [d for d in days if not d["gate_passed"]]

    old = S3.UNMAPPED_RATE_LIMIT
    S3.UNMAPPED_RATE_LIMIT = Q4_LIMIT
    days_relaxed = S3.run_batch(data)
    S3.UNMAPPED_RATE_LIMIT = old
    now_pass = [d["date"] for d, e in zip(days, days_relaxed) if not d["gate_passed"] and e["gate_passed"]]

    rows = S3.feature_rows(days)
    rows_relaxed = S3.feature_rows(days_relaxed)
    b = blocked[0]
    # 대상 지역: 차단된 날 매핑 건수가 가장 많은 lawd_cd (동률이면 코드 순)
    cd = sorted(b["by_region"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    tz = "+09:00"
    as_a = datetime.fromisoformat(f"2026-07-02T09:00:00{tz}")  # 미래 누출 문항용 — 마지막 확정일보다 항상 앞
    as_b = datetime.fromisoformat(b["date"] + f"T09:00:00{tz}") + timedelta(days=1)  # 차단일 다음 날 아침

    def pit(rs, as_of):
        known = [r for r in rs if r["lawd_cd"] == cd and r["known_at"] <= as_of]
        best = max(known, key=lambda r: r["known_at"]) if known else None
        if best is not None and as_of - best["known_at"] > S3.TTL:
            best = None
        return [best["covers"], best["value"]] if best else [None, None]

    mine = [r for r in rows if r["lawd_cd"] == cd]
    latest = max(mine, key=lambda r: r["known_at"])
    feat_rows = "\n".join(f"| {r['lawd_cd']} | {r['covers']} | {r['known_at']:%m-%d %H:%M} | {r['value']} |"
                          for r in mine)
    text = f"""### 문항 4 (B3 · 25점)

본인 일 배치의 총계 표다. 품질 게이트: 총계 보존식 성립 AND 미매핑률 = 미매핑 / (미기재 + 미매핑 + 매핑) ≤ 0.10.

| 날짜 | physical | 중복 | 마감 밖 | 미기재 | 미매핑 | 매핑 | 게이트 |
|---|---|---|---|---|---|---|---|
{day_rows}

(1) 차단된 날의 미매핑률을 분수와 소수 넷째 자리까지 쓴다. 임계를 {Q4_LIMIT}로 올리면 그날은 통과하는가. (5점)

(2) 「마감 밖」 건을 다음 날 파일로 넘기지 않고 그냥 버리면 7월 전체 합계에서 무엇이 틀어지는지, 본인 표의 숫자로 두 문장 이내로 쓴다. (6점)

(3) 아래는 lawd_cd {cd}의 피처 행(게이트 통과일만)이다. 알려진 시각은 다음 날 00:00, TTL은 3일이다. 차단된 날 {b['date']}에 이 지역으로 매핑된 건수는 {b['by_region'][cd]}건이다(보고서는 만들어지지 않았다).

| lawd_cd | covers | 알려진 시각 | 값 |
|---|---|---|---|
{feat_rows}

기준 시점 {as_a:%Y-%m-%d %H:%M}의 훈련 샘플에 시점 조인으로 붙는 covers 날짜와 값은? 같은 샘플에 최신값 조인을 쓰면 무엇이 붙고, 그것이 왜 문제인가. (8점)

(4) 기준 시점 {as_b:%Y-%m-%d %H:%M}의 샘플에 시점 조인으로 붙는 covers 날짜와 값은? 임계를 {Q4_LIMIT}로 올려 차단된 날이 통과하면 이 결과가 어떻게 바뀌는가. 이 변화가 「게이트를 느슨하게 하면 피처가 더 신선해지니 좋다」는 주장의 근거가 되는지, 되지 않는지 두 문장 이내로 쓴다. (6점)
"""
    key = {
        "q4_1": [{"date": d["date"], "unmapped_rate": d["unmapped_rate"],
                  "fraction": f"{d['unmapped']}/{d['missing'] + d['unmapped'] + d['mapped']}"} for d in blocked],
        "q4_1_pass_at_relaxed": now_pass,
        "q4_3_target": {"lawd_cd": cd, "as_of": as_a.isoformat()},
        "q4_3_pit": pit(rows, as_a),
        "q4_3_latest": [latest["covers"], latest["value"], latest["known_at"] > as_a],
        "q4_4_as_of": as_b.isoformat(),
        "q4_4_pit": pit(rows, as_b),
        "q4_4_pit_relaxed": pit(rows_relaxed, as_b),
    }
    return text, key


Q5 = """### 문항 5 (공통 · 10점)

동료가 m-3의 보고서에 `"generated_at": 실행 시각` 필드를 추가하자고 한다.

(1) 그렇게 하면 본인 산출물의 `report_sha256`과 `rerun_sha256`은 어떻게 되는가. (3점)

(2) 그 결과 6주차에서 말한 재현성 확인 중 무엇을 더는 할 수 없게 되는지, 그리고 실행 시각을 남기려면 어디에 두어야 하는지 쓴다. (7점)
"""


def build(student_id: str) -> tuple[str, dict]:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "input"
        manifest = GEN.generate(student_id, data)
        t1, k1 = q1(data)
        t2, k2 = q2_q3(data)
        t4, k4 = q4(data)
    head = f"""# 데이터 엔지니어링과 MLOps — 중간 미니 프로젝트 현장 검증

학번 **{student_id}** · 데이터 시드 {manifest['seed']} · 시간 50분 · 코딩 도구·인터넷 사용 불가 · 본인 산출물 인쇄본 지참 가능

- 이 문제지의 표는 본인 학번 데이터에서 뽑았다. 다른 학생과 정답이 다르다.
- 계산 과정을 쓴다. 답만 맞고 과정이 없으면 절반만 준다.
- 모르는 것은 모른다고 쓴다. 지어낸 값은 0점이다.

"""
    key = {"student_id": student_id, "seed": manifest["seed"], **k1, **k2, **k4}
    return head + t1 + "\n" + t2 + "\n" + t4 + "\n" + Q5, key


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="학번별 현장 예측 문항과 정답 키를 만든다")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--student-id")
    g.add_argument("--roster", type=Path)
    args = p.parse_args(argv)
    if args.roster:
        with open(args.roster, encoding="utf-8") as f:
            ids = [row[0].strip() for row in csv.reader(f) if row and row[0].strip() and row[0] != "student_id"]
    else:
        ids = [args.student_id]
    SHEET_DIR.mkdir(exist_ok=True)
    KEY_DIR.mkdir(exist_ok=True)
    for sid in ids:
        sheet, key = build(sid)
        (SHEET_DIR / f"{sid}.md").write_text(sheet, encoding="utf-8")
        (KEY_DIR / f"{sid}.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{sid}  문제지 sheets/{sid}.md  정답 keys/{sid}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
