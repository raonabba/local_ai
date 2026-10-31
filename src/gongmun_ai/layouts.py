"""한글 문서 양식.

- 기안문: 기관명 / 수신·(경유)·제목 / 본문 항목 / 붙임 / 발신명의 / 결재란·시행·주소
- 보고서(붙임 자료): 표지(등록번호·결재란, 제목 띠, 로고, 요약 상자, 기관명)와
  본문(Ⅰ 장 제목 상자, 1. 절 제목, 문단·○ 항목·※ 참고, 머리행 음영·이중선 표)
"""

from __future__ import annotations

from .gianmun import Gianmun
from .hwpx import DOUBLE, THICK, THIN, Cell, HwpxWriter, Line
from .proofread import _parse_item
from .report import ROMAN, Report, Table
from .settings import Settings

BLUE = Line("0.7 mm", "#1F3D99")
HEAD_FILL = "#D9D9D9"
LABEL_FILL = "#F2F2F2"
NO_BORDER = (None, None, None, None)


def _char_mm(w: HwpxWriter, size: float | None = None) -> float:
    """한글 한 글자 폭(mm)."""
    return (size or w.body_size) * 0.3528


def _spaced(name: str) -> str:
    """'국방부' → '국 방 부' (짧은 기관명은 글자 사이를 띄워 무게를 준다)."""
    return " ".join(name) if len(name) <= 4 and " " not in name else name


def _writer(s: Settings) -> HwpxWriter:
    return HwpxWriter(s.body_font, s.body_size)


# ---------------------------------------------------------------- 기안문

def gianmun_hwpx(doc: Gianmun, s: Settings) -> HwpxWriter:
    w = _writer(s)
    cm = _char_mm(w)
    rule = w.border(None, None, None, THICK)
    w.paragraph(s.org, w.char(20, True, s.title_font), w.para("CENTER", after=10))

    label = w.char(bold=True)
    for head, value in (("수신", doc.recipient), ("(경유)", ""), ("제목", doc.title)):
        border = rule if head == "제목" else None
        w.paragraph([(head + ("  " if value else ""), label), (value, w.char())],
                    para=w.para("LEFT", left=0, indent=0, border=border, after=6 if border else 0))

    for depth, mark, text in doc.body_lines():
        hang = cm * (len(mark) * 0.55 + 0.5) if mark else 0
        para = w.para(left=depth * cm + hang, indent=-hang)
        w.paragraph(f"{mark} {text}" if mark else text, para=para)
    lines = doc.attachment_lines()
    if lines:
        w.paragraph("")
        for line in lines:
            w.paragraph(line, para=w.para("LEFT", left=cm * 3, indent=-cm * 3))
    _append_end_mark(w)

    w.paragraph("")
    w.paragraph("")
    w.paragraph(s.sender, w.char(22, True, s.title_font), w.para("CENTER", after=14))

    small = 10.5
    n = len(s.approvers) + 1
    width = w.text_width / n
    titles = ["기안자", *("검토자" for _ in s.approvers[:-1]), "결재권자"]
    w.table([[Cell(f"{t} {p}", size=small) for t, p in zip(titles, ["", *s.approvers])],
             [Cell("", size=small) for _ in range(n)],
             [Cell("협조자", size=small, align="LEFT", colspan=n), *[None] * (n - 1)]],
            [width] * n, row_height_mm=7)
    foot = [f"시행  {s.dept}-(    )  (    )        접수  (    )",
            f"우 {s.address}" + (f"  /  {s.homepage}" if s.homepage else ""),
            f"전화번호 {s.phone}   전송 {s.fax}   /  {s.email}   /  {s.disclosure}"]
    rows = [[Cell(text, size=small, align="LEFT", borders=(None, None, THIN, None))] for text in foot]
    w.table(rows, [w.text_width], row_height_mm=6)
    return w


def _append_end_mark(w: HwpxWriter) -> None:
    """마지막 본문 문단 끝에 '  끝.'을 붙인다."""
    last = w._body[-1]
    idx = last.rfind("</hp:t>")
    w._body[-1] = last[:idx] + "  끝." + last[idx:]
    w._plain[-1] += "  끝."


# ---------------------------------------------------------------- 보고서

def report_hwpx(rep: Report, s: Settings) -> HwpxWriter:
    w = _writer(s)
    _cover(w, rep, s)
    w.page_break()
    for i, section in enumerate(rep.sections):
        _section(w, i, section, s)
    return w


