# 🗒️ 업그레이드 메모 — AI 문해력 논술 코칭 앱

> 작성일: 2025년
> 목적: Vercel 배포 이후 데이터 영구 저장을 위한 마이그레이션 가이드

---

## ⚠️ 현재 구조의 한계 (왜 Vercel에서 저장이 안 되나?)

현재 앱은 학생 글 데이터를 **로컬 파일 `schema.json`** 에 저장합니다.

```
[학생 제출] → server.py → schema.json (로컬 파일) → [관리자 조회]
```

Vercel Serverless 함수는 **읽기 전용 파일시스템**을 사용합니다.
코드 파일은 읽을 수 있지만, 새 파일을 쓰거나 기존 파일을 수정할 수 없습니다.
(단, `/tmp` 폴더에 임시 쓰기는 가능하지만 함수 호출이 끝나면 사라집니다.)

---

## 📋 영구 저장 마이그레이션 — 수정이 필요한 부분

### 🔴 server.py — 핵심 수정 대상

schema.json을 읽고 쓰는 코드가 총 **5곳** 있습니다.
이 모든 곳을 데이터베이스 연동 코드로 교체해야 합니다.

#### 수정 위치 1: `get_essays()` 함수 (GET /api/essays)
```python
# ❌ 현재 코드 (파일 읽기)
out_path = os.path.join(BASE_DIR, "schema.json")
with open(out_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# ✅ 수정 후 (DB 예시: Supabase)
# response = supabase.table("essays").select("*").execute()
# data = response.data
```

#### 수정 위치 2: `approve_essay()` 함수 (POST /api/essays/approve)
```python
# ❌ 현재 코드 (파일 읽기 + 수정 + 쓰기)
with open(out_path, "r", encoding="utf-8") as f:
    essays = json.load(f)
# ... 수정 후 ...
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(essays, f, ensure_ascii=False, indent=2)

# ✅ 수정 후 (DB 예시: Supabase)
# supabase.table("essays").update({
#     "process_status": "completed",
#     "teacher_final_feedback": final_feedback,
# }).eq("process_id", process_id).execute()
```

#### 수정 위치 3: `send_report()` 함수 (POST /api/essays/send-report)
```python
# ❌ 현재 코드 (파일 읽기 + 수정 + 쓰기)
# ... 동일한 파일 I/O 패턴 ...

# ✅ 수정 후 (DB 예시: Supabase)
# supabase.table("essays").update({
#     "student_sent": True,
#     "student_sent_at": now_iso,
# }).eq("process_id", process_id).execute()
```

#### 수정 위치 4: `process_essay_in_background()` 함수 (백그라운드 AI 처리)
```python
# ❌ 현재 코드 (파일에 append)
existing.append(schema)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(to_save, f, ensure_ascii=False, indent=2)

# ✅ 수정 후 (DB 예시: Supabase)
# supabase.table("essays").insert(schema).execute()
```

#### 수정 위치 5: `analyze()` 함수 (POST /analyze, 기존 호환용)
```python
# ❌ 현재 코드 (파일에 append) — 위와 동일한 패턴
# ✅ 수정 후 — 위와 동일하게 DB insert로 교체
```

---

## 🗄️ 추천 데이터베이스 옵션

### 옵션 A — Supabase (가장 추천 ⭐⭐⭐)

| 항목 | 내용 |
|------|------|
| 무료 플랜 | 500MB 저장, 50만 건/월 API 호출 |
| 난이도 | 쉬움 (PostgreSQL 기반, 관리 UI 제공) |
| Vercel 연동 | 공식 통합 지원 |
| Python SDK | `pip install supabase` |

**마이그레이션 단계:**
1. [supabase.com](https://supabase.com) 가입 → 새 프로젝트 생성
2. SQL Editor에서 테이블 생성:
```sql
CREATE TABLE essays (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    process_id TEXT UNIQUE NOT NULL,
    process_status TEXT DEFAULT 'ai_drafted',
    metadata JSONB,
    student_essay JSONB,
    evaluation JSONB,
    ai_feedback JSONB,
    teacher_correction JSONB,
    lesson_feedback TEXT,
    report_status JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```
3. `requirements.txt`에 추가: `supabase==2.x.x`
4. 환경 변수 추가 (Vercel 대시보드):
   - `SUPABASE_URL=https://xxx.supabase.co`
   - `SUPABASE_KEY=eyJ...`
5. server.py에서 파일 I/O를 supabase 클라이언트 호출로 교체

---

### 옵션 B — Firebase Firestore

| 항목 | 내용 |
|------|------|
| 무료 플랜 | Spark 플랜 (1GB 저장, 5만 건/일 읽기) |
| 난이도 | 보통 (NoSQL, JSON 구조 그대로 저장 가능) |
| Python SDK | `pip install firebase-admin` |

**장점:** 현재 schema.json의 중첩 JSON 구조를 그대로 Firestore 문서로 저장 가능 → 코드 변경 최소화

---

### 옵션 C — Railway (현재 코드 변경 없이 배포 가능) ⭐ 시연 후 빠른 전환

| 항목 | 내용 |
|------|------|
| 특징 | 기존 Flask 서버를 그대로 컨테이너로 실행 |
| 파일 I/O | 볼륨 마운트로 schema.json 영구 저장 가능 |
| 무료 플랜 | 월 $5 크레딧 제공 |
| **장점** | **server.py 코드 수정 불필요!** |

**Railway로 전환 시 추가 파일:**
```dockerfile
# Dockerfile (새로 생성)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "server.py"]
```

---

## 🔧 현재 시연용 배포 시 알아둘 점

Vercel 배포 후 `/submit`으로 글을 제출하면:
- AI 분석은 정상 동작 (OpenAI API 호출)
- schema.json 저장은 `/tmp`에 임시 저장 → **함수 재실행 시 데이터 소실**
- 따라서 관리자 페이지에서 데이터가 보이지 않을 수 있음

**시연 목적이라면:** 로컬(127.0.0.1:5000)에서 서버를 켜고, index.html/admin.html을 브라우저로 직접 열어서 사용하는 것이 가장 안정적입니다.

---

## 📅 마이그레이션 권장 순서

```
현재 (로컬 JSON 파일)
    ↓ 1단계 (빠른 배포)
Railway로 이전 (코드 수정 없음, 파일 볼륨 지속)
    ↓ 2단계 (안정화)
Supabase 연동 (DB 마이그레이션, Vercel 정식 배포)
    ↓ 3단계 (확장)
학생 로그인 / 반별 관리 기능 추가
```
