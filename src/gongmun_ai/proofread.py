"""공문서 규칙 기반 교정.

LLM 없이 즉시 동작하므로 저사양 PC에서도 바로 쓸 수 있다.
근거: 행정업무의 운영 및 혁신에 관한 규정 시행규칙, 행정업무운영 편람,
「공문서 작성법 길라잡이」(2025. 1. 8.)의 표기·항목·붙임·끝 표시 규칙.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .easy_words import EASY_WORDS


@dataclass(frozen=True)
class Issue:
    rule: str
    message: str
    start: int
    end: int
    original: str
    suggestion: str | None = None  # None이면 안내만 하고 자동 수정하지 않는다

    @property
    def fixable(self) -> bool:
        return self.suggestion is not None


# ---------------------------------------------------------------- 숫자 표기

_DIGITS = "영일이삼사오육칠팔구"
_SMALL_UNITS = ["", "십", "백", "천"]
_BIG_UNITS = ["", "만", "억", "조"]


def korean_amount(n: int) -> str:
    """123000 -> '일십이만삼천' (공문서 금액 한글 표기)."""
    if n == 0:
        return "영"
    groups = []
    while n:
        groups.append(n % 10000)
        n //= 10000
    out = []
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0:
            continue
        part = ""
        for pos in range(3, -1, -1):
            d = (g // 10**pos) % 10
            if d:
                part += _DIGITS[d] + _SMALL_UNITS[pos]
        out.append(part + _BIG_UNITS[gi])
    return "".join(out)


_DATE_KO = re.compile(r"(?<!\d)(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_DATE_SEP = re.compile(r"(?<![\d.])(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?![\d])\.?")
_DATE_SHORT_YEAR = re.compile(r"[’'‘](\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)\.?")
_WEEKDAY_AFTER = re.compile(r"\([월화수목금토일]\)\.")
_RANGE_DAY_ONLY = re.compile(r"(\d{4})\. (\d{1,2})\. (\d{1,2})\.\s*([~∼～-])\s*(\d{1,2})\.(?!\s*\d)")
_RANGE_UNTIL = re.compile(r"([~∼～][\d. :]*\d\.?)\s?까지")
DATE_MSG = "날짜는 '2025. 1. 6.'처럼 아라비아 숫자로 쓰고 '일' 다음에도 마침표를 찍습니다."


def _valid_date(m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31


def _check_dates(text: str):
    for m in _DATE_KO.finditer(text):
        y, mo, d = (int(g) for g in m.groups())
        if not _valid_date(mo, d):
            continue
        end = m.end()
        if end < len(text) and text[end] == ".":
            end += 1  # '31일.' 뒤 마침표를 함께 바꿔 '..'이 되지 않게 한다
        yield Issue("날짜", DATE_MSG, m.start(), end, text[m.start():end], f"{y}. {mo}. {d}.")
    for rx, century in ((_DATE_SEP, 0), (_DATE_SHORT_YEAR, 2000)):
        for m in rx.finditer(text):
            y, mo, d = (int(g) for g in m.groups())
            if not _valid_date(mo, d):
                continue
            canonical, end = f"{y + century}. {mo}. {d}.", m.end()
            # '2025. 1. 6(월).' → '2025. 1. 6.(월)'
            wd = _WEEKDAY_AFTER.match(text, end)
            if wd and not m.group(0).endswith("."):
                canonical += wd.group(0)[:-1]
                end = wd.end()
            if text[m.start():end] != canonical:
                yield Issue("날짜", DATE_MSG, m.start(), end, text[m.start():end], canonical)
    for m in _RANGE_DAY_ONLY.finditer(text):
        fixed = f"{m.group(1)}. {m.group(2)}. {m.group(3)}.{m.group(4)}{m.group(2)}. {int(m.group(5))}."
        yield Issue("기간", "기간 끝 날짜에도 월을 씁니다(2025. 2. 20.~2. 24.).",
                    m.start(), m.end(), m.group(0), fixed)
    for m in _RANGE_UNTIL.finditer(text):
        yield Issue("기간", "물결표(~)가 '까지'의 뜻을 담으므로 '까지'를 함께 쓰지 않습니다.",
                    m.start(), m.end(), m.group(0), m.group(1))


# 시각 표기: 24시각제, 십 미만은 0을 넣고, 시와 분은 쌍점으로 붙여 쓴다.
# 분 없이 시만 쓸 때는 '09시', '14시'처럼 숫자 다음에 '시'를 쓴다.
_TIME_AMPM = re.compile(r"(오전|오후|낮|밤)\s*(\d{1,2})\s*(?:시(?:\s*(\d{1,2})\s*분)?|:(\d{2}))")
_TIME_HM = re.compile(r"(?<!\d)(\d{1,2})\s*시\s*(\d{1,2})\s*분")
_TIME_H = re.compile(r"(?<![\d:])(\d{1,2})\s*시(?![간대작점])")
_TIME_CLOCK = re.compile(r"(?<![\d:])(\d{1,2})\s*:\s*(\d{2})(?![\d:])(시(?!간)|분)?")
TIME_MSG = "시각은 24시각제로 '14:30'처럼 씁니다."
AMBIGUOUS_MSG = "오전/오후가 분명하지 않습니다. 24시각제로 써 주세요(예: 15:30, 09시)."


def _to_24h(period: str, h: int) -> int | None:
    if h > 12:
        return h if period in ("오후", "낮", "밤") and h <= 23 else None  # '오후 16시' 같은 겹친 표기
    if period == "오전":
        return 0 if h == 12 else h
    if period == "낮":
        return 12 if h == 12 else (h + 12 if h <= 6 else None)
    if period == "밤":
        return None if h == 12 else (h + 12 if h >= 6 else None)
    return 12 if h == 12 else h + 12  # 오후


def _check_times(text: str):
    taken: list[tuple[int, int]] = []  # 앞 규칙이 이미 처리한 구간

    def free(m) -> bool:
        if any(s <= m.start() < e for s, e in taken):
            return False
        taken.append(m.span())
        return True

    for m in _TIME_AMPM.finditer(text):
        free(m)
        h, mi = int(m.group(2)), int(m.group(3) or m.group(4) or 0)
        h24 = _to_24h(m.group(1), h) if mi < 60 else None
        if h24 is None:
            yield Issue("시각", "시각이 모호합니다. 마감이라면 '2025. 2. 21. 18:00'처럼 분명하게 씁니다.",
                        m.start(), m.end(), m.group(0))
        else:
            yield Issue("시각", TIME_MSG, m.start(), m.end(), m.group(0), f"{h24:02d}:{mi:02d}")
    for m in _TIME_HM.finditer(text):
        if not free(m):
            continue
        h, mi = int(m.group(1)), int(m.group(2))
        if 13 <= h <= 23 or h == 0:
            yield Issue("시각", TIME_MSG, m.start(), m.end(), m.group(0), f"{h:02d}:{mi:02d}")
        elif h <= 12:
            yield Issue("시각", AMBIGUOUS_MSG, m.start(), m.end(), m.group(0))
    for m in _TIME_CLOCK.finditer(text):
        if not free(m):
            continue
        h, mi = int(m.group(1)), int(m.group(2))
        if h <= 24 and mi < 60:
            canonical = f"{h:02d}:{mi:02d}"
            if m.group(0) != canonical:
                yield Issue("시각", "시각은 '09:30'처럼 0을 넣고 쌍점 양쪽을 붙여 씁니다.",
                            m.start(), m.end(), m.group(0), canonical)
    for m in _TIME_H.finditer(text):
        if not free(m):
            continue
        h = int(m.group(1))
        if h == 24:
            yield Issue("시각", "'24시'는 다음 날과 헷갈립니다. 마감은 '18:00'처럼 분명하게 씁니다.",
                        m.start(), m.end(), m.group(0))
        elif 1 <= h <= 12:
            yield Issue("시각", AMBIGUOUS_MSG, m.start(), m.end(), m.group(0))


# '일금-원정'은 계약서 표기라 그대로 둔다.
_AMOUNT = re.compile(r"(?<![\d,])(금\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s?원(?![인장칙본형래리활점료정])(?![ \t]*\()")


def _check_amounts(text: str):
    for m in _AMOUNT.finditer(text):
        if m.group(1) and m.start() > 0 and text[m.start() - 1] == "일":
            continue
        n = int(m.group(2).replace(",", ""))
        yield Issue("금액", "금액은 '금113,560원(금일십일만삼천오백육십원)'처럼 숫자 뒤 괄호에 한글로 함께 씁니다.",
                    m.start(), m.end(), m.group(0), f"금{n:,}원(금{korean_amount(n)}원)")


# ---------------------------------------------------------------- 쉬운 말·띄어쓰기

def _check_easy_words(text: str):
    for pattern, repl, reason in EASY_WORDS:
        for m in re.finditer(pattern, text):
            if repl is None:
                yield Issue("표현", f"'{m.group(0)}': {reason}", m.start(), m.end(), m.group(0))
            else:
                new = m.expand(repl)
                yield Issue(reason, f"'{m.group(0)}' → '{new}'", m.start(), m.end(), m.group(0), new)


def _has_rieul_final(ch: str) -> bool:
    o = ord(ch)
    return 0xAC00 <= o <= 0xD7A3 and (o - 0xAC00) % 28 == 8


_BOUND_NOUN = re.compile(r"[가-힣](?:수(?=\s?(?:있|없|도))|것|때)")
_SU_ISS = re.compile(r"(?<=\s)수(?=있|없)")


def _check_spacing(text: str):
    for m in _BOUND_NOUN.finditer(text):
        s = m.group(0)
        if _has_rieul_final(s[0]):
            yield Issue("띄어쓰기", f"'{s}' → '{s[0]} {s[1:]}' (의존 명사는 띄어 씁니다)",
                        m.start(), m.end(), s, f"{s[0]} {s[1:]}")
    for m in _SU_ISS.finditer(text):
        yield Issue("띄어쓰기", "'수있다' → '수 있다'", m.start(), m.end(), "수", "수 ")


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
LONG_SENTENCE = 90


def _check_long_sentences(text: str):
    for m in _SENTENCE.finditer(text):
        s = m.group(0).strip()
        if len(s) > LONG_SENTENCE:
            yield Issue("긴 문장", f"문장이 깁니다({len(s)}자). 두 문장으로 나누면 이해가 쉬워집니다.",
                        m.start(), m.end(), m.group(0))


# ---------------------------------------------------------------- 공문서 서식

HANGUL_SEQ = "가나다라마바사아자차카타파하"
PAREN_NUM = "".join(chr(c) for c in range(0x2474, 0x2488))       # ⑴~⒇
PAREN_HANGUL = "".join(chr(c) for c in range(0x320E, 0x321C))    # ㈎~㈛
CIRCLED_NUM = "".join(chr(c) for c in range(0x2460, 0x2474))     # ①~⑳
CIRCLED_HANGUL = "".join(chr(c) for c in range(0x326E, 0x327C))  # ㉮~㉻

# (정규식, 번호 문자열, 표시 형식) — 순서가 곧 항목의 단계다.
_LEVELS = [
    (re.compile(r"(\d{1,2})\.(?=\s)"), None, "{}."),
    (re.compile(rf"([{HANGUL_SEQ}])\.(?=\s)"), HANGUL_SEQ, "{}."),
    (re.compile(r"(\d{1,2})\)(?=\s)"), None, "{})"),
    (re.compile(rf"([{HANGUL_SEQ}])\)(?=\s)"), HANGUL_SEQ, "{})"),
    (re.compile(rf"([{PAREN_NUM}])"), PAREN_NUM, "{}"),
    (re.compile(rf"([{PAREN_HANGUL}])"), PAREN_HANGUL, "{}"),
    (re.compile(rf"([{CIRCLED_NUM}])"), CIRCLED_NUM, "{}"),
    (re.compile(rf"([{CIRCLED_HANGUL}])"), CIRCLED_HANGUL, "{}"),
]
# 다섯째·여섯째 항목을 자판으로 친 '(1)', '(가)'는 '⑴', '㈎'로 바꾼다.
_TYPED_PAREN = [
    (4, re.compile(r"\((\d{1,2})\)(?=\s)"), None),
    (5, re.compile(rf"\(([{HANGUL_SEQ}])\)(?=\s)"), HANGUL_SEQ),
]
# 대등하게 늘어놓을 때는 첫째~넷째 항목 기호 대신 특수 부호를 써도 된다.
_SYMBOLS = {"□": 0, "○": 1, "-": 2, "•": 3, "∙": 3, "·": 3}
LEVEL_ORDER = "1. → 가. → 1) → 가) → ⑴ → ㈎ → ① → ㉮ (특수 부호: □ → ○ → - → •)"
INDENT = 2  # 하위 항목은 2타(한글 1자)씩 오른쪽에서 시작


def marker(level: int, index: int) -> str:
    """단계(0부터)와 순번(1부터)에 맞는 항목 기호."""
    _, seq, fmt = _LEVELS[level]
    return fmt.format(index if seq is None else seq[index - 1])


def _parse_item(line: str):
    """항목 줄이면 (단계, 순번 또는 None(특수 부호), 들여쓰기 길이, 기호 길이, 표준 기호 여부)."""
    stripped = line.lstrip(" \t")
    ws = len(line) - len(stripped)
    if stripped[:1] in _SYMBOLS and stripped[1:2] == " ":
        return _SYMBOLS[stripped[0]], None, ws, 1, True
    for level, (rx, seq, _) in enumerate(_LEVELS):
        if m := rx.match(stripped):
            tok = m.group(1)
            return level, int(tok) if seq is None else seq.index(tok) + 1, ws, m.end(), True
    for level, rx, seq in _TYPED_PAREN:
        if m := rx.match(stripped):
            tok = m.group(1)
            return level, int(tok) if seq is None else seq.index(tok) + 1, ws, m.end(), False
    return None


def _check_items(text: str):
    prev_level = -1
    counters: dict[int, int] = {}
    pos = 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        if line.lstrip().startswith("붙임"):
            break  # 붙임 목록은 본문 항목 규칙을 따르지 않는다
        parsed = _parse_item(line)
        if parsed is None:
            continue
        level, idx, ws, mlen, standard = parsed
        tok_start = line_start + ws
        token = line[ws:ws + mlen]
        if level > prev_level + 1:
            yield Issue("항목 순서", f"상위 항목 없이 '{token}'을(를) 썼습니다. 순서: {LEVEL_ORDER}",
                        tok_start, tok_start + mlen, token)
        else:
            if idx is not None:
                expected = counters.get(level, 0) + 1
                seq = _LEVELS[level][1]
                if expected <= (99 if seq is None else len(seq)):
                    want = marker(level, expected)
                    if idx != expected:
                        yield Issue("항목 번호", f"번호가 이어지지 않습니다. '{want}'이(가) 와야 합니다.",
                                    tok_start, tok_start + mlen, token, want)
                    elif not standard:
                        yield Issue("항목 기호", f"이 단계 항목 기호는 '{want}'입니다. 순서: {LEVEL_ORDER}",
                                    tok_start, tok_start + mlen, token, want)
                    idx = expected
            want_ws = level * INDENT
            if ws != want_ws:
                yield Issue("들여쓰기", f"이 단계 항목은 {want_ws}칸 들여 씁니다.",
                            line_start, line_start + ws, line[:ws], " " * want_ws)
        if idx is not None:
            counters[level] = idx
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        prev_level = level


_DOC_REF = re.compile(r"[가-힣A-Za-z]+-\d+\s*\(\d{4}\. \d{1,2}\. \d{1,2}\.\)(?!\s*[「｢『<〈])")


def _check_related(text: str):
    for m in _DOC_REF.finditer(text):
        yield Issue("관련 근거", "관련 문서는 번호 뒤에 「문서 명칭」을 함께 씁니다.",
                    m.start(), m.end(), m.group(0))


_END_MARK = re.compile(r"([ \t]*\n?[ \t]*)끝\.\s*$")


def _check_end_mark(text: str):
    body = text.rstrip()
    if not body:
        return
    m = _END_MARK.search(body)
    if m is None:
        yield Issue("끝 표시", "본문(또는 붙임) 끝에 두 칸 띄우고 '끝.'을 씁니다.",
                    len(body), len(body), "", "  끝.")
    elif not m.group(1).endswith("  "):
        prefix = "\n  " if "\n" in m.group(1) else "  "
        yield Issue("끝 표시", "'끝.' 앞은 두 칸 띄웁니다.",
                    m.start(1), m.end(1), m.group(1), prefix)


# ---------------------------------------------------------------- 공개 함수

def check(text: str, official: bool = True) -> list[Issue]:
    """교정 항목을 위치 순으로 돌려준다.

    official=True면 공문서 서식(항목 기호, 끝 표시)까지 검사한다.
    자동 수정 항목끼리 겹치면 앞선(같으면 더 긴) 것만 남긴다.
    """
    checks = [_check_dates, _check_times, _check_amounts, _check_easy_words,
              _check_spacing, _check_long_sentences]
    if official:
        checks += [_check_items, _check_related, _check_end_mark]
    issues = [i for c in checks for i in c(text)]
    issues.sort(key=lambda i: (i.start, -(i.end - i.start)))

    kept: list[Issue] = []
    last_end = -1
    for i in issues:
        if i.fixable:
            if i.start < last_end:
                continue
            last_end = max(last_end, i.end)
        kept.append(i)
    return kept


def apply_fixes(text: str, issues: list[Issue]) -> str:
    out, cursor = [], 0
    for i in sorted((i for i in issues if i.fixable), key=lambda i: i.start):
        if i.start < cursor:
            continue
        out.append(text[cursor:i.start])
        out.append(i.suggestion)
        cursor = i.end
    out.append(text[cursor:])
    return "".join(out)


def autofix(text: str, official: bool = True) -> tuple[str, list[Issue]]:
    """자동 수정한 글과, 사람이 판단해야 할 남은 안내 항목.

    한 번 고친 결과에서 새로 드러나는 항목(예: 날짜를 고친 뒤의 기간 표기)도
    고치도록 몇 차례 반복한다.
    """
    for _ in range(3):
        issues = check(text, official)
        if not any(i.fixable for i in issues):
            break
        text = apply_fixes(text, issues)
    return text, [i for i in check(text, official) if not i.fixable]
