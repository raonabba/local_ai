"""공문서 규칙 기반 교정.

LLM 없이 즉시 동작하므로 저사양 PC에서도 바로 쓸 수 있다.
근거: 행정업무의 운영 및 혁신에 관한 규정 시행규칙(날짜·시각·금액 표기, 항목 구분),
행정업무운영 편람(끝 표시, 항목 들여쓰기).
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
        yield Issue("날짜", "날짜는 '2026. 10. 31.' 형식으로 씁니다.",
                    m.start(), end, text[m.start():end], f"{y}. {mo}. {d}.")
    for m in _DATE_SEP.finditer(text):
        y, mo, d = (int(g) for g in m.groups())
        if not _valid_date(mo, d):
            continue
        canonical = f"{y}. {mo}. {d}."
        if m.group(0) != canonical:
            yield Issue("날짜", "날짜는 '2026. 10. 31.' 형식으로 씁니다.",
                        m.start(), m.end(), m.group(0), canonical)


_TIME_AMPM = re.compile(r"(오전|오후)\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?")
_TIME_HM = re.compile(r"(?<!\d)(\d{1,2})\s*시\s*(\d{1,2})\s*분")
_TIME_H = re.compile(r"(?<!\d)(\d{1,2})\s*시(?![간대작점])")


def _check_times(text: str):
    msg = "시각은 24시각제로 '14:30'처럼 씁니다."
    taken: list[tuple[int, int]] = []  # 앞 규칙이 이미 처리한 구간
    for m in _TIME_AMPM.finditer(text):
        taken.append(m.span())
        h, mi = int(m.group(2)), int(m.group(3) or 0)
        if not (1 <= h <= 12 and mi < 60):
            continue
        if m.group(1) == "오후" and h != 12:
            h += 12
        elif m.group(1) == "오전" and h == 12:
            h = 0
        yield Issue("시각", msg, m.start(), m.end(), m.group(0), f"{h:02d}:{mi:02d}")
    for rx in (_TIME_HM, _TIME_H):
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            taken.append(m.span())
            h = int(m.group(1))
            mi = int(m.group(2)) if rx is _TIME_HM else 0
            if h > 24 or mi >= 60:
                continue
            if 13 <= h <= 24 or h == 0:
                yield Issue("시각", msg, m.start(), m.end(), m.group(0), f"{h % 24:02d}:{mi:02d}")
            else:
                yield Issue("시각", "오전/오후가 분명하지 않습니다. 24시각제로 써 주세요(예: 15:30).",
                            m.start(), m.end(), m.group(0))


_AMOUNT = re.compile(r"(?<![\d,])(금\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s?원(?![인장칙본형래리활점료])(?!\s*\()")


def _check_amounts(text: str):
    for m in _AMOUNT.finditer(text):
        n = int(m.group(2).replace(",", ""))
        yield Issue("금액", "금액은 숫자 뒤 괄호 안에 한글로 함께 씁니다.",
                    m.start(), m.end(), m.group(0), f"금{n:,}원(금{korean_amount(n)}원)")


# ---------------------------------------------------------------- 쉬운 말·띄어쓰기

def _check_easy_words(text: str):
    for pattern, repl, reason in EASY_WORDS:
        for m in re.finditer(pattern, text):
            if repl is None:
                yield Issue("쉬운 말", f"'{m.group(0)}': {reason}", m.start(), m.end(), m.group(0))
            else:
                yield Issue(reason, f"'{m.group(0)}' → '{repl}'", m.start(), m.end(), m.group(0), repl)


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
CIRCLED_NUM = "".join(chr(c) for c in range(0x2460, 0x2474))   # ①~⑳
CIRCLED_HANGUL = "".join(chr(c) for c in range(0x326E, 0x327C))  # ㉮~㉻

# (정규식, 번호 문자열, 표시 형식) — 순서가 곧 항목의 단계다.
_LEVELS = [
    (re.compile(r"(\d{1,2})\.(?=\s)"), None, "{}."),
    (re.compile(rf"([{HANGUL_SEQ}])\.(?=\s)"), HANGUL_SEQ, "{}."),
    (re.compile(r"(\d{1,2})\)(?=\s)"), None, "{})"),
    (re.compile(rf"([{HANGUL_SEQ}])\)(?=\s)"), HANGUL_SEQ, "{})"),
    (re.compile(r"\((\d{1,2})\)(?=\s)"), None, "({})"),
    (re.compile(rf"\(([{HANGUL_SEQ}])\)(?=\s)"), HANGUL_SEQ, "({})"),
    (re.compile(rf"([{CIRCLED_NUM}])"), CIRCLED_NUM, "{}"),
    (re.compile(rf"([{CIRCLED_HANGUL}])"), CIRCLED_HANGUL, "{}"),
]
LEVEL_ORDER = "1. → 가. → 1) → 가) → (1) → (가) → ① → ㉮"
INDENT = 2


def marker(level: int, index: int) -> str:
    """단계(0부터)와 순번(1부터)에 맞는 항목 기호."""
    _, seq, fmt = _LEVELS[level]
    return fmt.format(index if seq is None else seq[index - 1])


def _parse_item(line: str):
    """항목 줄이면 (단계, 순번, 들여쓰기 길이, 기호 길이)."""
    stripped = line.lstrip(" \t")
    ws = len(line) - len(stripped)
    for level, (rx, seq, _) in enumerate(_LEVELS):
        m = rx.match(stripped)
        if m:
            tok = m.group(1)
            idx = int(tok) if seq is None else seq.index(tok) + 1
            return level, idx, ws, m.end()
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
        level, idx, ws, mlen = parsed
        tok_start = line_start + ws
        if level > prev_level + 1:
            yield Issue("항목 순서", f"상위 항목 없이 '{line[ws:ws + mlen]}'을(를) 썼습니다. 순서: {LEVEL_ORDER}",
                        tok_start, tok_start + mlen, line[ws:ws + mlen])
        else:
            expected = counters.get(level, 0) + 1
            if idx != expected and expected <= (20 if _LEVELS[level][1] is None else len(_LEVELS[level][1])):
                want = marker(level, expected)
                yield Issue("항목 번호", f"번호가 이어지지 않습니다. '{want}'이(가) 와야 합니다.",
                            tok_start, tok_start + mlen, line[ws:ws + mlen], want)
                idx = expected
            want_ws = level * INDENT
            if ws != want_ws:
                yield Issue("들여쓰기", f"이 단계 항목은 {want_ws}칸 들여 씁니다.",
                            line_start, line_start + ws, line[:ws], " " * want_ws)
        counters[level] = idx
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        prev_level = level


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
        checks += [_check_items, _check_end_mark]
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
    """자동 수정한 글과, 사람이 판단해야 할 남은 안내 항목."""
    issues = check(text, official)
    fixed = apply_fixes(text, issues)
    return fixed, [i for i in check(fixed, official) if not i.fixable]
