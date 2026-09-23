import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean import evidence_snapshot
from photoclean import recycle_evidence as workflow
from photoclean import recycle_review_cli, release_evidence_cli
from photoclean.diagnostics import RecycleVerificationError


class LexicalEvidencePathTests(unittest.TestCase):
    def test_absolute_helper_keeps_lexical_path_without_resolve(self):
        relative = Path("evidence") / "recycle-verification.json"
        expected = Path(os.path.abspath(os.fspath(relative)))
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
            actual = workflow._absolute_without_resolving(relative)
        self.assertEqual(actual, expected)

    def test_move_passes_lexical_manifest_to_hardened_loader(self):
        supplied = Path("evidence") / "recycle-verification.json"
        seen = []

        def stop(path):
            seen.append(path)
            raise RecycleVerificationError("sentinel")

        with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
            with patch.object(workflow, "load_recycle_verification", side_effect=stop):
                with self.assertRaisesRegex(RecycleVerificationError, "sentinel"):
                    workflow.move_restore_evidence(supplied)

        self.assertEqual(seen, [workflow._absolute_without_resolving(supplied)])

    def test_verify_passes_lexical_manifest_to_hardened_loader(self):
        supplied = Path("evidence") / "recycle-verification.json"
        seen = []

        def stop(path):
            seen.append(path)
            raise RecycleVerificationError("sentinel")

        with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
            with patch.object(workflow, "load_recycle_verification", side_effect=stop):
                with self.assertRaisesRegex(RecycleVerificationError, "sentinel"):
                    workflow.verify_restore_evidence(supplied)

        self.assertEqual(seen, [workflow._absolute_without_resolving(supplied)])

    def test_review_status_does_not_pre_resolve_manifest(self):
        supplied = Path("evidence") / "recycle-verification.json"
        seen = []

        def stop(path):
            seen.append(path)
            raise RecycleVerificationError("sentinel")

        with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
            with patch.object(
                recycle_review_cli,
                "load_recycle_verification",
                side_effect=stop,
            ):
                with self.assertRaisesRegex(RecycleVerificationError, "sentinel"):
                    recycle_review_cli._safe_status(supplied)

        self.assertEqual(seen, [workflow._absolute_without_resolving(supplied)])

    def test_attest_parser_preserves_report_and_output_ancestry(self):
        report = Path("redirected") / "recycle-evidence-report.json"
        output = Path("redirected") / "RELEASE_EVIDENCE.json"
        args = [
            os.fspath(report),
            "--output",
            os.fspath(output),
            "--confirm-manual-restore",
        ]
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
            parsed_report, parsed_output, confirmed = release_evidence_cli._parse_attest_args(args)

        self.assertEqual(parsed_report, workflow._absolute_without_resolving(report))
        self.assertEqual(parsed_output, workflow._absolute_without_resolving(output))
        self.assertTrue(confirmed)

    def test_snapshot_explicit_manifest_is_not_resolved_before_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            manifest = Path(folder) / "nested" / "recycle-verification.json"
            seen = []

            def validate(snapshot, *, manifest=None):
                seen.append(manifest)
                return object(), snapshot

            with patch.object(Path, "resolve", side_effect=AssertionError("resolve forbidden")):
                with patch.object(
                    evidence_snapshot,
                    "_read_stable_report_bytes",
                    return_value=b"{}",
                ), patch.object(
                    evidence_snapshot,
                    "validate_restore_evidence_report",
                    side_effect=validate,
                ):
                    evidence_snapshot.load_validated_restore_evidence_snapshot(
                        report,
                        manifest=manifest,
                    )

            self.assertEqual(
                seen,
                [evidence_snapshot._absolute_without_resolving(manifest)],
            )

    def test_snapshot_rejects_redirected_report_parent_when_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "real"
            real.mkdir()
            report = real / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            alias = root / "alias"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")

            redirected = alias / report.name
            with self.assertRaisesRegex(
                RecycleVerificationError,
                "directory ancestry must not contain",
            ):
                evidence_snapshot._read_stable_report_bytes(redirected)


if __name__ == "__main__":
    unittest.main()
