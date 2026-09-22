#!/usr/bin/env python3
"""실습 환경 점검과 준비.

    python scripts/setup_practice.py 4          # 점검 → venv 생성 → 패키지 설치
    python scripts/setup_practice.py 4 --check  # 점검만 (아무것도 바꾸지 않는다)
    python scripts/setup_practice.py 4 --no-docker

표준 라이브러리만 쓴다. Windows와 macOS/Linux에서 같은 명령으로 동작한다.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 주차별 선행 조건. pip 이름과 import 이름이 다르면 (pip, import)로 적는다.
CHAPTERS: dict[int, dict] = {
    1: {"pkgs": ["requests"], "env_optional": ["DATA_GO_KR_API_KEY"]},
    2: {"pkgs": ["requests", "pandas", "numpy", "matplotlib", "scipy"]},
    3: {"pkgs": [("PyYAML", "yaml")]},
    4: {
        "pkgs": [("kafka-python", "kafka")],
        "docker": "required",
        "ports": [2181, 9092, 29092],
        "compose": ("chapter3", ["zookeeper", "kafka"]),
    },
    5: {"pkgs": ["pyspark"], "java": 17},
    6: {"pkgs": [("apache-airflow", "airflow")], "posix_only": True, "network": True},
    7: {"pkgs": ["feast", "pandas", "pyarrow"]},
    9: {"pkgs": ["mlflow", ("scikit-learn", "sklearn"), "pandas", "pyarrow"]},
    10: {
        "pkgs": ["fastapi", "uvicorn", "mlflow", ("scikit-learn", "sklearn"),
                 "pandas", "pyarrow", "pytest", "httpx"],
        "docker": "optional",
    },
    11: {"pkgs": ["numpy", "pandas", "scipy"]},
    12: {"pkgs": [("scikit-learn", "sklearn"), "pandas", "numpy"]},
    13: {
        "pkgs": ["mlflow", ("scikit-learn", "sklearn"), "pandas", "pyarrow", "httpx"],
        "docker": "required",
    },
    14: {"pkgs": [], "env_optional": ["CLOVA_STUDIO_API_KEY", "OPENAI_API_KEY"]},
}

OK, WARN, FAIL = "OK  ", "주의", "실패"
_problems: list[str] = []
_warnings: list[str] = []


# 환경 점검 결과와 해결 방법을 터미널에 표시한다.
def say(mark: str, text: str, fix: str = "") -> None:
    print(f"  [{mark}] {text}")
    if fix:
        print(f"         {fix}")
    if mark == FAIL:
        _problems.append(text)
    elif mark == WARN:
        _warnings.append(text)


# 운영체제 명령을 실행하고 표준 출력과 오류를 수집한다.
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# 운영체제에 맞는 주차별 Python 가상환경 실행 파일 경로를 구한다.
def venv_python(chapter_dir: Path) -> Path:
    if platform.system() == "Windows":
        return chapter_dir / "venv" / "Scripts" / "python.exe"
    return chapter_dir / "venv" / "bin" / "python"


# 패키지 설치 명세에서 pip가 사용하는 배포 패키지 이름을 구한다.
def pip_name(spec) -> str:
    return spec[0] if isinstance(spec, tuple) else spec


# 패키지 설치 명세에서 Python이 import할 모듈 이름을 구한다.
def import_name(spec) -> str:
    return spec[1] if isinstance(spec, tuple) else spec


# ---------------------------------------------------------------- 점검

# 모든 실습의 기본 실행 환경인 Python 3.10 이상인지 확인한다.
def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        say(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        say(FAIL, f"Python {v.major}.{v.minor} — 3.10 이상이 필요하다",
            "python.org에서 최신 버전을 설치한다.")


# PySpark 실습에 필요한 Java가 설치됐고 최소 버전을 충족하는지 확인한다.
def check_java(minimum: int) -> None:
    if not shutil.which("java"):
        say(FAIL, "Java를 찾을 수 없다",
            f"PySpark 실행에 Java {minimum} 이상이 필요하다. Temurin JDK {minimum}을 설치한다.")
        return
    out = run(["java", "-version"]).stderr or run(["java", "-version"]).stdout
    m = re.search(r'version "(\d+)', out)
    if not m:
        say(WARN, "Java 버전을 읽지 못했다", "java -version 출력을 직접 확인한다.")
        return
    major = int(m.group(1))
    if major >= minimum:
        say(OK, f"Java {major}")
    else:
        say(FAIL, f"Java {major} — {minimum} 이상이 필요하다",
            f"Temurin JDK {minimum}을 설치하고 JAVA_HOME을 그쪽으로 맞춘다.")


# Kafka·통합 실습에 필요한 Docker CLI와 데몬의 실행 상태를 확인한다.
def check_docker(level: str) -> bool:
    mark = FAIL if level == "required" else WARN
    if not shutil.which("docker"):
        say(mark, "docker 명령을 찾을 수 없다", "Docker Desktop을 설치한다(4주차 강의자료 '시작 전 준비' 참조).")
        return False
    r = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if r.returncode != 0 or not r.stdout.strip():
        say(mark, "Docker 데몬에 연결할 수 없다", "Docker Desktop을 실행하고 다시 시도한다.")
        return False
    say(OK, f"Docker {r.stdout.strip()}")
    return True


# Kafka 컨테이너 등이 사용할 로컬 포트의 점유 상태를 확인한다.
def check_ports(ports: list[int]) -> None:
    busy = []
    for p in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                busy.append(p)
    if busy:
        say(WARN, f"이미 사용 중인 포트: {', '.join(map(str, busy))}",
            "이 실습의 컨테이너가 이미 떠 있으면 정상이다. 다른 프로그램이면 종료한다.")
    else:
        say(OK, f"포트 {', '.join(map(str, ports))} 사용 가능")


# Airflow처럼 POSIX 환경이 필요한 실습을 macOS·Linux·WSL에서 실행 중인지 확인한다.
def check_posix_only() -> None:
    if platform.system() == "Windows":
        say(FAIL, "이 실습은 Windows에서 직접 실행할 수 없다",
            "WSL2를 설치하고 Ubuntu 터미널에서 저장소를 열어 실행한다.")
    else:
        say(OK, f"{platform.system()} — 실행 가능한 환경")


# 외부 제약 파일을 내려받는 패키지 설치에 필요한 인터넷 연결을 확인한다.
def check_network() -> None:
    try:
        socket.create_connection(("raw.githubusercontent.com", 443), timeout=3).close()
        say(OK, "네트워크 연결 확인")
    except OSError:
        say(FAIL, "raw.githubusercontent.com에 연결할 수 없다",
            "이 실습은 설치 시 제약 파일을 내려받는다. 네트워크를 확인한다.")


# 현재 주차 실습이 요구하는 앞 주차의 실행 산출물이 준비됐는지 확인한다.
def check_needs(needs: list[tuple[str, str]]) -> None:
    for chap, fname in needs:
        path = REPO / "practice" / chap / "data" / "output" / fname
        if path.exists():
            say(OK, f"선행 산출물 {chap}/data/output/{fname}")
        else:
            n = re.sub(r"\D", "", chap)
            say(FAIL, f"선행 산출물이 없다: {chap}/data/output/{fname}",
                f"{n}장 실습을 먼저 실행한다.")


# 공공데이터·LLM API 실습에 선택적으로 쓰는 인증키 환경변수를 확인한다.
def check_env(names: list[str]) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if not missing:
        say(OK, f"환경변수 {', '.join(names)} 설정됨")
    else:
        say(WARN, f"환경변수 없음: {', '.join(missing)}",
            "선택 항목이다. 없으면 저장된 스냅샷으로 실행한다.")


# 주차별 가상환경에 실습용 Python 패키지가 설치됐는지 import로 확인한다.
def check_pkgs(py: Path, pkgs: list) -> list:
    if not pkgs:
        say(OK, "설치할 외부 패키지 없음")
        return []
    if not py.exists():
        say(WARN, "가상환경이 아직 없다", "--check 없이 다시 실행하면 만든다.")
        return pkgs
    missing = []
    for spec in pkgs:
        r = run([str(py), "-c", f"import {import_name(spec)}"])
        if r.returncode != 0:
            missing.append(spec)
    if missing:
        say(WARN, f"설치 필요: {', '.join(pip_name(s) for s in missing)}",
            "--check 없이 다시 실행하면 설치한다.")
    else:
        say(OK, f"패키지 {len(pkgs)}개 모두 설치됨")
    return missing


# ---------------------------------------------------------------- 준비

# 현재 주차 실습에 격리된 Python 가상환경을 생성한다.
def make_venv(chapter_dir: Path) -> Path:
    py = venv_python(chapter_dir)
    if py.exists():
        print(f"  가상환경이 이미 있다: {py.relative_to(REPO)}")
        return py
    print("  가상환경을 만든다 …")
    r = run([sys.executable, "-m", "venv", str(chapter_dir / "venv")])
    if r.returncode != 0:
        say(FAIL, "가상환경 생성 실패", r.stderr.strip()[:200])
        return py
    print(f"  만들었다: {py.relative_to(REPO)}")
    return py


# requirements.txt에 적힌 주차별 Python 패키지를 가상환경에 설치한다.
def install(py: Path, chapter_dir: Path, network: bool) -> None:
    req = chapter_dir / "code" / "requirements.txt"
    if not req.exists():
        print("  requirements.txt가 없다 — 건너뛴다")
        return
    cmd = [str(py), "-m", "pip", "install", "-q", "-r", str(req)]
    if network:  # Airflow는 제약 파일을 함께 쓴다
        cmd += ["--constraint",
                "https://raw.githubusercontent.com/apache/airflow/"
                "constraints-3.3.0/constraints-3.13.txt"]
    print(f"  패키지를 설치한다 … ({' '.join(cmd[-2:])})")
    r = run(cmd)
    if r.returncode == 0:
        say(OK, "패키지 설치 완료")
    else:
        say(FAIL, "패키지 설치 실패", r.stderr.strip().splitlines()[-1][:200] if r.stderr else "")


# Kafka 등 실습에 필요한 Docker Compose 서비스를 백그라운드에서 시작한다.
def start_compose(compose: tuple[str, list[str]]) -> None:
    chap, services = compose
    cwd = REPO / "practice" / chap
    print(f"  컨테이너를 띄운다: {' '.join(services)} ({chap}) …")
    r = run(["docker", "compose", "up", "-d", *services], cwd=str(cwd))
    if r.returncode == 0:
        say(OK, f"컨테이너 기동: {' '.join(services)}")
    else:
        say(FAIL, "컨테이너 기동 실패",
            (r.stderr or r.stdout).strip().splitlines()[-1][:200])


# ---------------------------------------------------------------- 본체

# 선택한 주차의 환경 점검, 가상환경 구성, 패키지 설치, 컨테이너 기동을 순서대로 수행한다.
def main() -> int:
    ap = argparse.ArgumentParser(description="실습 환경 점검과 준비")
    ap.add_argument("chapter", type=int, help="주차 번호 (예: 4)")
    ap.add_argument("--check", action="store_true", help="점검만 하고 아무것도 바꾸지 않는다")
    ap.add_argument("--no-docker", action="store_true", help="컨테이너를 띄우지 않는다")
    a = ap.parse_args()

    spec = CHAPTERS.get(a.chapter)
    if spec is None:
        print(f"{a.chapter}주차는 이 저장소의 실습 대상이 아니다. "
              f"가능한 주차: {', '.join(map(str, sorted(CHAPTERS)))}")
        return 2

    chapter_dir = REPO / "practice" / f"chapter{a.chapter}"
    if not chapter_dir.is_dir():
        print(f"실습 폴더가 없다: {chapter_dir}")
        return 2

    print(f"\n{a.chapter}주차 실습 환경 점검\n" + "-" * 44)
    check_python()
    if spec.get("posix_only"):
        check_posix_only()
    if spec.get("java"):
        check_java(spec["java"])
    if spec.get("network"):
        check_network()

    docker_up = False
    if spec.get("docker"):
        docker_up = check_docker(spec["docker"])
    if spec.get("ports"):
        check_ports(spec["ports"])
    if spec.get("needs"):
        check_needs(spec["needs"])
    if spec.get("env_optional"):
        check_env(spec["env_optional"])

    py = venv_python(chapter_dir)
    missing = check_pkgs(py, spec.get("pkgs", []))

    if not a.check and not _problems:
        print("\n환경 준비\n" + "-" * 44)
        py = make_venv(chapter_dir)
        if missing or not py.exists():
            install(py, chapter_dir, bool(spec.get("network")))
        else:
            print("  설치할 패키지가 없다")
        if spec.get("compose") and docker_up and not a.no_docker:
            start_compose(spec["compose"])

    print("\n" + "-" * 44)
    if _problems:
        print(f"준비 안 됨 — 해결할 항목 {len(_problems)}개")
        for p in _problems:
            print(f"  · {p}")
        print("\n위 항목을 해결한 뒤 다시 실행한다.")
        return 1

    if _warnings:
        print(f"준비 완료 (주의 {len(_warnings)}건)")
    else:
        print("준비 완료")

    act = venv_python(chapter_dir).parent
    activate = (f"{act}\\activate" if platform.system() == "Windows"
                else f"source {act}/activate")
    print(f"\n다음 명령으로 실습을 시작한다.\n"
          f"  cd practice/chapter{a.chapter}\n  {activate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
