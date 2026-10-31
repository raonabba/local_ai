"""설치 없이 쓰는 윈도우용 묶음(공문서AI 폴더와 ZIP)을 만든다.

GitHub Actions의 windows 러너에서 실행한다(.github/workflows/windows-zip.yml).
파이썬·tkinter·AI 엔진(llama.cpp)·HWP 읽기(python-hwpx)·PDF 읽기(pypdf)를 실행 파일 안에 넣는다.
"""

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = DIST / "공문서AI"
ZIP = DIST / "GongmunAI_windows.zip"  # GitHub 릴리스는 첨부 파일 이름의 한글을 지우므로 영문으로


def build_exe() -> None:
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", "GongmunAI", "--collect-data", "gongmun_ai",
            "--distpath", str(DIST / "pyinstaller"), "--workpath", str(ROOT / "build")]
    for pkg in ("llama_cpp", "hwpx", "pypdf"):
        if importlib.util.find_spec(pkg) is None:
            raise SystemExit(f"{pkg}이(가) 설치되지 않았습니다.")
        args += ["--collect-all", pkg]
    args.append(str(ROOT / "packaging" / "run_gui.py"))
    subprocess.run(args, check=True)


def assemble() -> None:
    shutil.rmtree(APP, ignore_errors=True)
    shutil.move(DIST / "pyinstaller" / "GongmunAI", APP)
    (APP / "GongmunAI.exe").rename(APP / "공문서AI.exe")
    shutil.copy(ROOT / "설정.toml", APP)
    shutil.copy(ROOT / "packaging" / "AI모델_받기.bat", APP)
    shutil.copy(ROOT / "packaging" / "사용설명.txt", APP)
    for folder in ("profiles", "examples"):
        shutil.copytree(ROOT / folder, APP / folder)
    (APP / "models").mkdir()
    shutil.copy(ROOT / "models" / "README.md", APP / "models")
    (APP / "지식").mkdir()
    (APP / "문서").mkdir()
    shutil.copy(ROOT / "docs" / "공문서_작성_규칙.md", APP / "문서")
    licenses = APP / "문서" / "라이선스"
    licenses.mkdir()
    for f in (ROOT / "src" / "gongmun_ai" / "templates").glob("*.txt"):
        shutil.copy(f, licenses)


def self_test() -> None:
    """만든 실행 파일이 실제로 동작하는지 창 없이 점검한다."""
    result = subprocess.run([str(APP / "공문서AI.exe"), "--self-test"], timeout=300)
    report = APP / "selftest.txt"
    text = report.read_text(encoding="utf-8") if report.exists() else "(selftest.txt 없음)"
    print(text)
    report.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SystemExit("자체 점검 실패")


def make_zip() -> None:
    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(APP.rglob("*")):
            z.write(f, f.relative_to(DIST))
    print(f"{ZIP.name}: {ZIP.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    build_exe()
    assemble()
    self_test()
    make_zip()
