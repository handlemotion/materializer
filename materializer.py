"""Materializer: local texture discovery and Arnold setup for existing Maya props.
Select props in Maya and scan for texture assignments.
"""

import json
import os
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

import maya.cmds as cmds
from maya import OpenMayaUI
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid, wrapInstance

from materializer_core import (
    EXTENSIONS,
    TextureIndex,
    identify,
    material_key,
)

__version__ = "0.2.0"  # x-release-please-version


LEGACY = {"phong", "blinn", "lambert", "surfaceShader", "phongE"}


def scene_meshes(selection=False):
    if not selection:
        return [
            x
            for x in cmds.ls(type="mesh", long=True)
            if not cmds.getAttr(x + ".intermediateObject")
        ]
    result = set()
    for item in cmds.ls(selection=True, long=True, objectsOnly=True) or []:
        if cmds.nodeType(item) == "mesh":
            result.add(item)
        for node in cmds.listRelatives(item, allDescendents=True, fullPath=True, type="mesh") or []:
            result.add(node)
    return sorted(x for x in result if not cmds.getAttr(x + ".intermediateObject"))


def inspect_materials(meshes):
    by_shader = {}
    for shape in meshes:
        for sg in set(cmds.listConnections(shape, type="shadingEngine") or []):
            shaders = (
                cmds.listConnections(sg + ".surfaceShader", source=True, destination=False) or []
            )
            if not shaders or shaders[0] == "lambert1":
                continue
            shader = shaders[0]
            row = by_shader.setdefault(
                shader,
                {
                    "shader": shader,
                    "type": cmds.nodeType(shader),
                    "shapes": set(),
                    "groups": set(),
                    "files": [],
                },
            )
            row["shapes"].add(shape)
            row["groups"].add(sg)
    for row in by_shader.values():
        for n in dict.fromkeys(cmds.listHistory(row["shader"], pruneDagObjects=True) or []):
            if cmds.nodeType(n) == "file":
                row["files"].append({"node": n, "path": cmds.getAttr(n + ".fileTextureName") or ""})
        row["shapes"] = sorted(row["shapes"])
        row["groups"] = sorted(row["groups"])
    return sorted(by_shader.values(), key=lambda r: r["shader"].casefold())


def plan_material(row, index):
    plan = dict(row, maps={}, reasons={}, issues=[], state="Needs textures")
    if row["type"] not in LEGACY:
        plan["state"] = "Existing shader"
        for item in row["files"]:
            role, _ = identify(item["path"])
            resolved, reason = index.resolve(item["path"])
            if resolved and role:
                plan["maps"][role] = str(resolved)
                plan["reasons"][role] = "existing shader; " + reason
            elif not resolved:
                plan["issues"].append(Path(item["path"].replace("\\", "/")).name + ": " + reason)
                plan["state"] = "Review"
        plan["issues"].append("Existing " + row["type"] + " network is preserved.")
        return plan
    candidates = defaultdict(list)
    for item in row["files"]:
        role, _ = identify(item["path"])
        if role:
            resolved, reason = index.resolve(item["path"])
            if resolved:
                candidates[role].append((resolved, "connected texture; " + reason))
            else:
                plan["issues"].append(Path(item["path"].replace("\\", "/")).name + ": " + reason)
    # Existing texture names establish a material group more strongly than mesh names.
    groups = {identify(item["path"])[1] for item in row["files"] if identify(item["path"])[0]}
    if not groups:
        groups = {material_key(row["shader"])}
    for group in groups:
        for role, path in index.by_group.get(group, []):
            if not candidates.get(role):
                candidates[role].append((path, "matching texture-set name"))
            elif all(candidate[1] == "matching texture-set name" for candidate in candidates[role]):
                candidates[role].append((path, "matching texture-set name"))
    for role, items in candidates.items():
        unique = list(dict.fromkeys(p for p, _ in items))
        if len(unique) == 1:
            plan["maps"][role] = str(unique[0])
            plan["reasons"][role] = items[0][1]
        else:
            # Same filename may appear in duplicated asset folders.
            resolved, reason = (
                index.resolve("/__missing__/" + unique[0].name)
                if len({p.name for p in unique}) == 1
                else (None, "multiple texture candidates")
            )
            if resolved:
                plan["maps"][role] = str(resolved)
                plan["reasons"][role] = reason
            else:
                plan["issues"].append(role + ": " + reason)
    if any(re.search(r"(?<!\d)100\d(?!\d)|<UDIM>", p, re.I) for p in plan["maps"].values()):
        plan["issues"].append("UDIM texture set: tile handling requires review by this tool.")
    unsupported = set(plan["maps"]) & {"Glossiness", "Packed ORM"}
    if unsupported:
        plan["issues"].append("Confirm packed channels or gloss conversion before applying.")
    plan["state"] = (
        "Ready"
        if "Base color" in plan["maps"] and not plan["issues"]
        else ("Review" if plan["maps"] else "Needs textures")
    )
    return plan


def plan_texture_set(row, index, group):
    """An explicit user choice replaces name inference, never scene assignment scope."""
    p = dict(row, maps={}, reasons={}, issues=[], state="Review", explicit_group=group)
    if row["type"] not in LEGACY:
        p["issues"] = ["Existing " + row["type"] + " material is preserved."]
        return p
    candidates = defaultdict(list)
    for role, path in index.by_group.get(group, []):
        candidates[role].append(str(path))
    for role, paths in candidates.items():
        paths = list(dict.fromkeys(paths))
        if role == "Glossiness" and "Roughness" in candidates:
            continue
        if len(paths) == 1:
            p["maps"][role] = paths[0]
            p["reasons"][role] = "texture set chosen for this material"
        else:
            p["issues"].append(role + ": multiple maps; choose a folder with one resolution.")
    if set(p["maps"]) & {"Glossiness", "Packed ORM"}:
        p["issues"].append("Packed channels or gloss conversion needs review.")
    if any(re.search(r"(?<!\d)100\d(?!\d)|<UDIM>", x, re.I) for x in p["maps"].values()):
        p["issues"].append("UDIM tiles need review.")
    if "Base color" not in p["maps"]:
        p["issues"].append("No base-color map found. Choose a named PBR texture set.")
    p["state"] = "Ready" if not p["issues"] else "Review"
    return p


def binding_key(shader):
    return (cmds.ls(shader, uuid=True) or [shader])[0]


def preferences():
    return QtCore.QSettings("Handlemotion", "Materializer")


def saved_bindings():
    try:
        return json.loads(preferences().value("textureBindings", "{}"))
    except (ValueError, TypeError):
        return {}


def remember_binding(shader, folder, group):
    bindings = saved_bindings()
    bindings[binding_key(shader)] = {"folder": str(folder), "group": group}
    preferences().setValue("textureBindings", json.dumps(bindings))


def index_folder(folder):
    paths = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        paths.extend(Path(root) / n for n in files if Path(n).suffix.lower() in EXTENSIONS)
    return TextureIndex(paths)


