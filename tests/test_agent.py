"""Offline protocol/validation tests: python -m unittest discover -s tests -v."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from pydantic import ValidationError

from src.agent import (
    NIMAgent, NIMRequestError, StructuredOutputError, SYSTEM_PROMPT,
    TOOL_NAME, analysis_tool, analyze_documents,
)
from src.schemas import AnalysisRequest, AnalysisResult


def request_data():
    return {
        "before": [{"id": "v8", "name": "До", "clauses": [
            {"id": "3.4", "text": "Блок включает ДНМ и ДККМ."},
            {"id": "2.1", "text": "ДНМ проверяет сохранность активов."},
        ]}],
        "after": [{"id": "v9", "name": "После", "clauses": [
            {"id": "3.4", "text": "Блок включает ДИТААД, ДОА, ДНМ и ДККМ."},
            {"id": "2.2", "text": "ДНМ проверяет сохранность активов."},
            {"id": "2.3", "text": "ДОА проверяет сохранность активов."},
        ]}],
    }


def source(side="before", clause="3.4", quote="ДНМ"):
    return {"side": side, "document_id": "v8" if side == "before" else "v9",
            "clause_id": clause, "quote": quote}


def result_data():
    return {
        "unit_changes": [{"status": "preserved", "before_units": ["ДНМ"],
                          "after_units": ["ДНМ"], "explanation": "Подразделение сохранено.",
                          "sources": [source(), source("after")]}],
        "function_mappings": [{"function": "Проверка сохранности активов",
                               "status": "preserved", "before_units": ["ДНМ"],
                               "after_units": ["ДНМ"], "explanation": "Изменился номер пункта.",
                               "sources": [source("before", "2.1", "ДНМ проверяет сохранность активов."),
                                           source("after", "2.2", "ДНМ проверяет сохранность активов.")]}],
        "findings": [], "summary": "ДНМ и его функция сохранены.",
        "limitations": [], "requires_human_review": True,
    }


def response(data=None, *, arguments=None, reason="tool_calls", name=TOOL_NAME):
    return {"choices": [{"finish_reason": reason, "message": {"tool_calls": [
        {"type": "function", "id": "call_1", "function": {
            "name": name, "arguments": arguments if arguments is not None else json.dumps(data or result_data()),
        }},
    ]}}]}


def object_response(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: object_response(v) for k, v in value.items()})
    if isinstance(value, list):
        return [object_response(v) for v in value]
    return value


class AgentTests(unittest.TestCase):
    def agent(self, responses, **kwargs):
        client = Mock()
        client.chat.completions.create.side_effect = responses
        return NIMAgent(model="test-model", client=client, **kwargs), client

    def test_success_and_tool_contract(self):
        agent, client = self.agent([object_response(response())])
        result = agent.analyze(request_data())
        self.assertEqual(result.function_mappings[0].status, "preserved")
        self.assertTrue(result.requires_human_review)
        self.assertTrue(result.limitations)
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["tool_choice"]["function"]["name"], TOOL_NAME)
        self.assertEqual(call["tools"], [analysis_tool()])
        self.assertFalse(call["stream"])
        self.assertIn("недоверенные данные", call["messages"][0]["content"])
        self.assertEqual(call["messages"][0]["content"], SYSTEM_PROMPT)
        self.assertNotIn("strict", call["tools"][0]["function"])

    def test_schema_contains_required_fields_and_rejects_extra(self):
        schema = analysis_tool()["function"]["parameters"]
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("sources", schema["$defs"]["Finding"]["required"])
        bad = result_data()
        bad["external_claim"] = "unknown"
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(bad)

    def test_repair_malformed_then_valid(self):
        agent, client = self.agent([response(arguments="{oops"), response()])
        agent.analyze(request_data())
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertIn("Malformed JSON", client.chat.completions.create.call_args.kwargs["messages"][-1]["content"])

    def test_invalid_responses_are_bounded(self):
        bad_ref = result_data()
        bad_ref["unit_changes"][0]["sources"][0]["clause_id"] = "999"
        bad_quote = result_data()
        bad_quote["unit_changes"][0]["sources"][0]["quote"] = "fabricated"
        missing = result_data()
        del missing["summary"]
        multiple = response()
        multiple["choices"][0]["message"]["tool_calls"] *= 2
        invalid = [response(bad_ref), response(bad_quote), response(missing),
                   response(arguments='{"summary":"one","summary":"two"}'),
                   response(reason="length"), response(reason="content_filter"),
                   response(name="execute_shell"), multiple, {},
                   {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result_data())}}]}]
        for value in invalid:
            with self.subTest(value=value):
                agent, client = self.agent([value, value], max_attempts=2)
                with self.assertRaises(StructuredOutputError):
                    agent.analyze(request_data())
                self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_source_whitespace_and_document_side(self):
        req = request_data()
        req["before"][0]["clauses"][1]["text"] = "ДНМ\nпроверяет   сохранность активов."
        AnalysisResult.model_validate(result_data()).validate_sources(AnalysisRequest.model_validate(req))
        req["before"][0]["id"] = "different"
        with self.assertRaises(ValueError):
            AnalysisResult.model_validate(result_data()).validate_sources(AnalysisRequest.model_validate(req))

    def test_input_is_validated_before_network(self):
        invalid = request_data()
        invalid["before"][0]["clauses"].append(invalid["before"][0]["clauses"][0])
        other = request_data()
        other["after"].append(other["after"][0])
        for req in [invalid, other, {"before": [], "after": []}]:
            agent, client = self.agent([])
            with self.assertRaises(ValidationError):
                agent.analyze(req)
            client.chat.completions.create.assert_not_called()

    def test_large_input_never_silently_truncated(self):
        agent, client = self.agent([], max_input_chars=10)
        with self.assertRaisesRegex(ValueError, "no documents were sent or truncated"):
            agent.analyze(request_data())
        client.chat.completions.create.assert_not_called()

    def test_provider_errors_do_not_leak_or_retry_as_json(self):
        agent, client = self.agent([RuntimeError("secret document or API key")])
        with self.assertRaises(NIMRequestError) as caught:
            agent.analyze(request_data())
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_cross_version_and_review_validation(self):
        for mutate in [
            lambda d: d.update(requires_human_review=False),
            lambda d: d.update(requires_human_review="true"),
            lambda d: d["unit_changes"][0].update(sources=[source()]),
            lambda d: d["function_mappings"][0].update(sources=[source()]),
        ]:
            bad = result_data()
            mutate(bad)
            agent, _ = self.agent([response(bad)], max_attempts=1)
            with self.assertRaises(StructuredOutputError):
                agent.analyze(request_data())

    def test_duplication_requires_distinct_after_evidence(self):
        data = result_data()
        finding = {"kind": "duplication", "severity": "medium", "units": ["ДНМ", "ДОА"],
                   "description": "Возможное пересечение функции.", "recommendation": "Уточнить границы.",
                   "sources": [source("after", "2.2", "ДНМ проверяет сохранность активов."),
                               source("after", "2.3", "ДОА проверяет сохранность активов.")]}
        data["findings"] = [finding]
        AnalysisResult.model_validate(data).validate_sources(AnalysisRequest.model_validate(request_data()))
        finding["sources"][1] = copy.deepcopy(finding["sources"][0])
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(data)

    def test_loss_requires_before_evidence(self):
        data = result_data()
        data["findings"] = [{"kind": "function_loss", "severity": "high", "units": ["ДНМ"],
                             "description": "Потенциальная потеря.", "recommendation": "Проверить передачу.",
                             "sources": [source("after")]}]
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(data)

    def test_convenience_api_does_not_close_injected_client(self):
        _, client = self.agent([response()])
        req = request_data()
        result = analyze_documents(req["before"], req["after"], model="test", client=client)
        self.assertIsInstance(result, AnalysisResult)
        client.close.assert_not_called()

    def test_missing_model_and_key_fail_explicitly(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "NIM_MODEL"):
                NIMAgent()
            with self.assertRaisesRegex(ValueError, "NVIDIA_API_KEY"):
                NIMAgent(model="test")

    def test_real_sdk_serialization_with_mock_http(self):
        received = []

        def handler(request):
            received.append(json.loads(request.content))
            self.assertEqual(request.url.path, "/v1/chat/completions")
            body = response()
            body.update(id="completion-1", object="chat.completion", created=0, model="test-model")
            body["choices"][0]["index"] = 0
            body["choices"][0]["message"].update(role="assistant", content=None)
            return httpx.Response(200, json=body)

        with OpenAI(api_key="offline-test", base_url="https://nim.test/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            agent = NIMAgent(model="test-model", client=client)
            result = agent.analyze(request_data())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["tools"][0]["function"]["name"], TOOL_NAME)
        self.assertEqual(result.unit_changes[0].status, "preserved")

    def test_owned_sdk_client_uses_settings_and_closes(self):
        with patch.dict("os.environ", {}, clear=True), patch("openai.OpenAI") as factory:
            factory.return_value.chat.completions.create.return_value = response()
            with NIMAgent(model="test-model", api_key="offline-test", timeout=45) as agent:
                agent.analyze(request_data())
            self.assertEqual(factory.call_args.kwargs["timeout"], 45)
            self.assertEqual(factory.call_args.kwargs["base_url"], "https://integrate.api.nvidia.com/v1")
            factory.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
