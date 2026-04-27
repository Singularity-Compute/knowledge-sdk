from __future__ import annotations

import unittest
from unittest.mock import patch

from sdk import ClientAuth, RAGOpenAIClient, SDKError


class SDKChatAPITests(unittest.TestCase):
    def test_chat_create_alias_delegates_to_chat_completions(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )
        expected = {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(client.chat.completions, "create", return_value=expected) as mocked_create:
            result = client.chat.create(
                project_id="project-1",
                messages=[{"role": "user", "content": "Hello"}],
                agent_mode="multi",
            )

        self.assertEqual(result, expected)
        mocked_create.assert_called_once()
        kwargs = mocked_create.call_args.kwargs
        self.assertEqual(kwargs["project_id"], "project-1")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "Hello"}])
        self.assertEqual(kwargs["agent_mode"], "multi")
        client.close()

    def test_chat_create_builds_query_and_history(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )
        captured_payload = {}

        def fake_request_json(method, path, *, json_body=None, data=None, files=None):
            captured_payload["method"] = method
            captured_payload["path"] = path
            captured_payload["json_body"] = json_body
            return {"answer": "OK", "sources": [], "context": []}

        with patch.object(client, "_request_json", side_effect=fake_request_json):
            response = client.chat.create(
                project_id="project-1",
                messages=[
                    {"role": "system", "content": "Be concise"},
                    {"role": "assistant", "content": "Sure"},
                    {"role": "user", "content": "Summarize docs"},
                ],
                agent_mode="multi",
            )

        self.assertEqual(captured_payload["method"], "POST")
        self.assertEqual(captured_payload["path"], "/api/v1/chat")
        self.assertEqual(captured_payload["json_body"]["project_id"], "project-1")
        self.assertEqual(captured_payload["json_body"]["query"], "Summarize docs")
        self.assertEqual(captured_payload["json_body"]["agent_mode"], "multi")
        self.assertEqual(
            captured_payload["json_body"]["history"],
            [
                {"role": "system", "content": "Be concise"},
                {"role": "assistant", "content": "Sure"},
            ],
        )
        self.assertEqual(response["choices"][0]["message"]["content"], "OK")
        client.close()

    def test_chat_response_exposes_agent_mode_in_rag_metadata(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )
        with patch.object(
            client,
            "_request_json",
            return_value={"answer": "OK", "sources": [], "context": [], "agent_mode": "multi"},
        ):
            response = client.chat.create(
                project_id="project-1",
                messages=[{"role": "user", "content": "Summarize docs"}],
            )
        self.assertEqual(response["rag"]["agent_mode"], "multi")
        client.close()

    def test_chat_create_requires_last_message_to_be_non_empty_user(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )

        with self.assertRaises(SDKError):
            client.chat.create(
                project_id="project-1",
                messages=[{"role": "assistant", "content": "Not valid"}],
            )
        client.close()

    def test_documents_list_calls_project_documents_endpoint(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )

        with patch.object(client, "_request_json", return_value={"documents": [], "total": 0}) as mocked:
            result = client.documents.list(project_id="project-1", limit=25, offset=10)

        self.assertEqual(result, {"documents": [], "total": 0})
        mocked.assert_called_once_with(
            "GET",
            "/api/v1/projects/project-1/documents?limit=25&offset=10",
        )
        client.close()

    def test_documents_delete_calls_delete_endpoint(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )

        with patch.object(client, "_request_json", return_value={"doc_id": "d-1"}) as mocked:
            result = client.documents.delete(doc_id="d-1")

        self.assertEqual(result["doc_id"], "d-1")
        mocked.assert_called_once_with("DELETE", "/api/v1/documents/d-1")
        client.close()

    def test_processing_status_maps_event_flags(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )

        with patch.object(client.documents, "status", return_value={"event_type": "embeddings_created"}):
            status = client.documents.processing_status(doc_id="doc-1")

        self.assertFalse(status["ready"])
        self.assertTrue(status["imported"])
        self.assertTrue(status["vectorized"])
        self.assertFalse(status["failed"])
        client.close()

    def test_wait_until_ready_returns_when_indexed(self) -> None:
        client = RAGOpenAIClient(
            base_url="https://gateway.example",
            auth=ClientAuth(api_key="sk-test"),
        )
        sequence = [
            {"event_type": "uploaded"},
            {"event_type": "ingested"},
            {"event_type": "indexed"},
        ]

        with patch.object(client.documents, "status", side_effect=sequence):
            final_status = client.documents.wait_until_ready(
                doc_id="doc-1",
                timeout_seconds=5,
                poll_interval_seconds=0,
            )

        self.assertTrue(final_status["ready"])
        self.assertEqual(final_status["event_type"], "indexed")
        client.close()


if __name__ == "__main__":
    unittest.main()