def _file(path, name, role):
    node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name=name)
    uv = cmds.shadingNode("place2dTexture", asUtility=True, name=name + "_UV")
    for attr in (
        "coverage",
        "translateFrame",
        "rotateFrame",
        "mirrorU",
        "mirrorV",
        "stagger",
        "wrapU",
        "wrapV",
        "repeatUV",
        "offset",
        "rotateUV",
        "noiseUV",
        "vertexUvOne",
        "vertexUvTwo",
        "vertexUvThree",
        "vertexCameraOne",
    ):
        cmds.connectAttr(uv + "." + attr, node + "." + attr)
    cmds.connectAttr(uv + ".outUV", node + ".uvCoord")
    cmds.connectAttr(uv + ".outUvFilterSize", node + ".uvFilterSize")
    cmds.setAttr(node + ".fileTextureName", str(path), type="string")
    cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)
    spaces = cmds.colorManagementPrefs(query=True, inputSpaceNames=True)
    colorspace = (
        ("sRGB" if "sRGB" in spaces else "sRGB Encoded Rec.709 (sRGB)")
        if role in ("Base color", "Emission")
        else "Raw"
    )
    cmds.setAttr(node + ".colorSpace", colorspace, type="string")
    cmds.setAttr(node + ".alphaIsLuminance", False)
    if re.search(r"(?<!\d)1001(?!\d)", str(path)):
        # UDIM sequences require explicit tile handling.
        raise RuntimeError("UDIM textures require review: " + str(path))
    return node


def apply_plans(plans, normal_mode="Auto"):
    if not plans or any(p["state"] != "Ready" for p in plans):
        raise RuntimeError("Choose only Ready materials.")
    for p in plans:
        if not cmds.objExists(p["shader"]):
            raise RuntimeError("Scene changed; scan again.")
        if cmds.referenceQuery(p["shader"], isNodeReferenced=True):
            raise RuntimeError("Referenced materials require a local asset workflow.")
        for path in p["maps"].values():
            if not Path(path).is_file():
                raise RuntimeError("Texture disappeared; scan again: " + path)
        for sg in p["groups"]:
            if (cmds.listConnections(sg + ".surfaceShader", s=True, d=False) or [None])[0] != p[
                "shader"
            ]:
                raise RuntimeError("Material assignments changed; scan again.")
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    if not cmds.undoInfo(query=True, state=True):
        raise RuntimeError("Enable Maya Undo before applying.")
    token = "Materializer " + uuid.uuid4().hex[:8]
    cmds.undoInfo(openChunk=True, chunkName=token)
    changed = []
    try:
        for p in plans:
            stem = re.sub("[^A-Za-z0-9_]", "_", p["shader"]) + "_Arnold"
            shader = cmds.shadingNode("aiStandardSurface", asShader=True, name=stem)
            cmds.setAttr(shader + ".base", 1)
            cmds.setAttr(shader + ".specularRoughness", 0.5)
            cmds.setAttr(shader + ".metalness", 0)
            for role, path in p["maps"].items():
                texture = _file(path, stem + "_" + role.replace(" ", "_"), role)
                if role == "Base color":
                    cmds.connectAttr(texture + ".outColor", shader + ".baseColor")
                elif role == "Normal":
                    normal = cmds.shadingNode(
                        "aiNormalMap", asUtility=True, name=stem + "_NormalMap"
                    )
                    lower = path.lower()
                    flip = normal_mode == "DirectX" or (
                        normal_mode == "Auto"
                        and bool(re.search(r"(?:directx|[_-]dx(?:[_\-.]|$))", lower))
                    )
                    cmds.setAttr(normal + ".invertY", flip)
                    cmds.connectAttr(texture + ".outColor", normal + ".input")
                    cmds.connectAttr(normal + ".outValue", shader + ".normalCamera")
                elif role in ("Roughness", "Metalness"):
                    dest = "specularRoughness" if role == "Roughness" else "metalness"
                    cmds.connectAttr(texture + ".outColorR", shader + "." + dest)
                elif role == "Emission":
                    cmds.setAttr(shader + ".emission", 1)
                    cmds.connectAttr(texture + ".outColor", shader + ".emissionColor")
                elif role == "Opacity":
                    for ch in "RGB":
                        cmds.connectAttr(texture + ".outColorR", shader + ".opacity" + ch)
            allowed = set(p["shapes"])
            for old_group in p["groups"]:
                members = []
                for member in cmds.sets(old_group, query=True) or []:
                    obj = member.split(".", 1)[0]
                    full = cmds.ls(obj, long=True) or []
                    shapes = (
                        full
                        if full and cmds.nodeType(full[0]) == "mesh"
                        else (cmds.listRelatives(obj, shapes=True, fullPath=True) or [])
                    )
                    if any(s in allowed for s in shapes):
                        members.append(member)
                if not members:
                    raise RuntimeError("No matching faces remain; scan again.")
                sg = cmds.sets(
                    renderable=True,
                    noSurfaceShader=True,
                    empty=True,
                    name=shader + "SG",
                )
                cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader")
                cmds.sets(members, edit=True, forceElement=sg)
            if "Opacity" in p["maps"]:
                for shape in p["shapes"]:
                    if cmds.attributeQuery("aiOpaque", node=shape, exists=True):
                        cmds.setAttr(shape + ".aiOpaque", False)
            changed.append(
                {
                    "old": p["shader"],
                    "new": shader,
                    "maps": p["maps"],
                    "shapes": p["shapes"],
                }
            )
    except Exception:
        cmds.undoInfo(closeChunk=True)
        cmds.undo()
        raise
    else:
        cmds.undoInfo(closeChunk=True)
    return token, changed


class IndexWorker(QtCore.QThread):
    ready = QtCore.Signal(object, float)
    failed = QtCore.Signal(str)

    def __init__(self, roots, parent=None):
        super().__init__(parent)
        self.roots = roots

    def run(self):
        try:
            start = time.monotonic()
            paths = set()
            for root in self.roots:
                for folder, dirs, files in os.walk(root, followlinks=False):
                    if self.isInterruptionRequested():
                        return
                    dirs[:] = [
                        d
                        for d in dirs
                        if not d.startswith(".")
                        and d not in ("node_modules", "Intermediate", "Saved", "Binaries")
                    ]
                    for name in files:
                        if Path(name).suffix.lower() in EXTENSIONS:
                            paths.add(str(Path(folder) / name))
            self.ready.emit(TextureIndex(sorted(paths)), time.monotonic() - start)
        except Exception as error:
            self.failed.emit(str(error))


