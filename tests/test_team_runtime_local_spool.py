import json
import tempfile
import unittest
from pathlib import Path

from core.team_runtime import LocalTeamRuntimeSpool


class LocalSpoolTests(unittest.TestCase):
    def _task(self, root, message_id="M-1"):
        p = Path(root) / "inbox" / f"{message_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"message_id": message_id, "task_id": "TEAM-RUNTIME-001", "body": {"request": "harmless"}}), encoding="utf-8")
        return p

    def test_verified_result_emits_evidence_and_persistent_dedupe_across_restart(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def handler(env, trace_id):
                calls.append((env.message_id, trace_id))
                return {"status": "VERIFIED", "evidence": {"kind": "test"}}
            spool = LocalTeamRuntimeSpool(td, handler)
            task = self._task(td)
            first = spool.process_file(task)
            self.assertEqual(first["status"], "VERIFIED")
            event = json.loads(Path(first["outbox"]).read_text(encoding="utf-8"))
            self.assertEqual(event["type"], "EVIDENCE")
            self.assertEqual(event["ack_of"], "M-1")
            restarted = LocalTeamRuntimeSpool(td, handler)
            second = restarted.process_file(task)
            self.assertEqual(second["status"], "DUPLICATE")
            self.assertEqual(len(calls), 1)

    def test_handler_failure_is_fail_closed_and_not_marked_processed(self):
        with tempfile.TemporaryDirectory() as td:
            def broken(env, trace_id):
                raise PermissionError("denied")
            spool = LocalTeamRuntimeSpool(td, broken)
            result = spool.process_file(self._task(td))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reason"], "AUTHORIZED_PIPELINE_FAILED")
            self.assertEqual(list((Path(td) / "outbox").glob("*.json")), [])
            self.assertEqual(list((Path(td) / "state" / "processed").glob("*.json")), [])

    def test_invalid_envelope_never_calls_handler(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            spool = LocalTeamRuntimeSpool(td, lambda env, trace: calls.append(1) or {"status": "VERIFIED"})
            p = Path(td) / "bad.json"
            p.write_text('{"task_id":"x","body":{}}', encoding="utf-8")
            result = spool.process_file(p)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reason"], "INVALID_ENVELOPE")
            self.assertFalse(calls)

    def test_non_terminal_or_untrusted_handler_status_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            spool = LocalTeamRuntimeSpool(td, lambda env, trace: {"status": "SUCCESS"})
            result = spool.process_file(self._task(td))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reason"], "AUTHORIZED_PIPELINE_FAILED")


if __name__ == "__main__":
    unittest.main()
