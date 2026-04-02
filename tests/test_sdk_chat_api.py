from __future__ import annotations

import unittest
from unittest.mock import patch

from client import ClientAuth, RAGOpenAIClient, SDKError


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
            )

        self.assertEqual(result, expected)
        mocked_create.assert_called_once()
        kwargs = mocked_create.call_args.kwargs
        self.assertEqual(kwargs["project_id"], "project-1")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "Hello"}])
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
            )

        self.assertEqual(captured_payload["method"], "POST")
        self.assertEqual(captured_payload["path"], "/api/v1/chat")
        self.assertEqual(captured_payload["json_body"]["project_id"], "project-1")
        self.assertEqual(captured_payload["json_body"]["query"], "Summarize docs")
        self.assertEqual(
            captured_payload["json_body"]["history"],
            [
                {"role": "system", "content": "Be concise"},
                {"role": "assistant", "content": "Sure"},
            ],
        )
        self.assertEqual(response["choices"][0]["message"]["content"], "OK")
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


if __name__ == "__main__":
    unittest.main()
