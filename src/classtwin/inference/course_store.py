"""Small SQLite-backed question bank and assignment store for the LMS demo."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class CourseStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_index INTEGER NOT NULL,
                    explanation TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    class_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignment_questions (
                    assignment_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (assignment_id, question_id),
                    FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_active_assignment
                    ON assignments(class_id, status, created_at);
            """)
            has_questions = db.execute("SELECT 1 FROM questions LIMIT 1").fetchone()
            if not has_questions:
                self._seed_demo(db)

    @staticmethod
    def _seed_demo(db):
        now = datetime.now(timezone.utc).isoformat()
        examples = [
            ("demo-algebra-01", "Đại số", "Nghiệm của phương trình 2x + 6 = 14 là gì?", ["x = 3", "x = 4", "x = 5", "x = 10"], 1, "Trừ 6 hai vế được 2x = 8, vậy x = 4."),
            ("demo-algebra-02", "Đại số", "Rút gọn 3(a + 2) − a.", ["2a + 6", "3a + 2", "2a + 2", "a + 6"], 0, "Phân phối 3 rồi thu gọn: 3a + 6 − a = 2a + 6."),
            ("demo-algebra-03", "Đại số", "20% của 150 bằng bao nhiêu?", ["20", "25", "30", "35"], 2, "20% = 0,2; 0,2 × 150 = 30."),
        ]
        for question_id, topic, prompt, options, correct_index, explanation in examples:
            db.execute(
                "INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (question_id, topic, prompt, json.dumps(options, ensure_ascii=False), correct_index, explanation, now),
            )
        assignment_id = "assignment-algebra-demo"
        db.execute(
            "INSERT INTO assignments VALUES (?, ?, ?, ?, ?)",
            (assignment_id, "class_scic_01", "Bài demo Đại số", "active", now),
        )
        db.executemany(
            "INSERT INTO assignment_questions VALUES (?, ?, ?)",
            [(assignment_id, row[0], index) for index, row in enumerate(examples)],
        )

    @staticmethod
    def _question(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "topic": row["topic"], "prompt": row["prompt"],
            "options": json.loads(row["options_json"]),
            "correct_index": row["correct_index"], "explanation": row["explanation"],
            "created_at": row["created_at"],
        }

    def list_questions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [self._question(row) for row in db.execute("SELECT * FROM questions ORDER BY created_at, id")]

    def create_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_id = f"question-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (question_id, payload["topic"], payload["prompt"], json.dumps(payload["options"], ensure_ascii=False), payload["correct_index"], payload["explanation"], now),
            )
            row = db.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
            return self._question(row)

    def publish_assignment(self, class_id: str, title: str, question_ids: list[str]) -> dict[str, Any]:
        assignment_id = f"assignment-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            found = {row[0] for row in db.execute(
                f"SELECT id FROM questions WHERE id IN ({','.join('?' for _ in question_ids)})", question_ids
            )}
            if len(found) != len(set(question_ids)):
                raise ValueError("Một hoặc nhiều câu hỏi không tồn tại.")
            db.execute("UPDATE assignments SET status = 'archived' WHERE class_id = ? AND status = 'active'", (class_id,))
            db.execute("INSERT INTO assignments VALUES (?, ?, ?, 'active', ?)", (assignment_id, class_id, title, now))
            db.executemany(
                "INSERT INTO assignment_questions VALUES (?, ?, ?)",
                [(assignment_id, question_id, position) for position, question_id in enumerate(question_ids)],
            )
        return self.get_active_assignment(class_id, include_answers=True)

    def get_active_assignment(self, class_id: str, include_answers: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM assignments WHERE class_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (class_id,),
            ).fetchone()
            if row is None:
                return None
            questions = db.execute(
                "SELECT q.* FROM questions q JOIN assignment_questions aq ON q.id = aq.question_id "
                "WHERE aq.assignment_id = ? ORDER BY aq.position",
                (row["id"],),
            ).fetchall()
            payload = {
                "id": row["id"], "class_id": row["class_id"], "title": row["title"],
                "status": row["status"], "created_at": row["created_at"],
                "questions": [self._question(question) for question in questions],
            }
            if not include_answers:
                for question in payload["questions"]:
                    question.pop("correct_index", None)
                    question.pop("explanation", None)
            return payload

    def get_assignment_answer(self, class_id: str, assignment_id: str, question_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT q.* FROM questions q "
                "JOIN assignment_questions aq ON q.id = aq.question_id "
                "JOIN assignments a ON aq.assignment_id = a.id "
                "WHERE a.id = ? AND a.class_id = ? AND a.status = 'active' AND q.id = ?",
                (assignment_id, class_id, question_id),
            ).fetchone()
            return self._question(row) if row else None
