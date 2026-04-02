from __future__ import annotations

import os

from client import ClientAuth, RAGOpenAIClient


def main() -> None:
    base_url = os.environ["RAG_GATEWAY_URL"]
    api_key = os.environ["RAG_API_KEY"]

    with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
        project = client.projects.ensure(
            name="sdk-demo-multiturn",
        )
        project_id = project["project_id"]
        print("project_id:", project_id)

        messages = [
            {"role": "system", "content": "Be concise and focus on factual details."},
            {"role": "user", "content": "What documents are available in this project?"},
            {"role": "assistant", "content": "I can answer using retrieved context and sources."},
            {"role": "user", "content": "Give a short architecture-focused summary."},
        ]

        completion = client.chat.create(
            project_id=project_id,
            messages=messages,
            mode="hybrid",
            top_k=5,
            use_hyde=True,
            use_fact_queries=True,
            include_sources=True,
            filters={"tags": ["architecture"]},
        )

        print("answer:", completion["choices"][0]["message"]["content"])
        rag = completion.get("rag", {})
        print("partial:", rag.get("partial"))
        print("sources:", len(rag.get("sources", [])))


if __name__ == "__main__":
    main()
