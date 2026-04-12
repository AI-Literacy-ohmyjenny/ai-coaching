import os
import json
import threading
import traceback
import logging
from datetime import datetime
from uuid import uuid4

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

# -----------------------------------------------------------------------
# 📋 로깅 설정
# -----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# -----------------------------------------------------------------------
# 🗄️ Supabase 설정
# Vercel 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
# -----------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# 교과 성취 기준 파일 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STANDARD_PATH = os.path.join(BASE_DIR, "S1_초등_5_국어_TXT_012230.json")

# -----------------------------------------------------------------------
# 🔒 로컬 파일 저장용 Lock (로컬 개발 fallback)
# -----------------------------------------------------------------------
_schema_lock = threading.Lock()


# -----------------------------------------------------------------------
# 📦 Supabase REST API 헬퍼
# -----------------------------------------------------------------------
def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _supabase_insert(essay_data: dict) -> dict:
    """essays 테이블에 새 레코드 삽입"""
    url = f"{SUPABASE_URL}/rest/v1/essays"
    payload = {
        "process_id": essay_data["process"]["process_id"],
        "data": essay_data,  # JSONB 컬럼에 전체 스키마 저장
    }
    resp = requests.post(url, headers=_supabase_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _supabase_select_all() -> list:
    """essays 테이블 전체 조회 (최신순)"""
    url = f"{SUPABASE_URL}/rest/v1/essays?order=created_at.desc&select=data"
    resp = requests.get(url, headers=_supabase_headers(), timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    return [row["data"] for row in rows if row.get("data")]


def _supabase_update(process_id: str, essay_data: dict) -> None:
    """process_id로 특정 레코드 업데이트"""
    url = f"{SUPABASE_URL}/rest/v1/essays?process_id=eq.{process_id}"
    payload = {"data": essay_data}
    resp = requests.patch(url, headers=_supabase_headers(), json=payload, timeout=30)
    resp.raise_for_status()


# -----------------------------------------------------------------------
# 📦 로컬 파일 fallback 헬퍼
# -----------------------------------------------------------------------
def get_schema_path() -> str:
    primary = os.path.join(BASE_DIR, "schema.json")
    try:
        with open(primary, "a", encoding="utf-8"):
            pass
        return primary
    except OSError:
        return "/tmp/schema.json"


def _read_essays_locked(out_path: str) -> list:
    if not os.path.exists(out_path):
        return []
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except Exception as e:
        logger.error(f"schema.json 읽기 실패: {e}")
        return []


def _write_essays_locked(out_path: str, essays: list) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(essays, f, ensure_ascii=False, indent=2)


def _append_essay_safe(schema: dict) -> None:
    """
    Supabase가 설정돼 있으면 Supabase에 저장,
    아니면 로컬 schema.json에 저장 (개발 환경 fallback).
    """
    if _is_supabase_configured():
        _supabase_insert(schema)
        logger.info(f"[Supabase 저장] process_id={schema['process']['process_id']}")
    else:
        out_path = get_schema_path()
        with _schema_lock:
            essays = _read_essays_locked(out_path)
            essays.append(schema)
            _write_essays_locked(out_path, essays)
        logger.info(f"[로컬 저장] process_id={schema['process']['process_id']} → {out_path}")


app = Flask(__name__)
CORS(app)


def load_achievement_standard_and_desc(standard_json_path: str):
    with open(standard_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    standards = data.get("source_data_info", {}).get("2015_achievement_standard", [])
    achievement_2015 = " ".join(standards) if standards else ""
    text_description = data.get("learning_data_info", {}).get("text_description", "")
    return achievement_2015, text_description


def _strip_json_markdown(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


def call_openai_for_feedback(student_text: str, achievement_2015: str, text_description: str):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    system_prompt = (
        "당신은 초등학교 5학년 국어 수업을 돕는 전문적인 AI 보조교사입니다. "
        "다음 성취 기준을 정확히 이해하고 학생 글을 평가하세요.\n\n"
        f"- 성취 기준: {achievement_2015}\n\n"
        "출력은 반드시 아래 JSON 형식의 한 개 객체로만 답하세요. "
        "절대 마크다운 코드블록(```json)으로 감싸지 마세요.\n"
        "{\n"
        '  \"feedback\": \"3단 구성 피드백 (각 문단 최소 2문장, 전체 6문장 이상):\\n'
        '    ① 따뜻한 공감과 격려 (2문장 이상)\\n'
        '    ② 성취기준 기반의 구체적인 어휘/문법 조언 (2문장 이상)\\n'
        '    ③ 아이의 생각을 넓혀주는 심화 질문 (2문장 이상)\",\n'
        '  \"achievement_explanation\": \"성취기준 [6국01-07]을 인용하며 왜 이런 피드백이 나왔는지 교사가 납득할 수 있는 상세한 근거 설명\",\n'
        '  \"revised_text\": \"학생 원문을 더 매끄럽고 수준 높게 다듬은 AI 추천 수정본 (전체 텍스트)\",\n'
        '  \"scores\": {\n'
        '    \"vocabulary\": 1-5 정수,\n'
        '    \"grammar\": 1-5 정수,\n'
        '    \"logic\": 1-5 정수,\n'
        '    \"empathy\": 1-5 정수\n'
        "  }\n"
        "}\n"
    )

    user_prompt = (
        "지문의 주제와 성취 기준을 참고하여 학생 글을 평가하세요.\n\n"
        f"지문 설명: {text_description}\n\n"
        f"학생 글:\n\"\"\"\n{student_text}\n\"\"\"\n\n"
        "요구사항:\n"
        "1. feedback은 반드시 3단 구성으로 작성 (각 문단 최소 2문장, 전체 6문장 이상)\n"
        "2. achievement_explanation은 성취기준을 명시적으로 인용하며 상세히 설명\n"
        "3. revised_text는 학생 원문의 의미를 유지하면서 더 매끄럽고 수준 높게 다듬은 전체 텍스트\n"
        "4. 반드시 순수 JSON만 출력할 것. ```json 코드블록 사용 금지.\n"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    resp = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    raw_content = data["choices"][0]["message"]["content"].strip()

    content = _strip_json_markdown(raw_content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(
            "OpenAI 응답 JSON 파싱 실패\n"
            f"  파싱 오류: {e}\n"
            f"  원본 응답(첫 500자): {raw_content[:500]}"
        )
        raise RuntimeError(f"모델 응답을 JSON으로 파싱하지 못했습니다: {e}") from e

    feedback_text = parsed.get("feedback", "").strip()
    achievement_explanation = parsed.get("achievement_explanation", "").strip()
    revised_text = parsed.get("revised_text", "").strip()
    scores = parsed.get("scores", {})
    return feedback_text, achievement_explanation, revised_text, scores


def build_schema(
    student_text: str,
    feedback_text: str,
    achievement_explanation: str,
    revised_text: str,
    scores: dict,
    achievement_2015: str,
    text_description: str,
):
    now_iso = datetime.utcnow().isoformat() + "Z"
    process_id = f"proc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    essay_id = f"ESSAY_{uuid4().hex[:8]}"

    schema = {
        "metadata": {
            "schema_version": "1.0.0",
            "created_at": now_iso,
            "updated_at": now_iso,
            "language": "ko",
            "grade": "초등학교 5학년",
            "semester": "2학기",
            "subject": "국어",
        },
        "lesson_context": {
            "lesson_id": "S1_초등_5_국어_TXT_012230",
            "text_title": text_description,
            "text_description": text_description,
            "achievement_standards": {"2015": [achievement_2015]},
        },
        "process": {
            "process_id": process_id,
            "status": "ai_drafted",
            "current_step": 3,
        },
        "student_essay": {
            "essay_id": essay_id,
            "prompt": "지문을 읽고, 자신과 생각이나 처지가 다른 사람과 어떻게 대화하면 좋을지 느낀 점을 써 보세요.",
            "student_answer": student_text,
            "submitted_at": now_iso,
        },
        "evaluation": {
            "dimensions": {
                "vocabulary": {"scale": 5, "value": int(scores.get("vocabulary", 3)), "comment": ""},
                "grammar":    {"scale": 5, "value": int(scores.get("grammar", 3)),    "comment": ""},
                "logic":      {"scale": 5, "value": int(scores.get("logic", 3)),      "comment": ""},
                "empathy":    {"scale": 5, "value": int(scores.get("empathy", 4)),    "comment": ""},
            }
        },
        "ai_feedback": {
            "model_name": "gpt-4o-mini",
            "created_at": now_iso,
            "prompt_template_id": "empathetic_feedback_v3",
            "ai_draft_feedback": feedback_text,
            "ai_feedback_type": "3단 구성 공감적 피드백",
            "ai_feedback_tags": ["공감", "경청", "존중", "긍정 강화", "성취기준 기반 조언", "심화 질문"],
            "achievement_explanation": achievement_explanation,
            "revised_text": revised_text,
        },
    }
    return schema


# -----------------------------------------------------------------------
# 라우트
# -----------------------------------------------------------------------

@app.route("/admin")
def admin():
    return send_from_directory(".", "admin.html")



@app.get("/api/essays")
def get_essays():
    """DB(Supabase) 또는 로컬 파일에서 모든 학생 글 데이터를 반환"""
    try:
        if _is_supabase_configured():
            essays = _supabase_select_all()
        else:
            out_path = get_schema_path()
            with _schema_lock:
                essays = _read_essays_locked(out_path)
        return jsonify({"essays": essays})
    except Exception as e:
        logger.error(f"GET /api/essays 오류: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e), "essays": []}), 500


@app.post("/api/essays/approve")
def approve_essay():
    """교사가 최종 승인한 피드백을 저장하고 status를 completed로 변경"""
    try:
        data = request.get_json(force=True)
        process_id = data.get("process_id")
        final_feedback = data.get("final_feedback", "").strip()

        if not process_id:
            return jsonify({"error": "process_id가 필요합니다."}), 400
        if not final_feedback:
            return jsonify({"error": "최종 피드백이 비어있습니다."}), 400

        now_iso = datetime.utcnow().isoformat() + "Z"

        if _is_supabase_configured():
            # Supabase에서 해당 레코드 조회
            url = f"{SUPABASE_URL}/rest/v1/essays?process_id=eq.{process_id}&select=data"
            resp = requests.get(url, headers=_supabase_headers(), timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404

            essay = rows[0]["data"]
            _apply_approval(essay, final_feedback, data.get("lesson_feedback", ""), now_iso)
            _supabase_update(process_id, essay)
        else:
            out_path = get_schema_path()
            with _schema_lock:
                essays = _read_essays_locked(out_path)
                essay_index = next(
                    (i for i, e in enumerate(essays)
                     if e.get("process", {}).get("process_id") == process_id),
                    None
                )
                if essay_index is None:
                    return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404
                _apply_approval(essays[essay_index], final_feedback, data.get("lesson_feedback", ""), now_iso)
                _write_essays_locked(out_path, essays)

        logger.info(f"[승인 완료] process_id={process_id}")
        return jsonify({"success": True, "message": "승인 완료", "process_id": process_id, "status": "completed"})

    except Exception as e:
        logger.error(f"POST /api/essays/approve 오류: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


def _apply_approval(essay: dict, final_feedback: str, lesson_feedback: str, now_iso: str) -> None:
    """essay 딕셔너리에 승인 데이터를 in-place로 적용"""
    essay["process"]["status"] = "completed"
    essay["process"]["current_step"] = 5
    essay["metadata"]["updated_at"] = now_iso

    if "teacher_correction" not in essay:
        essay["teacher_correction"] = {}
    essay["teacher_correction"].update({
        "teacher_id": "t_001",
        "corrected_at": now_iso,
        "teacher_final_feedback": final_feedback,
        "ai_draft_feedback": essay.get("ai_feedback", {}).get("ai_draft_feedback", ""),
    })

    essay["lesson_feedback"] = lesson_feedback.strip()

    if "ai_feedback" in essay:
        essay["ai_feedback"]["final_feedback"] = final_feedback
        essay["ai_feedback"]["approved_at"] = now_iso


@app.post("/api/essays/send-report")
def send_report():
    """리포트 발송 상태 업데이트"""
    try:
        data = request.get_json(force=True)
        process_id = data.get("process_id")
        report_type = data.get("report_type")

        if not process_id:
            return jsonify({"error": "process_id가 필요합니다."}), 400
        if report_type not in ["student", "parent"]:
            return jsonify({"error": "report_type은 'student' 또는 'parent'여야 합니다."}), 400

        now_iso = datetime.utcnow().isoformat() + "Z"

        if _is_supabase_configured():
            url = f"{SUPABASE_URL}/rest/v1/essays?process_id=eq.{process_id}&select=data"
            resp = requests.get(url, headers=_supabase_headers(), timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404

            essay = rows[0]["data"]
            if "report_status" not in essay:
                essay["report_status"] = {}
            if report_type == "student":
                essay["report_status"]["student_sent"] = True
                essay["report_status"]["student_sent_at"] = now_iso
            else:
                essay["report_status"]["parent_sent"] = True
                essay["report_status"]["parent_sent_at"] = now_iso
            essay["metadata"]["updated_at"] = now_iso
            _supabase_update(process_id, essay)
        else:
            out_path = get_schema_path()
            with _schema_lock:
                essays = _read_essays_locked(out_path)
                essay_index = next(
                    (i for i, e in enumerate(essays)
                     if e.get("process", {}).get("process_id") == process_id),
                    None
                )
                if essay_index is None:
                    return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404
                if "report_status" not in essays[essay_index]:
                    essays[essay_index]["report_status"] = {}
                if report_type == "student":
                    essays[essay_index]["report_status"]["student_sent"] = True
                    essays[essay_index]["report_status"]["student_sent_at"] = now_iso
                else:
                    essays[essay_index]["report_status"]["parent_sent"] = True
                    essays[essay_index]["report_status"]["parent_sent_at"] = now_iso
                essays[essay_index]["metadata"]["updated_at"] = now_iso
                _write_essays_locked(out_path, essays)

        logger.info(f"[리포트 발송] process_id={process_id} type={report_type}")
        return jsonify({"success": True, "message": f"{report_type} 리포트 발송 완료", "process_id": process_id})

    except Exception as e:
        logger.error(f"POST /api/essays/send-report 오류: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500



@app.route("/submit", methods=["POST"])
def submit():
    """학생이 글을 제출하면 AI 분석 후 DB에 저장 (동기 처리)"""
    try:
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"error": "텍스트가 비어 있습니다."}), 400

        process_id = f"proc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        logger.info(f"[제출 접수] process_id={process_id} 글 길이={len(text)}자")

        achievement_2015, text_description = load_achievement_standard_and_desc(STANDARD_PATH)
        feedback_text, achievement_explanation, revised_text, scores = call_openai_for_feedback(
            student_text=text,
            achievement_2015=achievement_2015,
            text_description=text_description,
        )
        schema = build_schema(
            student_text=text,
            feedback_text=feedback_text,
            achievement_explanation=achievement_explanation,
            revised_text=revised_text,
            scores=scores,
            achievement_2015=achievement_2015,
            text_description=text_description,
        )
        schema["process"]["process_id"] = process_id
        _append_essay_safe(schema)

        logger.info(f"[제출 완료] process_id={process_id}")
        return jsonify({"success": True, "message": "제출 완료", "process_id": process_id})

    except Exception as e:
        logger.error(f"POST /submit 오류: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.post("/analyze")
def analyze():
    """프런트엔드에서 글을 받아 분석 후 DB에 저장 (기존 호환성 유지)"""
    try:
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"error": "텍스트가 비어 있습니다."}), 400

        achievement_2015, text_description = load_achievement_standard_and_desc(STANDARD_PATH)
        feedback_text, achievement_explanation, revised_text, scores = call_openai_for_feedback(
            student_text=text,
            achievement_2015=achievement_2015,
            text_description=text_description,
        )
        schema = build_schema(
            student_text=text,
            feedback_text=feedback_text,
            achievement_explanation=achievement_explanation,
            revised_text=revised_text,
            scores=scores,
            achievement_2015=achievement_2015,
            text_description=text_description,
        )
        _append_essay_safe(schema)
        return jsonify({"success": True, "message": "제출 완료", "process_id": schema["process"]["process_id"]})

    except Exception as e:
        logger.error(f"POST /analyze 오류: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
