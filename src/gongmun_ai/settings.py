"""기관 정보 설정(설정.toml).

문서 머리·발신명의·결재란·표지에 들어갈 값이다. 메모장으로 고쳐 쓰면 된다.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def app_root() -> Path:
    """프로그램 폴더. 실행 파일로 묶였으면 exe가 있는 폴더, 아니면 저장소 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    org: str = "국방부"                     # 기관명(기안문 맨 위, 보고서 표지 아래)
    dept: str = "○○정책과"                  # 처리과
    sender: str = "국방부장관"               # 발신명의
    drafter: str = "○○○"                   # 기안자 이름
    approvers: list[str] = field(default_factory=lambda: ["과장", "국장", "실장"])  # 결재란 직위
    reg_no: str = "○○정책과-0000"           # 등록번호
    keep: str = "3년"                        # 보존기간
    disclosure: str = "공개"                 # 공개구분
    press: str = "×"                         # 언론홍보
    address: str = "00000 ○○시 ○○구 ○○로 00"
    homepage: str = ""
    phone: str = "02-000-0000"
    fax: str = "02-000-0000"
    email: str = "○○○@○○.○○"
    logo: str = "로고.png"                   # 프로그램 폴더의 그림 파일. 있으면 보고서 표지에 넣는다.
    body_font: str = "휴먼명조"
    title_font: str = "HY헤드라인M"
    body_size: float = 13

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        path = Path(path) if path else app_root() / "설정.toml"
        if not path.is_file():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def logo_bytes(self) -> bytes | None:
        p = Path(self.logo)
        if not p.is_absolute():
            p = app_root() / p
        return p.read_bytes() if p.is_file() else None
