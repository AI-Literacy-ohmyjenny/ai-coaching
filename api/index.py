"""
Vercel Serverless 진입점 (Entry Point)
=====================================
Vercel은 api/index.py 파일에서 `app` 변수(WSGI 앱)를 자동으로 감지합니다.
기존 server.py의 Flask 앱을 그대로 import해서 사용합니다.

중요: schema.json은 Vercel Serverless 환경에서 파일시스템에 쓸 수 없습니다.
실제 운영을 위해서는 데이터베이스(Supabase, PlanetScale 등) 연동이 필요합니다.
현재는 로컬 개발 및 기능 시연용으로 동작합니다.
"""

import sys
import os

# 상위 폴더(프로젝트 루트)를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# server.py의 Flask 앱을 가져옴
from server import app  # noqa: F401

# Vercel이 `app` 변수를 WSGI 핸들러로 사용
