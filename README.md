# RAG Gate v2 SDK

This SDK targets the `gate_v2` API.

Auth:
- pass your token as `Bearer` via `ClientAuth(api_key="sk-...")`

## Install

```bash
pip install -r client/requirements.txt
```

## Quick Start

```python
import os
from client import ClientAuth, RAGOpenAIClient

client = RAGOpenAIClient(
    base_url=os.environ["RAG_GATEWAY_URL"],
    auth=ClientAuth(api_key="sk-..."),
)

project = client.projects.ensure(
    name="my-project",
)

# See practical chat scenarios in the "Examples" section below.
client.close()
```

## API Style

- preferred call is `client.chat.create(...)`
- input uses `messages=[{role, content}, ...]`
- output includes `choices[0].message.content`
- currently **only chat-completions flow is supported**
- classic `completions` (prompt-based `/v1/completions`) is **not implemented yet**

Additionally, the response includes `rag` block with original gateway data:
- `sources`, `context`, `partial`, `degraded`, `raw`

## Streaming

```python
events = client.chat.create(
    project_id=project["project_id"],
    messages=[{"role": "user", "content": "Give me key points"}],
    stream=True,
)
for chunk in events:
    delta = chunk["choices"][0]["delta"].get("content", "")
    if delta:
        print(delta, end="")
```

## Project APIs

- `client.projects.create(name, description=None)`
- `client.projects.ensure(name)` (reuse by name if project limit is reached)
- `client.projects.list()`
- `client.projects.get(project_id)`
- `client.projects.delete(project_id)`

## Upload helper

`client.upload_document(project_id=..., file_path=..., title=..., description=...)`

## Examples

All snippets below assume:

```python
import os
from client import ClientAuth, RAGOpenAIClient

base_url = os.environ["RAG_GATEWAY_URL"]
api_key = os.environ["RAG_API_KEY"]
```

### 1) Create project and ask one question

```python
with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
    project = client.projects.ensure(
        name="sdk-demo-project",
    )
    completion = client.chat.create(
        project_id=project["project_id"],
        messages=[{"role": "user", "content": "What documents are available in this project?"}],
    )
    print(completion["choices"][0]["message"]["content"])
```

### 2) Streaming response

```python
with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
    project = client.projects.ensure(name="sdk-demo-stream")
    events = client.chat.create(
        project_id=project["project_id"],
        messages=[{"role": "user", "content": "Provide 3 key takeaways from the project content."}],
        stream=True,
    )
    for chunk in events:
        delta = chunk["choices"][0]["delta"].get("content", "")
        if delta:
            print(delta, end="", flush=True)
    print()
```

### 3) Upload a document and ask about it

```python
from pathlib import Path

file_path = Path("/path/to/doc.pdf")

with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
    project = client.projects.ensure(name="sdk-demo-upload")
    client.upload_document(
        project_id=project["project_id"],
        file_path=file_path,
        title=file_path.name,
        description="Uploaded from SDK example",
    )
    completion = client.chat.create(
        project_id=project["project_id"],
        messages=[{"role": "user", "content": "Summarize the uploaded document briefly."}],
        include_sources=True,
    )
    print(completion["choices"][0]["message"]["content"])
    print("sources:", len(completion["rag"]["sources"]))
```

### 4) Multi-turn chat with retrieval options

```python
messages = [
    {"role": "system", "content": "Be concise and focus on factual details."},
    {"role": "user", "content": "What documents are available in this project?"},
    {"role": "assistant", "content": "I can answer using retrieved context and sources."},
    {"role": "user", "content": "Give a short architecture-focused summary."},
]

with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
    project = client.projects.ensure(name="sdk-demo-multiturn")
    completion = client.chat.create(
        project_id=project["project_id"],
        messages=messages,
        mode="hybrid",
        top_k=5,
        use_hyde=True,
        use_fact_queries=True,
        include_sources=True,
        filters={"tags": ["architecture"]},
    )
    print(completion["choices"][0]["message"]["content"])
```

### 5) Project lifecycle (create/list/get/delete)

```python
import uuid

with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
    name = f"sdk-demo-lifecycle-{uuid.uuid4().hex[:8]}"
    created = client.projects.create(name=name, description="Lifecycle demo")
    project_id = created["project_id"]

    fetched = client.projects.get(project_id)
    projects = client.projects.list()
    deleted = client.projects.delete(project_id)

    print("fetched:", fetched["name"])
    print("total_projects:", len(projects))
    print("deleted:", deleted)
```

## Tests

SDK tests are in `client/tests`.

Run:

```bash
python -m unittest discover -s client/tests -p "test_*.py"
```

## Smoke Tests (SDK + Service)

Live end-to-end smoke checks are in `client/smoke`.

Run:

```bash
export RAG_GATEWAY_URL="https://your-gateway-host"
export RAG_API_KEY="sk-..."
python -m client.smoke.run_smoke
```

This validates SDK methods and the running gateway service in one pass.

## Diagrams

Mermaid diagrams for SDK flows:
- `client/MERMAID_DOCS.md`
