"""llama-cpp-python 소스가 CPU 세대별 AI 엔진(ggml-cpu-*)까지 패키지에 넣도록 고친다.

llama-cpp-python은 'ggml-cpu' 하나만 설치하므로, GGML_CPU_ALL_VARIANTS로 만든
ggml-cpu-haswell, ggml-cpu-sse42 같은 엔진이 빠진다. 그러면 AVX2가 없는 PC용 엔진도,
실행할 엔진 자체도 없게 된다.

    python packaging/patch_llama_cpp.py <llama-cpp-python 소스 폴더>
"""

import sys
from pathlib import Path

# llama.cpp ggml/src/CMakeLists.txt의 x86 변형 이름
VARIANTS = ("x64 sse42 sandybridge ivybridge piledriver haswell skylakex cannonlake cascadelake "
            "icelake cooperlake zen4 alderlake sapphirerapids")
ANCHOR = "    llama_cpp_python_install_target(ggml-cpu)\n"
PATCH = ANCHOR + (f"    foreach(variant {VARIANTS})\n"
                  "        llama_cpp_python_install_target(ggml-cpu-${variant})\n"
                  "    endforeach()\n")


def main(src: str) -> None:
    cmake = Path(src) / "CMakeLists.txt"
    text = cmake.read_text(encoding="utf-8")
    if "ggml-cpu-${variant}" in text:
        print("이미 고쳐져 있습니다.")
        return
    if ANCHOR not in text:
        raise SystemExit("CMakeLists.txt에서 ggml-cpu 설치 줄을 찾지 못했습니다(버전이 바뀜).")
    cmake.write_text(text.replace(ANCHOR, PATCH, 1), encoding="utf-8")
    print("CPU 세대별 엔진 설치 규칙을 넣었습니다.")


if __name__ == "__main__":
    main(sys.argv[1])