class MaterialRows(QtWidgets.QWidget):
    """Ordinary widgets, deliberately avoiding Qt 6.8.3's macOS item-view AX cache."""

    itemSelectionChanged = QtCore.Signal()
    checkedChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.current = -1
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QtWidgets.QLabel("Shader                                      Meshes       Result")
        header.setStyleSheet("padding:8px;background:#33363a;color:#b8bec7")
        layout.addWidget(header)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(1)
        self.body_layout.addStretch()
        scroll.setWidget(self.body)

    def set_plans(self, plans):
        for row in self.rows:
            row["widget"].hide()
            row["widget"].deleteLater()
        self.rows = []
        self.current = -1
        for i, p in enumerate(plans):
            widget = QtWidgets.QWidget()
            line = QtWidgets.QHBoxLayout(widget)
            line.setContentsMargins(8, 3, 8, 3)
            check = QtWidgets.QCheckBox()
            check.setAccessibleName("Apply " + p["shader"])
            check.setChecked(p["state"] == "Ready")
            check.setEnabled(p["state"] == "Ready")
            check.toggled.connect(lambda *_: self.checkedChanged.emit())
            line.addWidget(check)
            name = QtWidgets.QPushButton(p["shader"])
            name.setCheckable(True)
            name.setFlat(True)
            name.setToolTip("Show texture details for " + p["shader"])
            name.clicked.connect(lambda _=False, index=i: self.selectRow(index))
            line.addWidget(name, 1)
            count = QtWidgets.QLabel(str(len(p["shapes"])))
            count.setFixedWidth(50)
            count.setToolTip("\n".join(p["shapes"]))
            line.addWidget(count)
            state = QtWidgets.QLabel(p["state"])
            state.setFixedWidth(110)
            line.addWidget(state)
            self.body_layout.insertWidget(self.body_layout.count() - 1, widget)
            self.rows.append({"widget": widget, "check": check, "name": name, "state": state})

    def rowCount(self):
        return len(self.rows)

    def currentRow(self):
        return self.current

    def selectRow(self, index):
        self.current = index
        for i, row in enumerate(self.rows):
            row["name"].setChecked(i == index)
        self.itemSelectionChanged.emit()

    def is_checked(self, index):
        return self.rows[index]["check"].isChecked()

    def set_checked(self, index, checked):
        self.rows[index]["check"].setChecked(checked)

    def mark_applied(self, index):
        row = self.rows[index]
        row["check"].setChecked(False)
        row["check"].setEnabled(False)
        row["state"].setText("Applied")


