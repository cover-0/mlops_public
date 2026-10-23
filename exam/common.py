"""중간고사 공통 도구: 학번으로 조건 정하기, 자료 경로, 채점용 키 출력.

표준 라이브러리만 쓴다. 학번에서 숫자를 뽑을 때 난수 모듈을 쓰지 않고 해시값을 쓰므로,
파이썬 버전과 운영체제가 달라도 같은 학번이면 같은 조건이 나온다.
"""

import argparse
import hashlib
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parent.parent
PRACTICE = REPO / "practice"


def parse_id() -> str:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True, help="학번")
    return p.parse_args().id


def _h(student_id: str, salt: str) -> int:
    return int(hashlib.sha256(f"{student_id}|{salt}".encode("utf-8")).hexdigest()[:12], 16)


def pick_int(student_id: str, salt: str, lo: int, hi: int) -> int:
    """lo 이상 hi 이하의 정수 하나."""
    return lo + _h(student_id, salt) % (hi - lo + 1)


def pick_choice(student_id: str, salt: str, seq):
    return seq[_h(student_id, salt) % len(seq)]


def pick_subset(student_id: str, salt: str, n_total: int, k: int) -> list:
    """0 ~ n_total-1 가운데 k개의 위치를 오름차순으로."""
    order = sorted(range(n_total), key=lambda i: _h(student_id, f"{salt}:{i}"))
    return sorted(order[:k])


def key(name: str, value) -> None:
    """채점기가 읽는 줄. 이 줄의 이름을 바꾸거나 지우지 않는다."""
    if isinstance(value, float):
        value = round(value, 4)
    print(f"@@KEY {name}={value}")
