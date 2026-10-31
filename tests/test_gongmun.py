import json
import socket
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree
from pathlib import Path

from gongmun_ai import proofread, writer
from gongmun_ai.gianmun import Gianmun, Item
from gongmun_ai.llm import ScriptedBackend, clean_output, parse_json
from gongmun_ai.profiles import Profile
from gongmun_ai.security import NetworkBlockedError, block_network


def fixed(text, official=False):
    return proofread.autofix(text, official)[0]


class ProofreadTest(unittest.TestCase):
    def test_korean_amount(self):
        self.assertEqual(proofread.korean_amount(113560), "일십일만삼천오백육십")
        self.assertEqual(proofread.korean_amount(100000000), "일억")
        self.assertEqual(proofread.korean_amount(1050), "일천오십")

    def test_dates(self):
        self.assertEqual(fixed("2026년 10월 1일에 개최"), "2026. 10. 1.에 개최")
        self.assertEqual(fixed("(2026년 10월 1일.)"), "(2026. 10. 1.)")
        self.assertEqual(fixed("2026.01.05 기준"), "2026. 1. 5. 기준")
        self.assertEqual(fixed("2026. 10. 31. 기준"), "2026. 10. 31. 기준")

    def test_times(self):
        self.assertEqual(fixed("오후 2시 30분 시작"), "14:30 시작")
        self.assertEqual(fixed("오전 9시 시작"), "09:00 시작")
        self.assertEqual(fixed("오전 12시"), "00:00")
        self.assertEqual(fixed("14시 시작, 3시간 소요"), "14시 시작, 3시간 소요")
        self.assertEqual(fixed("오후 16시"), "16:00")
        self.assertEqual(fixed("9:30-12:20"), "09:30-12:20")
        self.assertEqual(fixed("13 : 20"), "13:20")
        self.assertEqual(fixed("09:00시"), "09:00")
        self.assertEqual(fixed("오전 10:20"), "10:20")
        self.assertFalse(proofread.check("밤 12시까지", False)[0].fixable)
        self.assertFalse(proofread.check("2025. 2. 21. 24시까지", False)[-1].fixable)
        hints = [i for i in proofread.check("3시 30분 시작", False) if i.rule == "시각"]
        self.assertEqual(len(hints), 1)
        self.assertFalse(hints[0].fixable)

    def test_ampm_not_double_reported(self):
        rules = [i.rule for i in proofread.check("오후 2시 30분", False)]
        self.assertEqual(rules, ["시각"])

    def test_amounts(self):
        self.assertEqual(fixed("예산 1,500,000원 소요"), "예산 금1,500,000원(금일백오십만원) 소요")
        already = "금1,500,000원(금일백오십만원)"
        self.assertEqual(fixed(already), already)
        self.assertEqual(fixed("3000원으로"), "금3,000원(금삼천원)으로")

    def test_easy_words_and_spacing(self):
        self.assertEqual(fixed("금일 필히 참석 요망"), "오늘 반드시 참석 바람")
        self.assertEqual(fixed("변경될수 있으며 할수록 좋고 할때 할것"),
                         "변경될 수 있으며 할수록 좋고 할 때 할 것")
        self.assertEqual(fixed("취득한 자격, 승인을 득하여"), "취득한 자격, 승인을 받아")
        self.assertEqual(fixed("결정되어지는 사항"), "결정되는 사항")
        self.assertEqual(fixed("하기 위해"), "하기 위해")

    def test_guide_dates(self):
        self.assertEqual(fixed("’24. 1. 6."), "2024. 1. 6.")
        self.assertEqual(fixed("날짜: 2025. 1. 6(월)."), "날짜: 2025. 1. 6.(월)")
        self.assertEqual(fixed("2025. 2. 20.~24."), "2025. 2. 20.~2. 24.")
        self.assertEqual(fixed("2025. 2. 20.~2. 24.까지"), "2025. 2. 20.~2. 24.")
        self.assertEqual(fixed("2025.2.20~2025.2.24 까지"), "2025. 2. 20.~2025. 2. 24.")

    def test_guide_amounts(self):
        self.assertEqual(fixed("금 113,560원"), "금113,560원(금일십일만삼천오백육십원)")
        self.assertEqual(fixed("예산: 500,000원\n(1) 다음"), "예산: 금500,000원(금오십만원)\n(1) 다음")
        contract = "일금12,300원정(일금일만이천삼백원정)"
        self.assertEqual(fixed(contract), contract)

    def test_guide_expressions(self):
        cases = {
            "회의를 개최하오니 참석 바랍니다": "회의를 개최하니 참석 바랍니다",
            "2월달 일정": "2월 일정",
            "매 2년마다 점검": "2년마다 점검",
            "역량을 향상시키고": "역량을 향상하고",
            "R&D 지원, 연구 개발(R&D) 확대": "연구 개발(R&D) 지원, 연구 개발(R&D) 확대",
            "1F 회의실": "1층 회의실",
            "건축법시행규칙": "건축법 시행규칙",
            "1년이상 근무": "1년 이상 근무",
            "장소 : 대회의실": "장소: 대회의실",
            "2025. 2. 28.자로 승진": "2025. 2. 28. 자로 승진",
            "별도 송부": "따로 보냄",
            "3. 1절 기념": "삼일절 기념",
            "불우 이웃 돕기": "이웃 돕기",
            "입금 요망바랍니다": "입금 바랍니다",
            "스크린도어 설치": "안전문 설치",
        }
        for src, want in cases.items():
            self.assertEqual(fixed(src), want, src)

    def test_guide_hints(self):
        for text in ("들어가지 마시오.", "관계자 외 출입 엄금", "여권을 교부합니다",
                     "이력서, 자기소개서 각1부."):
            issues = proofread.check(text, False)
            self.assertTrue(issues and not issues[0].fixable, text)

    def test_long_sentence_hint(self):
        hints = proofread.check("가" * 120 + ".", False)
        self.assertTrue(any(i.rule == "긴 문장" for i in hints))

    def test_items_and_end_mark(self):
        text = "1. 첫째\n 가. 하위\n  다. 둘째 하위\n2. 둘째\n2. 셋째"
        self.assertEqual(fixed(text, official=True),
                         "1. 첫째\n  가. 하위\n  나. 둘째 하위\n2. 둘째\n3. 셋째  끝.")

    def test_guide_item_symbols(self):
        text = "1. 가\n  가. 나\n    1) 다\n      가) 라\n        (1) 마\n          (가) 바  끝."
        self.assertEqual(fixed(text, official=True),
                         "1. 가\n  가. 나\n    1) 다\n      가) 라\n        ⑴ 마\n          ㈎ 바  끝.")
        symbols = "□ 개요\n  ○ 목적\n    - 세부  끝."
        self.assertEqual([i for i in proofread.check(symbols) if i.fixable], [])

    def test_related_needs_title(self):
        issues = proofread.check("1. 관련: 재난대응과-12(2025. 2. 1.)\n2. 내용  끝.")
        self.assertTrue(any(i.rule == "관련 근거" for i in issues))
        ok = "1. 관련: 재난대응과-12(2025. 2. 1.)「산불 대응 지침」\n2. 내용  끝."
        self.assertFalse(any(i.rule == "관련 근거" for i in proofread.check(ok)))

    def test_skipped_level(self):
        issues = proofread.check("1. 첫째\n    1) 바로 셋째 단계  끝.")
        self.assertTrue(any(i.rule == "항목 순서" for i in issues))

    def test_end_mark_spacing(self):
        self.assertEqual(fixed("1. 내용 끝.", True), "1. 내용  끝.")
        self.assertEqual(proofread.check("1. 내용  끝."), [])


