"""실행 파일(공문서AI.exe)의 시작점.

--self-test로 실행하면 창을 띄우지 않고 주요 기능을 점검해 selftest.txt에 결과를 적는다(빌드 확인용).
"""

import sys


def self_test() -> int:
    import tempfile
    import traceback
    from pathlib import Path

    from gongmun_ai.settings import app_root

    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"OK   {name}: {fn()}")
        except Exception:
            ok = False
            lines.append(f"FAIL {name}\n{traceback.format_exc()}")

    def hwpx_and_hwp():
        from gongmun_ai.examples import sample_report
        from gongmun_ai.layouts import report_hwpx
        from gongmun_ai.readers import read_document
        from gongmun_ai.settings import Settings
        d = Path(tempfile.mkdtemp())
        report_hwpx(sample_report(), Settings()).save(d / "a.hwpx")
        report_hwpx(sample_report(), Settings()).save(d / "a.hwp")
        return f"hwpx·hwp 저장, hwp 읽기 {len(read_document(d / 'a.hwp'))}자"

    def knowledge():
        from gongmun_ai.learning import KnowledgeBase
        kb = KnowledgeBase(Path(tempfile.mkdtemp()) / "k.db")
        kb.learn_texts([("시험", "Ⅰ. 개요\n1. 추진 배경\n국정감사 준비를 위해 자료를 정리함.")])
        return f"검색 {len(kb.search('감사 준비'))}건"

    def engine():
        import llama_cpp
        return f"llama-cpp-python {llama_cpp.__version__}"

    def gui():
        import tkinter
        return f"Tk {tkinter.TkVersion}"

    check("한글 문서", hwpx_and_hwp)
    check("지식 DB", knowledge)
    check("AI 엔진", engine)
    check("화면", gui)
    (app_root() / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from gongmun_ai.gui import main
    main()
