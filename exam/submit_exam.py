"""
중간고사 제출 파일 만들기
=========================
    python exam/submit_exam.py --id 학번 --name 이름

하는 일
1. 문제 1~6의 원본(결함 있는 코드) q1.py ~ q6.py 를 학번으로 실행해 "수정 전 출력"을 모은다.
2. 학생이 고친 q1_fixed.py ~ q6_fixed.py 가 있으면 실행해 "수정 후 출력"과 코드 전문을 모은다.
3. 답 칸이 붙은 제출 파일 하나를 exam/submissions/중간고사_학번.md 로 만든다.

학생이 할 일: 만들어진 파일을 열어 답 칸(">> 답:" 아래)을 채우고 그 파일 하나만 올린다.
수정본이 없거나 실행이 실패해도 파일은 만들어진다. 실패한 채로 제출해도 된다.
원본 q1.py ~ q6.py 는 고치지 않는다. 고치면 "수정 전 출력"이 달라져 제출에서 드러난다.
"""

import argparse
import hashlib
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EXAM = Path(__file__).resolve().parent
REPO = EXAM.parent
OUT_DIR = EXAM / "submissions"
TIMEOUT = 600

QUESTIONS = {
    1: ("1주 + 2주. 공공 API 대기질 수집", 10, [
        ("1-1", 2, "결함을 모두 찾아 줄과 원인을 쓴다 (결함은 둘 이상이다)"),
        ("1-2", 4, "수정 전·후 표: 수집 건수(전체 건수), 결측 수, 지수 평균, 최고 측정소"),
        ("1-3", 2, "결측('-')을 0으로 채운 평균과 유효값만 쓴 평균의 차이를 내 수치로 쓰고, 지표가 크게 튀지 않는데도 위험한 이유"),
        ("1-4", 2, "첫 페이지만 받았는데 프로그램이 오류 없이 끝난 이유, 이를 잡는 검사 하나, 그 검사가 잡지 못하는 것 하나"),
    ]),
    2: ("3주. 같은 집계를 두 계층에 둔 파이프라인", 15, [
        ("2-1", 3, "결함이 있는 줄과 원인"),
        ("2-2", 6, "수정 전·후 표: 창별 건수·평균, 어긋난 창 수, 빠진 이벤트 수, 평균의 최대 차이, 두 계층의 해시값 일치 여부"),
        ("2-3", 3, "프로그램이 오류 없이 끝난 이유와, 어느 계층이 어느 방향으로 어긋났는지 내 수치로"),
        ("2-4", 3, "집계 규칙을 한 곳에 두고 리플레이로 다시 처리하는 방식(Kappa)과 두 벌 로직(Lambda)의 비용 차이, 그리고 공공 감사에서 리플레이 가능한 범위를 정하는 것"),
    ]),
    3: ("4주. 소비자 장애 뒤에 적재된 행 수", 15, [
        ("3-1", 3, "결함 두 개: 줄과 원인"),
        ("3-2", 6, "수정 후 표: 적재 행 수, 중복 행 수, 중복 제거 뒤 행 수, 읽은 직후 커밋 규칙(B)의 유실 건수"),
        ("3-3", 3, "내 수치로 A 규칙의 중복과 B 규칙의 유실을 비교하고, 공공 서비스에서 어느 쪽을 먼저 피해야 하는지와 그 이유"),
        ("3-4", 3, "중복 제거 키로 event_id를 쓸 때와 (파티션, 오프셋)을 쓸 때 걸러내는 중복이 어떻게 다른지, 이 시험 자료에서는 결과가 같은지"),
    ]),
    4: ("5주. 늦게 도착한 이벤트", 15, [
        ("4-1", 3, "결함 두 개: 줄과 원인"),
        ("4-2", 6, "수정 후 표: 수용 건수, 폐기 건수, LATE_OK 판정, LATE_DROP 판정, 창-구 행 수"),
        ("4-3", 3, "내 지연 허용 값에서 LATE_OK와 LATE_DROP이 그렇게 판정된 이유를 watermark 값과 창 끝 시각으로 설명"),
        ("4-4", 3, "폐기가 집계 결과에 흔적을 남기지 않는 이유, 이를 감시하는 방법 하나, 지연 허용을 늘리면 치르는 대가"),
    ]),
    5: ("6주. 일별 민원 배치 보고서", 15, [
        ("5-1", 3, "결함을 모두 찾아 줄과 원인을 쓴다"),
        ("5-2", 6, "수정 후 표: 접수 건수, 중복 제거, 매핑, 미기재, 미매핑, 보존 여부, 지역 묶음 수(이름 기준과 코드 기준)"),
        ("5-3", 3, "내 수치로 합 검산식을 쓰고, 어느 항을 세지 않으면 어떤 일이 생기는지"),
        ("5-4", 3, "미기재와 미매핑을 '실패 n건'으로 합쳐 쓰지 않는 이유와 각각 고칠 곳, 그리고 내 배치 마감 시각이 이 숫자들에 미친 영향"),
    ]),
    6: ("7주. 훈련 샘플에 붙인 피처", 15, [
        ("6-1", 3, "결함 두 개: 줄과 원인"),
        ("6-2", 6, "수정 후 표: 입력 샘플 수, 조인 결과 행 수, 탈락(값 없음, TTL 초과), 미래 값이 붙을 뻔한 샘플 수, 붙은 건수의 합"),
        ("6-3", 3, "시점 조인에서 샘플이 탈락하는 두 이유를 내 샘플 하나씩으로 설명하고, 탈락을 알아채는 방법"),
        ("6-4", 3, "최신값 조인으로 훈련하면 평가가 왜곡되는 이유와, 샘플이 더 많이 남은 쪽이 오히려 누출된 쪽인 이유"),
    ]),
}
SYNTH = ("종합", 15, [
    ("S-1", 5, "6문제 중 오류 없이 끝나고 숫자가 나왔지만 틀렸던 침묵 실패 두 개를 골라, 각각 어떤 검사가 있었으면 잡혔을지 내 수치로"),
    ("S-2", 5, "공공 서비스에서 유실과 중복 중 무엇을 먼저 피하는지(문제 3), 지연 이벤트를 스트리밍이 폐기하고 배치가 포함하는 이유(문제 4와 5)를 내 수치로"),
    ("S-3", 5, "'정의를 한 곳에 둔다'는 원칙이 문제 2(집계 규칙)와 문제 6(피처)에서 어떻게 적용되는지, 피처 정의서에 적을 항목 세 가지"),
])


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def run(py: Path, student_id: str) -> dict:
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, py.name, "--id", student_id],
            cwd=str(EXAM), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=TIMEOUT, env=env,
        )
        return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr,
                "code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"[시간 초과] {TIMEOUT}초", "code": -1}


