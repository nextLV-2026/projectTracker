import os
import requests

UPSTAGE_API_KEY = os.environ.get("UPSTAGE_API_KEY")

def generate_project_workflow(project_info, team_metrics, meeting_minutes):
    url = "https://api.upstage.ai/v1/solar/chat/completions"
    headers = {
        "Authorization": f"Bearer {UPSTAGE_API_KEY}",
        "Content-Type": "application/json"
    }

    # AI에게 부여할 페르소나 및 출력 규칙 세팅
    system_prompt = """너는 IT 대학생 팀 프로젝트를 관리하는 수석 프로젝트 매니저야.
    주어진 프로젝트 정보, 팀원의 GitHub 역량 데이터, 그리고 회의록을 바탕으로 다음 내용을 마크다운 형식으로 작성해줘:
    1. 팀원별 역량에 맞춘 세부 역할 및 업무 분배
    2. 현재 회의록 상황에 맞춘 전체 워크플로우 및 우선순위
    3. 프로젝트 일정을 시각화하는 Mermaid.js 형식의 Gantt 차트 코드 (반드시 ```mermaid 로 감쌀 것)
    """

    # DB에서 가져온 실제 데이터 주입
    user_prompt = f"""
    [프로젝트 기본 정보]
    {project_info}

    [팀원 역량 데이터 (GitHub 분석)]
    {team_metrics}

    [최근 회의록 / 추가 컨텍스트]
    {meeting_minutes}
    """

    payload = {
        "model": "solar-pro",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        # LLM의 답변 텍스트만 추출해서 반환
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Solar LLM API Error: {e}")
        return None