from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timezone
import json
import time
from uuid import uuid4
import numpy as np

from .state_store import ClassroomStateStore
from .course_store import CourseStore
from .engine import DecisionSupportEngine
from ..twin.classroom_env import ClassroomDigitalTwinEnv
from ..twin.scenarios import counterfactual_twin_rollout

app = FastAPI(
    title="ClassTwin REST API",
    description="Online Decision Support System for Educators • SCIC 2026",
    version="1.0.0"
)

import torch
from ..policies.cql import DiscreteCQL
from ..policies.action_space import PEDAGOGICAL_ACTIONS
from ..state_estimation.gru_dkt import GRUDKT

repo_root = Path(__file__).resolve().parent.parent.parent.parent

# Global singleton runtime state
store = ClassroomStateStore()
course_store = CourseStore(repo_root / "data" / "classtwin_demo.sqlite3")

# Load trained GRU-DKT Model if exists
dkt_model_path = repo_root / "output" / "models" / "gru_dkt.pt"
dkt_inst = None
if dkt_model_path.exists():
    try:
        dkt_inst = GRUDKT(num_questions=12280, d_model=64, d_hidden=128, num_layers=1, dropout=0.0)
        dkt_inst.load_state_dict(torch.load(dkt_model_path, map_location="cpu"))
        dkt_inst.eval()
    except Exception:
        dkt_inst = None

# Load trained CQL Policy (Explicit Reward) if exists
cql_model_path = repo_root / "output" / "models" / "cql_policy.pt"
cql_inst = None
if cql_model_path.exists():
    try:
        sd = torch.load(cql_model_path, map_location="cpu")
        in_dim = sd["net.0.weight"].shape[1] if "net.0.weight" in sd else 12
        cql_inst = DiscreteCQL(d_state=in_dim, num_actions=len(PEDAGOGICAL_ACTIONS), d_hidden=128)
        cql_inst.q_net.load_state_dict(sd)
        cql_inst.q_net.eval()
    except Exception as e:
        cql_inst = None

# Load trained IRL-CQL Policy (Latent MaxEnt Reward) if exists
irl_model_path = repo_root / "output" / "models" / "irl_cql_policy.pt"
irl_inst = None
if irl_model_path.exists():
    try:
        sd_irl = torch.load(irl_model_path, map_location="cpu")
        in_dim_irl = sd_irl["net.0.weight"].shape[1] if "net.0.weight" in sd_irl else 12
        irl_inst = DiscreteCQL(d_state=in_dim_irl, num_actions=len(PEDAGOGICAL_ACTIONS), d_hidden=128)
        irl_inst.q_net.load_state_dict(sd_irl)
        irl_inst.q_net.eval()
    except Exception as e:
        irl_inst = None

engine = DecisionSupportEngine(state_store=store, cql_policy=cql_inst, irl_policy=irl_inst)
demo_envs: Dict[str, ClassroomDigitalTwinEnv] = {}

class EventBatchRequest(BaseModel):
    events: List[Dict[str, Any]]
    schema_version: str = "v1.0"

class RecommendationRequest(BaseModel):
    class_id: str
    topic: str = "general"
    time_remaining_minutes: float = 45.0
    current_workload: float = 3.0
    run_simulation: bool = True
    policy_mode: str = "cql_explicit"
    telemetry: Optional[Dict[str, Any]] = Field(default=None, description="Optional client telemetry features; missing fields are automatically imputed via calibrated empirical priors")

class TeacherDecisionRequest(BaseModel):
    decision_id: str
    status: str = Field(..., description="'ACCEPTED', 'MODIFIED', or 'REJECTED'")
    executed_action: Optional[str] = None
    actual_duration_s: Optional[int] = None
    override_reason: Optional[str] = None

class SimulationRequest(BaseModel):
    class_id: str
    candidate_actions: List[str]
    duration_minutes: float = 5.0
    num_samples: int = 10

