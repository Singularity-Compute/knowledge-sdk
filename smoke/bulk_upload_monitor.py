from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{now_utc()}] {msg}", flush=True)


@dataclass
class UploadResult:
    doc_id: str | None
    ok: bool
    upload_seconds: float
    status_seconds: float | None
    error: str | None
    status_trace: list[dict[str, Any]]


class GateV2Client:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers=self.headers,
            timeout=self.timeout,
            **kwargs,
        )
        return resp

    def create_project(self, name: str, description: str) -> dict[str, Any]:
        resp = self._request(
            "POST",
            "/api/v1/projects",
            json={"name": name, "description": description},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"create_project failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return data.get("project", data)

    def upload_document(self, project_id: str, file_path: Path, title: str, description: str) -> dict[str, Any]:
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh)}
            data = {"title": title, "description": description}
            resp = self._request("POST", f"/api/v1/projects/{project_id}/upload", files=files, data=data)
        if resp.status_code >= 400:
            raise RuntimeError(f"upload failed: {resp.status_code} {resp.text}")
        return resp.json()

    def get_status(self, doc_id: str) -> dict[str, Any]:
        resp = self._request("GET", f"/api/v1/documents/{doc_id}/status")
        if resp.status_code >= 400:
            raise RuntimeError(f"status failed: {resp.status_code} {resp.text}")
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"raw": resp.text}


