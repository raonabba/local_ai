import json
import socket
import tempfile
import unittest
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
        self.assertEqual(fixed("14시 시작, 3시간 소요"), "14:00 시작, 3시간 소요")
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

    def test_long_sentence_hint(self):
        hints = proofread.check("가" * 120 + ".", False)
        self.assertTrue(any(i.rule == "긴 문장" for i in hints))

    def test_items_and_end_mark(self):
        text = "1. 첫째\n 가. 하위\n  다. 둘째 하위\n2. 둘째\n2. 셋째"
        self.assertEqual(fixed(text, official=True),
                         "1. 첫째\n  가. 하위\n  나. 둘째 하위\n2. 둘째\n3. 셋째  끝.")

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
        self.assertTrue(Gianmun("제목", items=[Item("내용")]).render().endswith("1. 내용  끝."))


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


class LlmTest(unittest.TestCase):
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
