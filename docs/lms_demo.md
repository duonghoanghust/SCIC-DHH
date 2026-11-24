# ClassTwin LMS demo flow

The current vertical slice has three views served by the same application:

- `/teacher` creates questions and publishes the active assignment to `class_scic_01`.
- `/learn` loads that assignment, lets a demo learner select a roster entry, and submit answers.
- `/` shows the ClassTwin classroom dashboard and recent LMS activity.

The API stores questions and assignments in `data/classtwin_demo.sqlite3` and appends
synthetic learner events to `data/demo_results/learning_events.jsonl`. The answer key
is not included in the learner-facing assignment response; the API scores submitted
answers. The LMS loads the active assignment when it opens, so learners who already
have the page open should refresh after a teacher publishes a new assignment.

Key endpoints:

- `GET /v1/teacher/questions`
- `POST /v1/teacher/questions`
- `POST /v1/teacher/assignments`
- `GET /v1/classes/{class_id}/assignments/active`
- `POST /v1/assignments/{assignment_id}/answers`
- `GET /v1/classes/{class_id}/students`

This is a local demo implementation. Replace the demo roster with a real class roster
and move from local SQLite to persistent managed database storage before public use.
