from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "RECYCLE_RESTORE_RELEASE_TEST.md"
ENTRYPOINT = ROOT / "run.py"


class ReleaseRunbookContractTests(unittest.TestCase):
    def test_operator_runbook_tracks_packaged_cli_contract(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

        required_commands = (
            "--self-test",
            "--recycle-restore-prepare",
            "--recycle-restore-verify",
            "--recycle-restore-review",
            "--recycle-restore-attest",
        )
        for command in required_commands:
            with self.subTest(command=command):
                self.assertIn(command, runbook)
                self.assertIn(command, entrypoint)

        self.assertIn("--confirm-manual-restore", runbook)
        self.assertIn("ACCEPTANCE_GATE_CLOSED=no", runbook)

    def test_runbook_keeps_release_gate_fail_closed(self):
        runbook = RUNBOOK.read_text(encoding="utf-8").lower()
        self.assertIn("does not authorize a release by itself", runbook)
        self.assertIn("never use permanent deletion as a fallback", runbook)


if __name__ == "__main__":
    unittest.main()
