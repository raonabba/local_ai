"""이 PC의 지식 DB(자체 학습).

사용자가 보고서·공문을 넣을 때마다 쌓는다.
- 내용: 문단 단위로 색인해, 초안을 쓸 때 관련 문단을 찾아 AI에 참고 자료로 준다.
- 문서 습관: 자주 쓰는 소제목, 표 머리(열 구성), 문장 끝맺음을 세어 두고 AI 지침에 넣는다.
그래서 같은 프로그램이라도 PC마다 쌓인 지식에 따라 결과가 달라진다.

지식 꾸러미(.gkb, SQLite 파일)로 내보내고 다른 PC에서 가져와 합칠 수 있다.
같은 문서는 내용 해시로 걸러 중복으로 쌓이지 않는다.

모델 가중치를 바꾸는 학습(파인튜닝)이 아니라, 문서를 기억해 두고 찾아 쓰는 방식(RAG)이다.
저사양 PC에서도 즉시 반영되고, 문서를 지우면 지식에서도 바로 빠진다.
"""

from __future__ import annotations

import hashlib
import platform
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .readers import UnsupportedFile, read_document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
    id INTEGER PRIMARY KEY, hash TEXT UNIQUE, name TEXT, kind TEXT,
    added TEXT, origin TEXT, chars INTEGER, body TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc_id INTEGER, text TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_index USING fts5(grams);
