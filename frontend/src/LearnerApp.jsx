import { useEffect, useRef, useState } from 'react';
import './LearnerApp.css';

const CLASS_ID = 'class_scic_01';

export default function LearnerApp() {
  const [learners, setLearners] = useState([]);
  const [assignment, setAssignment] = useState(null);
  const [studentId, setStudentId] = useState('');
  const [questionIndex, setQuestionIndex] = useState(0);
  const [choice, setChoice] = useState(null);
  const [hints, setHints] = useState(0);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const questionStartedAt = useRef(Date.now());
  const lastOpenedRef = useRef('');
  const question = assignment?.questions?.[questionIndex];

  useEffect(() => {
    let cancelled = false;
    const loadLearners = async () => {
      try {
        let response = await fetch(`/v1/classes/${CLASS_ID}/students`);
        let data = response.ok ? await response.json() : { students: [] };
        if (!data.students?.length) {
          await fetch('/v1/demo/init-classroom', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ class_id: CLASS_ID, cohort_size: 48, seed: 42, duration_minutes: 180 })
          });
          response = await fetch(`/v1/classes/${CLASS_ID}/students`);
          data = response.ok ? await response.json() : { students: [] };
        }
        if (!cancelled) {
          const cohort = data.students || [];
          setLearners(cohort);
          setStudentId(cohort[0]?.id || 'demo_learner_01');
          const assignmentResponse = await fetch(`/v1/classes/${CLASS_ID}/assignments/active`);
          if (assignmentResponse.ok) setAssignment(await assignmentResponse.json());
          else setError('Lớp chưa được giáo viên giao bài. Hãy mở trang giáo viên để tạo và giao bài.');
        }
      } catch {
        if (!cancelled) setError('Không kết nối được backend. Hãy chạy ClassTwin API rồi tải lại trang.');
      }
    };
    loadLearners();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!assignment || !question || !studentId) return;
    const openKey = `${assignment.id}:${question.id}:${studentId}`;
    if (lastOpenedRef.current === openKey) return;
    lastOpenedRef.current = openKey;
    questionStartedAt.current = Date.now();
    fetch('/v1/events:batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: [{
        event_type: 'question_open', class_id: CLASS_ID, assignment_id: assignment.id,
        student_id: studentId, question_id: question.id, event_ts_ms: Date.now(),
        source: 'classtwin_lms'
      }] })
    }).catch(reason => console.warn('Could not record opened question:', reason));
  }, [assignment, question, studentId]);

  const submitAnswer = async () => {
    if (choice === null || busy || result) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/v1/assignments/${assignment.id}/answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          assignment_id: assignment.id,
          class_id: CLASS_ID,
          student_id: studentId,
          question_id: question.id,
          selected_index: choice,
          response_ms: Date.now() - questionStartedAt.current,
          video_progress: 1,
          hints_used: hints
        })
      });
      if (!response.ok) throw new Error('API từ chối sự kiện học tập.');
      setResult(await response.json());
    } catch (submitError) {
      setError(`${submitError.message} Hãy kiểm tra API đang chạy tại cổng 8000.`);
    } finally {
      setBusy(false);
    }
  };

  const nextQuestion = () => {
    setQuestionIndex(index => (index + 1) % assignment.questions.length);
    setChoice(null);
    setHints(0);
    setResult(null);
    questionStartedAt.current = Date.now();
  };

  return (
    <div className="learner-page">
      <header className="learner-header">
        <a className="learner-brand" href="/learn"><span>CT</span><div>ClassTwin <small>LEARNING SPACE</small></div></a>
        <nav><a href="/teacher">Trang giáo viên ↗</a><a href="/">Digital Twin</a></nav>
      </header>
      <main className="learner-layout">
        <section className="learner-welcome">
          <div className="learner-eyebrow">LỚP HỌC SỐ · TOÁN ỨNG DỤNG</div>
          <h1>Học theo nhịp độ<br /><em>của bạn.</em></h1>
          <p>Hoàn thành bài học và câu hỏi. ClassTwin ghi nhận tiến độ để giảng viên hiểu lớp học tốt hơn.</p>
          <label className="learner-select-label" htmlFor="learner-select">Học viên demo</label>
          <select id="learner-select" value={studentId} onChange={event => setStudentId(event.target.value)}>
            {learners.map((learner, index) => <option value={learner.id} key={learner.id}>Học viên {String(index + 1).padStart(2, '0')}</option>)}
            {!learners.length && <option value="demo_learner_01">Học viên demo</option>}
          </select>
          <div className="learner-progress"><div><span>{assignment?.title || 'BÀI TẬP'}</span><strong>{result ? 'ĐÃ NỘP' : 'ĐANG HỌC'}</strong></div><div className="progress-track"><i style={{ width: result ? `${Math.round(((questionIndex + 1) / (assignment?.questions?.length || 1)) * 100)}%` : '12%' }} /></div><small>Bài {questionIndex + 1} / {assignment?.questions?.length || '—'} · chọn tên học viên demo</small></div>
          <div className="learner-note"><span>✦</span><p><b>Learning twin đang hoạt động</b><br />Thời gian trả lời, kết quả và gợi ý được gửi đến ClassTwin.</p></div>
        </section>

        <section className="lesson-card">
          <div className="lesson-topline"><span>CHƯƠNG 01 <b>—</b> {question?.topic?.toUpperCase() || 'BÀI HỌC'}</span><span>{String(questionIndex + 1).padStart(2, '0')} / {String(assignment?.questions?.length || 0).padStart(2, '0')}</span></div>
          <div className="lesson-video"><div className="video-orbit orbit-one"/><div className="video-orbit orbit-two"/><div className="video-play">▶</div><span>MICRO LESSON · 02:14</span><div className="video-caption">Một phương trình,<br />một bước giải.</div></div>
          <div className="lesson-content">
            {question ? <>
              <div className="lesson-heading"><div><small>{assignment.title.toUpperCase()}</small><h2>Câu {questionIndex + 1}</h2></div><span className="lesson-tag">● Đang học</span></div>
              <p className="question-prompt">{question.prompt}</p>
              <div className="answer-list">
                {question.options.map((answer, index) => {
                  const isCorrectChoice = result?.is_correct && choice === index;
                  const isWrongChoice = result && choice === index && !result.is_correct;
                  return <button key={answer} disabled={Boolean(result)} className={`answer-option ${choice === index ? 'selected' : ''} ${isCorrectChoice ? 'correct' : ''} ${isWrongChoice ? 'incorrect' : ''}`} onClick={() => setChoice(index)}><span>{String.fromCharCode(65 + index)}</span>{answer}<i>{isCorrectChoice ? '✓' : isWrongChoice ? '×' : ''}</i></button>;
                })}
              </div>
            </> : <div className="assignment-empty">{error || 'Đang tải bài được giao…'}</div>}
            {result && <div className={`answer-feedback ${result.is_correct ? 'positive' : 'try-again'}`}><b>{result.is_correct ? 'Chính xác!' : 'Mình cùng xem lại nhé.'}</b><span>{result.explanation}</span></div>}
            {error && <div className="learner-error">{error}</div>}
            <div className="lesson-actions">
              <button className="hint-button" onClick={() => setHints(count => count + 1)} disabled={Boolean(result) || !question}>Gợi ý <span>({hints})</span></button>
              {!result ? <button className="submit-answer" onClick={submitAnswer} disabled={choice === null || busy || !question}>{busy ? 'Đang gửi…' : 'Kiểm tra đáp án'} <span>→</span></button> : <button className="submit-answer" onClick={nextQuestion}>Bài tiếp theo <span>→</span></button>}
            </div>
          </div>
        </section>
      </main>
      <footer className="learner-footer"><span>CLASSTWIN <b>·</b> DIGITAL TWIN FOR LEARNING</span><span>Dữ liệu demo · không dùng thông tin cá nhân thật</span></footer>
    </div>
  );
}
