from __future__ import annotations

import argparse
import os
import tempfile
import uuid
from pathlib import Path

from client import APIError, ClientAuth, RAGOpenAIClient


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SDK smoke tests against live gateway service.")
    parser.add_argument(
        "--upload-file",
        type=str,
        default="",
        help="Optional path to file for upload smoke check. If omitted, a temp .txt file is created.",
    )
    parser.add_argument(
        "--keep-projects",
        action="store_true",
        help="Do not delete created projects after test run.",
    )
    args = parser.parse_args()

    base_url = _require_env("RAG_GATEWAY_URL")
    api_key = _require_env("RAG_API_KEY")
    run_id = uuid.uuid4().hex[:8]

    created_project_ids: list[str] = []
    tmp_path: Path | None = None

    with RAGOpenAIClient(base_url=base_url, auth=ClientAuth(api_key=api_key)) as client:
        print("[1/9] projects.create")
        main_project_name = f"sdk-smoke-main-{run_id}"
        try:
            project = client.projects.create(
                name=main_project_name,
                description="SDK smoke project",
            )
            created_project_ids.append(project["project_id"])
        except APIError as exc:
            # Environments with strict project caps may block creating new projects.
            # In that case, reuse a stable smoke project to keep test coverage running.
            if exc.status_code == 400 and "project_limit_reached" in str(exc.message):
                fallback_name = "sdk-smoke-main"
                print(f"    project limit reached, reusing '{fallback_name}' via ensure")
                project = client.projects.ensure(name=fallback_name)
            else:
                raise
        project_id = project["project_id"]
        _assert(bool(project_id), "projects.create did not return project_id")

        print("[2/9] projects.ensure")
        ensured = client.projects.ensure(name="sdk-smoke-ensure")
        ensured_id = ensured["project_id"]
        _assert(bool(ensured_id), "projects.ensure did not return project_id")

        print("[3/9] projects.list")
        projects = client.projects.list()
        project_ids = {p.get("project_id") for p in projects}
        _assert(project_id in project_ids, "projects.list does not include created project")
        _assert(ensured_id in project_ids, "projects.list does not include ensured project")

        print("[4/9] projects.get")
        fetched = client.projects.get(project_id)
        _assert(fetched.get("project_id") == project_id, "projects.get returned unexpected project_id")

        print("[5/9] upload_document")
        if args.upload_file:
            file_path = Path(args.upload_file).expanduser().resolve()
            _assert(file_path.exists(), f"upload file not found: {file_path}")
        else:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                tmp.write("Smoke test upload document content.\n")
                tmp_path = Path(tmp.name)
            file_path = tmp_path

        upload_response = client.upload_document(
            project_id=project_id,
            file_path=file_path,
            title=f"smoke-{run_id}",
            description="SDK smoke upload",
        )
        _assert(isinstance(upload_response, dict), "upload_document returned non-dict response")

        print("[6/9] chat.create (non-stream)")
        completion = client.chat.create(
            project_id=project_id,
            messages=[{"role": "user", "content": "Return a short service health response."}],
            include_sources=True,
        )
        answer = completion["choices"][0]["message"]["content"]
        _assert(isinstance(answer, str), "chat.create(non-stream) returned invalid answer content")

        print("[7/9] chat.create (stream)")
        events = client.chat.create(
            project_id=project_id,
            messages=[{"role": "user", "content": "Return a short streamed response."}],
            stream=True,
        )
        stream_text = []
        got_done = False
        for chunk in events:
            delta = chunk["choices"][0]["delta"].get("content", "")
            if delta:
                stream_text.append(delta)
            finish_reason = chunk["choices"][0].get("finish_reason")
            if finish_reason == "stop":
                got_done = True
        _assert(got_done, "stream did not emit final stop chunk")

        print("[8/9] chat.completions.create compatibility")
        compatibility_completion = client.chat.completions.create(
            project_id=project_id,
            messages=[{"role": "user", "content": "Compatibility path check."}],
        )
        compat_answer = compatibility_completion["choices"][0]["message"]["content"]
        _assert(isinstance(compat_answer, str), "chat.completions.create returned invalid answer content")

        print("[9/9] projects.delete")
        if not args.keep_projects:
            while created_project_ids:
                pid = created_project_ids.pop()
                client.projects.delete(pid)
        else:
            print(f"Keeping projects: {created_project_ids}")

    if tmp_path is not None and tmp_path.exists():
        tmp_path.unlink()

    print("Smoke tests passed.")


if __name__ == "__main__":
    main()