class Materializer(QtWidgets.QDialog):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MaterializerInspector")
        self.setWindowTitle("Materializer · Arnold")
        self.setMinimumSize(520, 260)
        self.resize(620, 320)
        self.rows = []
        self.plans = []
        self.index = None
        self.worker = None
        self.undo_token = None
        self.scanned_meshes = []
        self.scanned_selection = True
        self._closing = False
        self.setStyleSheet("""QDialog{background:#292b2e;color:#f1f2f4} QLabel{color:#f1f2f4}
        QPushButton{padding:8px 14px;background:#3b4047;color:#f1f2f4;border:1px solid #515862;border-radius:5px}
        QPushButton:hover{background:#47515e} QPushButton:disabled{color:#9098a5;background:#33363a}
        QPushButton#primary{background:#86b9ff;color:#172337;border:0;font-weight:600} QPushButton#primary:disabled{background:#3b4655;color:#b8bec7}
        QLineEdit,QComboBox{background:#33363a;color:#f1f2f4;padding:7px;border:1px solid #555e6b;border-radius:4px}
        QTextBrowser{background:#303338;border:0;color:#f1f2f4;padding:12px} QCheckBox{color:#b8bec7}""")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        toolbar = QtWidgets.QHBoxLayout()
        outer.addLayout(toolbar)
        self.scope = QtWidgets.QComboBox()
        self.scope.addItems(["Selected meshes", "Whole scene"])
        toolbar.addWidget(self.scope)
        self.scan_button = QtWidgets.QPushButton("Scan")
        self.scan_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.scan_button.clicked.connect(self.scan)
        toolbar.addWidget(self.scan_button)
        toolbar.addStretch()
        self.add_folder = QtWidgets.QPushButton("Choose textures…")
        self.add_folder.setToolTip(
            "Choose a texture set for the selected material; this is not a global search folder."
        )
        self.add_folder.clicked.connect(self.choose_root)
        toolbar.addWidget(self.add_folder)
        self.roots_label = QtWidgets.QLabel("")
        self.roots_label.hide()
        self.roots_label.setStyleSheet("color:#b8bec7")
        outer.addWidget(self.roots_label)
        splitter = QtWidgets.QSplitter()
        outer.addWidget(splitter, 1)
        self.table = MaterialRows()
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.checkedChanged.connect(self.update_action)
        splitter.addWidget(self.table)
        self.details = QtWidgets.QTextBrowser()
        self.details.setOpenExternalLinks(False)
        self.details.setMinimumWidth(260)
        self.details.hide()
        splitter.addWidget(self.details)
        splitter.setSizes([640, 340])
        footer = QtWidgets.QHBoxLayout()
        outer.addLayout(footer)
        self.more_button = QtWidgets.QPushButton("Options")
        self.more_button.setCheckable(True)
        self.more_button.toggled.connect(self.toggle_options)
        footer.addWidget(self.more_button)
        self.normal_label = QtWidgets.QLabel("Normals")
        self.normal_label.hide()
        footer.addWidget(self.normal_label)
        self.normal_mode = QtWidgets.QComboBox()
        self.normal_mode.addItems(["Auto", "OpenGL", "DirectX"])
        self.normal_mode.setToolTip(
            "Auto uses OpenGL for unlabeled maps and flips green only when DX or DirectX is explicit. Change this when you know the source convention."
        )
        footer.addWidget(self.normal_mode)
        self.normal_mode.hide()
        self.details_button = QtWidgets.QPushButton("Details")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.toggle_details)
        footer.addWidget(self.details_button)
        footer.addStretch()
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.undo_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowBack)
        )
        self.undo_button.setToolTip("Undo the last material batch")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_last)
        footer.addWidget(self.undo_button)
        self.apply_button = QtWidgets.QPushButton("Apply ready materials")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.apply_button)
        self.status = QtWidgets.QLabel("Select props, then Scan. Or choose Whole scene.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#b8bec7")
        outer.addWidget(self.status)
        self.bindings = saved_bindings()
        self.extra_roots = []
        self.details.setPlainText(
            "Select a material to inspect its texture matches and any unresolved files."
        )

    def set_status(self, text):
        self.status.setText(text)
        self.changed.emit()

    def toggle_options(self, visible):
        self.normal_mode.setVisible(visible)
        self.normal_label.setVisible(visible)
        self.roots_label.setVisible(visible)

    def toggle_details(self, visible):
        self.details.setVisible(visible)
        if visible:
            self.resize(max(self.width(), 960), self.height())
        else:
            self.resize(620, self.height())

    def choose_root(self):
        if self.worker and self.worker.isRunning():
            self.set_status("Wait for the scan to finish, then choose textures.")
            return
        if not self.plans:
            self.set_status("Select the rug or prop in Maya and click Scan first.")
            return
        i = self.table.currentRow()
        if i < 0:
            self.set_status("Select a material row first.")
            return
        row = self.rows[i]
        if row["type"] not in LEGACY:
            self.set_status("This material already has an authored shader; it is preserved.")
            return
        last = preferences().value("lastTextureFolder", "")
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Textures for " + row["shader"], last
        )
        if not folder:
            return
        preferences().setValue("lastTextureFolder", folder)
        self.bind_folder(i, folder)

    def bind_folder(self, i, folder, group=None):
        # A selected material plus a chosen folder is intentional assignment evidence.
        index = index_folder(folder)
        groups = sorted(
            g
            for g, items in index.by_group.items()
            if any(role == "Base color" for role, _ in items)
        )
        if not groups:
            self.plans[i] = dict(
                self.rows[i],
                maps={},
                reasons={},
                issues=["No base-color map found in " + str(folder)],
                state="Needs textures",
            )
            self.render_plans(i)
            self.set_status(
                "No base-color map found. Supported names: BaseColor, Albedo, Diffuse or _A."
            )
            return False
        if group is None:
            if len(groups) == 1:
                group = groups[0]
            else:
                labels = [
                    next(path.name for role, path in index.by_group[g] if role == "Base color")
                    for g in groups
                ]
                choice, ok = QtWidgets.QInputDialog.getItem(
                    self,
                    "Choose texture set",
                    "Textures for " + self.rows[i]["shader"],
                    labels,
                    0,
                    False,
                )
                if not ok:
                    return False
                group = groups[labels.index(choice)]
        if group not in groups:
            self.set_status("The saved texture set is missing. Choose its new folder.")
            return False
        plan = plan_texture_set(self.rows[i], index, group)
        remember_binding(plan["shader"], folder, group)
        self.bindings = saved_bindings()
        self.plans[i] = plan
        self.render_plans(i)
        self.set_status(
            str(len(plan["maps"]))
            + " maps matched to "
            + plan["shader"]
            + ". "
            + ("Ready to apply." if plan["state"] == "Ready" else "Open Inspect to resolve issues.")
        )
        return True

    def scan(self):
        if self.worker and self.worker.isRunning():
            return
        meshes = scene_meshes(self.scope.currentIndex() == 0)
        self.scanned_meshes = meshes
        self.scanned_selection = self.scope.currentIndex() == 0
        if not meshes:
            self.rows = []
            self.plans = []
            self.table.set_plans([])
            self.details.clear()
            self.update_action()
            self.set_status("No meshes selected. Select props in Maya, or choose Whole scene.")
            return
        self.rows = inspect_materials(meshes)
        roots = set(self.extra_roots)
        for row in self.rows:
            binding = self.bindings.get(binding_key(row["shader"]))
            if binding and Path(binding["folder"]).is_dir():
                roots.add(binding["folder"])
        for row in self.rows:
            for item in row["files"]:
                p = Path(item["path"])
                if p.is_file():
                    roots.add(str(p.parent))
                    for ancestor in p.parents:
                        if re.search(r"assets|sourceimages", ancestor.name, re.I):
                            roots.add(str(ancestor))
                            break
        scene = Path(
            cmds.file(query=True, sceneName=True) or cmds.workspace(query=True, rootDirectory=True)
        )
        project = scene.parent.parent if scene.suffix else scene
        if project.is_dir():
            roots.add(str(project))
        roots = sorted({str(Path(root).resolve()) for root in roots})
        # Avoid scanning a child again when its parent is already indexed.
        roots = [
            r for r in roots if not any(r != p and Path(r).is_relative_to(Path(p)) for p in roots)
        ]
        self.roots_label.setText("Searching " + str(len(roots)) + " folders")
        self.roots_label.setToolTip("\n".join(roots))
        self.set_status("Indexing texture files… Maya stays responsive.")
        self.scan_button.setEnabled(False)
        self.add_folder.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.worker = IndexWorker(roots, self)
        self.worker.ready.connect(self.on_index)
        self.worker.failed.connect(self.on_error)
        self.worker.start()

    def on_error(self, message):
        self.set_status("Scan failed: " + message)
        self.scan_button.setEnabled(True)
        self.add_folder.setEnabled(True)

    def on_index(self, index, elapsed):
        if self._closing or self.sender() is not self.worker:
            return
        self.index = index
        self.plans = [plan_material(row, index) for row in self.rows]
        for i, row in enumerate(self.rows):
            binding = self.bindings.get(binding_key(row["shader"]))
            if binding:
                if Path(binding["folder"]).is_dir():
                    folder = Path(binding["folder"]).resolve()
                    scoped = TextureIndex(
                        path
                        for items in index.by_group.values()
                        for _, path in items
                        if path.is_relative_to(folder)
                    )
                    self.plans[i] = plan_texture_set(row, scoped, binding["group"])
                else:
                    self.plans[i]["state"] = "Review"
                    self.plans[i]["issues"].append(
                        "Chosen texture folder moved. Choose textures again."
                    )
        self.render_plans()
        ready = sum(p["state"] == "Ready" for p in self.plans)
        self.set_status(
            f"{len(self.plans)} materials · {ready} ready. Choose textures for unmatched materials."
        )

    def render_plans(self, selected=0):
        self.table.blockSignals(True)
        self.table.set_plans(self.plans)
        self.table.blockSignals(False)
        self.scan_button.setEnabled(True)
        self.add_folder.setEnabled(True)
        self.update_action()
        if self.plans:
            self.table.selectRow(min(selected, len(self.plans) - 1))

    def update_action(self, *_):
        n = sum(self.table.is_checked(i) for i in range(self.table.rowCount()))
        self.apply_button.setText(f"Apply {n} material" + ("s" if n != 1 else ""))
        self.apply_button.setEnabled(n > 0 and self.scan_button.isEnabled())
        self.changed.emit()

    def show_details(self):
        import html

        i = self.table.currentRow()
        if i < 0 or i >= len(self.plans):
            return
        p = self.plans[i]
        escape = html.escape
        parts = [
            f"<h3>{escape(p['shader'])}</h3>",
            f"<p>{escape(p['type'])}"
            + (" → Arnold Standard Surface" if p["type"] in LEGACY else "")
            + f"<br>{len(p['shapes'])} meshes · {escape(p['state'])}</p>",
        ]
        for role, path in p["maps"].items():
            parts.append(
                f'<p><b>{escape(role)}</b><br>{escape(Path(path).name)}<br><span style="color:#b8bec7">{escape(p["reasons"].get(role, ""))}</span></p>'
            )
        for issue in p["issues"]:
            parts.append(f'<p style="color:#f0ce8b">{escape(issue)}</p>')
        if p["state"] == "Ready":
            parts.append(
                "<p>Original materials are retained. Only the scanned mesh assignments change. Missing roughness uses 0.5.</p>"
            )
        self.details.setHtml("".join(parts))
        self.details.setToolTip("\n".join(p["maps"].values()))

    def apply(self):
        if self.scanned_selection and scene_meshes(True) != self.scanned_meshes:
            self.set_status("Selection changed. Scan the selected props before applying.")
            return
        chosen = [p for i, p in enumerate(self.plans) if self.table.is_checked(i)]
        try:
            self.undo_token, changed = apply_plans(chosen, self.normal_mode.currentText())
            self.undo_button.setEnabled(True)
            for p in chosen:
                p["state"] = "Applied"
            for i, p in enumerate(self.plans):
                if p["state"] == "Applied":
                    self.table.mark_applied(i)
            self.set_status(
                f"{len(changed)} Arnold materials connected. Geometry and transforms were preserved. Scene is not saved automatically."
            )
            self.update_action()
        except Exception as error:
            self.set_status("Nothing applied: " + str(error))

    def undo_last(self):
        if cmds.undoInfo(query=True, undoName=True) != self.undo_token:
            self.set_status(
                "Other scene edits happened afterward. Use Maya’s Undo history to return to the material change."
            )
            return
        cmds.undo()
        self.undo_button.setEnabled(False)
        self.scan()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.set_status("Stopping file scan…")
            event.ignore()
            QtCore.QTimer.singleShot(150, self.close)
            return
        super().closeEvent(event)


