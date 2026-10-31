"""창 프로그램.

파이썬에 기본으로 들어 있는 tkinter만 써서 별도 설치 없이 실행된다.
교정·결재권자 점검·학습·예시 문서는 AI 모델 없이 바로 쓸 수 있고, 톤 조정과 초안 작성은
models/ 폴더에 GGUF 모델이 있을 때 동작한다. 결과는 한글 파일(.hwpx, .hwp)로 저장한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import proofread, writer
from .cli import _show as show_change, read_text
from .examples import sample_gianmun, sample_report
from .layouts import gianmun_hwpx, report_hwpx, text_hwpx
from .learning import EXPORT_SUFFIX, KnowledgeBase
from .llm import LlamaCppBackend, find_model
from .profiles import Profile
from .readers import SUPPORTED, UnsupportedFile, read_document
from .security import block_network
from .settings import Settings, app_root

ROOT = app_root()  # 프로그램 폴더 (profiles/, models/, 지식/, 설정.toml)
PROFILE_DIR = ROOT / "profiles"
MODEL_DIR = ROOT / "models"
KB_PATH = ROOT / "지식" / "지식.db"
NO_PROFILE = "(선택 안 함)"
NO_MODEL_MSG = ("AI 모델이 없어 이 기능을 쓸 수 없습니다.\n\n"
                "models 폴더에 AI 모델 파일(.gguf)을 넣은 뒤 프로그램을 다시 여세요. "
                "('AI모델_받기.bat'으로 받을 수 있습니다.)\n\n"
                "교정·학습·결재권자 점검·예시 문서는 AI 없이 지금 바로 쓸 수 있습니다.")
LOAD_HINTS = ("이렇게 해 보세요.\n"
              "- 다른 프로그램을 닫아 메모리를 확보한 뒤 다시 누르세요(메모리 8GB 이상 권장).\n"
              "- 모델 파일 크기가 받기 페이지와 다르면 받다가 끊긴 것이니 다시 받으세요.\n"
              "- 2013년 이전 CPU(AVX2 미지원)에서는 AI 엔진이 동작하지 않습니다.")
DOC_TYPES = ("보고서(붙임)", "기안문")
DOC_FILES = [("한글 문서 (HWPX)", "*.hwpx"), ("한글 97~2022 (HWP)", "*.hwp")]
LEARN_FILES = [("문서", " ".join(f"*{e}" for e in SUPPORTED)), ("모든 파일", "*.*")]

SAMPLE = """제목  2025년도 직원 교육 계획
1. 관련: 총무과-12(2025. 2. 1.)
2. 교육을 아래와 같이 실시하오니 필히 참석하시오.
 가. 일시: ’25. 3. 4(화). 오후 2시 30분~17:00까지
 나. 장소 : 본관 1F 대회의실
  다. 예산 : 금 500,000원
