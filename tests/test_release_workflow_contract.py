from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows.yml"


class ReleaseWorkflowPublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_normal_windows_job_uses_candidate_build_gate(self):
        self.assertIn("python tools/release_gate.py --build-check", self.workflow)

    def test_publication_requires_explicit_prefix_and_strict_gate(self):
        self.assertIn(
            "startsWith(github.event.head_commit.message, '[publish-release] ')",
            self.workflow,
        )
        release_section = self.workflow.split("\n  release:\n", 1)[1]
        self.assertIn("python tools/release_gate.py --check", release_section)
        self.assertNotIn(
            "contains(github.event.head_commit.message, '[publish-release]')",
            release_section,
        )
        self.assertNotIn(
            "startsWith(github.event.head_commit.message, 'release:')",
            release_section,
        )

    def test_release_trigger_cannot_be_armed_by_token_in_commit_body(self):
        release_section = self.workflow.split("\n  release:\n", 1)[1]
        self.assertIn("prefix of the main-branch head commit message", release_section)
        self.assertIn("merely mentioning it in", release_section)

    def test_packaged_attestation_dispatch_is_smoke_tested(self):
        self.assertIn("'--recycle-restore-attest'", self.workflow)

    def test_release_assets_are_staged_and_verified_before_publication(self):
        text = self.workflow
        stable_create = (
            'gh release create "v$version" @releaseAssets --target $env:GITHUB_SHA '
            '--title "SWIR PhotoClean $version — Polski / English" '
            '--notes-file RELEASE_NOTES.md --draft'
        )
        prerelease_create = stable_create + " --prerelease"
        staged_verify = "Test-ReleaseAssets -Root $stagedRoot -Label 'draft'"
        publish = 'gh release edit "v$version" --draft=false'
        public_verify = "Test-ReleaseAssets -Root $publishedRoot -Label 'published'"

        self.assertIn(stable_create, text)
        self.assertIn(prerelease_create, text)
        self.assertIn(staged_verify, text)
        self.assertIn(publish, text)
        self.assertIn(public_verify, text)
        self.assertLess(text.index(staged_verify), text.index(publish))
        self.assertLess(text.index(publish), text.index(public_verify))

    def test_public_verification_failure_retracts_release_to_draft(self):
        text = self.workflow
        public_verify = "Test-ReleaseAssets -Root $publishedRoot -Label 'published'"
        rollback = 'gh release edit "v$version" --draft\n            if ($LASTEXITCODE -ne 0)'
        self.assertIn("try {", text)
        self.assertIn("catch {", text)
        self.assertIn(rollback, text)
        self.assertLess(text.index(public_verify), text.index(rollback))

    def test_published_channel_state_is_verified(self):
        text = self.workflow
        self.assertIn("gh release view \"v$version\" --json isDraft --jq '.isDraft'", text)
        self.assertIn("gh release view \"v$version\" --json isPrerelease --jq '.isPrerelease'", text)
        self.assertIn("Published release is still a draft", text)
        self.assertIn("Published release channel does not match release gate", text)


if __name__ == "__main__":
    unittest.main()