_ICON_CACHE = {}


def toolbar_icon(name, ready=False):
    """Blue beveled shapes sized to Maya's native blue reload icon."""
    key = (name, ready)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    from PySide6 import QtSvg

    shapes = {
        "folder": '<path d="M4 9V4h10l3 4h11v20H4z"/><path d="M4 12h24l-3 16H4z"/>',
        "undo": '<path d="M13 5 3 14l10 8v-6h5c5 0 7 3 7 8 5-7 2-14-7-14h-5z"/>',
        "inspect": '<rect x="5" y="4" width="22" height="24" rx="3"/><path d="M10 10h12M10 16h12M10 22h9" fill="none" stroke="#d5ebff" stroke-width="2"/>',
        "apply": '<path d="m4 16 6-5 5 6L26 4l4 4-15 21z"/>',
    }
    icon = QtGui.QIcon()
    for disabled in (False, True):
        if disabled or (name == "apply" and not ready):
            top, bottom, edge = "#8b9198", "#565c63", "#454a51"
        elif name == "apply":
            top, bottom, edge = "#b8ee8a", "#519e32", "#376d25"
        else:
            top, bottom, edge = "#9bd2f6", "#2e79b6", "#214b6d"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop stop-color="'
            + top
            + '"/><stop offset="1" stop-color="'
            + bottom
            + '"/></linearGradient></defs><g transform="translate(0,1)" opacity=".4" fill="#111820">'
            + shapes[name]
            + '</g><g fill="url(#b)" stroke="'
            + edge
            + '" stroke-width="1.3" stroke-linejoin="round">'
            + shapes[name]
            + "</g></svg>"
        )
        image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode())).render(painter)
        painter.end()
        icon.addPixmap(
            QtGui.QPixmap.fromImage(image),
            QtGui.QIcon.Mode.Disabled if disabled else QtGui.QIcon.Mode.Normal,
        )
    _ICON_CACHE[key] = icon
    return icon


class AssignmentLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class AssignmentPreview(QtWidgets.QDialog):
    """Plain controls and rich text; no synthesized tree/table accessibility cells."""

    def __init__(self, bar):
        pointer = OpenMayaUI.MQtUtil.mainWindow()
        parent = wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else bar
        super().__init__(
            parent, QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.bar = bar
        self.current_index = None
        self.sections = []
        self.setObjectName("MaterializerAssignments")
        self.setStyleSheet(
            "QDialog#MaterializerAssignments{background:#292b2e;border:1px solid #515862} QLabel{color:#e2e5e8} QTextBrowser{background:#292b2e;color:#e2e5e8;border:0} QPushButton{padding:5px 9px} QToolButton{padding:3px}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title = QtWidgets.QHBoxLayout()
        layout.addLayout(title)
        title.addWidget(QtWidgets.QLabel("Texture assignments"))
        title.addStretch()
        close = QtWidgets.QToolButton()
        close.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCloseButton)
        )
        close.setFixedSize(24, 24)
        close.setToolTip("Close preview (Esc)")
        close.setAccessibleName("Close assignment preview")
        close.clicked.connect(self.close)
        title.addWidget(close)
        self.context = QtWidgets.QLabel()
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(4)
        self.body_layout.addStretch()
        scroll.setWidget(self.body)
        footer = QtWidgets.QHBoxLayout()
        layout.addLayout(footer)
        self.targets = QtWidgets.QPushButton("Select meshes")
        self.targets.clicked.connect(self.select_targets)
        footer.addWidget(self.targets)
        self.textures = QtWidgets.QPushButton("Choose textures…")
        self.textures.clicked.connect(self.choose_textures)
        footer.addWidget(self.textures)
        footer.addStretch()
        advanced = QtWidgets.QPushButton("Inspector…")
        advanced.clicked.connect(self.open_inspector)
        footer.addWidget(advanced)
        self.resize(520, 340)

    def populate(self):
        import html

        c = self.bar.controller
        for section in self.sections:
            section["widget"].hide()
            section["widget"].deleteLater()
        self.sections = []
        self.current_index = 0 if c.plans else None
        stale = self.bar.selection_changed()
        n = len(c.scanned_meshes)
        self.context.setText(
            "Selection changed — scan again before applying."
            if stale
            else f"{n} scanned mesh part"
            + ("s" if n != 1 else "")
            + ". Checked rows create Arnold shaders; existing shaders stay as they are."
        )
        actions = {
            "Ready": "Create Arnold shader",
            "Existing shader": "Keep existing shader",
            "Applied": "Connected",
            "Needs textures": "Choose textures",
            "Review": "Needs review",
        }
        for i, p in enumerate(c.plans):
            widget = QtWidgets.QWidget()
            column = QtWidgets.QVBoxLayout(widget)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(4)
            line = QtWidgets.QHBoxLayout()
            column.addLayout(line)
            check = QtWidgets.QCheckBox()
            check.setAccessibleName("Apply " + p["shader"])
            check.setChecked(c.table.is_checked(i))
            check.setEnabled(p["state"] == "Ready" and not stale)
            check.toggled.connect(lambda checked, index=i: c.table.set_checked(index, checked))
            line.addWidget(check)
            disclosure = QtWidgets.QToolButton()
            disclosure.setText(p["shader"])
            disclosure.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            disclosure.setArrowType(QtCore.Qt.ArrowType.RightArrow)
            disclosure.setCheckable(True)
            disclosure.setToolTip("Show affected meshes and texture files")
            line.addWidget(disclosure, 1)
            action = QtWidgets.QLabel(actions.get(p["state"], p["state"]))
            line.addWidget(action)
            details = QtWidgets.QTextBrowser()
            details.setOpenLinks(False)
            details.setMinimumHeight(150)
            details.setMaximumHeight(210)
            parts = ["<b>Meshes</b>"]
            for shape in p["shapes"]:
                parts.append(html.escape(shape))
            parts.append("<br><b>Textures</b>")
            for role, path in p["maps"].items():
                parts.append(
                    html.escape(role)
                    + ' · <a style="color:#9bd2f6" href="'
                    + html.escape(Path(path).as_uri(), quote=True)
                    + '">'
                    + html.escape(Path(path).name)
                    + "</a>"
                )
            if not p["maps"]:
                parts.append("No named texture maps detected.")
            for issue in p["issues"]:
                parts.append(html.escape(issue))
            details.setHtml("<br>".join(parts))
            details.setToolTip("Hover a texture filename for its full path.")
            details.highlighted.connect(
                lambda url: (
                    QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), url.toLocalFile())
                    if url.isLocalFile()
                    else QtWidgets.QToolTip.hideText()
                )
            )
            details.anchorClicked.connect(
                lambda url: QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), url.toLocalFile())
            )
            column.addWidget(details)
            details.hide()
            disclosure.toggled.connect(lambda shown, index=i: self.expand_section(index, shown))
            self.body_layout.insertWidget(self.body_layout.count() - 1, widget)
            self.sections.append(
                {
                    "widget": widget,
                    "check": check,
                    "disclosure": disclosure,
                    "details": details,
                }
            )
        if len(self.sections) == 1:
            self.sections[0]["disclosure"].setChecked(True)
        self.targets.setEnabled(bool(c.plans))
        self.update_actions()

    def expand_section(self, index, shown):
        self.current_index = index
        section = self.sections[index]
        section["details"].setVisible(shown)
        section["disclosure"].setArrowType(
            QtCore.Qt.ArrowType.DownArrow if shown else QtCore.Qt.ArrowType.RightArrow
        )
        self.update_actions()

    def update_actions(self):
        i = self.current_index
        c = self.bar.controller
        self.textures.setEnabled(
            i is not None and c.plans[i]["type"] in LEGACY and not self.bar.selection_changed()
        )

    def choose_textures(self):
        if self.current_index is None:
            return
        self.close()
        self.bar.controller.table.selectRow(self.current_index)
        self.bar.controller.choose_root()

    def select_targets(self):
        if self.current_index is None:
            return
        targets = self.bar.controller.plans[self.current_index]["shapes"]
        cmds.select([x for x in targets if cmds.objExists(x)], replace=True)
        self.close()

    def open_inspector(self):
        self.close()
        self.bar.open_inspector()