class GianmunTest(unittest.TestCase):
    def test_render_passes_own_proofreader(self):
        doc = Gianmun("2027년 업무 계획 보고", related=["총무과-123(2026. 10. 1.)", "기획과-45"],
                      items=[Item("계획을 보고함", [Item("일정", [Item("세부")]), Item("예산")]),
                             Item("협조 바람")],
                      attachments=["업무 계획서", "예산 내역 2부"])
        text = doc.render()
        self.assertIn("1. 관련\n  가. 총무과-123(2026. 10. 1.)\n  나. 기획과-45", text)
        self.assertIn("2. 계획을 보고함\n  가. 일정\n    1) 세부\n  나. 예산\n3. 협조 바람", text)
        self.assertTrue(text.endswith("붙임  1. 업무 계획서 1부.\n      2. 예산 내역 2부.  끝."))
        self.assertEqual([i for i in proofread.check(text) if i.fixable], [])

    def test_single_attachment_and_none(self):
        self.assertTrue(Gianmun("제목", attachments=["계획서"]).render().endswith("붙임  계획서 1부.  끝."))
        # 항목이 하나뿐이면 번호를 붙이지 않는다.
        self.assertTrue(Gianmun("제목", items=[Item("내용")]).render().endswith("\n내용  끝."))
        self.assertTrue(Gianmun("제목", attachments=["규정 1부. (따로 보냄)"]).render()
                        .endswith("붙임  규정 1부. (따로 보냄)  끝."))

    def test_related_sorted_by_date(self):
        doc = Gianmun("제목", related=["B-2(2025. 3. 1.)「나」", "A-1(2025. 2. 1.)「가」"],
                      items=[Item("내용")])
        self.assertIn("  가. A-1(2025. 2. 1.)「가」\n  나. B-2(2025. 3. 1.)「나」", doc.render())


