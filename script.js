/**
 * 학생이 글을 제출하는 함수
 * 서버로 전송하고, 서버에서 AI가 초안 피드백을 생성하여 schema.json에 저장
 * API_BASE는 각 HTML 파일의 인라인 스크립트에서 window.API_BASE로 주입됩니다.
 */
async function submitEssay(event) {
    const textInput = document.getElementById('textInput');
    const resultDiv = document.getElementById('result');
    const button = event.currentTarget;
    
    const text = textInput.value.trim();
    
    // 입력값 확인
    if (!text) {
        resultDiv.textContent = '텍스트를 입력해주세요.';
        resultDiv.style.color = '#FF6B35';
        return;
    }

    // 로딩 상태 표시
    button.disabled = true;
    button.textContent = '제출 중...';
    resultDiv.textContent = '글을 전송하고 있어요...';
    resultDiv.style.color = '#5D4037';

    try {
        // 서버의 /submit 엔드포인트로 제출
        // 서버에서 AI가 즉시 초안 피드백을 생성하고 schema.json에 status: "ai_drafted"로 저장
        const response = await fetch(`${window.API_BASE}/submit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || '제출 중 오류가 발생했습니다.');
        }

        // 성공 메시지 표시
        resultDiv.textContent = '✅ 선생님께 소중한 글이 전달되었습니다! 선생님이 곧 확인하실 거예요 😊';
        resultDiv.style.color = '#4CAF50';
        
        // 입력창 비우기
        textInput.value = '';
        
    } catch (error) {
        // 오류 메시지 표시
        resultDiv.textContent = '오류: ' + error.message;
        resultDiv.style.color = '#FF6B35';
        console.error('제출 오류:', error);
    } finally {
        // 버튼 상태 복원
        button.disabled = false;
        button.textContent = '제출하기';
    }
}

