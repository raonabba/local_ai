"""명령줄 실행.

    gongmun 교정 문서.txt                 # AI 없이 즉시 규칙 교정
    gongmun 교정 문서.txt --ai            # 로컬 AI로 맞춤법까지 교정
    gongmun 톤 문서.txt --style 쉬운말
    gongmun 기안 "요청 내용" --profile profiles/팀장_예시.toml --ref 작년보고.txt
    gongmun 성향 점검 profiles/팀장_예시.toml 기안.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import proofread, writer
from .llm import LlamaCppBackend, find_model
from .profiles import Profile
from .security import block_network


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):  # 윈도우 메모장의 옛 한글 인코딩도 읽는다
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError(f"{path}: 글자 인코딩을 알 수 없습니다(UTF-8 또는 CP949로 저장해 주세요).")


def write_or_print(text: str, out: str | None) -> None:
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"\n저장했습니다: {out}")
    else:
        print(text)


def section(title: str, rows: list[str]) -> None:
    if rows:
        print(f"\n=== {title} {len(rows)}건 ===")
        for r in rows:
            print(f"  {r}")


def _show(s: str) -> str:
    if not s:
        return "(없음)"
    return s.strip() if s.strip() else f"공백 {len(s)}칸"


def report(result: writer.Result, fixes: list[proofread.Issue], out: str | None) -> None:
    print("=== 결과 ===")
    write_or_print(result.text.rstrip("\n"), out)
    section("자동 수정", [f"[{i.rule}] {_show(i.original)} → {_show(i.suggestion)}" for i in fixes])
    section("확인 필요", [f"[{i.rule}] {i.message}" for i in result.hints])
    section("주의", result.warnings)


def load_backend(args):
    path = find_model(args.model)
    print(f"모델 불러오는 중: {path.name} (처음 한 번은 수십 초 걸릴 수 있습니다)", file=sys.stderr)
    return LlamaCppBackend(path, n_ctx=args.ctx, n_gpu_layers=args.gpu_layers)


def load_profile(path: str | None) -> Profile | None:
    return Profile.load(path) if path else None


# ---------------------------------------------------------------- 명령

def cmd_proofread(args) -> None:
    text = read_text(args.file)
    official = not args.general
    fixes = [i for i in proofread.check(text, official) if i.fixable]
    if args.ai:
        result = writer.ai_proofread(load_backend(args), text, official)
    else:
        fixed, hints = proofread.autofix(text, official)
        result = writer.Result(fixed, hints)
    report(result, fixes, args.out)


def cmd_tone(args) -> None:
    text = read_text(args.file)
    result = writer.adjust_tone(load_backend(args), text, args.style, load_profile(args.profile))
    report(result, [], args.out)


def cmd_draft(args) -> None:
    refs = [(Path(p).name, read_text(p)) for p in args.ref]
    _, result = writer.draft(load_backend(args), args.request, load_profile(args.profile),
                             refs, args.tone)
    report(result, [], args.out)


def cmd_profile(args) -> None:
    profile = Profile.load(args.profile)
    if args.action == "보기":
        print(profile.to_prompt())
        return
    problems = profile.check(read_text(args.file))
    if problems:
        section(f"{profile.name} 기준 보완할 점", problems)
    else:
        print(f"{profile.name} 기준으로 보완할 점이 없습니다.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gongmun", description="외부 통신 없는 공문서 작성 보조 AI")
    sub = p.add_subparsers(dest="command", required=True)

    def model_opts(sp):
        sp.add_argument("--model", help="GGUF 모델 파일 (기본: models/ 폴더)")
        sp.add_argument("--ctx", type=int, default=4096, help="문맥 길이 (메모리가 적으면 줄이세요)")
        sp.add_argument("--gpu-layers", type=int, default=0, help="GPU에 올릴 층 수 (GPU 없으면 0)")

    sp = sub.add_parser("교정", aliases=["proofread"], help="공문서 표기·맞춤법 교정")
    sp.add_argument("file", help="문서 파일 (- 는 표준 입력)")
    sp.add_argument("--ai", action="store_true", help="로컬 AI로 맞춤법·어색한 문장까지 교정")
    sp.add_argument("--general", action="store_true", help="공문서 서식(항목 기호, 끝.) 검사 제외")
    sp.add_argument("--out", help="결과 저장 파일")
    model_opts(sp)
    sp.set_defaults(func=cmd_proofread)

    sp = sub.add_parser("톤", aliases=["tone"], help="문체 바꾸기")
    sp.add_argument("file")
    sp.add_argument("--style", required=True, choices=list(writer.TONES))
    sp.add_argument("--profile", help="결재권자 성향 파일(.toml)")
    sp.add_argument("--out")
    model_opts(sp)
    sp.set_defaults(func=cmd_tone)

    sp = sub.add_parser("기안", aliases=["draft"], help="기안문 초안 작성")
    sp.add_argument("request", help='요청 (예: "작년 결과보고 형식으로 올해 계획")')
    sp.add_argument("--profile", help="결재권자 성향 파일(.toml)")
    sp.add_argument("--ref", action="append", default=[], help="참고 문서(여러 번 지정 가능)")
    sp.add_argument("--tone", default="보고서", choices=list(writer.TONES))
    sp.add_argument("--out")
    model_opts(sp)
    sp.set_defaults(func=cmd_draft)

    sp = sub.add_parser("성향", aliases=["profile"], help="결재권자 성향 보기·점검")
    sp.add_argument("action", choices=["보기", "점검"])
    sp.add_argument("profile", help="성향 파일(.toml)")
    sp.add_argument("file", nargs="?", help="점검할 문서")
    sp.set_defaults(func=cmd_profile)
    return p


def main(argv: list[str] | None = None) -> int:
    block_network()
    args = build_parser().parse_args(argv)
    if getattr(args, "action", None) == "점검" and not args.file:
        print("점검할 문서 파일을 지정하세요.", file=sys.stderr)
        return 2
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