class ProfileTest(unittest.TestCase):
    def make(self):
        return Profile("김 팀장", conclusion_first=True, max_chars=100,
                       required_sections=["소요 예산"], avoid=["검토 중"])

    def test_check(self):
        problems = self.make().check("1. 관련: 문서\n2. 배경 설명\n3. 검토 중임")
        self.assertEqual(len(problems), 3)
        self.assertEqual(self.make().check("1. 승인 요청함\n2. 소요예산: 없음"), [])

    def test_load_examples(self):
        for path in Path("profiles").glob("*.toml"):
            self.assertTrue(Profile.load(path).name)


class WriterTest(unittest.TestCase):
    def test_fact_warnings(self):
        self.assertEqual(writer.fact_warnings("2026년 10월 1일 30명", "2026. 10. 1. 30명"), [])
        w = writer.fact_warnings("참석 30명", "참석 35명")
        self.assertEqual(len(w), 2)

    def test_adjust_tone(self):
        backend = ScriptedBackend("<think>생각</think>오늘 회의에 30명이 참석함")
        result = writer.adjust_tone(backend, "금일 회의 참석 인원은 30명입니다.", "보고서",
                                    Profile("팀장", avoid=["검토"]))
        self.assertEqual(result.text, "오늘 회의에 30명이 참석함")
        self.assertEqual(result.warnings, [])
        self.assertIn("팀장", backend.calls[0][0]["content"])

    def test_tone_flags_invented_number(self):
        result = writer.adjust_tone(ScriptedBackend("40명 참석"), "30명 참석", "간결")
        self.assertTrue(result.warnings)

    def test_draft(self):
        answer = {"title": "2027년 교육 계획 보고", "recipient": "내부결재",
                  "related": [], "items": [{"text": "교육 계획을 승인 요청함",
                                            "sub": ["일정: 2027년 3월 2일", "대상: 30명"]}],
                  "attachments": ["교육 계획서"]}
        backend = ScriptedBackend("```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```")
        doc, result = writer.draft(backend, "작년처럼 교육 계획", references=[("작년.txt", "대상 30명")])
        self.assertIn("  가. 일정: 2027. 3. 2.", result.text)
        self.assertTrue(result.text.endswith("붙임  교육 계획서 1부.  끝."))
        # 2027과 3, 2는 참고 문서에 없으므로 확인 경고가 나야 한다.
        self.assertTrue(any("원문에 없던 숫자" in w for w in result.warnings))

    def test_unknown_tone(self):
        with self.assertRaises(ValueError):
            writer.adjust_tone(ScriptedBackend(""), "글", "없는톤")


class KnowledgeTest(unittest.TestCase):
    def test_guide_in_prompts(self):
        backend = ScriptedBackend("결과", json.dumps({"title": "t", "recipient": "내부결재", "related": [],
                                                      "items": [], "attachments": []}))
        writer.adjust_tone(backend, "글", "안내문")
        writer.draft(backend, "요청")
        tone_system, draft_system = backend.calls[0][0]["content"], backend.calls[1][0]["content"]
        self.assertIn("비고압성", tone_system)
        self.assertNotIn("주최", tone_system)  # 짧은 작업에는 필요한 지침만 넣는다
        self.assertIn("1안건 1기안", draft_system)
        self.assertIn("주관", draft_system)


