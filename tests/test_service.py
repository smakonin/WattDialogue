# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from http.cookiejar import CookieJar
from pathlib import Path

from wattdialogue.config import Settings
from wattdialogue.openai_agent import APIError, OpenAIAgent
from wattdialogue.server import DisplayServer
from wattdialogue.service import WattDialogueService, fields_from_evidence


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.clean_environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_API_KEY_BACKUP": ""})
        self.clean_environment.start()
        self.addCleanup(self.clean_environment.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = self.root / "test.env"
        self.env.write_text("OPENAI_API_KEY=\nOPENAI_API_KEY_BACKUP=\n")
        self.service = WattDialogueService(env_file=self.env, registry_path=self.root / "labels.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_default_service_is_synthetic_and_home_scoped(self):
        result = self.service.summary("R1Hz", 17422)
        self.assertTrue(result["synthetic_fixture"])
        self.assertEqual(result["input_kind"], "synthetic")
        self.assertGreater(result["total_energy_kwh"], 0)
        self.assertLess(result["coverage"], 1)
        self.assertTrue(result["freshness"]["archive_replay"])
        self.assertTrue(result["components"])
        with self.assertRaises(ValueError):
            self.service.query({"home": "AMPds2", "block_id": 17422}, "R1Hz")

    def test_cloud_requires_consent_without_making_a_call(self):
        with self.assertRaisesRegex(ValueError, "consent"):
            self.service.query({"question": "What used electricity?", "block_id": 17422,
                                "mode": "openai", "consent": False}, "R1Hz")
        self.assertEqual(self.service.agent.calls, 0)

    def test_unconfigured_cloud_falls_back_honestly(self):
        result = self.service.query({"question": "What used electricity?", "block_id": 17422,
                                     "mode": "openai", "consent": True}, "R1Hz")
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["cloud_error"]["code"], "not_configured")

    def test_future_evidence_and_nested_scope_are_rejected(self):
        start, end = self.service.bounds("R1Hz", 17422)
        with self.assertRaisesRegex(ValueError, "after"):
            self.service.execute("get_window_summary", {"block_id": 17422, "as_of": end}, "R1Hz", 17422, start)
        with self.assertRaisesRegex(ValueError, "availability"):
            self.service.execute("compare_periods", {"period_a": {"block_id": 17422, "start": start,
                                       "end": end, "as_of": end}, "period_b": {}}, "R1Hz", 17422, start)

    def test_comparison_cannot_inherit_another_session_block(self):
        with self.assertRaisesRegex(ValueError, "session"):
            self.service.execute("compare_periods", {"block_id": 17428, "period_a": {}, "period_b": {}},
                                 "R1Hz", 17422)

    def test_cloud_mode_is_fixed_by_the_selected_evaluation_arm(self):
        with self.assertRaisesRegex(ValueError, "mode"):
            self.service.execute("get_window_summary", {"block_id": 17422, "mode": "revised"},
                                 "R1Hz", 17422, fixed_mode="online")

    def test_partial_summary_preserves_coverage_and_evidence_availability(self):
        start, end = self.service.bounds("R1Hz", 17422)
        summary = self.service.summary("R1Hz", 17422, start + 60)
        self.assertLess(summary["coverage"], 1)
        self.assertIn("coverage_details", summary)
        self.assertNotEqual(summary["available_time"], summary["observation_end"])

    def model_response(self, **changes):
        start, end = self.service.bounds("R1Hz", 17422)
        evidence = self.service.execute("get_component_features", {"block_id": 17422,
                 "component_id": "component_000", "start": start, "end": end, "as_of": end}, "R1Hz")
        result = {"answer": "This may be a refrigerator; its identity is uncertain.",
                  "evidence_ids": [evidence["evidence_id"]], "tool_evidence": [evidence],
                  "label_candidates": [], "clarification": None, "comfort_notes": [],
                  "usage": {"calls": 0}}
        result.update(changes)
        self.service.agent.run = lambda *args: result
        return result

    def cloud_query(self):
        return self.service.query({"question": "Help name component_000", "block_id": 17422,
                                   "mode": "openai", "consent": True}, "R1Hz")

    def test_model_screen_covers_clarification_and_candidate_reason_before_writes(self):
        result = self.model_response(clarification="Your bill will fall by 25 percent.")
        self.assertEqual(self.cloud_query()["mode"], "local")
        candidate = {"component_id": "component_000", "label": "fridge",
                     "reason": "This is definitely a fridge.", "alternatives": [],
                     "evidence_id": result["evidence_ids"][0]}
        self.model_response(label_candidates=[candidate])
        self.assertEqual(self.cloud_query()["mode"], "local")
        self.assertEqual(self.service.labels.get("R1Hz", "component_000", model_version=self.service.store.model_version)["status"], "unknown")

    def test_unqualified_appliance_identity_is_not_accepted(self):
        self.model_response(answer="Your refrigerator ran throughout the period.")
        self.assertEqual(self.cloud_query()["mode"], "local")

    def test_candidate_confirmation_uses_fresh_summary_evidence(self):
        result = self.model_response()
        candidate = {"component_id": "component_000", "label": "fridge",
                     "reason": "A fridge is a possible candidate.", "alternatives": ["freezer"],
                     "evidence_id": result["evidence_ids"][0]}
        self.model_response(label_candidates=[candidate], comfort_notes=["Your stated comfort limits still apply."])
        response = self.cloud_query()
        self.assertEqual(response["mode"], "openai")
        self.assertIn("comfort limits", response["answer"])
        proposed = response["label_candidates"][0]
        fresh = self.service.summary("R1Hz", 17422)
        self.assertEqual(proposed["confirmation_evidence_id"], fresh["evidence_id"])
        record = self.service.confirm_label({"block_id": 17422, "component_id": "component_000",
                    "label": "Fridge", "confirm": True, "model_version": fresh["model_version"],
                    "evidence_id": proposed["confirmation_evidence_id"]}, "R1Hz")["record"]
        self.assertEqual(record["status"], "occupant-confirmed")
        self.model_response(label_candidates=[{**candidate, "label": "freezer"}])
        self.cloud_query()
        self.assertEqual(self.service.labels.get("R1Hz", "component_000", model_version=self.service.store.model_version)["label"], "Fridge")

    def test_no_available_samples_do_not_become_zero_energy(self):
        start, _ = self.service.bounds("R1Hz", 17422)
        result = self.service.local_query({"question": "What used electricity?", "block_id": 17422,
                                           "as_of": start}, "R1Hz")
        self.assertTrue(result["abstained"])
        self.assertFalse(any(f["metric"] == "energy_kwh" for f in result["fields"]))

    def test_component_fields_are_estimates(self):
        fields = fields_from_evidence([{"component_id": "component_012", "energy_kwh": .4,
                                         "component_energy_kwh": .4, "average_power_w": 80}])
        self.assertTrue(all(f["source"] == "nilm_estimate" for f in fields))

    def test_label_requires_current_evidence_and_retains_simulation_source(self):
        result = self.service.summary("R1Hz", 17422)
        comp = result["components"][0]
        payload = {"home": "R1Hz", "block_id": 17422, "component_id": comp["component_id"],
                   "label": "Fridge", "confirm": True, "model_version": comp["model_version"],
                   "evidence_id": comp["evidence_id"]}
        confirmation = self.service.confirm_label(payload, "R1Hz")
        self.assertTrue(confirmation["record"]["source"]["simulation"])
        self.assertFalse(confirmation["record"]["definitive_identity"])
        with self.assertRaises(ValueError):
            self.service.confirm_label({**payload, "evidence_id": "invented"}, "R1Hz")


class APIBudgetTests(unittest.TestCase):
    def test_quota_backup_does_not_bypass_total_call_cap(self):
        keys = []
        def transport(payload, key):
            keys.append(key)
            if key == "PRIMARY_TEST_VALUE":
                raise APIError("insufficient_quota", "quota")
            return {"usage": {"input_tokens": 1, "output_tokens": 2}}
        agent = OpenAIAgent(lambda: Settings(primary_key="PRIMARY_TEST_VALUE", backup_key="BACKUP_TEST_VALUE",
                                            live_call_limit=2), transport)
        agent._request({})
        self.assertEqual(keys, ["PRIMARY_TEST_VALUE", "BACKUP_TEST_VALUE"])
        self.assertTrue(agent.backup_used)
        with self.assertRaisesRegex(APIError, "cap"):
            agent._request({})
        self.assertEqual(agent.calls, 2)

    def test_authentication_error_does_not_silently_switch_key(self):
        def transport(payload, key):
            raise APIError("invalid_api_key", "invalid")
        agent = OpenAIAgent(lambda: Settings(primary_key="PRIMARY_TEST_VALUE", backup_key="BACKUP_TEST_VALUE"), transport)
        with self.assertRaises(APIError):
            agent._request({})
        self.assertFalse(agent.backup_used)
        self.assertEqual(agent.calls, 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean_environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_API_KEY_BACKUP": ""})
        cls.clean_environment.start()
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        env = root / "empty.env"
        env.write_text("OPENAI_API_KEY=\n")
        cls.service = WattDialogueService(env_file=env, registry_path=root / "labels.json")
        cls.server = DisplayServer(("127.0.0.1", 0), cls.service)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.directory.cleanup()
        cls.clean_environment.stop()

    def test_credentials_and_private_oracle_are_not_served(self):
        for path in ("/.env.local", "/benchmark/private/expected.jsonl", "/../.env.local"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(caught.exception.code, 404)

    def test_session_scope_csrf_and_explicit_archive_change(self):
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        status = json.load(opener.open(self.base + "/api/status"))
        self.assertNotIn("primary_key", status)
        self.assertNotIn("backup_key", status)
        def post(path, payload, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["X-WattDialogue-Token"] = token
            return opener.open(urllib.request.Request(self.base + path, json.dumps(payload).encode(), headers))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post("/api/home", {"home": "AMPds2"})
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            opener.open(self.base + "/api/blocks?home=AMPds2")
        self.assertEqual(caught.exception.code, 403)
        json.load(post("/api/home", {"home": "AMPds2"}, status["csrf_token"]))
        blocks = json.load(opener.open(self.base + "/api/blocks?home=AMPds2"))
        self.assertEqual(blocks["home"], "AMPds2")


if __name__ == "__main__":
    unittest.main()
