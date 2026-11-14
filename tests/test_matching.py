import tempfile
import unittest
from pathlib import Path

from materializer_core import TextureIndex, collapse_tiles, identify, udim_path


class MatchingTests(unittest.TestCase):
    def test_export_names_stay_in_the_same_texture_set(self):
        self.assertEqual(
            identify("M_veg_transparent_BaseColor_1.png"), ("Base color", "mvegtransparent")
        )
        self.assertEqual(identify("M_veg_transparent_Normal_1.png"), ("Normal", "mvegtransparent"))
        self.assertEqual(identify("TV_A.png"), ("Base color", "tv"))
        self.assertEqual(identify("TV_M.png"), ("Metalness", "tv"))
        self.assertNotEqual(identify("TV_AO.png")[0], "Base color")

    def test_udim_sets_group_all_rows_without_merging_folders(self):
        self.assertEqual(identify("robot_BaseColor.1011.png"), ("Base color", "robot"))
        self.assertEqual(identify("robot_Normal.<UDIM>.png"), ("Normal", "robot"))
        self.assertIsNone(udim_path("/assets/1001/robot_BaseColor.png"))
        self.assertIsNone(udim_path("robot_BaseColor.1000.png"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = []
            for name in ("robot_BaseColor.1001.png", "robot_BaseColor.1011.png"):
                p = root / name
                p.write_bytes(b"tile")
                files.append(p)
            self.assertEqual(collapse_tiles(files), [files[0]])
            index = TextureIndex(files)
            self.assertEqual(
                TextureIndex().resolve(str(root / "robot_BaseColor.<UDIM>.png"))[0],
                files[0].resolve(),
            )
            self.assertEqual(
                index.resolve(str(root / "robot_BaseColor.<UDIM>.png"))[0], files[0].resolve()
            )
            other = root / "other" / files[0].name
            other.parent.mkdir()
            other.write_bytes(b"different")
            self.assertEqual(len(collapse_tiles(files + [other])), 2)
            index = TextureIndex(files + [other])
            self.assertIsNone(index.resolve("/missing/robot_BaseColor.<UDIM>.png")[0])

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
