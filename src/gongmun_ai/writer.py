"""AI 문서 작업: 톤 조정, AI 교정, 기안문 초안.

모든 결과는 규칙 기반 교정을 한 번 더 거치고, 원문의 숫자(날짜·금액·인원)가
바뀌거나 새로 생기지 않았는지 검사한다. 작은 모델이 사실을 지어내는 것을 막는 장치다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gianmun import SCHEMA, Gianmun
from .llm import Backend, clean_output, parse_json
from .profiles import Profile
from .proofread import Issue, apply_fixes, autofix, check

SYSTEM = (
    "당신은 대한민국 공공기관의 행정 문서 작성을 돕는 보조자입니다.\n"
    "- 원문에 없는 사실, 숫자, 날짜, 기관명을 지어내지 않습니다.\n"
    "- 공문서 표기 규칙을 지킵니다: 날짜 '2026. 10. 31.', 시각 '14:30', "
    "금액 '금1,000원(금일천원)'.\n"
    "- 어려운 한자어 대신 쉬운 우리말을 쓰고, 한 문장에는 한 가지 내용만 씁니다."
)

TONES: dict[str, str] = {
    "보고서": "개조식으로 바꾼다. 문장은 '~함', '~임', '~할 계획임'처럼 명사형으로 끝내고 핵심부터 쓴다.",
    "대외공문": "다른 기관에 보내는 정중한 문체로 바꾼다. '~합니다', '~하여 주시기 바랍니다'를 쓴다.",
    "쉬운말": "민원인이 한 번에 이해하도록 쉬운 우리말로 바꾼다. 문장을 짧게 나누고 전문 용어는 풀어 쓴다.",
    "간결": "뜻은 그대로 두고 분량을 절반 이하로 줄인다. 꾸밈말과 중복 표현을 없앤다.",
}

MAX_REFERENCE_CHARS = 2500  # 저사양 PC의 짧은 문맥 길이에 맞춘 참고자료 총량


@dataclass
class Result:
    text: str
    hints: list[Issue] = field(default_factory=list)      # 사람이 판단할 교정 안내
    warnings: list[str] = field(default_factory=list)     # 사실 변경 의심, 결재권자 기준 미달


# ---------------------------------------------------------------- 사실 보존 검사

_NUM = re.compile(r"\d[\d,]*")


def _numbers(text: str) -> list[str]:
    # 표기 규칙 차이(2026년 10월 → 2026. 10.)로 생기는 오탐을 없애려 먼저 정규화한다.
    norm = apply_fixes(text, check(text, official=False))
    return [n.replace(",", "").lstrip("0") or "0" for n in _NUM.findall(norm)]


def fact_warnings(source: str, output: str) -> list[str]:
    src, out = set(_numbers(source)), set(_numbers(output))
    warnings = []
    if missing := sorted(src - out, key=len):
        warnings.append(f"원문의 숫자가 빠졌습니다: {', '.join(missing)}")
    if added := sorted(out - src, key=len):
        warnings.append(f"원문에 없던 숫자가 생겼습니다(확인 필요): {', '.join(added)}")
    return warnings


# ---------------------------------------------------------------- 작업

def _messages(user: str, profile: Profile | None) -> list[dict]:
    system = SYSTEM + (f"\n\n{profile.to_prompt()}" if profile else "")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _finish(source: str, output: str, profile: Profile | None, official: bool,
            facts: str | None = None) -> Result:
    """facts: 사실 검사 대상(기본은 결과 전체). 서식 번호를 빼고 비교할 때 쓴다."""
    fixed, hints = autofix(output, official=official)
    warnings = fact_warnings(source, fixed if facts is None else facts)
    if facts is not None:
        # 초안은 원문 일부만 쓰므로 '빠진 숫자'는 문제가 아니다. 새로 생긴 숫자만 본다.
        warnings = [w for w in warnings if not w.startswith("원문의 숫자가 빠졌습니다")]
    if profile:
        warnings += [f"[{profile.name}] {p}" for p in profile.check(fixed)]
    return Result(fixed, hints, warnings)


def adjust_tone(backend: Backend, text: str, tone: str,
                profile: Profile | None = None) -> Result:
    if tone not in TONES:
        raise ValueError(f"알 수 없는 톤입니다: {tone} (가능: {', '.join(TONES)})")
    prompt = (f"다음 글의 문체를 바꾸세요. {TONES[tone]}\n"
              "숫자·날짜·이름은 그대로 두고, 바꾼 글만 출력하세요.\n\n"
              f"[원문]\n{text}")
    out = clean_output(backend.chat(_messages(prompt, profile), temperature=0.3))
    return _finish(text, out, profile, official=False)


def ai_proofread(backend: Backend, text: str, official: bool = True) -> Result:
    prompt = ("다음 글의 맞춤법, 띄어쓰기, 어색한 문장만 바로잡으세요. "
              "내용·구성·문체는 바꾸지 말고, 고친 글만 출력하세요.\n\n"
              f"[원문]\n{text}")
    out = clean_output(backend.chat(_messages(prompt, None), temperature=0.1))
    return _finish(text, out, None, official=official)


def draft(backend: Backend, request: str, profile: Profile | None = None,
          references: list[tuple[str, str]] | None = None,
          tone: str = "보고서") -> tuple[Gianmun, Result]:
    """요청과 참고 문서로 기안문 초안을 만든다. references는 (이름, 내용) 목록."""
    ref_block = ""
    if references:
        budget = MAX_REFERENCE_CHARS // len(references)
        ref_block = "\n\n[참고 문서]\n" + "\n\n".join(
            f"<{name}>\n{body[:budget]}" for name, body in references)
    prompt = (
        f"다음 요청에 맞는 기안문 내용을 JSON으로 작성하세요.\n[요청]\n{request}{ref_block}\n\n"
        "작성 방법:\n"
        "- title: 무엇을 하려는지 드러나는 짧은 제목\n"
        "- recipient: 수신자(내부 보고면 '내부결재')\n"
        "- related: 관련 근거 문서(참고 문서에 있는 것만, 없으면 빈 목록)\n"
        "- items: 본문 항목. text는 한 문장, sub는 세부 내용 목록\n"
        "- attachments: 붙임 파일 이름(없으면 빈 목록)\n"
        f"- 문체: {TONES.get(tone, TONES['보고서'])}\n"
        "- 항목 번호(1., 가.)와 '끝.'은 쓰지 마세요. 서식은 프로그램이 붙입니다.\n"
        "- 참고 문서에 없는 숫자는 쓰지 말고 '○○'으로 비워 두세요."
    )
    out = backend.chat(_messages(prompt, profile), json_schema=SCHEMA,
                       max_tokens=1500, temperature=0.4)
    doc = Gianmun.from_dict(parse_json(out))
    doc.map_text(lambda t: autofix(t, official=False)[0])

    source = request + "\n" + "\n".join(body for _, body in references or [])
    result = _finish(source, doc.render(), profile, official=True, facts=doc.content())
    return doc, result
