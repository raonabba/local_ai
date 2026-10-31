"""기안문 구조와 표준 서식 출력.

AI는 내용(JSON)만 만들고, 항목 기호·들여쓰기·붙임·끝 표시 같은 서식은 이 모듈이
규칙대로 찍는다. 작은 모델이 서식을 틀려도 결과물은 늘 서식에 맞는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .proofread import INDENT, marker


@dataclass
class Item:
    text: str
    children: list["Item"] = field(default_factory=list)


@dataclass
class Gianmun:
    title: str
    recipient: str = "내부결재"
    related: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Gianmun":
        def item(x) -> Item:
            if isinstance(x, str):
                return Item(x.strip())
            subs = x.get("sub") or x.get("children") or []
            return Item(str(x.get("text", "")).strip(), [item(s) for s in subs])

        return cls(
            title=str(d.get("title", "")).strip(),
            recipient=str(d.get("recipient") or "내부결재").strip(),
            related=[str(r).strip() for r in d.get("related") or [] if str(r).strip()],
            items=[item(x) for x in d.get("items") or []],
            attachments=[str(a).strip() for a in d.get("attachments") or [] if str(a).strip()],
        )

    def map_text(self, fn) -> None:
        """모든 문장에 fn을 적용한다(교정 결과 반영용)."""
        self.title = fn(self.title)
        self.related = [fn(r) for r in self.related]
        self.attachments = [fn(a) for a in self.attachments]

        def walk(items):
            for it in items:
                it.text = fn(it.text)
                walk(it.children)
        walk(self.items)

    def content(self) -> str:
        """서식 번호·붙임을 뺀 내용 문장만(사실 검사용)."""
        out = [self.title, *self.related]

        def walk(items):
            for it in items:
                out.append(it.text)
                walk(it.children)
        walk(self.items)
        return "\n".join(out)

    def render(self) -> str:
        lines = [f"수신  {self.recipient}", "(경유)", f"제목  {self.title}", ""]

        body: list[Item] = []
        if len(self.related) == 1:
            body.append(Item(f"관련: {self.related[0]}"))
        elif self.related:
            body.append(Item("관련", [Item(r) for r in self.related]))
        body += self.items

        def emit(items, depth):
            for n, it in enumerate(items, 1):
                lines.append(" " * (depth * INDENT) + f"{marker(depth, n)} {it.text}")
                emit(it.children, depth + 1)
        emit(body, 0)

        if self.attachments:
            lines.append("")
            for n, a in enumerate(self.attachments, 1):
                a = _attachment_text(a)
                if len(self.attachments) == 1:
                    lines.append(f"붙임  {a}")
                else:
                    lines.append(("붙임  " if n == 1 else "      ") + f"{n}. {a}")
        lines[-1] += "  끝."
        return "\n".join(lines)


_COPIES = re.compile(r"\d+\s*부\.?$")


def _attachment_text(a: str) -> str:
    a = a.rstrip(" .")
    if not _COPIES.search(a):
        a += " 1부"
    return a + "."


# 작은 모델도 지킬 수 있게 두 단계까지만 받는다(더 깊은 단계는 render가 지원).
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "recipient": {"type": "string"},
        "related": {"type": "array", "items": {"type": "string"}},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "sub": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "sub"]}},
        "attachments": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "recipient", "related", "items", "attachments"],
}
