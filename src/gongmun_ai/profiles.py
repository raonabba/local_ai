"""결재권자(팀장·부서장) 성향 프로필.

TOML 파일 하나에 한 사람의 선호를 적어 두면, 초안 작성과 톤 조정 때
그 사람이 좋아하는 구성·문체로 맞추고, 빠진 항목을 점검해 준다.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# 두괄식 여부를 판단할 때 첫 항목에 이런 말이 있으면 결론이 먼저 나온 것으로 본다.
CONCLUSION_WORDS = ("결론", "요약", "건의", "요청", "승인", "결정", "보고드림", "하고자 함", "계획임")


@dataclass
class Profile:
    name: str
    role: str = ""
    style: str = "개조식"           # 개조식 | 서술식
    conclusion_first: bool = False  # 두괄식(결론 먼저)
    max_chars: int = 0              # 0이면 제한 없음
    prefer: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "name" not in known:
            raise ValueError(f"{path}: name 항목이 필요합니다.")
        return cls(**known)

    def to_prompt(self) -> str:
        lines = [f"보고 대상: {self.name}" + (f" ({self.role})" if self.role else ""),
                 f"- 문체: {self.style}"]
        if self.conclusion_first:
            lines.append("- 첫 항목에 결론·요청 사항을 먼저 쓴다(두괄식).")
        if self.max_chars:
            lines.append(f"- 전체 분량은 {self.max_chars}자 이내로 줄인다.")
        if self.required_sections:
            lines.append(f"- 반드시 포함할 항목: {', '.join(self.required_sections)}")
        if self.prefer:
            lines.append(f"- 선호하는 표현: {', '.join(self.prefer)}")
        if self.avoid:
            lines.append(f"- 쓰지 말 표현: {', '.join(self.avoid)}")
        if self.notes:
            lines.append(f"- 참고: {self.notes}")
        return "\n".join(lines)

    def check(self, text: str) -> list[str]:
        """이 결재권자 기준으로 보완할 점."""
        problems = []
        for sec in self.required_sections:
            if sec.replace(" ", "") not in text.replace(" ", ""):
                problems.append(f"'{sec}' 항목이 없습니다.")
        for word in self.avoid:
            if word in text:
                problems.append(f"쓰지 말 표현 '{word}'이(가) 있습니다.")
        if self.max_chars and len(text) > self.max_chars:
            problems.append(f"분량이 {len(text)}자로, 기준 {self.max_chars}자를 넘습니다.")
        if self.conclusion_first:
            first = _first_item(text)
            if first and not any(w in first for w in CONCLUSION_WORDS):
                problems.append("첫 항목에 결론·요청 사항이 보이지 않습니다(두괄식 선호).")
        return problems


_ITEM_LINE = re.compile(r"^\s*\d{1,2}\.\s+(.*)$", re.M)


def _first_item(text: str) -> str | None:
    """'관련' 항목을 건너뛴 첫 본문 항목."""
    for m in _ITEM_LINE.finditer(text):
        if not m.group(1).startswith("관련"):
            return m.group(1)
    return None
