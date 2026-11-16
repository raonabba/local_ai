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

        def notes(v) -> list[str]:
            # '※'는 서식이 붙이므로 떼고, 작은 모델이 자리만 채운 '참고 사항' 같은 빈 말은 뺀다.
            out = [n.lstrip("※ ").strip() for n in strs(v)]
            return [n for n in out if n.replace(" ", "") not in ("참고사항", "참고", "비고", "없음", "")]

        def table(t) -> Table:
            t = t or {}
            cols = strs(t.get("columns"))
            rows = [[str(c).strip() for c in r][:len(cols)] + [""] * (len(cols) - len(r))
                    for r in t.get("rows") or [] if any(str(c).strip() for c in r)]
            return Table(str(t.get("title", "")).strip(), cols, rows if cols else [])

        def sub(x) -> Sub:
            bullets, extra_notes = strs(x.get("bullets")), []
            # 간결한 형식(AI 초안): items 하나에 ○ 항목과 '※ 참고'를 함께 받는다.
            for item in strs(x.get("items")):
                (extra_notes if item.startswith("※") else bullets).append(item)
            return Sub(str(x.get("heading", "")).strip(), strs(x.get("paragraphs")), bullets,
                       notes(x.get("notes")) + notes(extra_notes), table(x.get("table")))

        sections = [Section(str(s.get("title", "")).strip(), [sub(x) for x in s.get("subs") or []])
                    for s in d.get("sections") or []]
        rep = cls(str(d.get("title", "")).strip(), strs(d.get("summary")), sections)
        if t := table(d.get("table")):
            rep._place_table(t)
        return rep

    def _place_table(self, t: Table) -> None:
        """보고서에 하나만 받은 표를 일정·계획을 다루는 장(없으면 가운데 장)의 마지막 절에 붙인다."""
        subs_by_section = [s for s in self.sections if s.subs]
        if not subs_by_section:
            return
        target = next((s for s in subs_by_section if any(k in s.title for k in ("계획", "일정", "추진"))),
                      subs_by_section[min(1, len(subs_by_section) - 1)])
        target.subs[-1].table = t

    def drop_trivial_tables(self) -> None:
        """한두 칸짜리 표(예: 시작일 | 종료일 한 줄)는 항목과 같은 말이라 뺀다. 작은 모델이 절마다 표를 붙이는 버릇이 있다."""
        for s in self.sections:
            for sub in s.subs:
                t = sub.table
                if t and (len(t.rows) < 2 or len(t.columns) < 2):
                    sub.table = Table()

    def merge_duplicate_headings(self) -> None:
        """한 장 안에서 같은 소제목이 되풀이되면(작은 모델에서 흔함) 하나로 합친다."""
        for s in self.sections:
            merged: dict[str, Sub] = {}
            for sub in s.subs:
                key = sub.heading.replace(" ", "")
                if key in merged:
                    first = merged[key]
                    first.paragraphs += sub.paragraphs
                    first.bullets += sub.bullets
                    first.notes += sub.notes
                    if not first.table:
                        first.table = sub.table
                else:
                    merged[key] = sub
            s.subs = list(merged.values())

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


def _text(max_len: int) -> dict:
    return {"type": "string", "maxLength": max_len}


def _list(max_len: int, max_items: int, min_items: int = 0) -> dict:
    return {"type": "array", "items": _text(max_len), "minItems": min_items, "maxItems": max_items}


# AI 초안용 간결한 형식. 절마다 소제목과 항목(items)만 받고 표는 보고서에 하나만 받는다.
# 저사양 PC에서는 AI가 쓰는 낱말 하나하나가 시간이라, 빈 문단·참고·표 칸을 절마다 쓰게 하지 않는다.
# 글자 수와 항목 수의 상한도 문법으로 강제해 같은 말을 되풀이하며 길어지지 않게 한다(A4 2쪽 안팎).
SCHEMA = {
    "type": "object",
    "properties": {
        "title": _text(40),
        "summary": _list(60, 3, 2),
        "sections": {"type": "array", "minItems": 3, "maxItems": 3, "items": {
            "type": "object",
            "properties": {
                "title": _text(20),
                "subs": {"type": "array", "minItems": 1, "maxItems": 2, "items": {
                    "type": "object",
                    "properties": {"heading": _text(20), "items": _list(60, 4, 2)},
                    "required": ["heading", "items"]}},
            },
            "required": ["title", "subs"]}},
        "table": {"type": "object", "properties": {
            "title": _text(20),
            "columns": _list(10, 4),
            "rows": {"type": "array", "maxItems": 5, "items": _list(30, 4)}},
            "required": ["title", "columns", "rows"]},
    },
    "required": ["title", "summary", "sections", "table"],
}
