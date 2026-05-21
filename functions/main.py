import firebase_admin
from firebase_admin import firestore
from firebase_functions import https_fn, options
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app
from upstage_parser import process_and_save_document
import json

set_global_options(max_instances=10)

# Firebase Admin SDK 초기화 (중복 방지)
if not firebase_admin._apps:
    initialize_app()

# 공통으로 사용할 강력한 CORS 옵션 정의 (모든 포트/도메인 통과)
cors_configuration = options.CorsOptions(
    cors_origins="*",  
    cors_methods=["GET", "POST", "OPTIONS"]
)

@https_fn.on_request(cors=cors_configuration)
def process_github_data(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return https_fn.Response(status=204)

    github_data = req.get_json()

    if not github_data:
        return https_fn.Response("데이터가 없습니다.", status=400)
    
    username = github_data.get("user", {}).get("username", "Unknown")
    language_stats = github_data.get("summary", {}).get("language_percentages", {})

    used_frameworks = set()
    total_commits = 0
    total_additions = 0

    for repo in github_data.get("repositories", []):
        # 프레임워크 추출
        frameworks = repo.get("framework_library_analysis", {}).get("detected_frameworks_libraries", {})
        for category, libs in frameworks.items():
            used_frameworks.update(libs)
        
        # 기여도 추출
        contribution = repo.get("contribution", {})
        total_commits += contribution.get("commit_count_sampled", 0)
        total_additions += contribution.get("total_additions_sampled", 0)

    # DB에 저장하고 정제된 데이터 딕셔너리 생성
    refined_data = {
        "username": username,
        "main_languages": language_stats,
        "tech_stacks": list(used_frameworks),
        "activity_level": {
            "total_recent_commits": total_commits,
            "total_code_additions": total_additions
        }
    }

    # Firestore DB에 정제된 데이터 저장
    db = firestore.client()
    db.collection("team_github_metrics").document(username).set(refined_data)
    
    return https_fn.Response(f"{username}님의 GitHub 데이터 정제 및 DB 저장 완료")


# 🔥 [버그 수정 완료] 함수명을 parse_document_api로 변경하여 무한 루프 충돌을 해결했습니다.
@https_fn.on_request(cors=cors_configuration)
def parse_document_api(req: https_fn.Request) -> https_fn.Response:
    # CORS Preflight 통과용
    if req.method == "OPTIONS":
        return https_fn.Response(status=204)

    # 프론트에서 보낸 파일 받기 ('document' 키 매핑)
    uploaded_file = req.files.get('document')
    
    # upstage_parser.py 모듈 함수 실행 (이제 자기 자신을 호출하지 않고 정상 동작합니다)
    result = process_and_save_document(uploaded_file)
    
    # 브라우저가 정상적으로 인지할 수 있도록 응답을 JSON 규격으로 반환합니다.
    if result["status"] == "error":
        return https_fn.Response(
            json.dumps(result), 
            status=400, 
            mimetype="application/json"
        )
    
    return https_fn.Response(
        json.dumps(result), 
        status=200, 
        mimetype="application/json"
    )


@https_fn.on_request()
def github_webhook(req: https_fn.Request) -> https_fn.Response:
    # 깃허브에서 실시간으로 변경 데이터 JSON 받기
    payload = req.get_json()

    if not payload:
        return https_fn.Response("Webhook payload가 없습니다.", status=400)
    
    # Push 이벤트인지, Pull Request 이벤트인지 확인 가능
    event_type = req.headers.get('X-GitHub-Event')
    db = firestore.client()

    if event_type == 'push':
        repository = payload.get("repository", {})
        pusher = payload.get("pusher", {})
        sender = payload.get("sender", {})

        repo_name = repository.get("name", "")
        repo_full_name = repository.get("full_name", "")
        repo_url = repository.get("html_url", "")
        branch_ref = payload.get("ref", "")
        branch_name = branch_ref.replace("refs/heads/", "")

        pusher_name = pusher.get("name") or sender.get("login") or "Unknown"
        pusher_email = pusher.get("email", "")

        commits = payload.get("commits", [])
        extracted_commits = []

        for commit in commits:
            commit_id = commit.get("id", "")
            commit_message = commit.get("message", "")
            commit_url = commit.get("url", "")
            timestamp = commit.get("timestamp", "")

            author = commit.get("author", {})
            author_name = author.get("name", pusher_name)
            author_email = author.get("email", pusher_email)
            author_username = author.get("username", "")

            added_files = commit.get("added", [])
            modified_files = commit.get("modified", [])
            removed_files = commit.get("removed", [])

            changed_files = {
                "added": added_files,
                "modified": modified_files,
                "removed": removed_files,
                "all": added_files + modified_files + removed_files
            }

            extracted_commits.append({
                "commit_id": commit_id,
                "message": commit_message,
                "commit_url": commit_url,
                "timestamp": timestamp,
                "author": {
                    "name": author_name,
                    "email": author_email,
                    "username": author_username
                },
                "changed_files": changed_files
            })

        workflow_context = {
            "event_type": "push",
            "repository": {
                "name": repo_name,
                "full_name": repo_full_name,
                "url": repo_url,
                "branch": branch_name
            },
            "pusher": {
                "name": pusher_name,
                "email": pusher_email
            },
            "summary": {
                "commit_count": len(extracted_commits),
                "changed_file_count": sum(
                    len(commit["changed_files"]["all"])
                    for commit in extracted_commits
                )
            },
            "commits": extracted_commits,
            "received_at": firestore.SERVER_TIMESTAMP
        }

        # ai_workflow_context 컬렉션에 이벤트 단위로 저장
        doc_ref = db.collection("ai_workflow_context").document()
        doc_ref.set(workflow_context)

        return https_fn.Response(
            f"Push 이벤트 저장 완료: {repo_full_name}, commits={len(extracted_commits)}",
            status=200
        )

    return https_fn.Response("Webhook 실시간 수신 완료")


@https_fn.on_request()
def create_ai_workflow(req: https_fn.Request) -> https_fn.Response:
    db = firestore.client()
    
    # Firestore에서 데이터 수집
    # 프론트엔드에서 project_id를 전달받음 (예: ?project_id=project_01)
    project_id = req.args.get("project_id")
    if not project_id:
        return https_fn.Response("project_id 파라미터가 필요합니다.", status=400)

    try:
        # 특정 project_id에 해당하는 프로젝트 정보 가져오기
        project_doc = db.collection("project_metadata").document(project_id).get()
        project_info = project_doc.to_dict() if project_doc.exists else {}

        # 팀원 깃허브 데이터 (*특정 프로젝트에 속한 팀원들만 필터링 필요할 수 있음)
        team_docs = db.collection("team_github_metrics").stream()
        team_metrics = {doc.id: doc.to_dict() for doc in team_docs}

        # 해당 프로젝트의 모든 회의록을 시간순으로 가져오기
        # 회의록 데이터에 project_id 필드가 있어야 함
        meeting_docs = db.collection("meeting_minutes_logs")\
                         .where("project_id", "==", project_id)\
                         .order_by("timestamp", direction=firestore.Query.ASCENDING)\
                         .stream()
        
        # 모든 회의록 내용을 하나의 긴 텍스트로 병합
        all_meeting_minutes = "\n\n---\n\n".join([doc.to_dict().get("markdown_content", "") for doc in meeting_docs])
        
    except Exception as e:
        return https_fn.Response(f"DB 데이터 수집 에러: {str(e)}", status=500)

    # Solar LLM 호출
    ai_workflow_result = generate_project_workflow(project_info, team_metrics, all_meeting_minutes)

    if not ai_workflow_result:
        return https_fn.Response("AI 워크플로우 생성 실패", status=500)

    # 생성된 워크플로우 결과를 DB에 저장
    doc_ref = db.collection("ai_workflow_context").document()
    doc_ref.set({
        "project_id": "project_01",
        "workflow_markdown": ai_workflow_result,
        "timestamp": firestore.SERVER_TIMESTAMP
    })

    return https_fn.Response("AI 워크플로우 생성 및 DB 저장 성공", status=200)