class LlmTest(unittest.TestCase):
    def test_truncated_report_json_is_salvaged(self):
        from gongmun_ai.report import Report
        full = json.dumps({"title": "교육 계획", "summary": ["보고임."], "sections": [
            {"title": "개요", "subs": [{"heading": "목적", "paragraphs": [], "bullets": ["역량 향상", "안전 의식 \\ \"강화\""],
                                      "notes": [], "table": {"title": "", "columns": [], "rows": []}}]},
            {"title": "추진 계획", "subs": [{"heading": "일정", "paragraphs": [], "bullets": ["3월 시행"],
                                         "notes": [], "table": {"title": "", "columns": [], "rows": []}}]}]},
                          ensure_ascii=False)
        cut_in_value = full[:full.index("3월 시행") + 2]       # 값 문자열 한가운데서 끊김(CI에서 본 경우)
        cut_after_key = full[:full.index('"heading": "일정"') + 10]  # 이름 뒤에서 끊김
        for cut in (cut_in_value, cut_after_key, full[:-3]):
            rep = Report.from_dict(parse_json(cut))
            self.assertEqual(rep.title, "교육 계획")
            self.assertEqual(rep.sections[0].subs[0].bullets, ["역량 향상", '안전 의식 \\ "강화"'])
        self.assertEqual(Report.from_dict(parse_json(full[:-3])).sections[1].subs[0].bullets, ["3월 시행"])
        with self.assertRaises(ValueError):
            parse_json('{"tit')

    def test_parse_json(self):
        self.assertEqual(parse_json('설명입니다 {"a": 1} 끝'), {"a": 1})
        self.assertEqual(clean_output("<think>x</think>\n답"), "답")


class SecurityTest(unittest.TestCase):
    def test_block_network(self):
        block_network()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(NetworkBlockedError):
                s.connect(("127.0.0.1", 9))
        finally:
            s.close()
        with self.assertRaises(NetworkBlockedError):
            socket.create_connection(("example.com", 80))