def block(res: dict) -> str:
    text = res["stdout"].rstrip()
    if not res["ok"]:
        text += "\n[오류 종료 코드 %s]\n%s" % (res["code"], res["stderr"].rstrip())
    return "```text\n" + text + "\n```\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="학번")
    ap.add_argument("--name", required=True, help="이름")
    a = ap.parse_args()
    if not a.id.isalnum():
        print("학번은 숫자나 영문자만 써야 합니다.")
        return 2

    parts = [
        f"# 중간고사 제출 -- {a.id} {a.name}\n",
        f"- 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 실행 환경: Python {sys.version.split()[0]} / {platform.platform()}",
        "- 이 파일의 `>> 답:` 아래만 채워서 이 파일 하나를 올린다.\n",
    ]
    status = []
    for n, (title, pts, items) in QUESTIONS.items():
        orig = EXAM / f"q{n}.py"
        fixed = EXAM / f"q{n}_fixed.py"
        parts.append(f"\n---\n\n## 문제 {n} ({pts}점). {title}\n")
        parts.append(f"원본 코드 지문: `q{n}.py` (해시 {sha256_file(orig)})\n")
        parts.append("### 수정 전 출력\n")
        before = run(orig, a.id)
        parts.append(block(before))
        parts.append("### 수정 후 출력\n")
        if fixed.exists():
            after = run(fixed, a.id)
            parts.append(f"<!-- AFTER q{n} -->\n")
            parts.append(block(after))
            parts.append(f"### 수정한 코드 전문 (`q{n}_fixed.py`)\n")
            parts.append("```python\n" + fixed.read_text(encoding="utf-8").rstrip() + "\n```\n")
            note = ""
            if after["ok"] and "@@KEY" not in after["stdout"]:
                note = " -- @@KEY 줄이 출력되지 않음 (원본 q%d.py의 key(...) 줄을 확인)" % n
            status.append(f"문제 {n}: 수정본 실행 {'성공' if after['ok'] else '실패'}{note}")
        else:
            parts.append(f"(q{n}_fixed.py 가 없어 수정 후 출력이 없음. 막힌 곳을 아래 답에 적는다.)\n")
            status.append(f"문제 {n}: 수정본 없음")
        parts.append("### 답안\n")
        for code, p, desc in items:
            parts.append(f"**{code}** ({p}점) {desc}\n\n>> 답:\n\n")

    parts.append("\n---\n\n## 종합 (15점)\n")
    for code, p, desc in SYNTH[2]:
        parts.append(f"**{code}** ({p}점) {desc}\n\n>> 답:\n\n")
    parts.append("\n---\n\n## 선택: 사용한 AI 도구와 도움을 받은 부분 (감점 없음)\n\n>> 답:\n")

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"중간고사_{a.id}.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print("\n".join(status))
    print(f"제출 파일: {out}")
    print("열어서 '>> 답:' 아래를 채운 뒤 이 파일 하나만 올리세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
