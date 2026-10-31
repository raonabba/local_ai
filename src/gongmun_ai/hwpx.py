"""HWPX(한글 문서, KS X 6101) 작성기.

python-hwpx의 빈 문서(templates/skeleton.hwpx)를 바탕으로 글꼴·글자 모양·문단 모양·
테두리를 덧붙이고 본문을 써 넣는다. 한글 프로그램을 자동 조작하지 않고 파일을 직접 만든다.

단위: 글자 크기는 pt, 길이는 mm로 받아 HWPUNIT(1pt = 100, 1mm ≈ 283.5)으로 바꾼다.
줄 배치 정보(linesegarray)는 넣지 않는다. 한글이 파일을 열 때 다시 계산한다.
"""

from __future__ import annotations

import itertools
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

SKELETON = Path(__file__).parent / "templates" / "skeleton.hwpx"
LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
BASE_FONT_COUNT = 2  # skeleton에 언어마다 들어 있는 글꼴 수(함초롬돋움, 함초롬바탕)


def mm(value: float) -> int:
    return round(value * 283.465)


@dataclass(frozen=True)
class Line:
    """표·문단 테두리 선."""
    width: str = "0.12 mm"
    color: str = "#000000"
    type: str = "SOLID"


THIN = Line()
THICK = Line("0.4 mm")
DOUBLE = Line("0.5 mm", type="DOUBLE_SLIM")


@dataclass
class Cell:
    """표의 한 칸. 여러 줄은 '\\n'으로 나눈다. 병합으로 가려지는 칸은 표에 None으로 둔다."""
    text: str = ""
    colspan: int = 1
    rowspan: int = 1
    bold: bool = False
    align: str = "CENTER"
    fill: str | None = None
    size: float | None = None
    font: str | None = None
    color: str = "#000000"
    borders: tuple[Line | None, Line | None, Line | None, Line | None] | None = None  # 좌·우·위·아래
    valign: str = "CENTER"


