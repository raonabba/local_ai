"""로컬 LLM 실행.

llama.cpp를 프로세스 안에 직접 불러 쓴다. 로컬 HTTP 서버(포트)를 열지 않으므로
'AI 프로그램에는 통신 기능이 없다'는 보안 설계를 지킬 수 있다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol

Message = dict[str, str]


class Backend(Protocol):
    def chat(self, messages: list[Message], *, json_schema: dict | None = None,
             max_tokens: int = 1024, temperature: float = 0.3) -> str: ...


_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean_output(text: str) -> str:
    """추론형 모델의 <think> 블록과 코드 펜스를 걷어낸다."""
    text = _THINK.sub("", text).strip()
    m = re.fullmatch(r"```[a-zA-Z]*\n(.*)\n```", text, re.S)
    return (m.group(1) if m else text).strip()


def parse_json(text: str) -> dict:
    """모델 출력에서 JSON 객체를 꺼낸다(앞뒤 잡담이 붙어도 처리)."""
    text = clean_output(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("모델 출력에서 JSON을 찾지 못했습니다.") from None
        return json.loads(text[start:end + 1])


class LlamaCppBackend:
    def __init__(self, model_path: str | Path, n_ctx: int = 4096,
                 n_threads: int | None = None, n_gpu_layers: int = 0):
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError(
                "llama-cpp-python이 설치되지 않았습니다: pip install -e .[llm]") from e
        self._llm = Llama(model_path=str(model_path), n_ctx=n_ctx,
                          n_threads=n_threads or os.cpu_count(),
                          n_gpu_layers=n_gpu_layers, verbose=False)
        # Qwen3는 답하기 전에 길게 '생각'하는데, CPU에서는 몇 분씩 걸리므로 끈다.
        self.no_think = "qwen3" in Path(model_path).name.lower()
        self.name = Path(model_path).name

    def chat(self, messages, *, json_schema=None, max_tokens=1024, temperature=0.3):
        if self.no_think:
            messages = [*messages[:-1],
                        {**messages[-1], "content": messages[-1]["content"] + " /no_think"}]
        kwargs = {}
        if json_schema is not None:
            # 문법 제약으로 작은 모델도 형식이 깨지지 않은 JSON을 내게 한다.
            kwargs["response_format"] = {"type": "json_object", "schema": json_schema}
        out = self._llm.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
        return clean_output(out["choices"][0]["message"]["content"])


class ScriptedBackend:
    """테스트와 시연용: 미리 정한 답을 차례로 돌려준다."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    def chat(self, messages, *, json_schema=None, max_tokens=1024, temperature=0.3):
        self.calls.append(messages)
        return self.responses.pop(0)


def find_model(explicit: str | None = None, folder: str | Path = "models") -> Path:
    """--model 인자 > GONGMUN_MODEL 환경변수 > 모델 폴더의 첫 .gguf 순으로 찾는다."""
    for cand in (explicit, os.environ.get("GONGMUN_MODEL")):
        if cand:
            p = Path(cand)
            if not p.is_file():
                raise FileNotFoundError(f"모델 파일이 없습니다: {p}")
            return p
    found = sorted(Path(folder).glob("*.gguf"))
    if not found:
        raise FileNotFoundError(
            "모델 파일(.gguf)을 찾지 못했습니다. models/ 폴더에 넣거나 --model로 지정하세요.")
    return found[0]