def _cover(w: HwpxWriter, rep: Report, s: Settings) -> None:
    small = 10
    lab = dict(size=small, bold=True, fill=LABEL_FILL)
    gap = Cell("", borders=NO_BORDER)
    n = len(s.approvers)
    widths = [18, 30, 6, 20] + [(w.text_width - 74) / n] * n
    rows = [
        [Cell("등록번호", **lab), Cell(s.reg_no, size=small), gap, Cell("기  안", **lab),
         *(Cell(a, **lab) for a in s.approvers)],
        [Cell("보존기간", **lab), Cell(s.keep, size=small), gap, Cell(s.drafter, size=small, rowspan=3),
         *(Cell("", rowspan=3) for _ in s.approvers)],
        [Cell("결재일자", **lab), Cell("", size=small), gap, None, *[None] * n],
        [Cell("공개구분", **lab), Cell(s.disclosure, size=small), gap, None, *[None] * n],
        [Cell("언론홍보", **lab), Cell(s.press, size=small), gap, Cell("협  조", **lab),
         Cell(":", size=small, align="LEFT", colspan=n), *[None] * (n - 1)],
    ]
    w.table(rows, widths, row_height_mm=7)
    for _ in range(3):
        w.paragraph("")

    w.table([[Cell(rep.title, size=24, bold=True, font=s.title_font, borders=(None, None, BLUE, BLUE))]],
            [w.text_width], row_height_mm=20)
    w.paragraph("")
    logo = s.logo_bytes()
    if logo:
        w.image(logo, 55)
    else:
        for _ in range(6):
            w.paragraph("")
    w.paragraph("")

    if rep.summary:
        lines = [f"▫ {rep.summary[0]}", *(f" ․ {x}" for x in rep.summary[1:])]
        w.table([[Cell("\n".join(lines), size=13, align="LEFT")]], [110], row_height_mm=30)
    for _ in range(4):
        w.paragraph("")
    w.paragraph(_spaced(s.org), w.char(24, True, s.title_font), w.para("CENTER"))
    w.paragraph(s.dept, w.char(13, False, s.title_font), w.para("CENTER"))


def _section(w: HwpxWriter, i: int, section, s: Settings) -> None:
    head = dict(size=16, bold=True, font=s.title_font)
    w.table([[Cell(ROMAN[i % len(ROMAN)], borders=(THICK, THICK, THICK, THICK), **head),
              Cell(section.title, align="LEFT", borders=(None, THIN, THIN, THIN), **head)]],
            [14, w.text_width - 14], align="LEFT", row_height_mm=11)
    w.paragraph("", para=w.para(line=100))

    cm = _char_mm(w)
    body = w.char()
    note = w.char(w.body_size - 2)
    for j, sub in enumerate(section.subs, 1):
        w.paragraph(f"{j}. {sub.heading}", w.char(w.body_size + 1, True, s.title_font),
                    w.para("LEFT", before=10, after=4, keep_next=True))
        for p in sub.paragraphs:
            w.paragraph(p, body, w.para(left=cm * 1.5, indent=cm))  # 첫 줄 들여쓰기
        for b in sub.bullets:
            mark, text = _bullet(b)
            w.paragraph(f"{mark} {text}", body, w.para(left=cm * (2.5 if mark == "-" else 1.5) + cm * 1.2,
                                                        indent=-cm * 1.2))
        for n in sub.notes:
            w.paragraph(f"※ {n.removeprefix('※').strip()}", note, w.para(left=cm * 3, indent=-cm * 1.2))
        if sub.table:
            _table(w, sub.table, cm)


def _bullet(text: str) -> tuple[str, str]:
    """'- 세부' 처럼 하위 부호로 시작하면 그대로, 아니면 '○'."""
    text = text.strip()
    for mark in ("○", "◦", "-", "·", "•"):
        if text.startswith(mark):
            return ("-" if mark in "-·•" else "○"), text[len(mark):].strip()
    return "○", text


def _table(w: HwpxWriter, t: Table, cm: float) -> None:
    if t.title:
        w.paragraph(f"※ {t.title.removeprefix('※').strip()}", w.char(bold=True),
                    w.para("LEFT", left=cm * 1.5, before=6, keep_next=True))
    size = w.body_size - 2
    cols = len(t.columns)
    header = [Cell(c, bold=True, fill=HEAD_FILL, size=size) for c in t.columns]
    body = [[Cell(v, size=size) for v in r] for r in t.rows]
    # 첫 열에 같은 값이 이어지면 세로로 합친다(예: 소속).
    r = 0
    while r < len(body):
        k = r + 1
        while k < len(body) and body[k][0] is not None and body[k][0].text == body[r][0].text and body[r][0].text:
            k += 1
        if k - r > 1:
            body[r][0].rowspan = k - r
            for x in range(r + 1, k):
                body[x][0] = None
        r = k
    avail = w.text_width - cm * 1.5
    lens = [max([len(t.columns[c])] + [len(row[c]) for row in t.rows]) + 2 for c in range(cols)]
    widths = [max(avail * n / sum(lens), 14) for n in lens]
    widths = [x * avail / sum(widths) for x in widths]
    w.table([header, *body], widths, outer=THICK, header_rows=1, header_line=DOUBLE, row_height_mm=7.5)
    w.paragraph("", para=w.para(line=100))


# ---------------------------------------------------------------- 일반 글

def text_hwpx(text: str, s: Settings) -> HwpxWriter:
    """교정·톤 조정 결과 같은 일반 글을 한글 문서로. 항목 기호에 맞춰 내어쓰기한다."""
    w = _writer(s)
    cm = _char_mm(w)
    for line in text.split("\n"):
        parsed = _parse_item(line)
        stripped = line.strip()
        if parsed:
            level, _, _, mlen, _ = parsed
            hang = cm * (mlen * 0.55 + 0.5)
            w.paragraph(stripped, para=w.para(left=level * cm + hang, indent=-hang))
        elif stripped.startswith(("수신", "제목", "(경유)")):
            head, _, rest = stripped.partition(" ")
            w.paragraph([(head + ("  " if rest.strip() else ""), w.char(bold=True)), (rest.strip(), w.char())],
                        para=w.para("LEFT"))
        else:
            w.paragraph(stripped)
    return w
