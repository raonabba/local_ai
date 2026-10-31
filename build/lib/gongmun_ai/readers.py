"""여러 형식의 문서에서 글을 꺼낸다(학습·참고 문서용).

표는 칸을 ' | '로 이어 한 줄로 만든다.
- .txt: 바로 읽음 (UTF-8·CP949)
- .hwpx: 직접 읽음
- .hwp: python-hwpx(Apache-2.0)가 있으면 읽음 (실행 파일 묶음에는 들어 있음)
- .docx: 직접 읽음
- .pdf: pypdf가 있으면 읽음
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from . import hwpx

SUPPORTED = (".txt", ".hwpx", ".hwp", ".docx", ".pdf")


class UnsupportedFile(ValueError):
    pass


def read_document(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == ".txt":
            from .cli import read_text
            return read_text(str(path))
        if ext == ".hwpx":
            return hwpx.read_text(path)
        if ext == ".hwp":
            return _read_hwp(path)
        if ext == ".docx":
            return _read_docx(path)
        if ext == ".pdf":
            return _read_pdf(path)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise UnsupportedFile(f"{path.name}: 파일을 읽지 못했습니다({e}).") from e
    raise UnsupportedFile(f"{path.name}: 지원하지 않는 형식입니다({', '.join(SUPPORTED)}).")


def _read_hwp(path: Path) -> str:
    try:
        from hwpx import HwpxDocument
    except ImportError:
        raise UnsupportedFile(f"{path.name}: HWP 읽기 기능이 없습니다. 한글에서 HWPX로 저장한 뒤 넣어 주세요.") from None
    try:
        text = HwpxDocument.open(str(path)).text.plain()
    except Exception as e:  # 암호·배포용 문서 등
        raise UnsupportedFile(f"{path.name}: HWP 파일을 읽지 못했습니다(암호·배포용 문서일 수 있음). {e}") from e
    return "\n".join(" | ".join(c.strip() for c in line.split("\t")) if "\t" in line else line
                     for line in text.split("\n"))


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path: Path) -> str:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    lines: list[str] = []

    def para_text(p) -> str:
        return "".join(t.text or "" for t in p.iter(f"{_W}t"))

    for el in body:
        if el.tag == f"{_W}p":
            lines.append(para_text(el))
        elif el.tag == f"{_W}tbl":
            for tr in el.iter(f"{_W}tr"):
                cells = [" ".join(para_text(p) for p in tc.iter(f"{_W}p")).strip() for tc in tr.findall(f"{_W}tc")]
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise UnsupportedFile(f"{path.name}: PDF 읽기 기능이 없습니다.") from None
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return re.sub(r"[ \t]+\n", "\n", text)
