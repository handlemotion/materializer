"""Build a reproducible ZIP containing only distributable files."""

import ast
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "install_materializer.py",
    "materializer.py",
    "materializer_core.py",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "docs/development.md",
)


def build():
    tree = ast.parse((ROOT / "materializer.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    )
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    if version != (ROOT / "version.txt").read_text(encoding="utf-8").strip():
        raise RuntimeError("Release version does not match version.txt")
    archive = destination / f"materializer-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name in FILES:
            data = (ROOT / name).read_bytes()
            if name.endswith(".py"):
                compile(data, name, "exec")
            entry = zipfile.ZipInfo("materializer/" + name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, data)
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(archive)
    print(checksum)
    return archive


if __name__ == "__main__":
    build()
