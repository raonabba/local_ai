"""보고서(붙임 자료) 구조.

표지 제목·요약 상자, 'Ⅰ. 개요' 같은 큰 장, '1. 목적' 같은 절, 문단·○ 항목·※ 참고·표로 이루어진다.
AI는 이 구조를 JSON으로 채우고, 서식은 layouts가 한글 문서로 찍는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"


@dataclass
class Table:
    title: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.columns)


@dataclass
class Sub:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    table: Table = field(default_factory=Table)


@dataclass
class Section:
    title: str
    subs: list[Sub] = field(default_factory=list)


@dataclass
class Report:
    title: str
    summary: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        def strs(v) -> list[str]:
            return [str(x).strip() for x in v or [] if str(x).strip()]

        def table(t) -> Table:
            t = t or {}
            cols = strs(t.get("columns"))
            rows = [[str(c).strip() for c in r][:len(cols)] + [""] * (len(cols) - len(r))
                    for r in t.get("rows") or [] if any(str(c).strip() for c in r)]
            return Table(str(t.get("title", "")).strip(), cols, rows if cols else [])

        sections = []
        for s in d.get("sections") or []:
            subs = [Sub(str(x.get("heading", "")).strip(), strs(x.get("paragraphs")), strs(x.get("bullets")),
                        strs(x.get("notes")), table(x.get("table")))
                    for x in s.get("subs") or []]
            sections.append(Section(str(s.get("title", "")).strip(), subs))
        return cls(str(d.get("title", "")).strip(), strs(d.get("summary")), sections)

    def map_text(self, fn) -> None:
        self.title = fn(self.title)
        self.summary = [fn(x) for x in self.summary]
        for s in self.sections:
            s.title = fn(s.title)
            for sub in s.subs:
                sub.heading = fn(sub.heading)
                sub.paragraphs = [fn(x) for x in sub.paragraphs]
                sub.bullets = [fn(x) for x in sub.bullets]
                sub.notes = [fn(x) for x in sub.notes]
                sub.table.rows = [[fn(c) for c in r] for r in sub.table.rows]

    def content(self) -> str:
        """서식 번호를 뺀 내용(사실 검사용)."""
        out = [self.title, *self.summary]
        for s in self.sections:
            out.append(s.title)
            for sub in s.subs:
                out += [sub.heading, *sub.paragraphs, *sub.bullets, *sub.notes]
                out += [" ".join(r) for r in sub.table.rows]
        return "\n".join(out)

    def to_text(self) -> str:
        """화면 미리보기용 글."""
        lines = [f"[{self.title}]", ""]
        if self.summary:
            lines += [f"  ▫ {self.summary[0]}", *(f"   ․ {x}" for x in self.summary[1:]), ""]
        for i, s in enumerate(self.sections):
            lines.append(f"{ROMAN[i % len(ROMAN)]}. {s.title}")
            for j, sub in enumerate(s.subs, 1):
                lines.append(f"  {j}. {sub.heading}")
                lines += [f"    {p}" for p in sub.paragraphs]
                lines += [f"    ○ {b}" for b in sub.bullets]
                lines += [f"    ※ {n}" for n in sub.notes]
                if sub.table:
                    if sub.table.title:
                        lines.append(f"    ※ {sub.table.title}")
                    lines.append("    " + " | ".join(sub.table.columns))
                    lines += ["    " + " | ".join(r) for r in sub.table.rows]
            lines.append("")
        return "\n".join(lines).rstrip()


_STR_LIST = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": _STR_LIST,
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subs": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "paragraphs": _STR_LIST,
                        "bullets": _STR_LIST,
                        "notes": _STR_LIST,
                        "table": {"type": "object", "properties": {
                            "title": {"type": "string"},
                            "columns": _STR_LIST,
                            "rows": {"type": "array", "items": _STR_LIST}},
                            "required": ["title", "columns", "rows"]},
                    },
                    "required": ["heading", "paragraphs", "bullets", "notes", "table"]}},
            },
            "required": ["title", "subs"]}},
    },
    "required": ["title", "summary", "sections"],
}
