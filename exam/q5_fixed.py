"""
문제 5 (6주). 일별 민원 배치 보고서의 지역별 건수 - 수정본
===================================================
수정 사항:
1. 결함 원인 분석:
   - 결함 1: 중복 접수건(complaint_id)에 대한 중복 제거 부재 (dup_removed=1건 발생).
   - 결함 2: 지역명 정규화(공백 제거, 약칭 '강남'->'강남구' 등 보정) 및 표준 행정동코드(lawd_cd) 매핑 부재로
     자치구가 11개 그룹으로 분절되어 집계 왜곡 발생.
   - 결함 3: 미기재(missing, 1건) 및 미매핑(unmapped, 성남시/판교 2건) 건을 침묵 실패로 누락시키고
     보고서에는 "정상 집계 종료"로 왜곡 보고.
2. 결함 수정:
   - 6주차 정제 규칙 적용:
     ① 접수번호(complaint_id) 기준 중복 제거 (첫 번째 기록 보존)
     ② 앞뒤 공백 제거
     ③ 약칭 보정 (강남->강남구, 마포->마포구, 관악->관악구)
     ④ lawd_cd_seoul.csv 기반 표준 코드 매핑
   - 총계 보존식(physical == dup_removed + mapped + missing + unmapped) 검산 및 보존 여부(preserved=1) 확인.
   - 표준 코드별 집계 산출 (n_groups_by_code=3) 및 total_reported(54건) 집계.
"""

import csv
import json
from collections import Counter

from common import PRACTICE, key, parse_id, pick_int

sid = parse_id()
INPUT_DIR = PRACTICE / "chapter6" / "data" / "input"
DATES = ("2026-07-01", "2026-07-02", "2026-07-03")
_m = 16 * 60 + 10 * pick_int(sid, "q5-cutoff", 0, 21)          # 16:00 ~ 19:30, 10분 단위
CUTOFF = f"{_m // 60:02d}:{_m % 60:02d}"

ALIASES = {"강남": "강남구", "마포": "마포구", "관악": "관악구"}


def load_mapping():
    with open(INPUT_DIR / "lawd_cd_seoul.csv", encoding="utf-8") as f:
        return {row["region_std"]: row["lawd_cd"] for row in csv.DictReader(f)}


def read_day(ds):
    path = INPUT_DIR / "complaints" / f"{ds}.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


records = []
for ds in DATES:
    records += [r for r in read_day(ds) if r["created_at"][11:16] < CUTOFF]

physical = len(records)
mapping = load_mapping()

# 수정 전 기준: 원천 지역명 그룹 수
by_name = Counter()
for r in records:
    name = r.get("region_raw")
    if not name:
        continue
    by_name[name] += 1
n_groups_by_name = len(by_name)

# [결함 1 수정] 1단계: 접수번호 기준 중복 제거
seen = set()
dup_removed = 0
valid_records = []
for r in records:
    cid = r["complaint_id"]
    if cid in seen:
        dup_removed += 1
    else:
        seen.add(cid)
        valid_records.append(r)

# [결함 2 & 3 수정] 2단계: 공백 제거, 약칭 보정 및 표준 코드 매핑 (미기재/미매핑 분류)
mapped_records = []
missing = 0
unmapped = 0

for r in valid_records:
    raw = r.get("region_raw")
    name = (raw or "").strip()
    if not name:
        missing += 1
        continue
    name = ALIASES.get(name, name)
    if name in mapping:
        mapped_records.append({**r, "region_std": name, "lawd_cd": mapping[name]})
    else:
        unmapped += 1

mapped = len(mapped_records)

# 총계 보존 검산
preserved = 1 if physical == (dup_removed + mapped + missing + unmapped) else 0

# 표준 코드 기준 그룹화 집계
by_code = Counter(r["lawd_cd"] for r in mapped_records)
n_groups_by_code = len(by_code)
total_reported = sum(by_code.values())

print(f"배치 마감 {CUTOFF}, 접수 기록 {physical}건")
print(f"정제 회계: 중복제거 {dup_removed}건, 매핑 {mapped}건, 미기재 {missing}건, 미매핑 {unmapped}건 (보존여부: {preserved})")
print(f"지역 묶음 수: 이름 기준 {n_groups_by_name}개 -> 표준 코드 기준 {n_groups_by_code}개")
print(f"표준 코드별 집계:")
for code, count in sorted(by_code.items()):
    # 대표 자치구명 찾기
    r_name = [k for k, v in mapping.items() if v == code][0]
    print(f"  [{code}] {r_name}: {count}건")
print(f"집계 완료: 합계 {total_reported}건")

key("cutoff", CUTOFF)
key("physical", physical)
key("dup_removed", dup_removed)
key("mapped", mapped)
key("missing", missing)
key("unmapped", unmapped)
key("preserved", preserved)
key("n_groups_by_name", n_groups_by_name)
key("n_groups_by_code", n_groups_by_code)
key("total_reported", total_reported)
