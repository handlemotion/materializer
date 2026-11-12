import tempfile
import unittest
from pathlib import Path

from materializer_core import TextureIndex, identify


class MatchingTests(unittest.TestCase):
    def test_export_names_stay_in_the_same_texture_set(self):
        self.assertEqual(
            identify("M_veg_transparent_BaseColor_1.png"), ("Base color", "mvegtransparent")
        )
        self.assertEqual(identify("M_veg_transparent_Normal_1.png"), ("Normal", "mvegtransparent"))
        self.assertEqual(identify("TV_A.png"), ("Base color", "tv"))
        self.assertEqual(identify("TV_M.png"), ("Metalness", "tv"))
        self.assertNotEqual(identify("TV_AO.png")[0], "Base color")

    def test_windows_and_unc_paths_use_the_filename(self):
        for path in (
            r"C:\Users\Friend\Textures\Plant_BaseColor.png",
            r"\\server\assets\Plant_BaseColor.png",
        ):
            self.assertEqual(identify(path), ("Base color", "plant"))

    def test_conflicting_files_are_never_chosen_arbitrarily(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a = root / "one" / "wood_BaseColor.png"
            b = root / "two" / a.name
            a.parent.mkdir()
            b.parent.mkdir()
            a.write_bytes(b"first")
            b.write_bytes(b"other")
            index = TextureIndex([a, b])
            self.assertIsNone(index.resolve("/missing/" + a.name)[0])
            b.write_bytes(a.read_bytes())
            self.assertIn(index.resolve("/missing/" + a.name)[0], (a.resolve(), b.resolve()))


if __name__ == "__main__":
    unittest.main()