class QuestionCreateRequest(BaseModel):
    topic: str = "Đại số"
    prompt: str = Field(..., min_length=5, max_length=1000)
    options: List[str] = Field(..., min_length=2, max_length=6)
    correct_index: int = Field(..., ge=0)
    explanation: str = Field(default="", max_length=1000)

class AssignmentPublishRequest(BaseModel):
    class_id: str = "class_scic_01"
    title: str = Field(..., min_length=2, max_length=120)
    question_ids: List[str] = Field(..., min_length=1, max_length=100)

class StudentAnswerRequest(BaseModel):
    class_id: str = "class_scic_01"
    assignment_id: str
    student_id: str = Field(..., min_length=1, max_length=100)
    question_id: str
    selected_index: int = Field(..., ge=0)
    response_ms: int = Field(default=0, ge=0)
    hints_used: int = Field(default=0, ge=0)
    video_progress: float = Field(default=1.0, ge=0.0, le=1.0)

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "classtwin_api", "version": "1.0.0"}

@app.post("/v1/events:batch")
def ingest_events_batch(req: EventBatchRequest):
    accepted_ids = []
    results_dir = repo_root / "data" / "demo_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    event_log = results_dir / "learning_events.jsonl"
    for ev in req.events:
        student_id = ev.get("student_id")
        class_id = ev.get("class_id", "default_class")
        if student_id:
            event = {
                **ev,
                "event_id": ev.get("event_id") or f"evt_{uuid4().hex[:12]}",
                "event_ts_ms": ev.get("event_ts_ms") or int(time.time() * 1000),
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
            curr = store.get_or_create_student_state(class_id, student_id)
            prev_m = curr.get("mastery_estimate", 0.5)
            new_m = prev_m
            if event.get("event_type") == "quiz_answer" and "is_correct" in event:
                # Correct answers increase mastery; response latency and hints soften the gain.
                hints = max(0, int(event.get("hints_used", 0) or 0))
                response_ms = max(0, int(event.get("response_ms", 0) or 0))
                confidence = max(0.35, 1.0 - min(hints, 3) * 0.15)
                if response_ms > 90000:
                    confidence *= 0.8
                delta = 0.05 * confidence if bool(event["is_correct"]) else -0.05
                new_m = min(1.0, max(0.0, prev_m + delta))
                store.update_student_state(
                    class_id=class_id,
                    student_id=student_id,
                    hidden=curr["hidden"],
                    ts_ms=event["event_ts_ms"],
                    mastery=new_m
                )
            else:
                curr["last_ts"] = event["event_ts_ms"]
            store.record_learning_event(class_id, student_id, event)
            with event_log.open("a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")
            accepted_ids.append(event["event_id"])
    return {
        "status": "success",
        "accepted_count": len(accepted_ids),
        "accepted_ids": accepted_ids
    }

@app.get("/v1/classes/{class_id}/state")
def get_class_state(class_id: str):
    summary = store.get_class_summary(class_id)
    return summary

@app.get("/v1/classes/{class_id}/students")
def get_class_students(class_id: str):
    return {"class_id": class_id, "students": store.get_students(class_id)}

@app.get("/v1/teacher/questions")
def list_teacher_questions():
    return {"questions": course_store.list_questions()}

@app.post("/v1/teacher/questions", status_code=status.HTTP_201_CREATED)
def create_teacher_question(req: QuestionCreateRequest):
    if req.correct_index >= len(req.options):
        raise HTTPException(status_code=422, detail="correct_index phải trỏ đến một lựa chọn hiện có.")
    if any(not option.strip() for option in req.options):
        raise HTTPException(status_code=422, detail="Các lựa chọn không được để trống.")
    return course_store.create_question(req.model_dump())

@app.post("/v1/teacher/assignments", status_code=status.HTTP_201_CREATED)
def publish_teacher_assignment(req: AssignmentPublishRequest):
    try:
        return course_store.publish_assignment(req.class_id, req.title, req.question_ids)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

@app.get("/v1/classes/{class_id}/assignments/active")
def get_active_assignment(class_id: str):
    assignment = course_store.get_active_assignment(class_id, include_answers=False)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Lớp hiện chưa được giao bài.")
    return assignment

@app.post("/v1/assignments/{assignment_id}/answers")
def submit_student_answer(assignment_id: str, req: StudentAnswerRequest):
    if req.assignment_id != assignment_id:
        raise HTTPException(status_code=400, detail="assignment_id trong URL và nội dung không khớp.")
    question = course_store.get_assignment_answer(req.class_id, assignment_id, req.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy câu hỏi trong bài đang được giao.")
    if req.selected_index >= len(question["options"]):
        raise HTTPException(status_code=422, detail="Lựa chọn không hợp lệ.")
    is_correct = req.selected_index == question["correct_index"]
    event = {
        "event_id": f"answer_{uuid4().hex[:12]}",
        "event_type": "quiz_answer",
        "class_id": req.class_id,
        "assignment_id": assignment_id,
        "student_id": req.student_id,
        "question_id": req.question_id,
        "selected_index": req.selected_index,
        "is_correct": is_correct,
        "response_ms": req.response_ms,
        "hints_used": req.hints_used,
        "video_progress": req.video_progress,
        "event_ts_ms": int(time.time() * 1000),
        "source": "classtwin_lms",
    }
    ingest_events_batch(EventBatchRequest(events=[event]))
    return {"status": "accepted", "is_correct": is_correct, "explanation": question["explanation"]}

@app.get("/v1/policies/status")
def get_policies_status():
    return {
        "cql_explicit": {
            "loaded": cql_inst is not None,
            "path": str(cql_model_path),
            "description": "Offline CQL (Hàm thưởng đa mục tiêu cải tiến: Phạt CO2, Phạt dậm chân kiệt sức, Thưởng nghỉ ngơi)"
        },
        "cql_irl": {
            "loaded": irl_inst is not None,
            "path": str(irl_model_path),
            "description": "Inverse Reinforcement Learning (Học hàm thưởng ẩn MaxEnt R_psi từ quỹ đạo chuyên gia sư phạm)"
        }
    }

@app.post("/v1/recommendations")
def get_recommendation(req: RecommendationRequest):
    env_instance = demo_envs.get(req.class_id)
    if not env_instance:
        demo_init_classroom(DemoInitRequest(class_id=req.class_id))
        env_instance = demo_envs.get(req.class_id)

    rec = engine.generate_recommendation(
        class_id=req.class_id,
        topic=req.topic,
        time_remaining_minutes=req.time_remaining_minutes,
        current_workload=req.current_workload,
        run_simulation_rollout=req.run_simulation,
        env=env_instance,
        policy_mode=req.policy_mode,
        custom_telemetry=req.telemetry
    )
    return rec

@app.post("/v1/teacher-decisions")
def record_teacher_decision(req: TeacherDecisionRequest):
    dec = store.get_decision(req.decision_id)
    if not dec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision ID {req.decision_id} not found."
        )
    dec["teacher_status"] = req.status
    dec["executed_action"] = req.executed_action or dec.get("recommended_action")
    dec["actual_duration_s"] = req.actual_duration_s or dec.get("planned_duration_s")
    dec["override_reason"] = req.override_reason
    store.record_decision(req.decision_id, dec)
    return {
        "status": "recorded",
        "decision_id": req.decision_id,
        "recorded_action": dec["executed_action"]
    }

@app.post("/v1/simulations")
def simulate_counterfactuals(req: SimulationRequest):
    # Lấy chính môi trường lớp học đang chạy nếu có để phản ánh đúng thực tế
    env = demo_envs.get(req.class_id)
    if env is None:
        summary = store.get_class_summary(req.class_id)
        env = ClassroomDigitalTwinEnv(cohort_size=summary.get("n_enrolled", 53), use_real_data=True, seed=42, dkt_model=dkt_inst)
        env.reset()

    results = []
    for act in req.candidate_actions:
        stats = counterfactual_twin_rollout(
            base_env=env,
            candidate_action=act,
            duration_minutes=req.duration_minutes,
            num_mc_samples=req.num_samples
        )
        results.append(stats)

    return {
        "class_id": req.class_id,
        "simulations": results
    }

class DemoInitRequest(BaseModel):
    class_id: str = "class_scic_01"
    cohort_size: int = 48
    seed: Optional[int] = 42
    duration_minutes: float = 180.0

class DemoStepRequest(BaseModel):
    class_id: str = "class_scic_01"
    action: str = "lecture"
    duration_minutes: float = 5.0

@app.post("/v1/demo/init-classroom")
def demo_init_classroom(req: DemoInitRequest):
    # Khởi tạo Digital Twin thực tế từ ASSISTments, In-Gauge, SocioPatterns và GRU-DKT Neural Estimator
    env = ClassroomDigitalTwinEnv(
        cohort_size=req.cohort_size,
        episode_duration_minutes=req.duration_minutes,
        use_real_data=True,
        seed=req.seed,
        dkt_model=dkt_inst
    )
    env.reset()
    demo_envs[req.class_id] = env

    store._class_metadata[req.class_id] = {
        "n_enrolled": len(env.students),
        "last_action": "lecture",
        "cumulative_workload": 0.0
    }

    students_payload = []
    for idx, s in enumerate(env.students):
        student_id = s.student_id or f"u10{idx:03d}"
        hidden_vec = s.hidden_state[-1, 0].cpu().numpy() if s.hidden_state is not None else np.zeros(128, dtype=np.float32)
        store.update_student_state(
            class_id=req.class_id,
            student_id=student_id,
            hidden=hidden_vec,
            ts_ms=0,
            mastery=float(s.mastery)
        )
        row = (idx // 8) + 1
        col = (idx % 8) + 1
        students_payload.append({
            "id": student_id,
            "row": row,
            "col": col,
            "mastery": round(float(s.mastery), 3),
            "attention": round(float(s.attention), 3),
            "fatigue": round(float(s.fatigue), 3),
            "isWeak": s.mastery < 0.40,
            "recentLogs": [
                {"q": f"q{1000 + idx}", "ans": "Correct (b)" if s.mastery > 0.4 else "Incorrect (a)", "elapsed": "22s"},
                {"q": f"q{2000 + idx}", "ans": "Correct (c)" if s.mastery > 0.55 else "Incorrect (d)", "elapsed": "34s"}
            ]
        })

    summary = store.get_class_summary(req.class_id, default_enrolled=len(env.students))
    return {
        "status": "initialized",
        "class_id": req.class_id,
        "students": students_payload,
        "telemetry": {
            "meanMastery": summary["mean_mastery"],
            "q25Mastery": summary["q25_mastery"],
            "q75Mastery": summary["q75_mastery"],
            "meanAttention": float(np.mean([s.attention for s in env.students])),
            "meanFatigue": float(np.mean([s.fatigue for s in env.students])),
            "edaStress": float(np.mean([s.eda_stress for s in env.students])),
            "hrStrain": float(np.mean([s.hr_strain for s in env.students])),
            "accRestlessness": float(np.mean([s.acc_restlessness for s in env.students])),
            "peerClustering": float(env.peer_metrics.get("clustering_coef", 0.38)),
            "vleActivity": float(env.oulad_priors.get("vle_click_intensity", 0.45)),
            "stepErrorRate": float(np.mean([s.step_error_rate for s in env.students])),
            "timeRemainingMinutes": max(0.0, env.episode_duration_minutes - env.time_elapsed_minutes),
            "timeElapsedMinutes": float(env.time_elapsed_minutes),
            "workload": env.cumulative_workload,
            "co2": env.context_env["co2_ppm"],
            "temp": env.context_env["temp_c"],
            "noise": env.context_env["noise_db"],
            "currentAction": "lecture"
        }
    }

@app.post("/v1/demo/step-classroom")
def demo_step_classroom(req: DemoStepRequest):
    env = demo_envs.get(req.class_id)
    if not env:
        init_res = demo_init_classroom(DemoInitRequest(class_id=req.class_id))
        env = demo_envs[req.class_id]

    _, reward, done, info = env.step(action=req.action, duration_minutes=req.duration_minutes)

    students_payload = []
    for idx, s in enumerate(env.students):
        hidden_vec = s.hidden_state[-1, 0].cpu().numpy() if s.hidden_state is not None else np.zeros(128, dtype=np.float32)
        store.update_student_state(
            class_id=req.class_id,
            student_id=s.student_id,
            hidden=hidden_vec,
            ts_ms=int(env.time_elapsed_minutes * 60 * 1000),
            mastery=float(s.mastery)
        )
        row = (idx // 8) + 1
        col = (idx % 8) + 1
        students_payload.append({
            "id": s.student_id,
            "row": row,
            "col": col,
            "mastery": round(float(s.mastery), 3),
            "attention": round(float(s.attention), 3),
            "fatigue": round(float(s.fatigue), 3),
            "isWeak": s.mastery < 0.40,
            "recentLogs": [
                {"q": f"q{3000 + idx}", "ans": "Correct (b)" if s.mastery > 0.45 else "Incorrect (a)", "elapsed": "19s"},
                {"q": f"q{4000 + idx}", "ans": "Correct (d)" if s.mastery > 0.6 else "Incorrect (b)", "elapsed": "28s"}
            ]
        })

    summary = store.get_class_summary(req.class_id, default_enrolled=len(env.students))
    time_rem = max(0.0, round(float(env.episode_duration_minutes - env.time_elapsed_minutes), 1))
    is_completed = bool(time_rem <= 0.0)

    return {
        "status": "stepped",
        "action_executed": req.action,
        "reward": float(reward),
        "is_completed": is_completed,
        "students": students_payload,
        "telemetry": {
            "meanMastery": round(float(summary["mean_mastery"]), 3),
            "q25Mastery": round(float(summary["q25_mastery"]), 3),
            "q75Mastery": round(float(summary["q75_mastery"]), 3),
            "meanAttention": round(float(np.mean([s.attention for s in env.students])), 3),
            "meanFatigue": round(float(np.mean([s.fatigue for s in env.students])), 3),
            "edaStress": round(float(np.mean([s.eda_stress for s in env.students])), 3),
            "hrStrain": round(float(np.mean([s.hr_strain for s in env.students])), 3),
            "accRestlessness": round(float(np.mean([s.acc_restlessness for s in env.students])), 3),
            "peerClustering": round(float(env.peer_metrics.get("clustering_coef", 0.38)), 3),
            "vleActivity": round(float(env.oulad_priors.get("vle_click_intensity", 0.45)), 3),
            "stepErrorRate": round(float(np.mean([s.step_error_rate for s in env.students])), 3),
            "timeRemainingMinutes": time_rem,
            "timeElapsedMinutes": round(float(env.time_elapsed_minutes), 1),
            "workload": round(float(env.cumulative_workload), 1),
            "co2": round(float(env.context_env["co2_ppm"]), 0),
            "temp": round(float(env.context_env["temp_c"]), 1),
            "noise": round(float(env.context_env["noise_db"]), 1),
            "currentAction": req.action,
            "isCompleted": is_completed
        }
    }

# Mount Web Dashboard (Ưu tiên React Frontend Build, fallback static web)
repo_root = Path(__file__).resolve().parent.parent.parent.parent
react_dist = repo_root / "frontend" / "dist"
legacy_web_dir = Path(__file__).resolve().parent.parent / "web"

if react_dist.exists() and (react_dist / "index.html").exists():
    if (react_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(react_dist / "assets")), name="assets")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(str(react_dist / "index.html"))

    if (react_dist / "favicon.svg").exists():
        @app.get("/favicon.svg")
        def serve_favicon():
            return FileResponse(str(react_dist / "favicon.svg"))

    @app.get("/{spa_path:path}")
    def serve_spa_route(spa_path: str):
        if spa_path.startswith("v1/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        return FileResponse(str(react_dist / "index.html"))
elif legacy_web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(legacy_web_dir)), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(str(legacy_web_dir / "index.html"))


