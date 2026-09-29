from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer" / "SwirPhotoClean.iss"
WORKFLOW = ROOT / ".github" / "workflows" / "windows.yml"


class InstallerContractTests(unittest.TestCase):
    def test_installer_is_per_user_and_packages_exact_qa_directory(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\SwirPhotoClean", text)
        self.assertIn(r'Source: "..\dist\SwirPhotoClean\*"', text)
        self.assertIn("SwirPhotoClean-{#MyAppVersion}-Windows-Setup", text)
        self.assertIn(r"SetupIconFile=..\assets\SwirPhotoClean.ico", text)

    def test_windows_ci_installs_smokes_and_uninstalls_installer(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "Build Windows installer",
            "Smoke-test Windows installer",
            "SwirPhotoClean-windows-installer",
            "unins000.exe",
            "--self-test",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, workflow)

    def test_release_pipeline_includes_installer_integrity_assets(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("$installerChecksum", workflow)
        self.assertIn("$installerProvenance", workflow)
        self.assertIn("Test-InstallerPackage", workflow)


if __name__ == "__main__":
    unittest.main()
