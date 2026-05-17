import os
import requests
from firebase_admin import firestore

UPSTAGE_API_KEY = os.environ.get("UPSTAGE_API_KEY")

def process_and_save_document(uploaded_file):
    if not uploaded_file:
        return {"status": "error", "message": "파일이 없습니다."}

    # Upstage Document Parse API 호출
    url = "https://api.upstage.ai/v1/document-ai/document-parse"
    headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}"}
    files = {"document": (uploaded_file.filename, uploaded_file.stream, uploaded_file.mimetype)}
    
    response = requests.post(url, headers=headers, files=files)
    result = response.json()
    
    # Markdown 추출
    markdown_text = result.get("content", {}).get("markdown", "")
    
    # Firestore 저장
    db = firestore.client()
    doc_ref = db.collection("meeting_minutes_logs").document()
    doc_ref.set({
        "filename": uploaded_file.filename,
        "markdown_content": markdown_text,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    
    return {"status": "success", "message": "성공적으로 변환 및 저장되었습니다."}