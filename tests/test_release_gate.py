import unittest

from tools.release_gate import (
    ReleaseGateError,
    parse_version,
    release_channel,
    runtime_evidence_required,
    validate_qualified_acceptance,
    validate_release_notes,
)
from tools.release_evidence import ReleaseEvidenceError, validate_release_evidence


def valid_runtime_evidence():
    return {
        "schema_version": 1,
        "kind": "windows-recycle-restore",
        "session_id": "a" * 32,
        "fixture_sha256": "b" * 64,
        "manifest_fingerprint": "c" * 64,
        "evidence_report_sha256": "d" * 64,
        "verified_at_utc": "2026-09-21T05:00:00+00:00",
        "reviewed_at_utc": "2026-09-21T05:05:00+00:00",
        "physical_recycle_move_confirmed": True,
        "manual_restore_performed": True,
        "original_preserved": True,
        "restored_copy_sha256_verified": True,
        "report_review_valid": True,
        "acceptance_gate_closed": False,
    }


class ReleaseGateTests(unittest.TestCase):
    def test_zero_major_release_stays_prerelease(self):
        self.assertEqual(release_channel("0.3.0", 7, 8), "prerelease")

    def test_explicit_release_candidate_stays_prerelease(self):
        self.assertEqual(release_channel("1.0.0-rc.1", 7, 8), "prerelease")

    def test_stable_1_0_is_blocked_until_acceptance_is_complete(self):
        with self.assertRaisesRegex(ReleaseGateError, "7/8"):
            release_channel("1.0.0", 7, 8)

    def test_stable_1_0_is_allowed_only_when_acceptance_is_complete(self):
        self.assertEqual(release_channel("1.0.0", 8, 8), "stable")

    def test_invalid_acceptance_metrics_fail_closed(self):
        with self.assertRaises(ReleaseGateError):
            release_channel("1.0.0", 9, 8)

    def test_version_is_read_from_project_assignment(self):
        self.assertEqual(parse_version('__version__ = "1.0.0"\n'), "1.0.0")

    def test_non_semantic_version_is_rejected(self):
        with self.assertRaises(ReleaseGateError):
            parse_version('__version__ = "1.0"\n')

    def test_release_notes_must_match_exact_version(self):
        validate_release_notes("0.3.0", "# SWIR PhotoClean 0.3.0\n\nNotes\n")
        with self.assertRaises(ReleaseGateError):
            validate_release_notes("1.0.0", "# SWIR PhotoClean 0.3.0\n")

    def test_qualified_prerelease_is_blocked_until_acceptance_is_complete(self):
        with self.assertRaisesRegex(ReleaseGateError, "7/8"):
            validate_qualified_acceptance("1.0.0-rc.1", 7, 8)
        validate_qualified_acceptance("1.0.0-rc.1", 8, 8)
        validate_qualified_acceptance("0.3.0", 7, 8)

    def test_runtime_evidence_is_required_for_qualified_beta_rc_and_1_x(self):
        self.assertTrue(runtime_evidence_required("0.4.0-beta.1"))
        self.assertTrue(runtime_evidence_required("0.4.0-rc.2"))
        self.assertTrue(runtime_evidence_required("1.0.0-rc.1"))
        self.assertTrue(runtime_evidence_required("1.0.0"))
        self.assertFalse(runtime_evidence_required("0.3.0"))
        self.assertFalse(runtime_evidence_required("0.4.0-alpha.1"))

    def test_valid_runtime_evidence_contract_is_accepted(self):
        validated = validate_release_evidence(valid_runtime_evidence())
        self.assertEqual(validated["kind"], "windows-recycle-restore")
        self.assertFalse(validated["acceptance_gate_closed"])

    def test_runtime_evidence_required_flags_fail_closed(self):
        for field in (
            "physical_recycle_move_confirmed",
            "manual_restore_performed",
            "original_preserved",
            "restored_copy_sha256_verified",
            "report_review_valid",
        ):
            with self.subTest(field=field):
                payload = valid_runtime_evidence()
                payload[field] = False
                with self.assertRaises(ReleaseEvidenceError):
                    validate_release_evidence(payload)

    def test_runtime_evidence_identifiers_and_hashes_are_strict(self):
        payload = valid_runtime_evidence()
        payload["session_id"] = "not-a-session"
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(payload)

        payload = valid_runtime_evidence()
        payload["evidence_report_sha256"] = "ABC"
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(payload)

    def test_runtime_evidence_review_cannot_predate_verification(self):
        payload = valid_runtime_evidence()
        payload["reviewed_at_utc"] = "2026-09-21T04:59:59+00:00"
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(payload)

    def test_runtime_evidence_cannot_claim_to_close_acceptance_gate(self):
        payload = valid_runtime_evidence()
        payload["acceptance_gate_closed"] = True
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(payload)

    def test_runtime_evidence_rejects_unknown_fields(self):
        payload = valid_runtime_evidence()
        payload["comment"] = "ambiguous extra data"
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(payload)


if __name__ == "__main__":
    unittest.main()