class HwpxWriter:
    def __init__(self, body_font: str = "휴먼명조", body_size: float = 13,
                 margins_mm: tuple[float, float, float, float] = (20, 15, 15, 15)):
        with zipfile.ZipFile(SKELETON) as z:
            self._names = z.namelist()
            self._files = {n: z.read(n) for n in self._names}
        self.body_font, self.body_size = body_font, body_size
        self.margins = margins_mm  # 좌·우·위·아래
        self._fonts: dict[str, int] = {}
        self._chars: dict[tuple, int] = {}
        self._paras: dict[tuple, int] = {}
        self._borders: dict[tuple, int] = {}
        self._char_xml: list[str] = []
        self._para_xml: list[str] = []
        self._border_xml: list[str] = []
        header = self._files["Contents/header.xml"].decode("utf-8")
        self._base = {tag: int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', header).group(1))
                      for tag in ("charProperties", "paraProperties", "borderFills")}
        self._body: list[str] = []
        self._plain: list[str] = []
        self._images: list[tuple[str, bytes, str]] = []
        self._ids = itertools.count(1)

    # ------------------------------------------------------------ 모양 등록

    @property
    def text_width(self) -> float:
        """본문 폭(mm)."""
        return 210 - self.margins[0] - self.margins[1]

    def _font(self, face: str) -> int:
        if face not in self._fonts:
            self._fonts[face] = BASE_FONT_COUNT + len(self._fonts)
        return self._fonts[face]

    def char(self, size: float | None = None, bold: bool = False, font: str | None = None,
             color: str = "#000000", underline: bool = False, spacing: int = 0, ratio: int = 100) -> int:
        """글자 모양 번호. spacing은 자간(%), ratio는 장평(%)."""
        key = (size or self.body_size, bold, font or self.body_font, color, underline, spacing, ratio)
        if key in self._chars:
            return self._chars[key]
        cid = self._base["charProperties"] + len(self._char_xml)
        size, bold, face, color, underline, spacing, ratio = key
        fid = self._font(face)
        langs = " ".join(f'{l.lower()}="{{}}"' for l in LANGS)
        self._char_xml.append(
            f'<hh:charPr id="{cid}" height="{round(size * 100)}" textColor="{color}" shadeColor="none" '
            f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2">'
            f'<hh:fontRef {langs.format(*[fid] * 7)}/>'
            f'<hh:ratio {langs.format(*[ratio] * 7)}/>'
            f'<hh:spacing {langs.format(*[spacing] * 7)}/>'
            f'<hh:relSz {langs.format(*[100] * 7)}/>'
            f'<hh:offset {langs.format(*[0] * 7)}/>'
            + ("<hh:bold/>" if bold else "")
            + f'<hh:underline type="{"BOTTOM" if underline else "NONE"}" shape="SOLID" color="#000000"/>'
            '<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
            '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/></hh:charPr>')
        self._chars[key] = cid
        return cid

    def para(self, align: str = "JUSTIFY", left: float = 0, indent: float = 0, line: int = 160,
             before: float = 0, after: float = 0, keep_next: bool = False, border: int | None = None) -> int:
        """문단 모양 번호. left·indent는 mm(indent가 음수면 내어쓰기), before·after는 pt.
        border는 border()로 만든 번호로, 문단 위·아래에 가로줄을 그을 때 쓴다."""
        key = (align, left, indent, line, before, after, keep_next, border)
        if key in self._paras:
            return self._paras[key]
        pid = self._base["paraProperties"] + len(self._para_xml)

        def margin(scale: int) -> str:
            v = lambda x: round(x * scale)  # noqa: E731
            return (f'<hh:margin><hc:intent value="{v(mm(indent))}" unit="HWPUNIT"/>'
                    f'<hc:left value="{v(mm(left))}" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/>'
                    f'<hc:prev value="{v(before * 100)}" unit="HWPUNIT"/>'
                    f'<hc:next value="{v(after * 100)}" unit="HWPUNIT"/></hh:margin>'
                    f'<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>')

        # 한글은 호환용 기본값(default)에 여백을 두 배로 적는다.
        self._para_xml.append(
            f'<hh:paraPr id="{pid}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" '
            f'suppressLineNumbers="0" checked="0" textDir="LTR">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/>'
            '<hh:heading type="NONE" idRef="0" level="0"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" '
            f'keepWithNext="{int(keep_next)}" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
            '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            '<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
            f'{margin(1)}</hp:case><hp:default>{margin(2)}</hp:default></hp:switch>'
            f'<hh:border borderFillIDRef="{border or 2}" offsetLeft="0" offsetRight="0" offsetTop="0" '
            f'offsetBottom="{200 if border else 0}" connect="0" ignoreMargin="1"/></hh:paraPr>')
        self._paras[key] = pid
        return pid

    def border(self, left: Line | None = THIN, right: Line | None = THIN, top: Line | None = THIN,
               bottom: Line | None = THIN, fill: str | None = None) -> int:
        """테두리·배경 번호(표와 칸에 쓴다)."""
        key = (left, right, top, bottom, fill)
        if key in self._borders:
            return self._borders[key]
        bid = self._base["borderFills"] + 1 + len(self._border_xml)  # 테두리 번호는 1부터

        def side(name: str, ln: Line | None) -> str:
            if ln is None:
                return f'<hh:{name} type="NONE" width="0.1 mm" color="#000000"/>'
            return f'<hh:{name} type="{ln.type}" width="{ln.width}" color="{ln.color}"/>'

        brush = (f'<hc:fillBrush><hc:winBrush faceColor="{fill}" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
                 if fill else "")
        self._border_xml.append(
            f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            + side("leftBorder", left) + side("rightBorder", right)
            + side("topBorder", top) + side("bottomBorder", bottom)
            + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>' + brush + "</hh:borderFill>")
        self._borders[key] = bid
        return bid

    # ------------------------------------------------------------ 본문

    def _p(self, runs: list[tuple[str, int]], para_id: int, page_break: bool = False) -> str:
        body = "".join(f'<hp:run charPrIDRef="{c}"><hp:t>{escape(t)}</hp:t></hp:run>' for t, c in runs)
        if not runs:
            body = f'<hp:run charPrIDRef="{self.char()}"><hp:t/></hp:run>'
        return (f'<hp:p id="{next(self._ids)}" paraPrIDRef="{para_id}" styleIDRef="0" '
                f'pageBreak="{int(page_break)}" columnBreak="0" merged="0">{body}</hp:p>')

    def paragraph(self, text: str | list[tuple[str, int]] = "", char: int | None = None,
                  para: int | None = None, page_break: bool = False) -> None:
        """문단 하나. text에 (글, 글자 모양) 목록을 주면 한 문단에 모양을 섞어 쓴다."""
        runs = [(text, char if char is not None else self.char())] if isinstance(text, str) else text
        runs = [(t, c) for t, c in runs if t]
        self._body.append(self._p(runs, para if para is not None else self.para(), page_break))
        self._plain.append("".join(t for t, _ in runs))

    def page_break(self) -> None:
        self._body.append(self._p([], self.para(), page_break=True))

    def table(self, rows: list[list[Cell | None]], widths_mm: list[float], align: str = "CENTER",
              outer: Line | None = None, header_rows: int = 0, row_height_mm: float = 8,
              header_line: Line | None = None) -> None:
        """표. 병합으로 가려지는 칸은 None. outer를 주면 바깥 테두리만 그 선으로 바꾼다.
        header_line을 주면 머리행 아래를 그 선(예: 이중선)으로 긋는다."""
        widths = [mm(w) for w in widths_mm]
        n_rows, n_cols = len(rows), len(widths)
        tr_xml = []
        for r, row in enumerate(rows):
            cells = []
            c = 0
            for cell in row:
                if cell is None:
                    c += 1
                    continue
                cells.append(self._cell(cell, r, c, widths, n_rows, n_cols, outer, r < header_rows,
                                        mm(row_height_mm), header_line if r + cell.rowspan == header_rows else None))
                c += cell.colspan
            tr_xml.append("<hp:tr>" + "".join(cells) + "</hp:tr>")
        width, height = sum(widths), mm(row_height_mm) * n_rows
        tbl = (f'<hp:tbl id="{next(self._ids)}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
               f'repeatHeader="{int(header_rows > 0)}" rowCnt="{n_rows}" colCnt="{n_cols}" cellSpacing="0" '
               f'borderFillIDRef="{self.border(None, None, None, None)}" noAdjust="0">'
               f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
               '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
               + "".join(tr_xml) + "</hp:tbl>")
        self._body.append(
            f'<hp:p id="{next(self._ids)}" paraPrIDRef="{self.para(align, line=100)}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{self.char()}">{tbl}<hp:t/></hp:run></hp:p>')
        self._plain.extend(" | ".join(c.text for c in row if c) for row in rows)

    def _cell(self, cell: Cell, r: int, c: int, widths, n_rows, n_cols, outer, header, height,
              header_line: Line | None) -> str:
        left, right, top, bottom = cell.borders or (THIN, THIN, THIN, THIN)
        if outer is not None and cell.borders is None:
            left = outer if c == 0 else left
            right = outer if c + cell.colspan == n_cols else right
            top = outer if r == 0 else top
            bottom = outer if r + cell.rowspan == n_rows else bottom
        if header_line is not None and cell.borders is None:
            bottom = header_line
        bf = self.border(left, right, top, bottom, cell.fill)
        cp = self.char(cell.size, cell.bold, cell.font, cell.color)
        pp = self.para(cell.align, line=130)
        paras = "".join(self._p([(line, cp)] if line else [], pp) for line in cell.text.split("\n"))
        width = sum(widths[c:c + cell.colspan])
        return (f'<hp:tc name="" header="{int(header)}" hasMargin="0" protect="0" editable="0" dirty="0" '
                f'borderFillIDRef="{bf}"><hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
                f'vertAlign="{cell.valign}" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" '
                f'hasTextRef="0" hasNumRef="0">{paras}</hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="{cell.colspan}" rowSpan="{cell.rowspan}"/>'
                f'<hp:cellSz width="{width}" height="{height * cell.rowspan}"/>'
                '<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')

    def image(self, data: bytes, width_mm: float, align: str = "CENTER") -> None:
        """그림(PNG·JPEG)을 글자처럼 문단 안에 넣는다."""
        ext, (px_w, px_h) = _image_size(data)
        name = f"image{len(self._images) + 1}"
        self._images.append((name, data, ext))
        w = mm(width_mm)
        h = round(w * px_h / px_w)
        dim_w, dim_h = px_w * 75, px_h * 75  # 96dpi 기준 1픽셀 = 75 HWPUNIT
        oid = next(self._ids)
        pic = (f'<hp:pic id="{oid}" zOrder="1" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
               'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
               f'instid="{oid + 100000}" reverse="0"><hp:offset x="0" y="0"/>'
               f'<hp:orgSz width="{w}" height="{h}"/><hp:curSz width="{w}" height="{h}"/>'
               '<hp:flip horizontal="0" vertical="0"/>'
               f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
               '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
               '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
               '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
               f'<hc:img binaryItemIDRef="{name}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
               f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/>'
               f'<hc:pt3 x="0" y="{h}"/></hp:imgRect>'
               f'<hp:imgClip left="0" right="{dim_w}" top="0" bottom="{dim_h}"/>'
               '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
               f'<hp:imgDim dimwidth="{dim_w}" dimheight="{dim_h}"/><hp:effects/>'
               f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="1" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>')
        self._body.append(
            f'<hp:p id="{next(self._ids)}" paraPrIDRef="{self.para(align, line=100)}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{self.char()}">{pic}<hp:t/></hp:run></hp:p>')

    # ------------------------------------------------------------ 저장

    def _header(self) -> str:
        h = self._files["Contents/header.xml"].decode("utf-8")
        for lang in LANGS:
            m = re.search(rf'<hh:fontface lang="{lang}" fontCnt="(\d+)">(.*?)</hh:fontface>', h, re.S)
            fonts = "".join(
                f'<hh:font id="{fid}" face="{escape(face)}" type="TTF" isEmbedded="0">'
                '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="0" contrast="0" strokeVariation="1" '
                'armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>'
                for face, fid in self._fonts.items())
            count = int(m.group(1)) + len(self._fonts)
            h = (h[:m.start()] + f'<hh:fontface lang="{lang}" fontCnt="{count}">' + m.group(2) + fonts
                 + "</hh:fontface>" + h[m.end():])
        for tag, items in (("charProperties", self._char_xml), ("paraProperties", self._para_xml),
                           ("borderFills", self._border_xml)):
            total = self._base[tag] + len(items)
            h = re.sub(rf'<hh:{tag} itemCnt="\d+">', f'<hh:{tag} itemCnt="{total}">', h, count=1)
            h = h.replace(f"</hh:{tag}>", "".join(items) + f"</hh:{tag}>", 1)
        return h

    def _section(self) -> str:
        s = self._files["Contents/section0.xml"].decode("utf-8")
        left, right, top, bottom = (mm(v) for v in self.margins)
        s = re.sub(r'<hp:margin header="\d+" footer="\d+" gutter="0" left="\d+" right="\d+" top="\d+" bottom="\d+"/>',
                   f'<hp:margin header="1417" footer="1417" gutter="0" left="{left}" right="{right}" '
                   f'top="{max(top - 1417, 0)}" bottom="{max(bottom - 1417, 0)}"/>', s, count=1)
        return s.replace("</hs:sec>", "".join(self._body) + "</hs:sec>")

    def to_bytes(self) -> bytes:
        files = dict(self._files)
        # 글자 모양을 먼저 다 등록해야 header에 글꼴 목록이 맞게 들어간다.
        section = self._section()
        files["Contents/section0.xml"] = section.encode("utf-8")
        files["Contents/header.xml"] = self._header().encode("utf-8")
        files["Preview/PrvText.txt"] = "\r\n".join(self._plain)[:1000].encode("utf-8")
        names = list(self._names)
        if self._images:
            hpf = files["Contents/content.hpf"].decode("utf-8")
            items = "".join(f'<opf:item id="{n}" href="BinData/{n}.{e}" media-type="image/{e}" isEmbeded="1"/>'
                            for n, _, e in self._images)
            files["Contents/content.hpf"] = hpf.replace("</opf:manifest>", items + "</opf:manifest>").encode("utf-8")
            for n, data, e in self._images:
                files[f"BinData/{n}.{e}"] = data
                names.append(f"BinData/{n}.{e}")

        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            # mimetype은 압축하지 않고 맨 앞에 둔다(OCF 규칙).
            z.writestr(zipfile.ZipInfo("mimetype"), files["mimetype"], compress_type=zipfile.ZIP_STORED)
            for n in names:
                if n != "mimetype":
                    z.writestr(n, files[n], compress_type=zipfile.ZIP_DEFLATED)
        return buf.getvalue()

    def save(self, path: str | Path) -> Path:
        """.hwpx로 저장한다. 확장자가 .hwp면 python-hwpx로 한글 97~2022 형식(HWP 5.0)으로 바꿔 저장한다."""
        path = Path(path)
        data = self.to_bytes()
        if path.suffix.lower() != ".hwp":
            path.write_bytes(data)
            return path
        try:
            from hwpx import HwpxDocument  # python-hwpx (실행 파일 묶음에 들어 있음)
        except ImportError:
            raise RuntimeError("HWP 형식으로 저장하는 기능이 없습니다. .hwpx로 저장하세요(한글에서 그대로 열립니다).") from None
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "doc.hwpx"
            tmp.write_bytes(data)
            HwpxDocument.open(str(tmp)).save_to_path(str(path))
        return path


def _image_size(data: bytes) -> tuple[str, tuple[int, int]]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", (w, h)
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ValueError("PNG 또는 JPEG 그림만 넣을 수 있습니다.")


def read_text(path: str | Path) -> str:
    """HWPX 파일의 글을 문단 단위로 읽는다. 표는 칸을 ' | '로 이어 한 줄로 만든다."""
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n))
        xml = "".join(z.read(n).decode("utf-8") for n in sections)
    lines = []
    # 표 행은 한 줄로, 그 밖의 문단은 한 줄씩 꺼낸다.
    token = re.compile(r"<hp:tr>(.*?)</hp:tr>|<hp:p [^>]*>(.*?)</hp:p>", re.S)
    for m in token.finditer(_strip_tables_in_paragraphs(xml)):
        if m.group(1) is not None:
            cells = re.findall(r"<hp:tc .*?</hp:tc>", m.group(1), re.S)
            row = [" ".join(_texts(c)).strip() for c in cells]
            lines.append(" | ".join(row))
        else:
            lines.append("".join(_texts(m.group(2))))
    return "\n".join(line.rstrip() for line in lines)


def _texts(xml: str) -> list[str]:
    return [_unescape(t) for t in re.findall(r"<hp:t(?: [^>]*)?>(.*?)</hp:t>", xml, re.S)]


def _unescape(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)  # <hp:t> 안의 탭·줄바꿈 표시 등
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def _strip_tables_in_paragraphs(xml: str) -> str:
    """표를 담은 문단은 표 행만 남기고, 표 칸 안의 문단은 행에서 처리하도록 표를 펼친다."""
    out, pos = [], 0
    for m in re.finditer(r"<hp:tbl .*?</hp:tbl>", xml, re.S):
        out.append(xml[pos:m.start()])
        out.append("</hp:p>" + "".join(re.findall(r"<hp:tr>.*?</hp:tr>", m.group(0), re.S)) + '<hp:p x="">')
        pos = m.end()
    out.append(xml[pos:])
    return "".join(out)
