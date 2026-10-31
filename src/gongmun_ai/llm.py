"""로컬 LLM 실행.

llama.cpp를 프로세스 안에 직접 불러 쓴다. 로컬 HTTP 서버(포트)를 열지 않으므로
'AI 프로그램에는 통신 기능이 없다'는 보안 설계를 지킬 수 있다.
"""

from __future__ import annotations

import json
import os
import re
import sys
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
        model_path = Path(model_path)
        with open(model_path, "rb") as f:
            if f.read(4) != b"GGUF":
                raise ValueError(f"{model_path.name}: GGUF 모델 파일이 아닙니다(받다가 끊겼거나 다른 파일).")
        self.cpu = load_cpu_backend()
        self.progress = None  # 작성 중 글자 수를 알려 받을 함수(화면의 진행 표시용)
        self._llm = Llama(model_path=_engine_path(model_path), n_ctx=n_ctx,
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
        if self.progress is None:
            out = self._llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
            return clean_output(out["choices"][0]["message"]["content"])
        # 저사양 PC에서는 몇 분 걸리므로, 조금씩 받아 가며 진행 상황을 알린다.
        parts: list[str] = []
        for chunk in self._llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True, **kwargs):
            piece = chunk["choices"][0]["delta"].get("content")
            if piece:
                parts.append(piece)
                self.progress(sum(len(p) for p in parts))
        return clean_output("".join(parts))


_cpu_backend: str | None = None


def load_cpu_backend() -> str:
    """CPU에 맞는 AI 엔진을 고른다.

    윈도우 묶음은 AI 엔진을 CPU 세대별로 여러 벌 넣어 두고(GGML_CPU_ALL_VARIANTS), 실행할 때
    이 PC가 지원하는 가장 빠른 것을 불러온다. 그래서 AVX2가 없는 저사양·구형 CPU에서도 동작한다.
    한 벌만 들어 있는 엔진(일반 설치)이면 아무것도 하지 않는다."""
    global _cpu_backend
    if _cpu_backend is not None:
        return _cpu_backend
    import ctypes
    import llama_cpp
    from llama_cpp._ggml import libggml
    lib_dir = Path(llama_cpp.__file__).parent / "lib"
    if not list(lib_dir.glob("*ggml-cpu-*")):
        _cpu_backend = "기본"
        return _cpu_backend
    libggml.ggml_backend_load_all_from_path.argtypes = [ctypes.c_char_p]
    libggml.ggml_backend_load_all_from_path(str(_engine_path(lib_dir)).encode("utf-8"))
    libggml.ggml_backend_dev_count.restype = ctypes.c_size_t
    if libggml.ggml_backend_dev_count() == 0:
        raise RuntimeError("이 PC의 CPU에 맞는 AI 엔진을 찾지 못했습니다.")
    _cpu_backend = _device_name(libggml, lib_dir)
    return _cpu_backend


def _device_name(libggml, lib_dir: Path) -> str:
    """불러온 엔진의 장치 이름(상태 줄 표시용). 못 읽어도 AI 사용에는 지장이 없다."""
    import ctypes
    try:
        libggml.ggml_backend_dev_get.restype = ctypes.c_void_p
        libggml.ggml_backend_dev_get.argtypes = [ctypes.c_size_t]
        dev = libggml.ggml_backend_dev_get(0)
        # 윈도우에서는 이 함수가 ggml.dll이 아니라 ggml-base.dll에 들어 있다.
        from llama_cpp._ctypes_extensions import load_shared_library
        for lib in (libggml, load_shared_library("ggml-base", lib_dir)):
            fn = getattr(lib, "ggml_backend_dev_description", None)
            if fn is not None:
                fn.restype = ctypes.c_char_p
                fn.argtypes = [ctypes.c_void_p]
                return fn(dev).decode("utf-8", "replace").strip()
    except (OSError, AttributeError, RuntimeError):
        pass
    return "CPU"


def total_memory_gb() -> float:
    """이 PC의 메모리(GB). 알 수 없으면 0."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemoryStatus()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        return 0.0


def _engine_path(path: Path) -> str:
    """AI 엔진에 넘길 경로. 윈도우에서 경로에 한글이 있으면 영문 짧은 경로(8.3)로 바꿔
    엔진이 한글 경로를 못 여는 경우를 피한다. 짧은 경로를 못 얻으면 원래 경로를 쓴다."""
    s = str(path.resolve())
    if sys.platform != "win32" or s.isascii():
        return s
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, len(buf))
    return buf.value if 0 < n < len(buf) else s


class ScriptedBackend:
    """테스트와 시연용: 미리 정한 답을 차례로 돌려준다."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    progress = None

    def chat(self, messages, *, json_schema=None, max_tokens=1024, temperature=0.3):
        self.calls.append(messages)
        out = self.responses.pop(0)
        if self.progress:
            self.progress(len(out))
        return out


def find_model(explicit: str | None = None, folder: str | Path = "models") -> Path:
    """--model 인자 > GONGMUN_MODEL 환경변수 > 모델 폴더의 첫 .gguf 순으로 찾는다."""
    for cand in (explicit, os.environ.get("GONGMUN_MODEL")):
        if cand:
            p = Path(cand)
            if not p.is_file():
                raise FileNotFoundError(f"모델 파일이 없습니다: {p}")
            return p
    found = sorted(Path(folder).glob("*.gguf"), key=lambda p: p.stat().st_size)
    if not found:
        raise FileNotFoundError(
            "모델 파일(.gguf)을 찾지 못했습니다. models/ 폴더에 넣거나 --model로 지정하세요.")
    return choose_model(found, total_memory_gb())


def choose_model(models: list[Path], memory_gb: float) -> Path:
    """모델이 여럿이면 메모리에 맞는 것: 8GB 미만이면 가장 작은 것, 아니면 가장 큰 것."""
    by_size = sorted(models, key=lambda p: p.stat().st_size)
    return by_size[0] if 0 < memory_gb < 7.5 else by_size[-1]