class QuickBar(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """A small action strip; the material list opens only when needed."""

    def __init__(self, controller, parent=None):
        super().__init__(parent=parent)
        self.controller = controller
        self.setObjectName("MaterializerQuickBar")
        self.setWindowTitle("Materializer")
        self.setStyleSheet(
            "QWidget#MaterializerQuickBar{background:#303236;color:#e2e5e8} QToolButton{border:0;border-radius:4px;padding:4px;background:transparent;color:#d9e3ee} QToolButton:hover{background:#4b5058} QToolButton:focus{background:#4b5058} QToolButton:disabled{color:#747a82} QLabel{color:#c7cbd1}"
        )
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(5)

        def button(title, standard, callback):
            b = QtWidgets.QToolButton()
            b.setIcon(self.style().standardIcon(standard))
            b.setIconSize(QtCore.QSize(24, 24))
            b.setFixedSize(34, 34)
            b.setToolTip(title)
            b.setAccessibleName(title)
            b.clicked.connect(callback)
            layout.addWidget(b)
            return b

        pix = QtWidgets.QStyle.StandardPixmap
        self.scan = button("Scan selected props", pix.SP_BrowserReload, self.scan_selection)
        self.textures = button(
            "Choose textures for selected material",
            pix.SP_DirOpenIcon,
            self.choose_textures,
        )
        self.apply = button(
            "Apply matched Arnold materials", pix.SP_DialogApplyButton, self.apply_ready
        )
        self.apply.setIcon(toolbar_icon("apply", ready=False))
        self.undo = button("Undo last material batch", pix.SP_ArrowBack, controller.undo_last)
        self.label = AssignmentLabel("Select props · scan")
        self.label.setMinimumWidth(160)
        self.label.setMaximumWidth(260)
        self.label.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.label.clicked.connect(self.open_preview)
        layout.addWidget(self.label, 1)
        self.inspect = button(
            "Preview mesh and texture assignments",
            pix.SP_FileDialogDetailedView,
            self.open_preview,
        )
        layout.addStretch(1)
        self.preview = None
        self._row_limits = []
        self._selection_signature = None
        self._current_meshes = []
        self.scan.setIcon(self.style().standardIcon(pix.SP_BrowserReload))
        for b, name in (
            (self.textures, "folder"),
            (self.undo, "undo"),
            (self.inspect, "inspect"),
        ):
            b.setIcon(toolbar_icon(name))
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.resize(400, 42)
        self.setMinimumWidth(360)
        self.setMinimumHeight(42)
        self.setMaximumHeight(48)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(200)
        controller.changed.connect(self.sync)
        self.sync()

    def context_menu(self, point):
        menu = QtWidgets.QMenu(self)
        dock = menu.addAction("Dock beside timeline tools")
        floating = menu.addAction("Float toolbar")
        inspector = menu.addAction("Open inspector…")
        menu.addSeparator()
        importer = menu.addAction("Import static FBX…")
        updates = menu.addAction("Downloads and updates…")
        action = menu.exec(self.mapToGlobal(point))
        if action == dock:
            if self.isDockable():
                arrange_toolbar(self)
            else:
                self.show(dockable=True, floating=False, area="bottom", height=48)
        elif action == floating:
            if self.isDockable():
                cmds.workspaceControl(
                    self.objectName() + "WorkspaceControl", edit=True, floating=True
                )
        elif action == inspector:
            self.open_inspector()
        elif action == importer:
            choose_static_fbx()
        elif action == updates:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl("https://github.com/handlemotion/materializer/releases/latest")
            )

    def scan_selection(self):
        self.timer.start(200)
        self.controller.scope.setCurrentIndex(0)
        self.controller.scan()
        self.sync()

    def choose_textures(self):
        c = self.controller
        if len(c.plans) > 1:
            self.open_preview()
            return
        c.choose_root()

    def apply_ready(self):
        self.controller.apply()
        self.sync()

    def open_preview(self):
        if self.preview is None:
            self.preview = AssignmentPreview(self)
        elif self.preview.isVisible():
            self.preview.close()
            return
        self.preview.populate()
        self.preview.adjustSize()
        self.preview.resize(520, 340)
        point = self.mapToGlobal(QtCore.QPoint(0, 0))
        screen = self.screen().availableGeometry()
        anchor = QtCore.QPoint(
            max(screen.left(), min(point.x(), screen.right() - self.preview.width())),
            max(screen.top(), point.y() - self.preview.height() - 6),
        )
        self.preview.move(anchor)
        self.preview.show()
        self.preview.raise_()
        self.preview.activateWindow()

    def selection_changed(self):
        signature = tuple(cmds.ls(selection=True, long=True, objectsOnly=True) or [])
        if signature != self._selection_signature:
            self._selection_signature = signature
            self._current_meshes = scene_meshes(True)
        c = self.controller
        return c.scanned_selection and self._current_meshes != c.scanned_meshes

    def open_inspector(self):
        self.controller.show()
        self.controller.raise_()
        self.controller.activateWindow()

    def sync(self):
        c = self.controller
        busy = bool(c.worker and c.worker.isRunning())
        stale = self.selection_changed()
        self.scan.setEnabled(not busy)
        self.textures.setEnabled(
            any(p["type"] in LEGACY for p in c.plans) and not busy and not stale
        )
        ready = c.apply_button.isEnabled() and not busy and not stale
        self.apply.setEnabled(ready)
        self.apply.setIcon(toolbar_icon("apply", ready=ready))
        self.undo.setEnabled(c.undo_button.isEnabled())
        text = c.status.text()
        count = len({p.rsplit("|", 1)[0] for p in c.scanned_meshes})
        prefix = f"{count} mesh" + ("es" if count != 1 else "")
        checked = sum(c.table.is_checked(i) for i in range(c.table.rowCount()))
        affected = len(
            {shape for i, p in enumerate(c.plans) if c.table.is_checked(i) for shape in p["shapes"]}
        )
        if busy:
            summary = prefix + " · finding textures…"
        elif stale:
            summary = "Selection changed · scan"
        elif not c.scanned_meshes:
            summary = "Select props · scan"
        elif checked:
            summary = prefix + f" · {checked} ready"
        elif any(p["state"] == "Review" for p in c.plans):
            summary = prefix + " · needs review"
        elif any(p["state"] == "Needs textures" for p in c.plans):
            summary = prefix + " · choose textures"
        elif c.plans:
            summary = prefix + " · already shaded"
        else:
            summary = prefix + " · no editable shaders"
        if not stale and text.startswith(
            (
                "Nothing applied:",
                "Scan failed:",
                "No named",
                "No base-color",
                "The saved",
                "Other scene",
            )
        ):
            summary = text
        self.label.setText(
            self.label.fontMetrics().elidedText(summary, QtCore.Qt.TextElideMode.ElideRight, 260)
        )
        import html

        lines = ["<b>Scanned texture assignments</b>"]
        for p in c.plans[:8]:
            targets = ", ".join(x.rsplit("|", 2)[-2] if "|" in x else x for x in p["shapes"][:3])
            action = (
                "Create Arnold shader"
                if p["state"] == "Ready"
                else "Keep existing shader"
                if p["state"] == "Existing shader"
                else p["state"]
            )
            lines.append(
                html.escape(targets)
                + " → "
                + html.escape(p["shader"])
                + "<br>"
                + html.escape(action)
            )
        lines.append("Click for meshes, texture filenames and full paths.")
        self.label.setToolTip("<br><br>".join(lines))
        self.apply.setToolTip(
            (
                f"Connect {checked} checked shader"
                + ("s" if checked != 1 else "")
                + f" to {affected} mesh parts. Click status to preview assignments."
            )
            if not stale
            else "Selection changed. Scan again before applying."
        )

    def floatingChanged(self, floating):
        if floating:
            release_row_limits(self)
        else:
            QtCore.QTimer.singleShot(0, lambda: fit_toolbar_row(self) if isValid(self) else None)

    def closeEvent(self, event):
        release_row_limits(self)
        self.timer.stop()
        if self.preview:
            self.preview.close()
            self.preview.deleteLater()
            self.preview = None
        super().closeEvent(event)


