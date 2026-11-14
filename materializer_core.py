"""Texture filename matching. No Maya dependency."""

import hashlib
import re
from collections import defaultdict
from pathlib import Path

EXTENSIONS = {".png", ".jpg", ".jpeg", ".exr", ".tga", ".tif", ".tiff", ".bmp"}
ROLES = [
    ("Base color", r"base[ _-]*colou?r|albedo|diffuse|(?<![a-z])diff(?![a-z])"),
    ("Normal", r"normal(?:map)?|(?<![a-z])nor(?:[ _-]*(?:gl|dx))?(?![a-z])"),
    ("Roughness", r"roughness|(?<![a-z])rough(?![a-z])"),
    ("Metalness", r"metallic|metalness"),
    ("Opacity", r"opacity|cutout|(?<![a-z])alpha(?![a-z])"),
    ("Emission", r"emissi(?:on|ve)(?:[ _-]*colou?r)?"),
    ("Glossiness", r"glossiness|(?<![a-z])gloss(?![a-z])"),
    ("Packed ORM", r"(?<![a-z])(?:orm|arm|rma|raom)(?![a-z])"),
]


def udim_path(path):
    """Return a tile pattern only for a delimited UDIM number in the filename."""
    path = Path(path)
    match = re.search(r"(?<=[._-])(1\d{3})(?=[._-])", path.name)
    if not match or int(match[1]) < 1001:
        return None
    return path.with_name(path.name[: match.start()] + "<UDIM>" + path.name[match.end() :])


def collapse_tiles(paths):
    families = {}
    for value in paths:
        path = Path(value)
        key = str(udim_path(path) or path)
        families[key] = min(path, families.get(key, path))
    return list(families.values())


def compact(value):
    return re.sub("[^a-z0-9]", "", value.lower())


def identify(path):
    stem = Path(str(path).replace("\\", "/")).stem.lower().replace("<udim>", "1001")
    short = re.fullmatch(r"(.+)[_. -](a|n|r|m)(?:[_. -](?:[1248]k|1\d{3}))?", stem)
    if short:
        return {"a": "Base color", "n": "Normal", "r": "Roughness", "m": "Metalness"}[
            short[2]
        ], compact(short[1])
    for role, pattern in ROLES:
        match = re.search(pattern, stem)
        if match:
            group = stem[: match.start()] + stem[match.end() :]
            group = re.sub(r"(?:[._ -](?:1\d{3}|[124816]+k|opengl|directx|gl|dx|\d+))+$", "", group)
            return role, compact(group)
    return None, compact(stem)


def material_key(name):
    name = name.rsplit(":", 1)[-1]
    name = re.sub(r"FBXASC\d+", "_", name)
    name = re.sub(r"(?:_texture|_material|_mtl|_mat)$", "", name, flags=re.I)
    return compact(name)


class TextureIndex:
    def __init__(self, paths=()):
        self.by_name = defaultdict(list)
        self.by_group = defaultdict(list)
        self.by_udim_name = defaultdict(list)
        for value in paths:
            path = Path(value).resolve()
            self.by_name[path.name.casefold()].append(path)
            pattern = udim_path(path)
            if pattern:
                self.by_udim_name[pattern.name.casefold()].append(path)
            role, group = identify(path)
            if role:
                self.by_group[group].append((role, path))

    def resolve(self, original):
        path = Path(original)
        if path.is_file():
            return path.resolve(), "existing path"
        filename = original.replace("\\", "/").rsplit("/", 1)[-1]
        if "<udim>" in filename.casefold():
            pattern = re.sub(r"<udim>", "1[0-9][0-9][0-9]", filename, flags=re.I)
            local_tiles = collapse_tiles(
                p.resolve() for p in path.parent.glob(pattern) if udim_path(p)
            )
            if len(local_tiles) == 1:
                return local_tiles[0], "existing UDIM sequence"
            matches = collapse_tiles(self.by_udim_name.get(filename.casefold(), []))
            local = [p for p in matches if p.parent == path.parent.resolve()]
            matches = local or matches
            if len(matches) == 1:
                return matches[0], "UDIM tile sequence"
            return None, "ambiguous UDIM folders" if matches else "UDIM tiles not found"
        matches = list(dict.fromkeys(self.by_name.get(filename.casefold(), [])))
        if len(matches) == 1:
            return matches[0], "exact filename"
        if matches:
            # Equal bytes are equivalent candidates; never choose among different contents.
            if len({p.stat().st_size for p in matches}) == 1:
                hashes = set()
                for p in matches:
                    digest = hashlib.sha256()
                    with p.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    hashes.add(digest.digest())
                if len(hashes) == 1:
                    return min(matches, key=lambda p: len(str(p))), "identical file copies"
            return None, str(len(matches)) + " different files have this name"
        return None, "file not found"