CREATE TABLE IF NOT EXISTS doc_headings(doc_id INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS doc_tables(doc_id INTEGER, columns TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS doc_phrases(doc_id INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
"""

CHUNK_CHARS = 500
EXPORT_SUFFIX = ".gkb"


# ---------------------------------------------------------------- 글 분석

def grams(text: str) -> str:
    """색인용 낱말: 한글은 두 글자씩 겹쳐 자르고(감사→'감사', 국정감사→'국정 정감 감사'),
    영문·숫자는 낱말 그대로 쓴다. 형태소 분석기 없이도 한국어 검색이 된다."""
    out = []
    for run in re.findall(r"[가-힣]+|[A-Za-z0-9]+", text):
        if run[0] >= "가":
            out += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
        else:
            out.append(run.lower())
    return " ".join(out)


_HEADING = re.compile(
    r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s*[.|]?|[IVX]{1,4}\.|\d{1,2}\.|[가-하]\.|[□■❑◆◇▣●]|<)\s*"
    r"(?P<h>[가-힣][^.!?|:<>]{1,24}?)\s*>?\s*:?\s*$")


def _clean_heading(h: str) -> str:
    h = h.strip()
    parts = h.split()
    if len(parts) > 1 and all(len(p) == 1 for p in parts):  # '목  적' → '목적'
        h = "".join(parts)
    return re.sub(r"\s+", " ", h)


def extract_headings(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if m and not re.search(r"\d{4}|\d+[.,]\d", m.group("h")):
            out.append(_clean_heading(m.group("h")))
    return out


def extract_tables(text: str) -> list[tuple[str, str]]:
    """표 머리(열 이름을 '|'로 이은 것)와 표 제목."""
    out, prev, in_table = [], "", False
    for line in text.split("\n"):
        if " | " in line:
            if not in_table:
                cells = [re.sub(r"\s+", "", c) for c in line.split(" | ")]
                # 장 제목 상자(Ⅰ | 개요)나 '항목 | 값' 두 칸짜리는 표 양식으로 보지 않는다.
                if (3 <= len(cells) <= 8 and all(0 < len(c) <= 12 for c in cells)
                        and cells[0][0] not in "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
                        and not any(re.fullmatch(r"[\d.,()]+", c) for c in cells)):
                    title = prev.strip().lstrip("※").strip() if len(prev.strip()) <= 30 else ""
                    out.append(("|".join(cells), title))
            in_table = True
        else:
            in_table = False
            if line.strip():
                prev = line
    return out


_ENDING = re.compile(r"([가-힣]{2,}(?:함|임|음|됨|람|니다|정|획))[.]?\s*$")


def extract_phrases(text: str) -> list[str]:
    """문장 끝맺음(예: '보고함', '추진할 계획임'의 마지막 낱말)."""
    out = []
    for line in text.split("\n"):
        if len(line.strip()) >= 10 and " | " not in line:
            m = _ENDING.search(line)
            if m:
                out.append(m.group(1))
    return out


def guess_kind(text: str) -> str:
    if re.search(r"^\s*수신", text, re.M) and re.search(r"^\s*제목", text, re.M):
        return "기안문"
    if re.search(r"[ⅠⅡⅢ]|^\s*[□❑]", text, re.M):
        return "보고서"
    return "기타"


def chunk(text: str) -> list[str]:
    """빈 줄과 큰 항목을 경계로 500자 안팎의 문단 묶음을 만든다."""
    blocks, cur = [], []
    for line in text.split("\n"):
        starts_new = not line.strip() or re.match(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|\d{1,2}\.\s)", line)
        if starts_new and sum(len(x) for x in cur) > 80:
            blocks.append("\n".join(cur).strip())
            cur = []
        if line.strip():
            cur.append(line.rstrip())
        if sum(len(x) for x in cur) > CHUNK_CHARS:
            blocks.append("\n".join(cur).strip())
            cur = []
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if len(b) >= 10]


def _hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", "", text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 결과 보고

@dataclass
class LearnReport:
    learned: list[tuple[str, str]] = field(default_factory=list)  # (문서 이름, 종류)
    duplicates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    chunks: int = 0
    new_headings: list[str] = field(default_factory=list)
    new_tables: list[str] = field(default_factory=list)

    def message(self) -> str:
        lines = []
        if self.learned:
            kinds = Counter(k for _, k in self.learned)
            lines.append(f"문서 {len(self.learned)}건을 학습했습니다 "
                         f"({', '.join(f'{k} {n}건' for k, n in kinds.items())}, 문단 묶음 {self.chunks}개).")
            if self.new_headings:
                lines.append(f"새로 배운 소제목: {', '.join(self.new_headings[:8])}"
                             + (f" 외 {len(self.new_headings) - 8}개" if len(self.new_headings) > 8 else ""))
            if self.new_tables:
                lines.append(f"새로 배운 표 양식: {' / '.join(self.new_tables[:4])}")
            lines.append("이제 초안을 쓸 때 이 문서들의 내용과 구성을 참고합니다.")
        if self.duplicates:
            lines.append(f"이미 학습한 문서라 건너뜀: {', '.join(self.duplicates)}")
        if self.errors:
            lines.append("읽지 못한 문서:")
            lines += [f"  {e}" for e in self.errors]
        return "\n".join(lines) or "학습할 문서가 없습니다."


# ---------------------------------------------------------------- 지식 DB

class KnowledgeBase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 화면과 작업 스레드가 번갈아 쓴다(동시에 쓰지 않도록 화면 쪽에서 한 번에 한 작업만 돌린다).
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -------------------------------------------------------- 학습

    def learn_files(self, paths: list[str | Path]) -> LearnReport:
        report = LearnReport()
        for p in paths:
            p = Path(p)
            try:
                text = read_document(p)
            except UnsupportedFile as e:
                report.errors.append(str(e))
                continue
            self._learn(p.name, text, report)
        self.db.commit()
        return report

    def learn_texts(self, docs: list[tuple[str, str]]) -> LearnReport:
        """이미 읽어 둔 (이름, 글) 목록을 학습한다."""
        report = LearnReport()
        for name, text in docs:
            self._learn(name, text, report)
        self.db.commit()
        return report

    def _learn(self, name: str, text: str, report: LearnReport, origin: str | None = None,
               kind: str | None = None, added: str | None = None) -> bool:
        if len(text.strip()) < 20:
            report.errors.append(f"{name}: 글이 거의 없습니다(그림으로 된 문서일 수 있음).")
            return False
        h = _hash(text)
        if self.db.execute("SELECT 1 FROM docs WHERE hash=?", (h,)).fetchone():
            report.duplicates.append(name)
            return False
        known_headings = self._heading_set()
        known_tables = self._table_set()
        kind = kind or guess_kind(text)
        cur = self.db.execute(
            "INSERT INTO docs(hash, name, kind, added, origin, chars, body) VALUES(?,?,?,?,?,?,?)",
            (h, name, kind, added or datetime.now().isoformat(timespec="seconds"),
             origin or platform.node() or "이 PC", len(text), text))
        doc_id = cur.lastrowid
        for c in chunk(text):
            cid = self.db.execute("INSERT INTO chunks(doc_id, text) VALUES(?,?)", (doc_id, c)).lastrowid
            self.db.execute("INSERT INTO chunk_index(rowid, grams) VALUES(?,?)", (cid, grams(c)))
            report.chunks += 1
        for hd in extract_headings(text):
            self.db.execute("INSERT INTO doc_headings VALUES(?,?)", (doc_id, hd))
            if hd not in known_headings and hd not in report.new_headings:
                report.new_headings.append(hd)
        for cols, title in extract_tables(text):
            self.db.execute("INSERT INTO doc_tables VALUES(?,?,?)", (doc_id, cols, title))
            if cols not in known_tables and cols.replace("|", " | ") not in report.new_tables:
                report.new_tables.append(cols.replace("|", " | "))
        self.db.executemany("INSERT INTO doc_phrases VALUES(?,?)", [(doc_id, p) for p in extract_phrases(text)])
        report.learned.append((name, kind))
        return True

    def _heading_set(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT DISTINCT text FROM doc_headings")}

    def _table_set(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT DISTINCT columns FROM doc_tables")}

    # -------------------------------------------------------- 활용

    def search(self, query: str, k: int = 4, max_chars: int = 600) -> list[tuple[str, str]]:
        """요청과 관련된 문단 묶음 (문서 이름, 내용)."""
        terms = sorted(set(grams(query).split()))
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self.db.execute(
            "SELECT d.name, c.text FROM chunk_index JOIN chunks c ON c.id = chunk_index.rowid "
            "JOIN docs d ON d.id = c.doc_id WHERE chunk_index MATCH ? ORDER BY bm25(chunk_index) LIMIT ?",
            (match, k)).fetchall()
        return [(name, text[:max_chars]) for name, text in rows]

    def top_headings(self, n: int = 10) -> list[tuple[str, int]]:
        return self.db.execute("SELECT text, COUNT(*) c FROM doc_headings GROUP BY text "
                               "ORDER BY c DESC, text LIMIT ?", (n,)).fetchall()

    def top_tables(self, n: int = 5) -> list[tuple[str, int]]:
        return self.db.execute("SELECT columns, COUNT(*) c FROM doc_tables GROUP BY columns "
                               "ORDER BY c DESC, columns LIMIT ?", (n,)).fetchall()

    def top_phrases(self, n: int = 8) -> list[tuple[str, int]]:
        return self.db.execute("SELECT text, COUNT(*) c FROM doc_phrases GROUP BY text HAVING c > 1 "
                               "ORDER BY c DESC, text LIMIT ?", (n,)).fetchall()

    def style_hints(self) -> str:
        """AI 지침에 넣을 '이 PC가 배운 문서 습관'."""
        lines = []
        if hs := self.top_headings(10):
            lines.append("- 자주 쓰는 소제목: " + ", ".join(h for h, _ in hs))
        if ts := self.top_tables(4):
            lines.append("- 자주 쓰는 표 머리: " + " / ".join(c.replace("|", "·") for c, _ in ts))
        if ps := self.top_phrases(6):
            lines.append("- 자주 쓰는 끝맺음: " + ", ".join(p for p, _ in ps))
        return ("[이 기관 문서에서 배운 습관]\n" + "\n".join(lines)) if lines else ""

    # -------------------------------------------------------- 관리

    def stats(self) -> dict:
        q = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
        return {"docs": q("SELECT COUNT(*) FROM docs"), "chunks": q("SELECT COUNT(*) FROM chunks"),
                "headings": q("SELECT COUNT(DISTINCT text) FROM doc_headings"),
                "tables": q("SELECT COUNT(DISTINCT columns) FROM doc_tables"),
                "origins": q("SELECT COUNT(DISTINCT origin) FROM docs")}

    def summary(self) -> str:
        s = self.stats()
        if not s["docs"]:
            return "아직 학습한 문서가 없습니다. 보고서·공문을 넣어 주세요."
        out = [f"학습한 문서 {s['docs']}건 · 문단 묶음 {s['chunks']}개 · 소제목 {s['headings']}종 · "
               f"표 양식 {s['tables']}종 (출처 PC {s['origins']}대)"]
        if hs := self.top_headings(8):
            out.append("자주 쓰는 소제목: " + ", ".join(f"{h}({c})" for h, c in hs))
        if ts := self.top_tables(3):
            out.append("자주 쓰는 표: " + " / ".join(f"{c.replace('|', '·')}({n})" for c, n in ts))
        return "\n".join(out)

    def documents(self) -> list[tuple[int, str, str, str, str]]:
        """(번호, 이름, 종류, 학습 일시, 출처 PC)."""
        return self.db.execute("SELECT id, name, kind, added, origin FROM docs ORDER BY id DESC").fetchall()

    def forget(self, doc_id: int) -> None:
        """문서를 지식에서 바로 뺀다."""
        ids = [r[0] for r in self.db.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        self.db.executemany("DELETE FROM chunk_index WHERE rowid=?", [(i,) for i in ids])
        for table in ("chunks", "doc_headings", "doc_tables", "doc_phrases"):
            self.db.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
        self.db.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        self.db.commit()

    # -------------------------------------------------------- 나누기

    def export(self, path: str | Path) -> Path:
        """지식 꾸러미 파일로 내보낸다."""
        path = Path(path)
        if path.exists():
            path.unlink()
        self.db.commit()
        self.db.execute("VACUUM INTO ?", (str(path),))
        return path

    def import_package(self, path: str | Path) -> LearnReport:
        """다른 PC의 지식 꾸러미를 합친다. 이미 있는 문서는 건너뛴다."""
        report = LearnReport()
        other = sqlite3.connect(str(path))
        try:
            rows = other.execute("SELECT name, kind, added, origin, body FROM docs").fetchall()
        except sqlite3.DatabaseError as e:
            raise ValueError(f"지식 꾸러미 파일이 아닙니다: {e}") from e
        finally:
            other.close()
        for name, kind, added, origin, body in rows:
            self._learn(name, body, report, origin=origin, kind=kind, added=added)
        self.db.commit()
        return report
