from __future__ import annotations

import unittest

from src.ai_response_parser import parse_ai_response


class AIResponseParserTests(unittest.TestCase):
    def test_parse_valid_explanation_envelope(self) -> None:
        payload = parse_ai_response(
            '{"type":"explanation","message":"Hello","filter_plan":null,"write_proposal":null,"report_draft":null,"confidence":"high","requires_user_confirmation":false}'
        )
        self.assertEqual(payload["type"], "explanation")
        self.assertEqual(payload["message"], "Hello")
        self.assertEqual(payload["confidence"], "high")

    def test_parse_valid_filter_plan_envelope(self) -> None:
        payload = parse_ai_response(
            '{"type":"filter_plan","message":"Use this filter","filter_plan":{"table":"customers","keyword":"Makassar","filters":[],"sort_by":"id","sort_direction":"asc","limit":100},"write_proposal":null,"report_draft":null,"confidence":"medium","requires_user_confirmation":false}'
        )
        self.assertEqual(payload["type"], "filter_plan")
        self.assertEqual(payload["filter_plan"]["table"], "customers")

    def test_parse_valid_write_proposal_envelope(self) -> None:
        payload = parse_ai_response(
            '{"type":"write_proposal","message":"Propose update","filter_plan":null,"write_proposal":{"action":"update","table":"customers","primary_key_column":"id","primary_key_value":"1","changes":{"status":"inactive"},"reason":"User requested change","risk_level":"medium"},"report_draft":null,"confidence":"medium","requires_user_confirmation":true}'
        )
        self.assertEqual(payload["type"], "write_proposal")
        self.assertTrue(payload["requires_user_confirmation"])
        self.assertEqual(payload["write_proposal"]["action"], "update")

    def test_invalid_json_falls_back_to_plain_explanation(self) -> None:
        payload = parse_ai_response('{"type":"explanation","message":"oops"')
        self.assertEqual(payload["type"], "explanation")
        self.assertIn("oops", payload["message"])


if __name__ == "__main__":
    unittest.main()

