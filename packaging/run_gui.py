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

    def real_models():
        """models 폴더의 실제 모델마다 보고서 초안을 써 본다(--ai)."""
        import time
        from gongmun_ai import writer
        from gongmun_ai.layouts import report_hwpx
        from gongmun_ai.llm import LlamaCppBackend, total_memory_gb
        from gongmun_ai.settings import Settings
        results = []
        for path in sorted((app_root() / "models").glob("*.gguf"), key=lambda p: p.stat().st_size):
            t0 = time.time()
            backend = LlamaCppBackend(path)
            t1 = time.time()
            rep, result = writer.draft_report(backend, "2026년 국정감사 수감 준비 계획 보고서. 대상은 본부 및 소속기관.")
            t2 = time.time()
            report_hwpx(rep, Settings()).save(Path(tempfile.mkdtemp()) / "ai.hwpx")
            lines.append(f"----- {path.name} 초안 -----\n" + result.text
                         + "\n----- 주의 -----\n" + "\n".join(result.warnings))
            results.append(f"{path.name}: 불러오기 {t1 - t0:.0f}초, 초안 {t2 - t1:.0f}초, "
                           f"장 {len(rep.sections)}개 · 절 {sum(len(s.subs) for s in rep.sections)}개")
            del backend
        if not results:
            raise FileNotFoundError("models 폴더에 모델이 없습니다.")
        return f"엔진 {__import__('gongmun_ai.llm').llm.load_cpu_backend()}, 메모리 {total_memory_gb():.0f}GB | " + " / ".join(results)

    check("한글 문서", hwpx_and_hwp)
    check("지식 DB", knowledge)
    check("AI 엔진", engine)
    check("화면", gui)
    if "--ai" in sys.argv:
        check("실제 AI 모델", real_models)
    (app_root() / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from gongmun_ai.gui import main
    main()
