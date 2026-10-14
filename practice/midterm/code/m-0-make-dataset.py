#!/usr/bin/env python3
"""중간 미니 프로젝트 m-0: 학번으로 본인 입력 데이터를 만든다.

같은 학번이면 언제 어디서 돌려도 글자 하나까지 같은 파일이 나오고,
학번이 다르면 측정소 구성·결함 위치·이벤트 건수가 달라진다.

  B1  data/input/b1/resp_01.json ~ resp_06.json
      에어코리아 응답 6개. 측정값은 2주차 입력(2026-06-28 22:00·23:00 서울
      실제 응답)에서 측정소 25곳을 골라 그대로 옮긴다. resp_02~05에는
      결함을 하나씩 심는다(어느 응답에 무엇을 심었는지는 파일에 적지 않는다).
  B2  data/input/b2/batch1.jsonl ~ batch3.jsonl
      민원 접수 이벤트(시뮬레이션). 중복 재전송·지연 도착·순서 뒤바뀜이 섞여 있다.
  B3  data/input/b3/complaints/2026-07-01.jsonl ~ 2026-07-04.jsonl,
      data/input/b3/lawd_cd_seoul.csv, data/input/b3/samples.csv
      일별 민원 원장(시뮬레이션)과 표준 코드 사전, 시점 조인용 훈련 샘플.

학번은 다음 순서로 찾는다: --student-id 인자 → practice/midterm/student_id.txt 첫 줄.

실행:
    python code/m-0-make-dataset.py --student-id 20231234
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PRACTICE_DIR = BASE_DIR.parent
INPUT_DIR = BASE_DIR / "data" / "input"
STUDENT_ID_FILE = BASE_DIR / "student_id.txt"

# B1 원천 — 2주차 실습 입력(실제 응답)
AIR_2200 = PRACTICE_DIR / "chapter2" / "data" / "input" / "airquality_seoul_2200.json"
AIR_2300 = PRACTICE_DIR / "chapter2" / "data" / "input" / "airquality_seoul_current.json"
B1_STATIONS = 25
B1_DEFECTS = ["truncated", "zero_filled", "field_renamed", "high_missing", "result_code_error"]

# B2·B3 공통
DISTRICTS = ["강남구", "마포구", "관악구"]
CATEGORIES = ["불법주차", "소음", "도로파손", "청소", "환경"]
LAWD = {"강남구": "11680", "마포구": "11440", "관악구": "11620"}
ALIASES = {"강남구": "강남", "마포구": "마포", "관악구": "관악"}
UNMAPPED_NAMES = ["강남구청", "서울시", "마포구청앞", "관악산"]
B3_DAYS = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]


def seed_of(student_id: str) -> int:
    return int(hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:8], 16)


def read_student_id(arg: str | None) -> str:
    if arg:
        return arg.strip()
    if STUDENT_ID_FILE.exists():
        first = STUDENT_ID_FILE.read_text(encoding="utf-8").strip().splitlines()
        if first and first[0].strip():
            return first[0].strip()
    raise SystemExit(
        "학번을 찾지 못했다. 둘 중 하나로 준다.\n"
        "    python code/m-0-make-dataset.py --student-id 20231234\n"
        f"    또는 {STUDENT_ID_FILE.relative_to(PRACTICE_DIR.parent).as_posix()} 첫 줄에 학번을 적는다"
    )


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ------------------------------------------------------------------ B1
def _real_items(path: Path) -> dict[str, dict]:
    items = json.loads(path.read_text(encoding="utf-8"))["response"]["body"]["items"]
    keep = ["stationName", "sidoName", "dataTime", "pm10Value", "pm25Value", "khaiValue"]
    return {it["stationName"]: {k: it.get(k) for k in keep} for it in items}


def _response(items: list[dict], total: int, code: str = "00", msg: str = "NORMAL_CODE") -> dict:
    return {"response": {
        "header": {"resultCode": code, "resultMsg": msg},
        "body": {"totalCount": total, "pageNo": 1, "numOfRows": 100, "items": items},
    }}


def _apply_defect(rng: random.Random, items: list[dict], defect: str) -> dict:
    n = len(items)
    if defect == "truncated":
        return _response(items[: rng.randint(12, 20)], n)
    if defect == "zero_filled":
        # 측정값 k건이 결측('-')으로 왔고, 수집 코드가 그것을 0으로 채워 저장한 상황
        for i in rng.sample(range(n), rng.randint(3, 5)):
            items[i]["pm10Value"] = "0"
        return _response(items, n)
    if defect == "field_renamed":
        for it in items:
            it["pm10value"] = it.pop("pm10Value")
        return _response(items, n)
    if defect == "high_missing":
        for i in rng.sample(range(n), rng.randint(3, 6)):
            items[i]["pm10Value"] = "-"
        return _response(items, n)
    if defect == "result_code_error":
        return _response([], 0, code="03", msg="NODATA_ERROR")
    raise ValueError(defect)


def make_b1(rng: random.Random, out: Path) -> dict:
    a, b = _real_items(AIR_2200), _real_items(AIR_2300)
    common = sorted(set(a) & set(b))
    stations = rng.sample(common, B1_STATIONS)
    defects = rng.sample(B1_DEFECTS, 4)
    plan = ["clean"] + defects + ["clean"]
    for k, kind in enumerate(plan, start=1):
        src = b if k == 6 or (2 <= k <= 5 and rng.random() < 0.5) else a
        items = [dict(src[s]) for s in stations]
        rng.shuffle(items)
        resp = _response(items, len(items)) if kind == "clean" else _apply_defect(rng, items, kind)
        dump_json(out / "b1" / f"resp_{k:02d}.json", resp)
    return {"stations": B1_STATIONS, "responses": len(plan)}


# ------------------------------------------------------------------ B2
def _event(eid: int, t: datetime, rng: random.Random) -> dict:
    return {"event_id": f"E{eid:03d}", "district": rng.choice(DISTRICTS),
            "category": rng.choice(CATEGORIES), "event_time": t.strftime("%Y-%m-%d %H:%M:%S")}


def make_b2(rng: random.Random, out: Path) -> dict:
    day = datetime(2026, 7, 7, 22, 0, 0)
    batches: list[list[dict]] = [[], [], []]
    eid = 0

    def minute(lo: int, hi: int) -> datetime:
        return day + timedelta(minutes=rng.randint(lo, hi), seconds=rng.choice([0, 15, 30, 45]))

    # 제때 도착한 이벤트 — 배치마다 담당 20분
    for b, (lo, hi) in enumerate([(0, 19), (20, 39), (40, 59)]):
        for _ in range(rng.randint(12, 16)):
            eid += 1
            batches[b].append(_event(eid, minute(lo, hi), rng))
    # 지연 도착 — batch2에 앞 구간 이벤트, batch3에 중간 구간 이벤트
    for _ in range(rng.randint(2, 4)):
        eid += 1
        batches[1].append(_event(eid, minute(5, 18), rng))
    for _ in range(rng.randint(3, 6)):
        eid += 1
        batches[2].append(_event(eid, minute(12, 36), rng))
    # 중복 재전송 — 앞 배치에서 이미 보낸 이벤트를 뒤 배치에 한 번 더
    for _ in range(rng.randint(3, 6)):
        src = rng.choice([0, 1])
        dst = rng.choice([b for b in (1, 2) if b > src])
        batches[dst].append(dict(rng.choice(batches[src])))
    for b, rows in enumerate(batches, start=1):
        rng.shuffle(rows)
        dump_jsonl(out / "b2" / f"batch{b}.jsonl", rows)
    return {"events_sent": sum(len(r) for r in batches)}


# ------------------------------------------------------------------ B3
def make_b3(rng: random.Random, out: Path) -> dict:
    base = out / "b3"
    with open(base / "lawd_cd_seoul.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["region_std", "lawd_cd"])
        for name, cd in LAWD.items():
            w.writerow([name, cd])

    gate_fail_day = rng.choice(B3_DAYS[1:])
    for ds in B3_DAYS:
        d0 = datetime.fromisoformat(ds + "T08:00:00")
        n = rng.randint(22, 28)
        unmapped_n = rng.randint(4, 6) if ds == gate_fail_day else rng.randint(0, 1)
        missing_n = rng.randint(0, 2)
        recs: list[dict] = []
        for i in range(1, n + 1):
            t = d0 + timedelta(minutes=rng.randint(0, 14 * 60))
            region = rng.choice(DISTRICTS)
            style = rng.random()
            if style < 0.15:
                raw = f" {region} "
            elif style < 0.30:
                raw = ALIASES[region]
            else:
                raw = region
            recs.append({"complaint_id": f"C{ds[2:4]}{ds[5:7]}{ds[8:10]}-{i:03d}", "region_raw": raw,
                         "category": rng.choice(CATEGORIES), "created_at": t.strftime("%Y-%m-%dT%H:%M:00+09:00")})
        picks = rng.sample(range(n), unmapped_n + missing_n)
        for j in picks[:unmapped_n]:
            recs[j]["region_raw"] = rng.choice(UNMAPPED_NAMES)
        for j in picks[unmapped_n:]:
            recs[j]["region_raw"] = rng.choice([None, "", "  "])
        # 마감 뒤 도착 — 다음 날 0시 이후에 접수된 건이 이 날 파일에 섞임
        nxt = datetime.fromisoformat(ds) + timedelta(days=1)
        for k in range(rng.randint(1, 3)):
            t = nxt + timedelta(minutes=rng.randint(1, 50))
            recs.append({"complaint_id": f"C{nxt:%y%m%d}-L{k + 1:02d}", "region_raw": rng.choice(DISTRICTS),
                         "category": rng.choice(CATEGORIES), "created_at": t.strftime("%Y-%m-%dT%H:%M:00+09:00")})
        # 중복 — 같은 접수 번호가 한 번 더 들어옴
        for _ in range(rng.randint(1, 3)):
            recs.append(dict(rng.choice(recs[:n])))
        rng.shuffle(recs)
        dump_jsonl(base / "complaints" / f"{ds}.jsonl", recs)

    samples = []
    for k in range(6):
        day_idx = rng.randint(1, 5)  # 2026-07-02 ~ 2026-07-06 오전 9시
        as_of = datetime(2026, 7, 1 + day_idx, 9, 0)
        samples.append((rng.choice(list(LAWD.values())), as_of))
    samples.append((rng.choice(list(LAWD.values())), datetime(2026, 7, 9, 9, 0)))
    with open(base / "samples.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "lawd_cd", "as_of"])
        for i, (cd, t) in enumerate(samples, start=1):
            w.writerow([f"S{i}", cd, t.strftime("%Y-%m-%dT%H:%M:00+09:00")])
    return {"days": len(B3_DAYS), "samples": len(samples)}


def generate(student_id: str, out: Path) -> dict:
    """학번 하나로 B1·B2·B3 입력을 out 아래에 만든다. 채점에서도 이 함수를 그대로 쓴다."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "b3").mkdir()
    seed = seed_of(student_id)
    rng = random.Random(seed)
    summary = {"b1": make_b1(rng, out), "b2": make_b2(rng, out), "b3": make_b3(rng, out)}
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "student_id": student_id,
        "seed": seed,
        "summary": summary,
        "files": {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    dump_json(out / "manifest.json", manifest)
    return manifest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="학번으로 중간 미니 프로젝트 입력 데이터를 만든다")
    parser.add_argument("--student-id")
    args = parser.parse_args(argv)
    sid = read_student_id(args.student_id)

    manifest = generate(sid, INPUT_DIR)
    print(f"[1] 학번 {sid} → 시드 {manifest['seed']}")
    print(f"[2] 만든 파일 {len(manifest['files'])}개 → {INPUT_DIR.relative_to(PRACTICE_DIR.parent).as_posix()}/")
    for rel, digest in manifest["files"].items():
        print(f"    {rel:<34} {digest[:16]}…")
    print("[3] manifest.json에 파일별 SHA-256을 적었다. 보고서에 시드와 이 해시 앞 16자리를 옮겨 적는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
