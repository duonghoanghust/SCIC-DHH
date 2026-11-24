import { useEffect, useState } from 'react';
import './TeacherPortal.css';

const emptyDraft = { topic: 'Đại số', prompt: '', options: ['', '', '', ''], correct_index: 0, explanation: '' };

export default function TeacherPortal() {
  const [questions, setQuestions] = useState([]);
  const [selected, setSelected] = useState([]);
  const [draft, setDraft] = useState(emptyDraft);
  const [title, setTitle] = useState('Bài tập mới');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const loadQuestions = async () => {
    const response = await fetch('/v1/teacher/questions');
    if (!response.ok) throw new Error('Không tải được ngân hàng câu hỏi.');
    const data = await response.json();
    setQuestions(data.questions || []);
  };

  useEffect(() => {
    loadQuestions().catch(reason => setError(reason.message));
  }, []);

  const saveQuestion = async event => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/v1/teacher/questions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...draft, options: draft.options.map(option => option.trim()) })
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || 'Không lưu được câu hỏi.');
      }
      const question = await response.json();
      setQuestions(current => [...current, question]);
      setSelected(current => [...new Set([...current, question.id])]);
      setDraft(emptyDraft);
      setMessage('Đã lưu câu hỏi vào ngân hàng.');
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const publishAssignment = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/v1/teacher/assignments', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ class_id: 'class_scic_01', title, question_ids: selected })
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || 'Không giao được bài.');
      }
      const assignment = await response.json();
      setMessage(`Đã giao “${assignment.title}” gồm ${assignment.questions.length} câu. Học sinh có thể mở LMS để làm bài.`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const updateOption = (index, value) => setDraft(current => ({ ...current, options: current.options.map((option, optionIndex) => optionIndex === index ? value : option) }));

  return (
    <div className="teacher-page">
      <header className="teacher-header">
        <a href="/teacher" className="teacher-brand"><span>CT</span><div>ClassTwin <small>TEACHER WORKSPACE</small></div></a>
        <nav><a href="/">Digital Twin</a><a href="/learn">Mở LMS ↗</a></nav>
      </header>
      <main className="teacher-shell">
        <div className="teacher-intro"><div><div className="teacher-eyebrow">LỚP SCIC · CLASS_SCIC_01</div><h1>Soạn & giao bài</h1><p>Tạo câu hỏi, chọn nội dung và gửi bài tập đến không gian học tập của học sinh.</p></div><div className="teacher-live"><i/> API CLASSROOM ONLINE</div></div>
        <div className="teacher-columns">
          <section className="teacher-panel question-authoring">
            <div className="teacher-panel-title"><span className="step-number">01</span><div><h2>Tạo câu hỏi</h2><p>Câu hỏi được lưu vào ngân hàng để dùng lại.</p></div></div>
            <form onSubmit={saveQuestion}>
              <label>Chủ đề<input value={draft.topic} onChange={event => setDraft(current => ({ ...current, topic: event.target.value }))} required /></label>
              <label>Nội dung câu hỏi<textarea value={draft.prompt} onChange={event => setDraft(current => ({ ...current, prompt: event.target.value }))} placeholder="Nhập nội dung câu hỏi…" required minLength={5} /></label>
              <div className="options-title"><span>Các lựa chọn</span><small>Chọn đáp án đúng</small></div>
              <div className="teacher-options">
                {draft.options.map((option, index) => <div className="teacher-option-row" key={index}><input type="radio" name="correct-option" checked={draft.correct_index === index} onChange={() => setDraft(current => ({ ...current, correct_index: index }))} aria-label={`Chọn lựa chọn ${index + 1} là đáp án đúng`} /><span>{String.fromCharCode(65 + index)}</span><input value={option} onChange={event => updateOption(index, event.target.value)} placeholder={`Lựa chọn ${String.fromCharCode(65 + index)}`} required /></div>)}
              </div>
              <label>Giải thích đáp án<input value={draft.explanation} onChange={event => setDraft(current => ({ ...current, explanation: event.target.value }))} placeholder="Giải thích ngắn cho học sinh" /></label>
              <button className="teacher-primary" disabled={busy}>{busy ? 'Đang lưu…' : 'Lưu câu hỏi'} <span>→</span></button>
            </form>
          </section>

          <section className="teacher-panel assignment-builder">
            <div className="teacher-panel-title"><span className="step-number">02</span><div><h2>Chọn câu hỏi & giao bài</h2><p>Học sinh sẽ nhận bài đang hoạt động trong LMS.</p></div></div>
            <label>Tên bài tập<input value={title} onChange={event => setTitle(event.target.value)} /></label>
            <div className="bank-heading"><span>NGÂN HÀNG CÂU HỎI</span><span>{selected.length} ĐÃ CHỌN</span></div>
            <div className="question-bank">
              {questions.map(question => <label className={`bank-question ${selected.includes(question.id) ? 'checked' : ''}`} key={question.id}>
                <input type="checkbox" checked={selected.includes(question.id)} onChange={event => setSelected(current => event.target.checked ? [...current, question.id] : current.filter(id => id !== question.id))} />
                <span><small>{question.topic}</small><b>{question.prompt}</b><em>{question.options.length} lựa chọn</em></span>
              </label>)}
              {!questions.length && <p className="bank-empty">Chưa có câu hỏi. Hãy tạo câu hỏi đầu tiên.</p>}
            </div>
            {error && <div className="teacher-alert error">{error}</div>}
            {message && <div className="teacher-alert success">{message} <a href="/learn">Mở LMS →</a></div>}
            <button className="teacher-publish" onClick={publishAssignment} disabled={busy || !selected.length || !title.trim()}><span>Giao bài cho lớp</span><b>↗</b></button>
            <div className="teacher-footnote">Học viên demo chọn tên từ danh sách lớp. Câu trả lời được chấm ở backend và gửi đến ClassTwin.</div>
          </section>
        </div>
      </main>
    </div>
  );
}