class GuiTest(unittest.TestCase):
    def test_proofread_and_sample_tabs(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as e:  # tkinter가 없거나 화면이 없는 환경
            self.skipTest(f"화면 없음: {e}")
        from gongmun_ai import gui
        old_kb = gui.KB_PATH
        try:
            with tempfile.TemporaryDirectory() as d:
                gui.KB_PATH = Path(d) / "k.db"
                app = gui.App(root)

                def find(w, cls):
                    for c in w.winfo_children():
                        yield from ([c] if isinstance(c, cls) else [])
                        yield from find(c, cls)

                nb = next(find(root, gui.ttk.Notebook))
                tabs = [root.nametowidget(t) for t in nb.tabs()]
                draft, proof = tabs[0], tabs[1]

                buttons = {b.cget("text"): b for b in find(proof, gui.ttk.Button)}
                buttons["예시 글 넣기"].invoke()
                buttons["교정하기 (AI 없이 즉시)"].invoke()
                src, out = list(find(proof, tk.Text))[:2]
                self.assertIn("2025. 3. 4.(화) 14:30~17:00", out.get("1.0", "end"))
                self.assertTrue(src.tag_ranges("fix"))

                {b.cget("text"): b for b in find(draft, gui.ttk.Button)}["예시 문서 보기 (AI 없이)"].invoke()
                self.assertIn("국정감사", list(find(draft, tk.Text))[1].get("1.0", "end"))
                app.close()
        finally:
            gui.KB_PATH = old_kb


class HwpxTest(unittest.TestCase):
    def test_writer_roundtrip(self):
        from gongmun_ai.hwpx import Cell, HwpxWriter, read_text
        w = HwpxWriter()
        w.paragraph("제목 & <특수문자>", w.char(16, True, "HY헤드라인M"), w.para("CENTER"))
        w.table([[Cell("소속", fill="#D9D9D9"), Cell("성명")],
                 [Cell("기획조정실", rowspan=2), Cell("홍길동")],
                 [None, Cell("김철수")]], [40, 40], header_rows=1)
        with tempfile.TemporaryDirectory() as d:
            path = w.save(Path(d) / "t.hwpx")
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.namelist()[0], "mimetype")
                self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
                for name in z.namelist():
                    if name.endswith((".xml", ".hpf")):
                        ElementTree.fromstring(z.read(name))  # 잘 짜인 XML인지
                header = z.read("Contents/header.xml").decode()
            self.assertIn('face="HY헤드라인M"', header)
            text = read_text(path)
        self.assertIn("제목 & <특수문자>", text)
        self.assertIn("소속 | 성명", text)
        self.assertIn("기획조정실 | 홍길동", text)

    def test_image_size(self):
        from gongmun_ai.hwpx import _image_size
        png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (300).to_bytes(4, "big") + (200).to_bytes(4, "big")
        self.assertEqual(_image_size(png), ("png", (300, 200)))
        with self.assertRaises(ValueError):
            _image_size(b"GIF89a")

    def test_layouts(self):
        from gongmun_ai.examples import sample_gianmun, sample_report
        from gongmun_ai.hwpx import read_text
        from gongmun_ai.layouts import gianmun_hwpx, report_hwpx, text_hwpx
        from gongmun_ai.settings import Settings
        s = Settings(org="국방부", approvers=["과장", "국장"])
        with tempfile.TemporaryDirectory() as d:
            gian = read_text(gianmun_hwpx(sample_gianmun(), s).save(Path(d) / "g.hwpx"))
            rep = read_text(report_hwpx(sample_report(), s).save(Path(d) / "r.hwpx"))
            txt = read_text(text_hwpx("1. 하나\n  가. 둘  끝.", s).save(Path(d) / "t.hwpx"))
        self.assertIn("붙임  2026년 국정감사 수감 준비 계획 1부.  끝.", gian)
        self.assertIn("국방부장관", gian)
        self.assertIn("기안자 | 검토자 과장 | 결재권자 국장", gian)
        self.assertIn("등록번호 |", rep)
        self.assertIn("Ⅰ | 감사 개요", rep)
        self.assertIn("국 방 부", rep)
        self.assertIn("소 속 | 직 위 | 성 명 | 비 고", rep)
        self.assertIn("가. 둘  끝.", txt)


class LearningTest(unittest.TestCase):
    REPORT = ("Ⅰ. 개요\n1. 추진 배경\n국정감사 수감 준비를 위해 부서별 답변 자료를 정리함.\n"
              "2. 추진 일정\n일자 | 기관 | 장소\n10. 1. | ○○사단 | ○○\n※ 세부 일정은 따로 알림")

    def test_grams(self):
        from gongmun_ai.learning import grams
        self.assertEqual(grams("국정감사 AI 2026"), "국정 정감 감사 ai 2026")

    def test_learn_search_share_forget(self):
        from gongmun_ai.learning import KnowledgeBase
        with tempfile.TemporaryDirectory() as d:
            kb = KnowledgeBase(Path(d) / "a.db")
            report = kb.learn_texts([("작년보고.txt", self.REPORT)])
            self.assertEqual(report.learned, [("작년보고.txt", "보고서")])
            self.assertIn("추진 배경", report.new_headings)
            self.assertIn("일자 | 기관 | 장소", report.new_tables)
            self.assertIn("학습했습니다", report.message())
            self.assertEqual(kb.search("감사 준비")[0][0], "작년보고.txt")
            self.assertIn("추진 배경", kb.style_hints())
            self.assertEqual(kb.learn_texts([("사본.txt", self.REPORT)]).duplicates, ["사본.txt"])

            other = KnowledgeBase(Path(d) / "b.db")
            other.learn_texts([("다른PC.txt", "Ⅰ. 개요\n1. 기대 효과\n업무 시간이 줄어듦.")])
            kb.export(Path(d) / "a.gkb")
            merged = other.import_package(Path(d) / "a.gkb")
            self.assertEqual([n for n, _ in merged.learned], ["작년보고.txt"])
            self.assertEqual(other.stats()["docs"], 2)
            self.assertEqual(other.import_package(Path(d) / "a.gkb").duplicates, ["작년보고.txt"])

            doc_id = next(i for i, name, *_ in other.documents() if name == "작년보고.txt")
            other.forget(doc_id)
            self.assertEqual(other.search("감사 준비"), [])
            kb.close()
            other.close()

    def test_readers(self):
        from gongmun_ai.readers import UnsupportedFile, read_document
        with tempfile.TemporaryDirectory() as d:
            docx = Path(d) / "a.docx"
            w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xml = (f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>개요</w:t></w:r></w:p>'
                   "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>구분</w:t></w:r></w:p></w:tc>"
                   "<w:tc><w:p><w:r><w:t>내용</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>")
            with zipfile.ZipFile(docx, "w") as z:
                z.writestr("word/document.xml", xml)
            self.assertEqual(read_document(docx), "개요\n구분 | 내용")
            with self.assertRaises(UnsupportedFile):
                read_document(Path(d) / "a.xyz")


