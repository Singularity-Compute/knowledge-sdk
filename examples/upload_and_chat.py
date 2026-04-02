from __future__ import annotations

import os
import sys
from pathlib import Path

from client import ClientAuth, RAGOpenAIClient


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python client/examples/upload_and_chat.py /path/to/document")

    file_path = Path(sys.argv[1]).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    base_url = os.environ["RAG_GATEWAY_URL"]
    api_key = os.environ["RAG_API_KEY"]

    with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
        project = client.projects.ensure(
            name="sdk-demo-upload",
        )
        project_id = project["project_id"]
        print("project_id:", project_id)

        uploaded = client.upload_document(
            project_id=project_id,
            file_path=file_path,
            title=file_path.name,
            description="Uploaded from SDK example",
        )
        print("uploaded:", uploaded.get("document_id") or uploaded)

        completion = client.chat.create(
            project_id=project_id,
            messages=[{"role": "user", "content": "Summarize the uploaded document briefly."}],
            include_sources=True,
        )
        print("answer:", completion["choices"][0]["message"]["content"])
        print("sources:", len(completion.get("rag", {}).get("sources", [])))


if __name__ == "__main__":
    main()
