# SDK Smoke Tests

This folder contains live smoke checks for the SDK against a running gateway service.

## What it validates

- SDK project APIs: `create`, `ensure`, `list`, `get`, `delete`
- SDK upload helper: `upload_document`
- Chat API (preferred): `client.chat.create(...)`
- Chat API compatibility path: `client.chat.completions.create(...)`
- Service availability and end-to-end request handling through the gateway

## Prerequisites

- Running gateway service URL
- Valid API key

## Run

```bash
export RAG_GATEWAY_URL="https://your-gateway-host"
export RAG_API_KEY="sk-..."
python -m client.smoke.run_smoke
```

Optional flags:

```bash
# use existing file for upload check
python -m client.smoke.run_smoke --upload-file /path/to/doc.txt

# keep created projects for inspection
python -m client.smoke.run_smoke --keep-projects
```
