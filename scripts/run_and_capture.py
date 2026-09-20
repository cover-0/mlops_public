"""
실행 증거 게이트 (Execution Evidence Gate)
==========================================
하네스 엔지니어링 원칙 "instructions decay, enforcement persists"의 MLOps 구현.

CLAUDE.md 최우선 원칙("모든 코드는 실제 실행하여 결과 획득, 가짜 결과 금지")을
*산문 지시*가 아니라 *위조 불가능한 증거*로 강제한다.

장(chapter)의 실습 코드를 실제로 실행하여:
  1. stdout/stderr 전체를 로그로 캡처   → results/{파일}.log
  2. 소스 코드와 출력의 SHA-256 해시 기록 → results/{파일}.evidence.json
  3. 실행 시각·소요시간·종료코드·파이썬버전·플랫폼 기록

본문에 들어가는 실행 결과 수치는 반드시 이 로그에서만 인용한다.
로그 없는 결과 서술은 금지(= 가짜 결과로 간주).

사용법:
    # 10장 전체 코드 실행 + 증거 생성
    python scripts/run_and_capture.py 10

    # 특정 파일만
    python scripts/run_and_capture.py 10 --file 10-1-model-serving.py

    # 검증 모드: 캡처 이후 소스가 바뀌었는지(= 결과가 낡았는지) 확인
    python scripts/run_and_capture.py 10 --verify

크로스 플랫폼(Windows/macOS) 호환: pathlib + sys.executable 사용.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트 = 이 스크립트의 부모의 부모 (scripts/run_and_capture.py 기준)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRACTICE_DIR = PROJECT_ROOT / "practice"


def resolve_chapter_dir(chapter: str) -> Path:
    """장 번호로 실제 폴더를 해석한다.

    프로젝트에 chapter9 / chapter09 두 가지 번호 체계가 공존할 수 있으므로
    code/ 하위 폴더를 가진 첫 후보를 선택한다.
    """
    candidates = [f"chapter{chapter}", f"chapter{int(chapter):02d}"]
    for name in candidates:
        d = PRACTICE_DIR / name
        if (d / "code").is_dir():
            return d
    raise FileNotFoundError(
        f"code/ 폴더를 가진 장 폴더를 찾지 못했습니다. "
        f"기준=practice/, 시도: {candidates}"
    )


def sha256_of_text(text: str) -> str:
    """문자열의 SHA-256 해시. 출력·소스 무결성 증거용."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_code_files(chapter_dir: Path, only: str | None) -> list[Path]:
    """실행 대상 .py 파일 목록. requirements 등 비실습 파일은 제외."""
    code_dir = chapter_dir / "code"
    if only:
        target = code_dir / only
        if not target.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {target}")
        return [target]
    files = sorted(
        p for p in code_dir.glob("*.py")
        if not p.name.startswith("_") and "requirements" not in p.name
    )
    return files


def run_one(py_file: Path, timeout: int) -> tuple[dict, str]:
    """단일 코드 파일을 실행하고 (증거 딕셔너리, 합친 로그)를 반환한다."""
    source = py_file.read_text(encoding="utf-8")
    started = time.perf_counter()
    started_iso = datetime.now(timezone.utc).astimezone().isoformat()

    try:
        # 현재 활성 파이썬(venv 포함)으로 실행. cwd는 code/ 폴더
        # (코드가 ../data 같은 상대 경로를 쓰는 관행에 맞춤)
        proc = subprocess.run(
            [sys.executable, py_file.name],
            cwd=py_file.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        exit_code = None
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\n[TIMEOUT] {timeout}s 초과로 중단됨"
        timed_out = True

    duration = round(time.perf_counter() - started, 2)
    combined = f"$ {sys.executable} {py_file.name}\n\n=== STDOUT ===\n{stdout}\n=== STDERR ===\n{stderr}"

    evidence = {
        "file": py_file.name,
        "chapter_relpath": str(py_file.relative_to(PROJECT_ROOT)),
        "started_at": started_iso,
        "duration_sec": duration,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "success": (exit_code == 0),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "source_sha256": sha256_of_text(source),
        "output_sha256": sha256_of_text(combined),
        "output_log": None,  # run()에서 채움
    }
    return evidence, combined


def write_results(chapter_dir: Path, py_file: Path, evidence: dict, combined: str) -> None:
    """로그(.log)와 증거(.evidence.json)를 results/ 폴더에 기록."""
    results_dir = chapter_dir / "results"
    results_dir.mkdir(exist_ok=True)
    stem = py_file.stem

    log_path = results_dir / f"{stem}.log"
    log_path.write_text(combined, encoding="utf-8")

    evidence["output_log"] = str(log_path.relative_to(PROJECT_ROOT))
    ev_path = results_dir / f"{stem}.evidence.json"
    ev_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def verify(chapter_dir: Path, files: list[Path]) -> int:
    """캡처 이후 소스가 변경되었는지 검사. 변경 시 결과는 '낡음'으로 경고."""
    results_dir = chapter_dir / "results"
    problems = 0
    for py_file in files:
        ev_path = results_dir / f"{py_file.stem}.evidence.json"
        if not ev_path.exists():
            print(f"  ❌ 증거 없음: {py_file.name} (아직 실행/캡처 안 됨)")
            problems += 1
            continue
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        current = sha256_of_text(py_file.read_text(encoding="utf-8"))
        if current != ev["source_sha256"]:
            print(f"  ⚠️  낡은 결과: {py_file.name} — 캡처 이후 소스가 변경됨. 재실행 필요")
            problems += 1
        elif not ev.get("success"):
            print(f"  ⚠️  실패한 실행: {py_file.name} — exit_code={ev.get('exit_code')}")
            problems += 1
        else:
            print(f"  ✅ 유효: {py_file.name} (소스 일치, 정상 종료)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="실행 증거 게이트")
    parser.add_argument("chapter", help="장 번호 (예: 10)")
    parser.add_argument("--file", default=None, help="특정 코드 파일만 실행")
    parser.add_argument("--timeout", type=int, default=1800, help="파일당 제한시간(초)")
    parser.add_argument("--verify", action="store_true", help="실행 없이 무결성만 검증")
    args = parser.parse_args()

    chapter_dir = resolve_chapter_dir(args.chapter)
    files = discover_code_files(chapter_dir, args.file)

    if not files:
        print(f"실행할 .py 파일이 없습니다: {chapter_dir / 'code'}")
        return 1

    label = chapter_dir.relative_to(PROJECT_ROOT).as_posix()

    if args.verify:
        print(f"[검증] {label} — {len(files)}개 파일")
        problems = verify(chapter_dir, files)
        print(f"\n검증 완료: 문제 {problems}건")
        return 1 if problems else 0

    print(f"[실행] {label} — {len(files)}개 파일\n")
    all_ok = True
    for py_file in files:
        print(f"▶ {py_file.name} 실행 중...", flush=True)
        evidence, combined = run_one(py_file, args.timeout)
        write_results(chapter_dir, py_file, evidence, combined)
        status = "✅ 성공" if evidence["success"] else f"❌ 실패(exit={evidence['exit_code']})"
        print(f"  {status}  {evidence['duration_sec']}s  "
              f"→ results/{py_file.stem}.log  (출력해시 {evidence['output_sha256'][:12]}…)")
        all_ok = all_ok and evidence["success"]

    print(f"\n증거 생성 완료 → {(chapter_dir / 'results').relative_to(PROJECT_ROOT)}/")
    print("본문의 실행 결과는 위 .log 파일에서만 인용할 것.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
