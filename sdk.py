from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

import requests


class SDKError(Exception):
    """Base SDK exception."""


class APIError(SDKError):
    """HTTP-level API error with status and response body."""

    def __init__(self, status_code: int, message: str, payload: Any | None = None):
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload


@dataclass(frozen=True)
class ClientAuth:
    api_key: str

    def as_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


class _ProjectsAPI:
    def __init__(self, client: "RAGOpenAIClient"):
        self._client = client

    def create(self, name: str, description: str | None = None) -> Dict[str, Any]:
        payload = {"name": name, "description": description}
        data = self._client._request_json("POST", "/api/v1/projects", json_body=payload)
        return data.get("project", data)

    def ensure(self, name: str, description: str | None = None) -> Dict[str, Any]:
        """
        Create a project by name, or reuse existing one with the same name.

        Helpful when server project limits are reached.
        """
        try:
            return self.create(name=name, description=description)
        except APIError as exc:
            if exc.status_code != 400 or "project_limit_reached" not in str(exc.message):
                raise
            projects = self.list()
            for project in projects:
                if project.get("name") == name:
                    return project
            raise

    def list(self) -> List[Dict[str, Any]]:
        data = self._client._request_json("GET", "/api/v1/projects")
        return data.get("projects", [])

    def get(self, project_id: str) -> Dict[str, Any]:
        data = self._client._request_json("GET", f"/api/v1/projects/{project_id}")
        return data.get("project", data)

    def delete(self, project_id: str) -> Dict[str, Any]:
        return self._client._request_json("DELETE", f"/api/v1/projects/{project_id}")


class _ChatCompletionsAPI:
    def __init__(self, client: "RAGOpenAIClient"):
        self._client = client

    def create(
        self,
        *,
        project_id: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        include_sources: bool = True,
        mode: str | None = None,
        top_k: int | None = None,
        max_llm_calls: int | None = None,
        max_fact_queries: int | None = None,
        use_hyde: bool | None = None,
        use_fact_queries: bool | None = None,
        use_retry: bool | None = None,
        use_tools: bool | None = None,
        filters: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | Iterator[Dict[str, Any]]:
        query, history = self._split_messages(messages)
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "query": query,
            "history": history,
            "include_sources": include_sources,
        }
        optional = {
            "mode": mode,
            "top_k": top_k,
            "max_llm_calls": max_llm_calls,
            "max_fact_queries": max_fact_queries,
            "use_hyde": use_hyde,
            "use_fact_queries": use_fact_queries,
            "use_retry": use_retry,
            "use_tools": use_tools,
            "filters": filters,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})

        if stream:
            return self._stream_completion(payload)
        raw = self._client._request_json("POST", "/api/v1/chat", json_body=payload)
        return self._to_openai_chat_response(raw)

    @staticmethod
    def _split_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
        if not messages:
            raise SDKError("messages must not be empty")
        last = messages[-1]
        role = last.get("role")
        content = (last.get("content") or "").strip()
        if role != "user" or not content:
            raise SDKError("last message must be a non-empty user message")
        history = [
            {"role": m.get("role", ""), "content": m.get("content", "")}
            for m in messages[:-1]
            if m.get("role") in {"user", "assistant", "system"} and m.get("content")
        ]
        return content, history

    def _stream_completion(self, payload: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        stream = self._client._request_stream("POST", "/api/v1/chat/stream", json_body=payload)
        for event in self._client._iter_sse_events(stream):
            event_type = event.get("type")
            if event_type == "done":
                yield {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "rag_event": event,
                }
                break

            delta_text = event.get("delta") or event.get("token") or event.get("content") or ""
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": delta_text} if delta_text else {},
                        "finish_reason": None,
                    }
                ],
                "rag_event": event,
            }

    @staticmethod
    def _to_openai_chat_response(raw: Dict[str, Any]) -> Dict[str, Any]:
        answer = raw.get("answer", "")
        return {
            "id": raw.get("trace_id", f"chatcmpl-{uuid.uuid4().hex}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": raw.get("mode", "rag-agent"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": None,
            "rag": {
                "sources": raw.get("sources", []),
                "context": raw.get("context", []),
                "partial": raw.get("partial", False),
                "degraded": raw.get("degraded", []),
                "raw": raw,
            },
        }


class _ChatAPI:
    def __init__(self, client: "RAGOpenAIClient"):
        self.completions = _ChatCompletionsAPI(client)

    def create(
        self,
        *,
        project_id: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        include_sources: bool = True,
        mode: str | None = None,
        top_k: int | None = None,
        max_llm_calls: int | None = None,
        max_fact_queries: int | None = None,
        use_hyde: bool | None = None,
        use_fact_queries: bool | None = None,
        use_retry: bool | None = None,
        use_tools: bool | None = None,
        filters: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | Iterator[Dict[str, Any]]:
        """
        Preferred chat entrypoint for SDK users.

        This delegates to chat-completions compatibility layer internally.
        """
        return self.completions.create(
            project_id=project_id,
            messages=messages,
            stream=stream,
            include_sources=include_sources,
            mode=mode,
            top_k=top_k,
            max_llm_calls=max_llm_calls,
            max_fact_queries=max_fact_queries,
            use_hyde=use_hyde,
            use_fact_queries=use_fact_queries,
            use_retry=use_retry,
            use_tools=use_tools,
            filters=filters,
        )


class RAGOpenAIClient:
    """
    Python SDK for gate_v2 API.

    Usage:
        client = RAGOpenAIClient(
            base_url="http://localhost:8917",
            auth=ClientAuth(api_key="sk-..."),
        )
        project = client.projects.create(name="my-project")
        resp = client.chat.completions.create(
            project_id=project["project_id"],
            messages=[{"role": "user", "content": "Explain RAG in 2 lines"}],
        )
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth: ClientAuth,
        timeout_seconds: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()
        self.projects = _ProjectsAPI(self)
        self.chat = _ChatAPI(self)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "RAGOpenAIClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upload_document(
        self,
        *,
        project_id: str,
        file_path: str | Path,
        title: str | None = None,
        description: str | None = None,
    ) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise SDKError(f"file not found: {path}")
        data = {
            "title": title or path.name,
            "description": description or "",
        }
        with path.open("rb") as fh:
            files = {"file": (path.name, fh)}
            return self._request_json(
                "POST",
                f"/api/v1/projects/{project_id}/upload",
                data=data,
                files=files,
            )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        files: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        headers = {"Accept": "application/json", **self.auth.as_headers()}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._session.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            timeout=self.timeout_seconds,
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise APIError(resp.status_code, "non_json_response", payload=resp.text) from None

    def _request_stream(self, method: str, path: str, *, json_body: Dict[str, Any]) -> requests.Response:
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            **self.auth.as_headers(),
        }
        resp = self._session.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            json=json_body,
            timeout=self.timeout_seconds,
            stream=True,
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)
        return resp

    @staticmethod
    def _iter_sse_events(resp: requests.Response) -> Iterator[Dict[str, Any]]:
        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload in {"", "[DONE]"}:
                    continue
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"type": "raw", "content": payload}
        finally:
            resp.close()

    @staticmethod
    def _raise_api_error(resp: requests.Response) -> None:
        payload: Any
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                message = payload.get("detail") or payload.get("error") or str(payload)
            else:
                message = str(payload)
        except ValueError:
            payload = resp.text
            message = resp.text
        raise APIError(resp.status_code, message, payload=payload)
