from __future__ import annotations

import os
import uuid

from client import ClientAuth, RAGOpenAIClient


def main() -> None:
    base_url = os.environ["RAG_GATEWAY_URL"]
    api_key = os.environ["RAG_API_KEY"]
    project_name = f"sdk-demo-lifecycle-{uuid.uuid4().hex[:8]}"

    with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
        created = client.projects.create(
            name=project_name,
            description="Project lifecycle demo",
        )
        project_id = created["project_id"]
        print("created:", project_id)

        fetched = client.projects.get(project_id)
        print("fetched_name:", fetched.get("name"))

        projects = client.projects.list()
        print("total_projects:", len(projects))

        deleted = client.projects.delete(project_id)
        print("deleted:", deleted)


if __name__ == "__main__":
    main()
