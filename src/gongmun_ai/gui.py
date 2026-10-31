"""창 프로그램.

파이썬에 기본으로 들어 있는 tkinter만 써서 별도 설치 없이 실행된다.
교정과 성향 점검은 AI 모델 없이 바로 쓸 수 있고, 톤 조정과 기안문 초안은
models/ 폴더에 GGUF 모델이 있을 때 동작한다.
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
from .llm import LlamaCppBackend, find_model
from .profiles import Profile
from .security import block_network

ROOT = Path(__file__).resolve().parents[2]  # 프로그램 폴더 (profiles/, models/, examples/)
PROFILE_DIR = ROOT / "profiles"
MODEL_DIR = ROOT / "models"
NO_PROFILE = "(선택 안 함)"
NO_MODEL_MSG = ("AI 모델이 없어 이 기능을 쓸 수 없습니다.\n\n"
                "'2_AI기능_설치.bat'을 실행해 AI 엔진과 모델을 받은 뒤 프로그램을 다시 여세요.\n"
                "(교정과 성향 점검은 AI 없이 지금 바로 쓸 수 있습니다.)")

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
        self.busy = False
        self.ai_buttons: list[ttk.Button] = []

        root.title("공문서 작성 보조 AI (외부 통신 없음)")
        root.geometry("1200x780")
        root.minsize(900, 600)
        self.font = self._pick_font()
        style = ttk.Style()
        style.configure(".", font=self.font)
        style.configure("TNotebook.Tab", padding=(16, 6))

        self.status = tk.StringVar(value="AI 모델 확인 중...")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        nb.add(self._proofread_tab(nb), text="  교정  ")
        nb.add(self._tone_tab(nb), text="  톤 조정  ")
        nb.add(self._draft_tab(nb), text="  기안문 초안  ")
        nb.add(self._profile_tab(nb), text="  결재권자 점검  ")
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(10, 4)).pack(fill="x")

        threading.Thread(target=self._load_model, daemon=True).start()

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

    def _split(self, parent, input_label: str):
        """왼쪽 입력, 오른쪽 결과·안내 영역을 만든다."""
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
        ttk.Button(out_bar, text="결과 복사", command=lambda: self._copy(out)).pack(side="left")
        ttk.Button(out_bar, text="파일로 저장", command=lambda: self._save(out)).pack(side="left", padx=4)
        ttk.Label(right, text="고친 내용과 확인할 점").pack(anchor="w")
        notes = self._text(right, height=8)
        return left, src, out, notes, file_bar

    def _profile_combo(self, parent) -> ttk.Combobox:
        names = [NO_PROFILE] + sorted(p.stem for p in PROFILE_DIR.glob("*.toml"))
        combo = ttk.Combobox(parent, values=names, state="readonly", width=22, font=self.font)
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
        path = filedialog.askopenfilename(filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        if path:
            try:
                self._set(text, read_text(path))
            except ValueError as e:
                messagebox.showerror("파일 열기", str(e))

    def _copy(self, text: tk.Text) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._get(text))
        self.status.set("결과를 복사했습니다. 한글(HWP) 문서에 붙여 넣으세요.")

    def _save(self, text: tk.Text) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("텍스트 파일", "*.txt")])
        if path:
            Path(path).write_text(self._get(text) + "\n", encoding="utf-8")
            self.status.set(f"저장했습니다: {path}")

    def _show(self, out: tk.Text, notes: tk.Text, result: writer.Result,
              fixes: list[proofread.Issue] = ()) -> None:
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
        if not (result.warnings or result.hints or fixes):
            notes.insert("end", "고칠 점이 없습니다.")

    # ------------------------------------------------------------ AI 실행

    def _load_model(self) -> None:
        try:
            path = find_model(folder=MODEL_DIR)
        except FileNotFoundError:
            self._after_status("AI 모델 없음: 교정·결재권자 점검은 바로 쓸 수 있습니다. "
                               "(톤 조정·초안은 '2_AI기능_설치.bat' 실행 후 사용)")
            return
        self._after_status(f"AI 모델 불러오는 중: {path.name} ...")
        try:
            backend = LlamaCppBackend(path)
        except Exception as e:  # 엔진 미설치, 메모리 부족 등
            self._after_status(f"AI 모델을 불러오지 못했습니다: {e}")
            return
        self.backend = backend
        self._after_status(f"AI 준비 완료: {path.name}  |  외부 통신 차단됨")

    def _after_status(self, msg: str) -> None:
        self.root.after(0, self.status.set, msg)

    def _run_ai(self, job, on_done) -> None:
        if self.busy:
            return
        if self.backend is None:
            messagebox.showinfo("AI 기능", NO_MODEL_MSG)
            return
        self.busy = True
        for b in self.ai_buttons:
            b.state(["disabled"])
        before = self.status.get()
        self.status.set("AI가 작성하는 중입니다... (저사양 PC에서는 1~3분 걸릴 수 있습니다)")

        def work():
            try:
                result, error = job(self.backend), None
            except Exception as e:
                result, error = None, e
            self.root.after(0, finish, result, error)

        def finish(result, error):
            self.busy = False
            for b in self.ai_buttons:
                b.state(["!disabled"])
            self.status.set(before)
            if error:
                messagebox.showerror("AI 오류", str(error))
            else:
                on_done(result)

        threading.Thread(target=work, daemon=True).start()

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

    # ------------------------------------------------------------ 탭: 기안문 초안

    def _draft_tab(self, nb):
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
        self._ai_button(bar, "초안 작성", lambda: run()).pack(side="left")

        left, src, out, notes, file_bar = self._split(
            tab, "요청 내용 (예: 작년 결과보고 형식으로 2026년 직원 교육 계획을 내부결재로 작성)")
        refs: list[tuple[str, str]] = []
        ref_label = ttk.Label(left, text="참고 문서: 없음", foreground="#555")
        ref_label.pack(anchor="w")

        def add_ref():
            for path in filedialog.askopenfilenames(filetypes=[("텍스트 파일", "*.txt")]):
                try:
                    refs.append((Path(path).name, read_text(path)))
                except ValueError as e:
                    messagebox.showerror("참고 문서", str(e))
            ref_label.configure(text="참고 문서: " + (", ".join(n for n, _ in refs) or "없음"))

        def clear_refs():
            refs.clear()
            ref_label.configure(text="참고 문서: 없음")

        ttk.Button(file_bar, text="참고 문서 추가", command=add_ref).pack(side="left", padx=(12, 0))
        ttk.Button(file_bar, text="참고 문서 비우기", command=clear_refs).pack(side="left", padx=4)

        def run():
            request = self._get(src).strip()
            if not request:
                messagebox.showinfo("기안문 초안", "요청 내용을 입력하세요.")
                return
            chosen, prof, ref_copy = tone.get(), self._profile(profile), list(refs)
            self._run_ai(lambda b: writer.draft(b, request, prof, ref_copy, chosen)[1],
                         lambda r: self._show(out, notes, r))
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
        ttk.Button(bar, text="성향 파일 폴더 열기", command=self._open_profiles).pack(side="right")
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

    def _open_profiles(self) -> None:
        if sys.platform == "win32":
            os.startfile(PROFILE_DIR)  # noqa: S606 - 탐색기로 폴더 열기
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(PROFILE_DIR)])


def main() -> None:
    block_network()
    if sys.platform == "win32":
        try:  # 고해상도 화면에서 글자가 흐리게 보이지 않게 한다
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