class ReportModelTest(unittest.TestCase):
    def test_merge_duplicate_headings(self):
        from gongmun_ai.report import Report
        rep = Report.from_dict({"title": "t", "summary": [], "sections": [{"title": "추진 계획", "subs": [
            {"heading": "단계별 계획", "paragraphs": ["첫 단계"], "bullets": [], "notes": [], "table": {}},
            {"heading": "단계별  계획", "paragraphs": ["둘째 단계"], "bullets": ["점검"], "notes": [], "table": {}},
            {"heading": "예산", "paragraphs": [], "bullets": ["○○원"], "notes": [], "table": {}}]}]})
        rep.merge_duplicate_headings()
        subs = rep.sections[0].subs
        self.assertEqual([x.heading for x in subs], ["단계별 계획", "예산"])
        self.assertEqual(subs[0].paragraphs, ["첫 단계", "둘째 단계"])

    def test_choose_model_by_memory(self):
        from gongmun_ai.llm import choose_model
        with tempfile.TemporaryDirectory() as d:
            small, big = Path(d) / "a-1.7b.gguf", Path(d) / "b-4b.gguf"
            small.write_bytes(b"GGUF" + b"0" * 10)
            big.write_bytes(b"GGUF" + b"0" * 100)
            self.assertEqual(choose_model([big, small], 4.0), small)
            self.assertEqual(choose_model([small, big], 16.0), big)
            self.assertEqual(choose_model([small, big], 0), big)  # 메모리를 모르면 큰 것


class ReportDraftTest(unittest.TestCase):
    def test_draft_report_uses_knowledge(self):
        from gongmun_ai.learning import KnowledgeBase
        answer = {"title": "2026년 교육 계획", "summary": ["교육 계획 보고임."],
                  "sections": [{"title": "개요", "subs": [{
                      "heading": "목적", "paragraphs": ["직무 역량을 향상시키고자 함"], "bullets": [], "notes": [],
                      "table": {"title": "", "columns": ["구분", "인원"], "rows": [["간부", "30명"]]}}]}]}
        with tempfile.TemporaryDirectory() as d:
            kb = KnowledgeBase(Path(d) / "k.db")
            kb.learn_texts([("작년.txt", LearningTest.REPORT)])
            backend = ScriptedBackend(json.dumps(answer, ensure_ascii=False))
            rep, result = writer.draft_report(backend, "국정감사 준비 교육 보고서 (대상 30명)", kb=kb)
            kb.close()
        system, user = backend.calls[0][0]["content"], backend.calls[0][1]["content"]
        self.assertIn("추진 배경", system)          # 배운 소제목
        self.assertIn("학습한 문서: 작년.txt", user)  # 찾은 관련 문단
        self.assertEqual(rep.sections[0].subs[0].paragraphs, ["직무 역량을 향상하고자 함"])  # 교정 반영
        self.assertIn("Ⅰ. 개요", result.text)
        self.assertFalse(any("30" in w for w in result.warnings))


class CliTest(unittest.TestCase):
    def test_proofread_cp949_file(self):
        from gongmun_ai.cli import main
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d, "in.txt"), Path(d, "out.txt")
            src.write_bytes("1. 금일 필히 참석".encode("cp949"))
            self.assertEqual(main(["교정", str(src), "--out", str(out)]), 0)
            self.assertEqual(out.read_text(encoding="utf-8").strip(), "1. 오늘 반드시 참석  끝.")


if __name__ == "__main__":
    unittest.main()