def status_key(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    stage = payload.get("stage")
    typ = payload.get("type")
    event_type = payload.get("event_type")
    if state or stage or typ or event_type:
        return f"type={typ}|state={state}|stage={stage}|event_type={event_type}"
    return json.dumps(payload, sort_keys=True)


def is_terminal_status(payload: dict[str, Any]) -> bool:
    state = str(payload.get("state", "")).lower()
    stage = str(payload.get("stage", "")).lower()
    typ = str(payload.get("type", "")).lower()
    event_type = str(payload.get("event_type", "")).lower()
    if state in {"done", "completed", "failed", "error"}:
        return True
    if stage in {"indexed", "completed", "failed", "error", "deleted"}:
        return True
    if typ in {"error", "failed", "done"}:
        return True
    if event_type in {"processed", "failed", "error"}:
        return True
    return False


def upload_and_track(
    client: GateV2Client,
    project_id: str,
    file_path: Path,
    *,
    poll_interval_s: float,
    max_wait_s: float,
) -> UploadResult:
    log(f"UPLOAD START file={file_path} size_bytes={file_path.stat().st_size}")
    upload_started = time.perf_counter()
    status_trace: list[dict[str, Any]] = []

    try:
        upload_data = client.upload_document(
            project_id=project_id,
            file_path=file_path,
            title=file_path.name,
            description="bulk smoke upload",
        )
    except Exception as exc:
        elapsed = time.perf_counter() - upload_started
        log(f"UPLOAD ERROR file={file_path.name} elapsed_s={elapsed:.2f} error={exc}")
        return UploadResult(
            doc_id=None,
            ok=False,
            upload_seconds=elapsed,
            status_seconds=None,
            error=str(exc),
            status_trace=status_trace,
        )

    upload_elapsed = time.perf_counter() - upload_started
    doc_id = upload_data.get("doc_id")
    log(f"UPLOAD OK file={file_path.name} doc_id={doc_id} upload_s={upload_elapsed:.2f}")

    if not doc_id:
        return UploadResult(
            doc_id=None,
            ok=False,
            upload_seconds=upload_elapsed,
            status_seconds=None,
            error=f"missing doc_id in response: {upload_data}",
            status_trace=status_trace,
        )

    poll_started = time.perf_counter()
    last_key = ""
    while True:
        waited = time.perf_counter() - poll_started
        if waited > max_wait_s:
            err = f"status timeout after {waited:.2f}s"
            log(f"STATUS TIMEOUT doc_id={doc_id} {err}")
            return UploadResult(
                doc_id=doc_id,
                ok=False,
                upload_seconds=upload_elapsed,
                status_seconds=waited,
                error=err,
                status_trace=status_trace,
            )

        try:
            payload = client.get_status(doc_id)
        except Exception as exc:
            log(f"STATUS ERROR doc_id={doc_id} error={exc}")
            return UploadResult(
                doc_id=doc_id,
                ok=False,
                upload_seconds=upload_elapsed,
                status_seconds=time.perf_counter() - poll_started,
                error=str(exc),
                status_trace=status_trace,
            )

        key = status_key(payload)
        if key != last_key:
            last_key = key
            point = {"ts": now_utc(), "payload": payload}
            status_trace.append(point)
            log(f"STATUS doc_id={doc_id} {json.dumps(payload, ensure_ascii=False)}")

        if is_terminal_status(payload):
            total_status = time.perf_counter() - poll_started
            state = str(payload.get("state", "")).lower()
            stage = str(payload.get("stage", "")).lower()
            event_type = str(payload.get("event_type", "")).lower()
            ok = (
                state not in {"failed", "error"}
                and stage not in {"failed", "error"}
                and event_type not in {"failed", "error"}
            )
            return UploadResult(
                doc_id=doc_id,
                ok=ok,
                upload_seconds=upload_elapsed,
                status_seconds=total_status,
                error=None if ok else f"terminal failure payload={payload}",
                status_trace=status_trace,
            )

        time.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create project, upload files, and track /status in real time.")
    parser.add_argument("--base-url", required=True, help="Gateway base URL, e.g. http://127.0.0.1:8917")
    parser.add_argument("--api-key", required=True, help="Bearer API key (sk-...)")
    parser.add_argument("--file-1", required=True, help="Path to first large file")
    parser.add_argument("--file-2", required=True, help="Path to second large file")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Status poll interval in seconds")
    parser.add_argument("--max-wait", type=float, default=1800.0, help="Max wait per file status in seconds")
    args = parser.parse_args()

    file_1 = Path(args.file_1).expanduser().resolve()
    file_2 = Path(args.file_2).expanduser().resolve()
    for fp in (file_1, file_2):
        if not fp.exists():
            raise SystemExit(f"File not found: {fp}")

    run_suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    project_name = f"sdk-bulk-upload-{run_suffix}"
    project_desc = "SDK bulk upload tracking run"

    client = GateV2Client(base_url=args.base_url, api_key=args.api_key)
    results: dict[str, UploadResult] = {}

    try:
        log(f"PROJECT CREATE name={project_name}")
        project = client.create_project(project_name, project_desc)
        project_id = project.get("project_id")
        if not project_id:
            raise RuntimeError(f"No project_id in response: {project}")
        log(f"PROJECT CREATED id={project_id}")

        # Small-file sanity check before large uploads.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("small precheck upload for status tracking\n")
            small_file = Path(tmp.name)
        try:
            log(f"PRECHECK small_file={small_file}")
            results["small_precheck"] = upload_and_track(
                client,
                project_id,
                small_file,
                poll_interval_s=args.poll_interval,
                max_wait_s=args.max_wait,
            )
        finally:
            if small_file.exists():
                small_file.unlink()

        results[file_1.name] = upload_and_track(
            client,
            project_id,
            file_1,
            poll_interval_s=args.poll_interval,
            max_wait_s=args.max_wait,
        )
        results[file_2.name] = upload_and_track(
            client,
            project_id,
            file_2,
            poll_interval_s=args.poll_interval,
            max_wait_s=args.max_wait,
        )
    finally:
        client.close()

    log("=== SUMMARY ===")
    log(f"project_name={project_name}")
    for name, res in results.items():
        log(
            f"file={name} ok={res.ok} doc_id={res.doc_id} "
            f"upload_s={res.upload_seconds:.2f} status_s={res.status_seconds} error={res.error}"
        )


if __name__ == "__main__":
    main()