def toolbar(restoring=False):
    import builtins

    previous = getattr(builtins, "_materializer_bar", None)
    if previous:
        try:
            previous.show()
            previous.timer.start(200)
            previous.raise_()
            return previous
        except RuntimeError:
            pass
    controller = getattr(builtins, "_materializer_window", None)
    if controller is None:
        controller = show()
        controller.hide()
    parent = controller.parentWidget()
    bar = QuickBar(controller, parent)
    builtins._materializer_bar = bar
    if not restoring:
        control = bar.objectName() + "WorkspaceControl"
        if cmds.workspaceControl(control, query=True, exists=True):
            cmds.deleteUI(control)
        floating = preferences().value("toolbarFloating", False, type=bool)
        restore_command = (
            "import sys; p=%r; sys.path.insert(0,p) if p not in sys.path else None; import materializer; materializer.restore_workspace()"
            % str(Path(__file__).resolve().parent)
        )
        bar.show(
            dockable=True,
            floating=floating,
            area="bottom",
            height=48,
            heightSizingProperty="fixed",
            retain=True,
            uiScript=restore_command,
        )
        embed_toolbar(bar)
        if not floating:
            arrange_toolbar(bar)
    if scene_meshes(True):
        bar.scan_selection()
    return bar


def shutdown():
    """Stop indexing before disposing the UI that owns its worker."""
    import builtins

    window = getattr(builtins, "_materializer_window", None)
    if window is not None and isValid(window):
        if window.worker and window.worker.isRunning():
            window.worker.requestInterruption()
            if not window.worker.wait(2000):
                raise RuntimeError("The texture scan is stopping. Try again shortly.")
        window._closing = True
    control = "MaterializerQuickBarWorkspaceControl"
    if cmds.workspaceControl(control, query=True, exists=True):
        preferences().setValue(
            "toolbarFloating", cmds.workspaceControl(control, query=True, floating=True)
        )
    for key in ("_materializer_bar", "_materializer_window"):
        widget = getattr(builtins, key, None)
        if widget is not None and isValid(widget):
            widget.close()
            widget.deleteLater()
        setattr(builtins, key, None)
    if cmds.workspaceControl(control, query=True, exists=True):
        cmds.deleteUI(control)


_WINDOW = None


def show():
    global _WINDOW
    # Retain native Maya parenting and a strong reference across runpy invocations.
    import builtins

    previous = getattr(builtins, "_materializer_window", None)
    if previous:
        try:
            previous.show()
            previous.raise_()
            previous.activateWindow()
            return previous
        except RuntimeError:
            pass
    pointer = OpenMayaUI.MQtUtil.mainWindow()
    if not pointer or not isinstance(QtWidgets.QApplication.instance(), QtWidgets.QApplication):
        raise RuntimeError("Open this tool inside the Maya desktop application.")
    parent = wrapInstance(int(pointer), QtWidgets.QWidget)
    _WINDOW = Materializer(parent)
    builtins._materializer_window = _WINDOW
    _WINDOW.show()
    return _WINDOW


