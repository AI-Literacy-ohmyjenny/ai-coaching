import os
import json
import threading
from datetime import datetime
from uuid import uuid4

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # 환경 변수에 OpenAI API Key 설정

# 교과 성취 기준 파일 경로 (Vercel 배포 시에도 절대경로로 찾을 수 있도록)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STANDARD_PATH = os.path.join(BASE_DIR, "S1_초등_5_국어_TXT_012230.json")

# -----------------------------------------------------------------------
# 📦 데이터 저장 경로 결정
# Vercel Serverless: BASE_DIR는 읽기 전용 → /tmp 폴더로 fallback
# 로컬 개발: BASE_DIR에 직접 schema.json 저장
# -----------------------------------------------------------------------
def get_schema_path() -> str:
    """schema.json 저장 경로 반환. 쓰기 가능한 디렉터리를 자동 선택."""
    primary = os.path.join(BASE_DIR, "schema.json")
    # 쓰기 테스트
    try:
        with open(primary, "a", encoding="utf-8"):
            pass
        return primary
    except OSError:
        # Vercel 등 읽기 전용 환경 → /tmp 사용
        return "/tmp/schema.json"

app = Flask(__name__)
CORS(app)  # CORS 허용 (브라우저 차단 문제 해결)


def load_achievement_standard_and_desc(standard_json_path: str):
    """성취 기준과 지문 설명 로드"""
    with open(standard_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    standards = data.get("source_data_info", {}).get("2015_achievement_standard", [])
    achievement_2015 = " ".join(standards) if standards else ""
    text_description = data.get("learning_data_info", {}).get("text_description", "")

    return achievement_2015, text_description


def call_openai_for_feedback(student_text: str, achievement_2015: str, text_description: str):
    """OpenAI에 학생 글을 보내 3단 구성 피드백, 성취기준 설명, 추천 수정본을 JSON 형태로 받아오기"""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    system_prompt = (
        "당신은 초등학교 5학년 국어 수업을 돕는 전문적인 AI 보조교사입니다. "
        "다음 성취 기준을 정확히 이해하고 학생 글을 평가하세요.\n\n"
        f"- 성취 기준: {achievement_2015}\n\n"
        "출력은 반드시 아래 JSON 형식의 한 개 객체로만 답하세요.\n"
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
    content = data["choices"][0]["message"]["content"].strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("모델 응답을 JSON으로 파싱하지 못했습니다:\n" + content)

    feedback_text = parsed.get("feedback", "").strip()
    achievement_explanation = parsed.get("achievement_explanation", "").strip()
    revised_text = parsed.get("revised_text", "").strip()
    scores = parsed.get("scores", {})

    return feedback_text, achievement_explanation, revised_text, scores


def build_schema(student_text: str, feedback_text: str, achievement_explanation: str, revised_text: str, scores: dict, achievement_2015: str, text_description: str):
    """설계한 schema.json 구조에 맞게 데이터 블록 생성"""
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
            "subject": "국어"
        },
        "lesson_context": {
            "lesson_id": "S1_초등_5_국어_TXT_012230",
            "text_title": text_description,
            "text_description": text_description,
            "achievement_standards": {
                "2015": [achievement_2015]
            }
        },
        "process": {
            "process_id": process_id,
            "status": "ai_drafted",
            "current_step": 3
        },
        "student_essay": {
            "essay_id": essay_id,
            "prompt": "지문을 읽고, 자신과 생각이나 처지가 다른 사람과 어떻게 대화하면 좋을지 느낀 점을 써 보세요.",
            "student_answer": student_text,
            "submitted_at": now_iso
        },
        "evaluation": {
            "dimensions": {
                "vocabulary": {
                    "scale": 5,
                    "value": int(scores.get("vocabulary", 3)),
                    "comment": ""
                },
                "grammar": {
                    "scale": 5,
                    "value": int(scores.get("grammar", 3)),
                    "comment": ""
                },
                "logic": {
                    "scale": 5,
                    "value": int(scores.get("logic", 3)),
                    "comment": ""
                },
                "empathy": {
                    "scale": 5,
                    "value": int(scores.get("empathy", 4)),
                    "comment": ""
                }
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
            "revised_text": revised_text
        }
    }

    return schema


@app.route("/admin")
def admin():
    """교사 관리자 페이지"""
    return send_from_directory(".", "admin.html")


@app.get("/api/essays")
def get_essays():
    """schema.json에서 모든 학생 글 데이터를 반환"""
    try:
        out_path = get_schema_path()
        if not os.path.exists(out_path):
            return jsonify({"essays": []})

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 리스트가 아니면 리스트로 변환
        if not isinstance(data, list):
            data = [data]

        return jsonify({"essays": data})
    except Exception as e:
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

        out_path = get_schema_path()
        if not os.path.exists(out_path):
            return jsonify({"error": "schema.json 파일을 찾을 수 없습니다."}), 404

        # schema.json 읽기
        with open(out_path, "r", encoding="utf-8") as f:
            essays = json.load(f)

        # 리스트가 아니면 리스트로 변환
        if not isinstance(essays, list):
            essays = [essays]

        # process_id로 해당 항목 찾기
        essay_index = None
        for i, essay in enumerate(essays):
            if essay.get("process", {}).get("process_id") == process_id:
                essay_index = i
                break

        if essay_index is None:
            return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404

        # 업데이트
        now_iso = datetime.utcnow().isoformat() + "Z"
        essays[essay_index]["process"]["status"] = "completed"
        essays[essay_index]["process"]["current_step"] = 5
        essays[essay_index]["metadata"]["updated_at"] = now_iso

        # teacher_correction 섹션 추가/업데이트
        if "teacher_correction" not in essays[essay_index]:
            essays[essay_index]["teacher_correction"] = {}

        essays[essay_index]["teacher_correction"]["teacher_id"] = "t_001"  # 실제로는 세션에서 가져오기
        essays[essay_index]["teacher_correction"]["corrected_at"] = now_iso
        essays[essay_index]["teacher_correction"]["teacher_final_feedback"] = final_feedback
        essays[essay_index]["teacher_correction"]["ai_draft_feedback"] = essays[essay_index].get("ai_feedback", {}).get("ai_draft_feedback", "")

        # 수업 참여 피드백 저장
        lesson_feedback = data.get("lesson_feedback", "").strip()
        essays[essay_index]["lesson_feedback"] = lesson_feedback

        # ai_feedback에도 최종 피드백 반영 (선택사항)
        if "ai_feedback" in essays[essay_index]:
            essays[essay_index]["ai_feedback"]["final_feedback"] = final_feedback
            essays[essay_index]["ai_feedback"]["approved_at"] = now_iso

        # 파일 저장
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(essays, f, ensure_ascii=False, indent=2)

        return jsonify({
            "success": True,
            "message": "승인 완료",
            "process_id": process_id,
            "status": "completed"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/essays/send-report")
def send_report():
    """리포트 발송 상태 업데이트"""
    try:
        data = request.get_json(force=True)
        process_id = data.get("process_id")
        report_type = data.get("report_type")  # "student" or "parent"

        if not process_id:
            return jsonify({"error": "process_id가 필요합니다."}), 400

        if report_type not in ["student", "parent"]:
            return jsonify({"error": "report_type은 'student' 또는 'parent'여야 합니다."}), 400

        out_path = get_schema_path()
        if not os.path.exists(out_path):
            return jsonify({"error": "schema.json 파일을 찾을 수 없습니다."}), 404

        # schema.json 읽기
        with open(out_path, "r", encoding="utf-8") as f:
            essays = json.load(f)

        # 리스트가 아니면 리스트로 변환
        if not isinstance(essays, list):
            essays = [essays]

        # process_id로 해당 항목 찾기
        essay_index = None
        for i, essay in enumerate(essays):
            if essay.get("process", {}).get("process_id") == process_id:
                essay_index = i
                break

        if essay_index is None:
            return jsonify({"error": "해당 process_id를 가진 데이터를 찾을 수 없습니다."}), 404

        # report_status 섹션 초기화
        if "report_status" not in essays[essay_index]:
            essays[essay_index]["report_status"] = {}

        # 리포트 발송 상태 업데이트
        now_iso = datetime.utcnow().isoformat() + "Z"
        if report_type == "student":
            essays[essay_index]["report_status"]["student_sent"] = True
            essays[essay_index]["report_status"]["student_sent_at"] = now_iso
        else:
            essays[essay_index]["report_status"]["parent_sent"] = True
            essays[essay_index]["report_status"]["parent_sent_at"] = now_iso

        essays[essay_index]["metadata"]["updated_at"] = now_iso

        # 파일 저장
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(essays, f, ensure_ascii=False, indent=2)

        return jsonify({
            "success": True,
            "message": f"{report_type} 리포트 발송 완료",
            "process_id": process_id
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def process_essay_in_background(text: str, process_id: str):
    """백그라운드 스레드에서 AI 분석 후 schema.json에 저장"""
    try:
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
        # 미리 생성한 process_id 덮어쓰기
        schema["process"]["process_id"] = process_id

        out_path = get_schema_path()
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
            if isinstance(existing, list):
                existing.append(schema)
                to_save = existing
            else:
                to_save = [existing, schema]
        else:
            to_save = [schema]

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"[백그라운드 처리 오류] process_id={process_id}: {e}")


@app.route('/submit', methods=['POST'])
def submit():
    """학생이 글을 제출하면 즉시 응답하고, AI 분석은 백그라운드에서 처리"""
    try:
        data = request.get_json(force=True)
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"error": "텍스트가 비어 있습니다."}), 400

        # 즉시 process_id 생성 후 백그라운드 스레드 시작
        process_id = f"proc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        thread = threading.Thread(
            target=process_essay_in_background,
            args=(text, process_id),
            daemon=True
        )
        thread.start()

        # AI 처리를 기다리지 않고 즉시 응답
        return jsonify({
            "success": True,
            "message": "제출 완료",
            "process_id": process_id
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/analyze")
def analyze():
    """프런트엔드에서 글을 받아 분석 후 schema.json에 저장 (기존 호환성 유지)"""
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

        out_path = get_schema_path()
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

            if isinstance(existing, list):
                existing.append(schema)
                to_save = existing
            else:
                to_save = [existing, schema]
        else:
            to_save = [schema]

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)

        # 학생 화면에는 성공 메시지만 반환 (분석 결과는 보여주지 않음)
        return jsonify({
            "success": True,
            "message": "제출 완료",
            "process_id": schema["process"]["process_id"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


