# ClassTwin LMS demo results

The API appends submitted learner events to `learning_events.jsonl` in this folder.
Each line is one synthetic demo event from the `/learn` experience. The file is
created automatically when the first event is submitted.

The question bank and active demo assignment are stored in
`data/classtwin_demo.sqlite3` and survive local API restarts. That SQLite file is
for local development; a public multi-user deployment should use persistent managed
database storage. Keep real student names, email addresses, and other identifying
information out of demo sessions.