def import_static_fbx(path):
    """Import a static prop without animation takes; preserve FBX settings."""
    import maya.mel as mel

    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".fbx":
        raise RuntimeError("Choose an existing FBX file.")
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya", quiet=True)
    namespace = re.sub("[^A-Za-z0-9_]", "_", path.stem)
    if not namespace or namespace[0].isdigit():
        namespace = "Prop_" + namespace
    mel.eval("FBXPushSettings;")
    try:
        mel.eval('FBXResetImport; FBXImportSetTake -takeIndex 0; FBXImportMode -v "add";')
        nodes = cmds.file(
            str(path),
            i=True,
            type="FBX",
            ignoreVersion=True,
            namespace=namespace,
            mergeNamespacesOnClash=False,
            returnNewNodes=True,
        )
        meshes = [n for n in nodes if cmds.objExists(n) and cmds.nodeType(n) == "mesh"]
        if not meshes:
            raise RuntimeError("FBX imported no meshes. Check the Script Editor log.")
        return meshes
    finally:
        mel.eval("FBXPopSettings;")


def choose_static_fbx():
    paths = cmds.fileDialog2(
        caption="Import static prop (no animation)",
        fileFilter="FBX (*.fbx)",
        fileMode=1,
    )
    if not paths:
        return
    try:
        meshes = import_static_fbx(paths[0])
        cmds.select(
            cmds.listRelatives(meshes, parent=True, fullPath=True) or meshes,
            replace=True,
        )
        window = show()
        window.scan()
    except Exception as error:
        cmds.warning(str(error))


def launch(action="materials"):
    if action == "import":
        return choose_static_fbx()
    if action == "materials":
        return toolbar()
    window = show()
    if action == "folder":
        if window.plans:
            window.choose_root()
        else:
            window.scan()
            if window.worker:
                QtCore.QTimer.singleShot(0, lambda: _choose_after_scan(window))
    elif scene_meshes(True):
        window.scan()
    return window


def _choose_after_scan(window):
    if window.worker and window.worker.isRunning():
        QtCore.QTimer.singleShot(100, lambda: _choose_after_scan(window))
        return
    window.choose_root()


def restore_workspace():
    parent = OpenMayaUI.MQtUtil.getCurrentParent()
    bar = toolbar(restoring=True)
    pointer = OpenMayaUI.MQtUtil.findControl(bar.objectName())
    if parent and pointer:
        OpenMayaUI.MQtUtil.addWidgetToMayaLayout(int(pointer), int(parent))
    embed_toolbar(bar)
    if not cmds.workspaceControl(bar.objectName() + "WorkspaceControl", query=True, floating=True):
        arrange_toolbar(bar)
    bar.timer.start(200)
    return bar


def embed_toolbar(bar):
    # Maya 2027's mixin may create the workspace before findControl sees the Qt widget.
    control = bar.objectName() + "WorkspaceControl"
    pointer = OpenMayaUI.MQtUtil.findControl(control)
    if not pointer:
        raise RuntimeError("Maya did not create the toolbar workspace.")
    host = wrapInstance(int(pointer), QtWidgets.QWidget)
    if bar.parentWidget() is not host:
        bar.setParent(host, QtCore.Qt.WindowType.Widget)
        layout = host.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(bar)
    QtWidgets.QWidget.setVisible(bar, True)
    bar.timer.start(200)


def arrange_toolbar(bar):
    import sys

    import maya.mel as mel

    control = bar.objectName() + "WorkspaceControl"
    timeline = mel.eval('getUIComponentToolBar("Time Slider", false)')
    # TKM's installed workspace is named 'k'. Verify its owner before docking to it.
    neighbor = None
    if cmds.workspaceControl("k", query=True, exists=True):
        tkm = sys.modules.get("TheKeyMachine.core.toolbar")
        if (
            getattr(tkm, "WorkspaceName", None) == "k"
            and cmds.workspaceControl("k", query=True, visible=True)
            and not cmds.workspaceControl("k", query=True, floating=True)
        ):
            neighbor = "k"
    if neighbor:
        cmds.workspaceControl(control, edit=True, dockToControl=(neighbor, "left"))
    elif timeline:
        cmds.workspaceControl(control, edit=True, dockToControl=(timeline, "top"))
    else:
        cmds.workspaceControl(control, edit=True, dockToMainWindow=("bottom", False))
    cmds.workspaceControl(
        control,
        edit=True,
        label="MA",
        tabPosition=("east", False),
        actLikeMayaUIElement=True,
        heightProperty="fixed",
        minimumHeight=42,
        maximumHeight=48,
        widthProperty="preferred" if neighbor else "free",
        minimumWidth=360,
        maximumWidth=440 if neighbor else 16777215,
    )
    host = bar.parentWidget()
    if host:
        host.setMinimumHeight(42)
        host.setMaximumHeight(48)
        host.setMaximumWidth(440 if neighbor else 16777215)
    fit_toolbar_row(bar)
    QtCore.QTimer.singleShot(0, lambda: fit_toolbar_row(bar) if isValid(bar) else None)


def release_row_limits(bar):
    for widget, minimum, maximum, policy in getattr(bar, "_row_limits", []):
        if widget is not None and isValid(widget):
            widget.setMinimumHeight(minimum)
            widget.setMaximumHeight(maximum)
            widget.setSizePolicy(policy)
    bar._row_limits = []


def fit_toolbar_row(bar, height=48):
    """Constrain the allocated dock row, including Maya's tab containers."""
    release_row_limits(bar)
    host = bar.parentWidget()
    if host is None:
        return
    container = host
    while container and not isinstance(container, QtWidgets.QTabWidget):
        container = container.parentWidget()
    if container is None:
        return
    row = container
    parent = container.parentWidget()
    if (
        isinstance(parent, QtWidgets.QSplitter)
        and parent.orientation() == QtCore.Qt.Orientation.Horizontal
    ):
        row = parent
    splitter = row.parentWidget()
    sizes = splitter.sizes() if isinstance(splitter, QtWidgets.QSplitter) else []
    index = splitter.indexOf(row) if sizes else -1
    limits = [container, row] if container is not row else [container]
    for widget in limits:
        bar._row_limits.append(
            (
                widget,
                widget.minimumHeight(),
                widget.maximumHeight(),
                widget.sizePolicy(),
            )
        )
        widget.setMinimumHeight(42)
        widget.setMaximumHeight(height)
        policy = widget.sizePolicy()
        policy.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.Fixed)
        widget.setSizePolicy(policy)
    if index >= 0 and splitter.orientation() == QtCore.Qt.Orientation.Vertical and len(sizes) > 1:
        recipient = max((i for i in range(len(sizes)) if i != index), key=sizes.__getitem__)
        sizes[recipient] = max(1, sizes[recipient] + sizes[index] - height)
        sizes[index] = height
        splitter.setSizes(sizes)
