import unittest

from tools.release_gate import (
    ReleaseGateError,
    parse_version,
    release_channel,
    validate_release_notes,
)


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


if __name__ == "__main__":
    unittest.main()
