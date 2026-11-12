import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_materializer as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "download"
        self.target = root / "installed"
        self.source.mkdir()
        self.target.mkdir()
        for name in installer.MODULES:
            (self.source / name).write_text("version = 2\n")
            (self.target / name).write_text("version = 1\n")

    def test_invalid_download_leaves_installed_files_untouched(self):
        (self.source / installer.MODULES[1]).write_text("invalid python !")
        with self.assertRaises(SyntaxError):
            installer.install_files(self.source, self.target)
        for name in installer.MODULES:
            self.assertEqual((self.target / name).read_text(), "version = 1\n")

    def test_partial_update_rolls_back_both_modules(self):
        replace = installer.os.replace
        calls = 0

        def fail_second(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk error")
            replace(source, target)

        with patch.object(installer.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                installer.install_files(self.source, self.target)
        for name in installer.MODULES:
            self.assertEqual((self.target / name).read_text(), "version = 1\n")
        self.assertEqual(len(list(self.target.iterdir())), len(installer.MODULES))

    def test_reinstall_uses_the_same_files(self):
        installer.install_files(self.source, self.target)
        installer.install_files(self.source, self.target)
        self.assertEqual(len(list(self.target.iterdir())), len(installer.MODULES))
        for name in installer.MODULES:
            self.assertEqual((self.target / name).read_text(), "version = 2\n")


if __name__ == "__main__":
    unittest.main()