3. 교육 결과는 익일 송부할 것임
"""

FIX_COLOR, HINT_COLOR = "#fff3b0", "#ffd6d6"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.backend: LlamaCppBackend | None = None
        self.model_state = "loading"  # loading | ready | none | error
        self.model_error = ""
        self.busy = False
        self.ai_buttons: list[ttk.Button] = []
        self.settings = Settings.load()
        self.kb = KnowledgeBase(KB_PATH)

        root.title("공문서 작성 보조 AI (외부 통신 없음)")
        # 화면보다 크게 열리면 아래쪽(상태 줄)이 잘리므로 화면 크기에 맞춘다.
        w = min(1240, root.winfo_screenwidth() - 40)
        h = min(800, root.winfo_screenheight() - 90)
        root.geometry(f"{w}x{h}+10+10")
        root.minsize(960, 620)
        self.font = self._pick_font()
        style = ttk.Style()
        style.configure(".", font=self.font)
        style.configure("TNotebook.Tab", padding=(16, 6))

        self.status = tk.StringVar(value="AI 모델 확인 중...")
        # 상태 줄을 먼저 아래에 붙여야 창이 작아져도 잘리지 않는다(모델 오류 이유가 여기 나온다).
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(10, 4),
                  relief="sunken").pack(side="bottom", fill="x")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        nb.add(self._draft_tab(nb), text="  초안 작성  ")
        nb.add(self._proofread_tab(nb), text="  교정  ")
        nb.add(self._tone_tab(nb), text="  톤 조정  ")
        nb.add(self._learn_tab(nb), text="  학습(지식)  ")
        nb.add(self._profile_tab(nb), text="  결재권자 점검  ")

        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._load_model, daemon=True).start()

    def close(self) -> None:
        """창을 닫을 때 지식 DB를 닫는다(윈도우는 열린 파일을 옮기거나 지울 수 없게 잠근다)."""
        self.kb.close()
        self.root.destroy()

    # ------------------------------------------------------------ 공통 화면 부품

    def _pick_font(self):
        families = set(tkfont.families())
        for name in ("맑은 고딕", "Malgun Gothic", "Apple SD Gothic Neo", "NanumGothic", "Noto Sans CJK KR"):
            if name in families:
                return (name, 11)
        return ("TkDefaultFont", 11)

    def _text(self, parent, height=10) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", font=self.font, height=height, undo=True,
                       padx=8, pady=6, relief="solid", borderwidth=1)
        bar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("fix", background=FIX_COLOR)
        text.tag_configure("hint", background=HINT_COLOR)
        text.tag_configure("head", font=(self.font[0], self.font[1], "bold"))
        return text

    def _split(self, parent, input_label: str, save_hwp=None):
        """왼쪽 입력, 오른쪽 결과·안내 영역. save_hwp는 '한글 파일로 저장' 때 문서를 만드는 함수."""
        pane = ttk.PanedWindow(parent, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(6, 0))
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        ttk.Label(left, text=input_label).pack(anchor="w")
        src = self._text(left)
        file_bar = ttk.Frame(left)
        file_bar.pack(fill="x", pady=4)
        ttk.Button(file_bar, text="파일 열기", command=lambda: self._open_into(src)).pack(side="left")
        ttk.Button(file_bar, text="지우기", command=lambda: src.delete("1.0", "end")).pack(side="left", padx=4)

        ttk.Label(right, text="결과").pack(anchor="w")
        out = self._text(right, height=14)
        out_bar = ttk.Frame(right)
        out_bar.pack(fill="x", pady=4)
        make = save_hwp or (lambda: text_hwpx(self._get(out), self.settings))
        ttk.Button(out_bar, text="한글 파일로 저장", command=lambda: self._save_hwp(make)).pack(side="left")
        ttk.Button(out_bar, text="결과 복사", command=lambda: self._copy(out)).pack(side="left", padx=4)
        ttk.Button(out_bar, text="글 파일로 저장", command=lambda: self._save_txt(out)).pack(side="left")
        ttk.Label(right, text="고친 내용과 확인할 점").pack(anchor="w")
        notes = self._text(right, height=8)
        return left, src, out, notes, file_bar

    def _profile_combo(self, parent) -> ttk.Combobox:
        names = [NO_PROFILE] + sorted(p.stem for p in PROFILE_DIR.glob("*.toml"))
        combo = ttk.Combobox(parent, values=names, state="readonly", width=16, font=self.font)
        combo.set(NO_PROFILE)
        return combo

    def _profile(self, combo: ttk.Combobox) -> Profile | None:
        name = combo.get()
        return None if name == NO_PROFILE else Profile.load(PROFILE_DIR / f"{name}.toml")

    def _ai_button(self, parent, text, command) -> ttk.Button:
        btn = ttk.Button(parent, text=text, command=command)
        self.ai_buttons.append(btn)
        return btn

    @staticmethod
    def _get(text: tk.Text) -> str:
        return text.get("1.0", "end-1c")

    @staticmethod
    def _set(text: tk.Text, value: str) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", value)

    def _open_into(self, text: tk.Text) -> None:
        path = filedialog.askopenfilename(filetypes=LEARN_FILES)
        if path:
            try:
                self._set(text, read_document(path))
            except UnsupportedFile as e:
                messagebox.showerror("파일 열기", str(e))

    def _copy(self, text: tk.Text) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._get(text))
        self.status.set("결과를 복사했습니다. 한글 문서에 붙여 넣으세요.")

    def _save_txt(self, text: tk.Text) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("글 파일", "*.txt")])
        if path:
            Path(path).write_text(self._get(text) + "\n", encoding="utf-8")
            self.status.set(f"저장했습니다: {path}")

    def _save_hwp(self, make) -> None:
        """make()가 만든 한글 문서를 저장하고, 원하면 바로 연다."""
        try:
            doc = make()
        except ValueError as e:
            messagebox.showinfo("한글 파일로 저장", str(e))
            return
        path = filedialog.asksaveasfilename(defaultextension=".hwpx", filetypes=DOC_FILES)
        if not path:
            return
        try:
            doc.save(path)
        except Exception as e:  # HWP 변환 기능 없음 등
            messagebox.showerror("한글 파일로 저장", str(e))
            return
        self.status.set(f"저장했습니다: {path}")
        if messagebox.askyesno("한글 파일로 저장", "저장했습니다. 지금 한글로 열어 볼까요?"):
            self._open_path(Path(path))

    @staticmethod
    def _open_path(path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - 연결된 프로그램(한글)으로 열기
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def _show(self, out: tk.Text, notes: tk.Text, result: writer.Result,
              fixes: list[proofread.Issue] = (), extra: list[str] = ()) -> None:
        self._set(out, result.text.rstrip("\n"))
        notes.delete("1.0", "end")

        def section(title, rows, tag):
            if rows:
                notes.insert("end", f"{title} {len(rows)}건\n", "head")
                for r in rows:
                    notes.insert("end", f"  {r}\n", tag)
                notes.insert("end", "\n")

        section("■ 주의", result.warnings, "hint")
        section("■ 확인 필요", [f"[{i.rule}] {i.message}" for i in result.hints], "hint")
        section("■ 자동으로 고침", [f"[{i.rule}] {show_change(i.original)} → {show_change(i.suggestion)}"
                                for i in fixes], "fix")
        section("■ 참고", list(extra), "")
        if not (result.warnings or result.hints or fixes or extra):
            notes.insert("end", "고칠 점이 없습니다.")

    # ------------------------------------------------------------ AI 실행

    def _load_model(self) -> None:
        self.model_state = "loading"
        try:
            path = find_model(folder=MODEL_DIR)
        except FileNotFoundError:
            self.model_state = "none"
            self._after_status("AI 모델 없음: 교정·학습·결재권자 점검·예시 문서는 바로 쓸 수 있습니다. "
                               "(톤 조정·초안은 models 폴더에 모델을 넣은 뒤 사용)")
            return
        self._after_status(f"AI 모델 불러오는 중: {path.name} ... (처음에는 1분 정도 걸릴 수 있습니다)")
        try:
            backend = LlamaCppBackend(path)
        except Exception as e:  # 엔진 없음, 파일 손상, 메모리 부족 등
            self.model_error = f"{type(e).__name__}: {e}"
            self.model_state = "error"
            log_error(f"AI 모델 불러오기 실패: {path}")
            self._after_status(f"AI 모델을 불러오지 못했습니다: {e}")
            return
        self.backend = backend
        self.model_state = "ready"
        self._after_status(f"AI 준비 완료: {path.name}  |  엔진: {backend.cpu}  |  외부 통신 차단됨")

    def _reload_model(self) -> None:
        self.model_state = "loading"
        threading.Thread(target=self._load_model, daemon=True).start()

    def _ai_ready(self) -> bool:
        """AI를 쓸 수 있으면 True. 아니면 이유를 알려 주고, 필요하면 모델을 다시 찾는다."""
        if self.backend is not None:
            return True
        if self.model_state == "loading":
            messagebox.showinfo("AI 기능", "AI 모델을 불러오는 중입니다.\n\n"
                                "아래 상태 줄에 'AI 준비 완료'가 뜨면 다시 눌러 주세요. "
                                "(처음에는 1분 정도 걸릴 수 있습니다)")
        elif self.model_state == "error":
            messagebox.showerror("AI 기능", f"AI 모델을 불러오지 못했습니다.\n\n{self.model_error}\n\n{LOAD_HINTS}")
            self._reload_model()  # 메모리 부족처럼 잠깐의 문제일 수 있어 다시 시도한다
        elif any(MODEL_DIR.glob("*.gguf")):
            # 프로그램을 켠 뒤에 모델을 넣은 경우: 다시 열지 않아도 되게 지금 불러온다.
            self._reload_model()
            messagebox.showinfo("AI 기능", "models 폴더에서 AI 모델을 찾았습니다. 지금 불러오는 중입니다.\n\n"
                                "아래 상태 줄에 'AI 준비 완료'가 뜨면 다시 눌러 주세요.")
        else:
            messagebox.showinfo("AI 기능", NO_MODEL_MSG)
        return False

    def _after_status(self, msg: str) -> None:
        self.root.after(0, self.status.set, msg)

    def _background(self, job, on_done, message: str, need_ai: bool = True) -> None:
        """오래 걸리는 일을 뒤에서 돌리고, 끝나면 on_done(결과)을 화면 쪽에서 부른다."""
        if self.busy:
            return
        if need_ai and not self._ai_ready():
            return
        self.busy = True
        for b in self.ai_buttons:
            b.state(["disabled"])
        before = self.status.get()
        self.status.set(message)

        def work():
            try:
                result, error = job(), None
            except Exception as e:
                result, error = None, e
            self.root.after(0, finish, result, error)

        def finish(result, error):
            self.busy = False
            for b in self.ai_buttons:
                b.state(["!disabled"])
            self.status.set(before)
            if error:
                messagebox.showerror("오류", str(error))
            else:
                on_done(result)

        threading.Thread(target=work, daemon=True).start()

    def _run_ai(self, job, on_done) -> None:
        import time
        start = time.monotonic()

        def progress(chars: int) -> None:
            # 저사양 PC에서는 몇 분 걸리므로 멈춘 것이 아님을 보여 준다.
            self._after_status(f"AI가 작성하는 중입니다... {chars:,}자 ({time.monotonic() - start:.0f}초)")

        def run():
            self.backend.progress = progress
            try:
                return job(self.backend)
            finally:
                self.backend.progress = None
        self._background(run, on_done, "AI가 작성을 준비하는 중입니다... (저사양 PC에서는 몇 분 걸릴 수 있습니다)")

    # ------------------------------------------------------------ 탭: 초안 작성

    def _draft_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Label(bar, text="문서").pack(side="left")
        kind = ttk.Combobox(bar, values=DOC_TYPES, state="readonly", width=11, font=self.font)
        kind.set(DOC_TYPES[0])
        kind.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="문체").pack(side="left")
        tone = ttk.Combobox(bar, values=list(writer.TONES), state="readonly", width=8, font=self.font)
        tone.set("보고서")
        tone.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="결재권자").pack(side="left")
        profile = self._profile_combo(bar)
        profile.pack(side="left", padx=(4, 10))
        use_kb = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="학습한 지식 활용", variable=use_kb).pack(side="left", padx=(0, 10))
        self._ai_button(bar, "초안 작성 (AI)", lambda: run()).pack(side="left")
        ttk.Button(bar, text="예시 문서 보기 (AI 없이)", command=lambda: show_sample()).pack(side="right")

        current = {"doc": None}  # 마지막으로 만든 Gianmun 또는 Report

        def make_hwp():
            doc = current["doc"]
            if doc is None:
                raise ValueError("먼저 [초안 작성]이나 [예시 문서 보기]를 눌러 문서를 만드세요.")
            return report_hwpx(doc, self.settings) if hasattr(doc, "sections") else gianmun_hwpx(doc, self.settings)

        left, src, out, notes, file_bar = self._split(
            tab, "요청 내용 (예: 작년 결과보고 형식으로 2026년 국정감사 수감 준비 계획 보고서 작성)", make_hwp)
        refs: list[tuple[str, str]] = []
        ref_label = ttk.Label(left, text="참고 문서: 없음 (학습한 지식은 자동으로 참고합니다)", foreground="#555")
        ref_label.pack(anchor="w")

        def add_ref():
            for path in filedialog.askopenfilenames(filetypes=LEARN_FILES):
                try:
                    refs.append((Path(path).name, read_document(path)))
                except UnsupportedFile as e:
                    messagebox.showerror("참고 문서", str(e))
            ref_label.configure(text="참고 문서: " + (", ".join(n for n, _ in refs) or "없음"))

        def clear_refs():
            refs.clear()
            ref_label.configure(text="참고 문서: 없음")

        ttk.Button(file_bar, text="참고 문서 추가", command=add_ref).pack(side="left", padx=(12, 0))
        ttk.Button(file_bar, text="참고 문서 비우기", command=clear_refs).pack(side="left", padx=4)

        def show_sample():
            doc = sample_report() if kind.get() == DOC_TYPES[0] else sample_gianmun()
            current["doc"] = doc
            text = doc.to_text() if hasattr(doc, "sections") else doc.render()
            self._show(out, notes, writer.Result(text),
                       extra=["AI 없이 만든 예시 문서입니다. [한글 파일로 저장]을 눌러 양식을 확인하세요.",
                              "기관명·결재란은 프로그램 폴더의 '설정.toml'에서 바꿀 수 있습니다."])

        def run():
            request = self._get(src).strip()
            if not request:
                messagebox.showinfo("초안 작성", "요청 내용을 입력하세요.")
                return
            chosen_kind, chosen_tone, prof = kind.get(), tone.get(), self._profile(profile)
            ref_copy, kb = list(refs), (self.kb if use_kb.get() else None)

            def job(backend):
                if chosen_kind == DOC_TYPES[0]:
                    return writer.draft_report(backend, request, prof, ref_copy, kb)
                return writer.draft(backend, request, prof, ref_copy, chosen_tone, kb)

            def done(pair):
                current["doc"], result = pair
                extra = ["[한글 파일로 저장]을 누르면 기관 양식으로 저장됩니다."]
                if kb is not None and self.kb.stats()["docs"]:
                    extra.insert(0, f"학습한 문서 {self.kb.stats()['docs']}건을 참고했습니다.")
                self._show(out, notes, result, extra=extra)
            self._run_ai(job, done)
        return tab

    # ------------------------------------------------------------ 탭: 교정

    def _proofread_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        official = tk.BooleanVar(value=True)
        ttk.Button(bar, text="교정하기 (AI 없이 즉시)", command=lambda: run_rules()).pack(side="left")
        self._ai_button(bar, "AI로 맞춤법까지 교정", lambda: run_ai()).pack(side="left", padx=6)
        ttk.Checkbutton(bar, text="공문서 서식(항목 기호, 끝.)도 검사", variable=official).pack(side="left", padx=6)
        ttk.Button(bar, text="예시 글 넣기", command=lambda: self._set(src, SAMPLE)).pack(side="right")
        ttk.Label(tab, text="노란색: 자동으로 고친 곳   분홍색: 직접 확인할 곳",
                  foreground="#555").pack(anchor="w", pady=(6, 0))
        _, src, out, notes, _ = self._split(tab, "고칠 글 (붙여 넣거나 파일 열기)")

        def mark(text: str) -> list[proofread.Issue]:
            issues = proofread.check(text, official.get())
            src.tag_remove("fix", "1.0", "end")
            src.tag_remove("hint", "1.0", "end")
            for i in issues:
                if i.end == i.start:
                    continue  # '끝.' 덧붙이기처럼 원문에 표시할 글자가 없는 것
                src.tag_add("fix" if i.fixable else "hint", f"1.0+{i.start}c", f"1.0+{i.end}c")
            return [i for i in issues if i.fixable]

        def run_rules():
            text = self._get(src)
            fixes = mark(text)
            fixed, hints = proofread.autofix(text, official.get())
            self._show(out, notes, writer.Result(fixed, hints), fixes)

        def run_ai():
            text = self._get(src)
            fixes = mark(text)
            self._run_ai(lambda b: writer.ai_proofread(b, text, official.get()),
                         lambda r: self._show(out, notes, r, fixes))
        return tab

    # ------------------------------------------------------------ 탭: 톤 조정

    def _tone_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Label(bar, text="문체").pack(side="left")
        tone = ttk.Combobox(bar, values=list(writer.TONES), state="readonly", width=10, font=self.font)
        tone.set("보고서")
        tone.pack(side="left", padx=(4, 12))
        ttk.Label(bar, text="결재권자").pack(side="left")
        profile = self._profile_combo(bar)
        profile.pack(side="left", padx=(4, 12))
        self._ai_button(bar, "문체 바꾸기", lambda: run()).pack(side="left")
        desc = ttk.Label(tab, text=writer.TONES["보고서"], foreground="#555")
        desc.pack(anchor="w", pady=(6, 0))
        tone.bind("<<ComboboxSelected>>", lambda _e: desc.configure(text=writer.TONES[tone.get()]))
        _, src, out, notes, _ = self._split(tab, "바꿀 글")

        def run():
            text, chosen, prof = self._get(src), tone.get(), self._profile(profile)
            self._run_ai(lambda b: writer.adjust_tone(b, text, chosen, prof),
                         lambda r: self._show(out, notes, r))
        return tab

    # ------------------------------------------------------------ 탭: 학습(지식)

    def _learn_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        ttk.Label(tab, text="보고서·공문을 넣을수록 이 PC의 AI가 기관의 문서 내용과 구성(소제목, 표 양식, 끝맺음)을 "
                            "배워 초안에 반영합니다. 지식은 이 PC 안에만 저장되며, 꾸러미로 내보내 다른 PC와 나눌 수 있습니다.",
                  foreground="#555", wraplength=1150).pack(anchor="w")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="문서 넣어 학습시키기", command=lambda: learn_files()).pack(side="left")
        ttk.Button(bar, text="폴더째 학습시키기", command=lambda: learn_folder()).pack(side="left", padx=4)
        ttk.Button(bar, text="선택한 문서 잊기", command=lambda: forget()).pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="지식 꾸러미 가져오기", command=lambda: import_pkg()).pack(side="right")
        ttk.Button(bar, text="지식 꾸러미 내보내기", command=lambda: export_pkg()).pack(side="right", padx=4)

        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=3)
        pane.add(right, weight=2)
        ttk.Label(left, text="학습한 문서").pack(anchor="w")
        cols = ("name", "kind", "added", "origin")
        tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        for c, title, width in zip(cols, ("문서", "종류", "학습 일시", "출처 PC"), (360, 70, 150, 120)):
            tree.heading(c, text=title)
            tree.column(c, width=width, anchor="w" if c == "name" else "center")
        tree.pack(fill="both", expand=True)
        ttk.Label(right, text="이 PC가 배운 것").pack(anchor="w")
        summary = self._text(right, height=20)

        def refresh(message: str = ""):
            tree.delete(*tree.get_children())
            for doc_id, name, kind, added, origin in self.kb.documents():
                tree.insert("", "end", iid=str(doc_id), values=(name, kind, added.replace("T", " "), origin))
            self._set(summary, (message + "\n\n" if message else "") + self.kb.summary())

        def learn(paths):
            if not paths:
                return
            # 오래 걸리는 파일 읽기(HWP 변환 등)는 뒤에서, DB 저장은 끝난 뒤 화면 쪽에서 한다.
            def job():
                texts, errors = [], []
                for p in paths:
                    try:
                        texts.append((Path(p).name, read_document(p)))
                    except UnsupportedFile as e:
                        errors.append(str(e))
                return texts, errors

            def done(res):
                texts, errors = res
                report = self.kb.learn_texts(texts)
                report.errors += errors
                refresh(report.message())
                messagebox.showinfo("학습", report.message())
            self._background(job, done, f"문서 {len(paths)}건을 읽고 학습하는 중입니다...", need_ai=False)

        def learn_files():
            learn(list(filedialog.askopenfilenames(filetypes=LEARN_FILES)))

        def learn_folder():
            folder = filedialog.askdirectory()
            if folder:
                learn([p for p in Path(folder).rglob("*") if p.suffix.lower() in SUPPORTED])

        def forget():
            chosen = tree.selection()
            if chosen and messagebox.askyesno("문서 잊기", f"선택한 문서 {len(chosen)}건을 지식에서 뺄까요?"):
                for iid in chosen:
                    self.kb.forget(int(iid))
                refresh(f"문서 {len(chosen)}건을 지식에서 뺐습니다.")

        def export_pkg():
            path = filedialog.asksaveasfilename(defaultextension=EXPORT_SUFFIX,
                                                filetypes=[("지식 꾸러미", f"*{EXPORT_SUFFIX}")])
            if path:
                self.kb.export(path)
                messagebox.showinfo("지식 꾸러미", f"내보냈습니다: {path}\n다른 PC에서 [지식 꾸러미 가져오기]로 합칠 수 있습니다.")

        def import_pkg():
            path = filedialog.askopenfilename(filetypes=[("지식 꾸러미", f"*{EXPORT_SUFFIX}"), ("모든 파일", "*.*")])
            if path:
                try:
                    report = self.kb.import_package(path)
                except ValueError as e:
                    messagebox.showerror("지식 꾸러미", str(e))
                    return
                refresh(report.message())
                messagebox.showinfo("지식 꾸러미", report.message())

        refresh()
        return tab

    # ------------------------------------------------------------ 탭: 결재권자 점검

    def _profile_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Label(bar, text="결재권자").pack(side="left")
        profile = self._profile_combo(bar)
        profile.pack(side="left", padx=(4, 12))
        ttk.Button(bar, text="점검하기 (AI 없이 즉시)", command=lambda: run()).pack(side="left")
        ttk.Button(bar, text="성향 파일 폴더 열기", command=lambda: self._open_path(PROFILE_DIR)).pack(side="right")
        _, src, out, notes, _ = self._split(tab, "점검할 문서")

        def show_profile(_e=None):
            prof = self._profile(profile)
            self._set(out, prof.to_prompt() if prof else "결재권자를 고르면 성향이 여기에 보입니다.")
        profile.bind("<<ComboboxSelected>>", show_profile)
        show_profile()

        def run():
            prof = self._profile(profile)
            if prof is None:
                messagebox.showinfo("결재권자 점검", "결재권자를 고르세요.")
                return
            problems = prof.check(self._get(src))
            notes.delete("1.0", "end")
            if problems:
                notes.insert("end", f"■ {prof.name} 기준 보완할 점 {len(problems)}건\n", "head")
                for p in problems:
                    notes.insert("end", f"  {p}\n", "hint")
            else:
                notes.insert("end", f"{prof.name} 기준으로 보완할 점이 없습니다.")
        return tab


LOG_PATH = ROOT / "오류기록.txt"


def log_error(title: str, exc: BaseException | None = None) -> None:
    """지금 처리 중인 예외를 오류기록.txt에 남긴다(문의할 때 이 파일을 보내면 된다)."""
    import platform
    import traceback
    from datetime import datetime
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} {title}\n"
                    f"{platform.platform()} | {platform.processor()} | CPU {os.cpu_count()}개\n"
                    + ("".join(traceback.format_exception(exc)) if exc else traceback.format_exc()))
    except OSError:
        pass


def main() -> None:
    block_network()
    import faulthandler
    try:
        # AI 엔진이 CPU 명령어 문제 등으로 프로그램째 멈추는 경우에도 이유를 남긴다.
        faulthandler.enable(open(LOG_PATH, "a", encoding="utf-8"))
    except OSError:
        pass
    if sys.platform == "win32":
        try:  # 고해상도 화면에서 글자가 흐리게 보이지 않게 한다
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        log_error("화면 처리 중 오류", val)
        messagebox.showerror("오류", f"{val}\n\n자세한 내용은 '{LOG_PATH.name}'에 남겼습니다.")
    root.report_callback_exception = report
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
