"""
문제 1 (1주 + 2주). 공공 API 대기질 수집 - 수정본
=========================================
수정 사항:
1. 페이징 결함 해결: 첫 페이지만 가져오던 것을 전체 건수(totalCount)에 도달할 때까지 반복 수집
2. 결측치 처리 결함 해결: 결측치('-')를 임의로 0으로 대체하지 않고 유효한 측정값만으로 평균 산출
3. 최고 측정소 선정: 전체 유효 측정소 중에서 최고 지수 측정소 탐색 (동점 시 이름 오름차순)
"""

import json

from common import PRACTICE, key, parse_id, pick_int, pick_subset

sid = parse_id()
SRC = PRACTICE / "chapter2" / "data" / "input" / "airquality_seoul_2200.json"
ITEMS = json.loads(SRC.read_text(encoding="utf-8"))["response"]["body"]["items"]

PAGE_SIZE = pick_int(sid, "q1-page", 12, 28)
for i in pick_subset(sid, "q1-miss", len(ITEMS), pick_int(sid, "q1-nmiss", 2, 6)):
    ITEMS[i]["khaiValue"] = "-"


def fetch_page(page_no: int) -> dict:
    """API 한 페이지를 돌려준다. 실제 API와 같은 header/body 두 계층이다."""
    start = (page_no - 1) * PAGE_SIZE
    return {
        "header": {"resultCode": "00", "resultMsg": "NORMAL_CODE"},
        "body": {
            "totalCount": len(ITEMS), "pageNo": page_no, "numOfRows": PAGE_SIZE,
            "items": ITEMS[start:start + PAGE_SIZE],
        },
    }


# [결함 1 수정] 전체 건수(totalCount)까지 모든 페이지 순회 수집
all_rows = []
page_no = 1
total_count = None

while True:
    resp = fetch_page(page_no)
    header, body = resp["header"], resp["body"]
    if header["resultCode"] != "00":
        raise SystemExit(f"API 오류: {header['resultMsg']}")

    if total_count is None:
        total_count = body["totalCount"]

    items = body.get("items", [])
    if not items:
        break
    all_rows.extend(items)

    if len(all_rows) >= total_count:
        break
    page_no += 1

n_collected = len(all_rows)
complete = 1 if n_collected == total_count else 0

# [결함 2 수정] 결측치('-')를 0으로 왜곡하지 않고 분리 집계
missing_rows = [r for r in all_rows if r["khaiValue"] == "-"]
valid_rows = [r for r in all_rows if r["khaiValue"] != "-"]

n_missing_khai = len(missing_rows)
valid_values = [int(r["khaiValue"]) for r in valid_rows]
mean_khai = sum(valid_values) / len(valid_values) if valid_values else 0.0

# [결함 3 수정] 전체 유효 측정소 기준 최고 측정소 탐색
top = sorted(valid_rows, key=lambda r: (-int(r["khaiValue"]), r["stationName"]))[0]
max_khai_station = top["stationName"]

print(f"응답 코드 {header['resultCode']} ({header['resultMsg']})")
print(f"수집 {n_collected}/{total_count}건 -- {'수집 완료' if complete else '수집 미완료'}")
print(f"통합대기환경지수 평균 {mean_khai:.2f}, 최고 {max_khai_station} ({top['khaiValue']})")

key("total_count", total_count)
key("n_collected", n_collected)
key("complete", complete)
key("n_missing_khai", n_missing_khai)
key("mean_khai", float(mean_khai))
key("max_khai_station", max_khai_station)
