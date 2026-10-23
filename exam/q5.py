"""
문제 5 (6주). 일별 민원 배치 보고서의 지역별 건수
===================================================
구청이 7월 1~3일 민원을 지역별로 세어 보고한다. 자료는 6주차 실습의 실제 접수 기록 3일치(60건)이다.
학번마다 배치 마감 시각이 다르다. 각 날짜에서 접수 시각이 마감 시각 이전인 민원만 그날 배치에 들어간다.

참고 파일: practice/chapter6/data/input/lawd_cd_seoul.csv (지역 표준명 -> 표준 코드)

보고서의 문장: "민원 접수 건수를 지역별로 집계했고 오류 없이 종료되었다."

실행: python exam/q5.py --id 학번
수정본은 q5_fixed.py 로 저장해 같은 방식으로 실행한다.
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


def read_day(ds):
    path = INPUT_DIR / "complaints" / f"{ds}.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


records = []
for ds in DATES:
    records += [r for r in read_day(ds) if r["created_at"][11:16] < CUTOFF]

by_name = Counter()
for r in records:
    name = r.get("region_raw")
    if not name:
        continue
    by_name[name] += 1

print(f"배치 마감 {CUTOFF}, 접수 기록 {len(records)}건")
for name, n in sorted(by_name.items()):
    print(f"  {name!r:<12}{n:>4}건")
print(f"집계 완료: {len(by_name)}개 지역, 합계 {sum(by_name.values())}건")
key("cutoff", CUTOFF)
key("physical", len(records))
key("n_groups_by_name", len(by_name))
key("total_reported", sum(by_name.values()))
