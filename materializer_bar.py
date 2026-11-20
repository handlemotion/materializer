"""Materializer: a tall icon toolbar docked on Maya's right edge.

Open it with:
    import materializer_bar; materializer_bar.show()

Tools (click = main action, right-click or click-and-hold = menu):
  Guides   composition overlay on the active camera (thirds, golden, ...)
  Offset   click, move the control, click again: every key shifts by that move
  -- shading group --
  Add textures       find and connect textures on the selected props (undo, review)
  Move textures      copy shading first selected -> rest (or from the original rig file)
  Shading workspace  switch to it and back (graph selected meshes)
"""
import os
import importlib
from maya import cmds
from maya import OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance

CTRL = "MaterializerWorkspaceControl"
OLD_CTRLS = ("HMSidebarWorkspaceControl",)
CHAR_CTRL = "CharacterToolWorkspaceControl"
GUIDE_NODE = "hmCompGuide"
BAR_WIDTH = 44
ICON = "#8c8c8c"
ACCENT = "#5d9fd1"

_ui = None
_offset = None  # snapshot while the offset helper is armed


# --------------------------------------------------------------------- utils
def _data_dir():
    d = os.path.join(cmds.internalVar(userAppDir=True), "materializer_bar")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def _msg(text):
    print("[Materializer] " + text)
    try:
        cmds.inViewMessage(amg=text, pos="topCenter", fade=True, fadeStayTime=1800)
    except Exception:
        pass


def _opt(name, default):
    key = "hmSidebar_" + name
    return cmds.optionVar(q=key) if cmds.optionVar(exists=key) else default


def _set_opt(name, value):
    cmds.optionVar(sv=("hmSidebar_" + name, value))


# --------------------------------------------------------------------- icons
# Thin grey line drawing, one solid accent shape per icon. The accent is the
# tool group's colour, so groups read at a glance (TKM-style).
GROUP_COLORS = {"brand": "#f2522e", "camera": "#e8d75a", "anim": "#4fbfa0", "shade": "#e0648a"}
ICON_GROUP = {"guides": "camera", "offset": "anim", "materials": "shade",
              "transfer": "shade", "shading": "shade", "logo": "brand"}

_SVG = {
    # One system: 24 grid, live area 3-21, 1.5 stroke, radius 2,
    # one outlined form + one solid accent of similar weight per icon.
    # frame with thirds; the accent dot sits on a power point
    "guides": '<rect x="3" y="5" width="18" height="14" rx="2"/>'
              '<path d="M9 5 V19 M15 5 V19 M3 9.67 H21 M3 14.33 H21" stroke-width="1"/>'
              '<circle cx="15" cy="9.67" r="2.4" fill="{a}" stroke="none"/>',
    # three keys on one line, the middle one solid, arrow = shift in time
    "offset": '<path d="M5 5.5 H19 M16 2.5 L19 5.5 L16 8.5"/>'
              '<path d="M4.5 12.5 L7.5 15.5 L4.5 18.5 L1.5 15.5 Z"/>'
              '<path d="M12 12.5 L15 15.5 L12 18.5 L9 15.5 Z" fill="{a}" stroke="{a}"/>'
              '<path d="M19.5 12.5 L22.5 15.5 L19.5 18.5 L16.5 15.5 Z"/>',
    # add textures: solid tile + plus where the new one goes
    "materials": '<rect x="3" y="3" width="9" height="9" rx="2" fill="{a}" stroke="{a}"/>'
                 '<path d="M16.5 12.5 V20.5 M12.5 16.5 H20.5"/>',
    # move textures: solid tile, arrow round the corner, empty tile
    "transfer": '<rect x="3" y="3" width="9" height="9" rx="2" fill="{a}" stroke="{a}"/>'
                '<rect x="12" y="12" width="9" height="9" rx="2"/>'
                '<path d="M13.5 7.5 H14.5 Q16.5 7.5 16.5 9.5 V10 M14.5 8 L16.5 10 L18.5 8"/>',
    # sphere with a solid crescent of shade
    "shading": '<circle cx="12" cy="12" r="9"/>'
               '<path d="M16.93 4.47 A9 9 0 1 1 4.47 16.93 A9 9 0 0 0 16.93 4.47 Z" fill="{a}" stroke="{a}" stroke-width="1"/>',
    # Materializer mark: a sunburst, solid core with twelve rays
    "logo": '<g stroke="{a}" stroke-width="1.6"><line x1="18.20" y1="12.00" x2="22.50" y2="12.00"/><line x1="17.37" y1="15.10" x2="21.09" y2="17.25"/><line x1="15.10" y1="17.37" x2="17.25" y2="21.09"/><line x1="12.00" y1="18.20" x2="12.00" y2="22.50"/><line x1="8.90" y1="17.37" x2="6.75" y2="21.09"/><line x1="6.63" y1="15.10" x2="2.91" y2="17.25"/><line x1="5.80" y1="12.00" x2="1.50" y2="12.00"/><line x1="6.63" y1="8.90" x2="2.91" y2="6.75"/><line x1="8.90" y1="6.63" x2="6.75" y2="2.91"/><line x1="12.00" y1="5.80" x2="12.00" y2="1.50"/><line x1="15.10" y1="6.63" x2="17.25" y2="2.91"/><line x1="17.37" y1="8.90" x2="21.09" y2="6.75"/></g>'
            '<circle cx="12" cy="12" r="4.6" fill="{a}" stroke="none"/>',
}


def _icon(name, color=ICON):
    accent = GROUP_COLORS[ICON_GROUP.get(name, "shade")]
    icon = QtGui.QIcon()
    icon.addFile(_icon_path(name, color, accent), mode=QtGui.QIcon.Normal, state=QtGui.QIcon.Off)
    icon.addFile(_icon_path(name, "#e6e6e6", accent), mode=QtGui.QIcon.Normal, state=QtGui.QIcon.On)
    return icon


def _icon_path(name, color, accent=None):
    accent = accent or GROUP_COLORS[ICON_GROUP.get(name, "shade")]
    path = os.path.join(_data_dir(), "v3_%s_%s_%s.svg" % (name, color.strip("#"), accent.strip("#")))
    if not os.path.exists(path):
        body = _SVG[name].replace("{a}", accent)
        with open(path, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                    '<g fill="none" stroke="%s" stroke-width="1.5" stroke-linecap="round" '
                    'stroke-linejoin="round">%s</g></svg>' % (color, body))
    return path


# --------------------------------------------------------- composition guides
GUIDES = [("off", "Off"), ("thirds", "Rule of thirds"), ("golden", "Golden ratio (phi grid)"),
          ("center", "Center cross"), ("diagonals", "Diagonals"), ("quarters", "Quarters")]
FRAMES = [("none", "Render size (no mask)"), ("2.39", "2.39 : 1 Scope"), ("1.85", "1.85 : 1 Flat"),
          ("1.78", "16 : 9"), ("1.33", "4 : 3"), ("1.0", "1 : 1 Square"), ("0.8", "4 : 5 Portrait"),
          ("0.5625", "9 : 16 Vertical")]


def _active_camera():
    panel = cmds.playblast(activeEditor=True).split("|")[-1]
    if cmds.getPanel(typeOf=panel) != "modelPanel":
        return None
    cam = cmds.modelPanel(panel, q=True, camera=True)
    if cmds.nodeType(cam) == "transform":
        cam = cmds.listRelatives(cam, shapes=True, type="camera", fullPath=True)[0]
    return cam


def _render_aspect():
    w = cmds.getAttr("defaultResolution.width")
    h = cmds.getAttr("defaultResolution.height")
    return w, h, cmds.getAttr("defaultResolution.deviceAspectRatio")


def _draw_guide(guide, frame):
    w, h, ar = _render_aspect()
    scale = 1920.0 / max(w, 1)
    W, H = int(round(w * scale)), int(round(w * scale / ar))
    img = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    # Frame rectangle (masked aspect inside the render gate)
    fx, fy, fw, fh = 0.0, 0.0, float(W), float(H)
    if frame != "none":
        target = float(frame)
        if target >= ar:
            fh = W / target
            fy = (H - fh) / 2.0
        else:
            fw = H * target
            fx = (W - fw) / 2.0
        shade = QtGui.QColor(0, 0, 0, 150)
        p.fillRect(QtCore.QRectF(0, 0, W, fy), shade)
        p.fillRect(QtCore.QRectF(0, fy + fh, W, H - fy - fh), shade)
        p.fillRect(QtCore.QRectF(0, fy, fx, fh), shade)
        p.fillRect(QtCore.QRectF(fx + fw, fy, W - fx - fw, fh), shade)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 120), 2))
        p.drawRect(QtCore.QRectF(fx, fy, fw, fh))

    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 170), 2.5))

    def vline(t):
        x = fx + fw * t
        p.drawLine(QtCore.QPointF(x, fy), QtCore.QPointF(x, fy + fh))

    def hline(t):
        y = fy + fh * t
        p.drawLine(QtCore.QPointF(fx, y), QtCore.QPointF(fx + fw, y))

    if guide == "thirds":
        for t in (1 / 3.0, 2 / 3.0):
            vline(t); hline(t)
    elif guide == "golden":
        for t in (0.381966, 0.618034):
            vline(t); hline(t)
    elif guide == "quarters":
        for t in (0.25, 0.5, 0.75):
            vline(t); hline(t)
    elif guide == "center":
        vline(0.5); hline(0.5)
        r = min(fw, fh) * 0.03
        p.drawEllipse(QtCore.QPointF(fx + fw / 2, fy + fh / 2), r, r)
    elif guide == "diagonals":
        p.drawLine(QtCore.QPointF(fx, fy), QtCore.QPointF(fx + fw, fy + fh))
        p.drawLine(QtCore.QPointF(fx + fw, fy), QtCore.QPointF(fx, fy + fh))
    p.end()
    path = os.path.join(_data_dir(), "guide_%s_%s.png" % (guide, frame))
    img.save(path)
    return path


def _guide_planes():
    """Every overlay this bar (or the earlier thirds snippet) put in the scene."""
    found = []
    for ip in cmds.ls(type="imagePlane", long=True) or []:
        name = (cmds.getAttr(ip + ".imageName") or "").replace("\\", "/")
        xf = cmds.listRelatives(ip, parent=True, fullPath=True) or [ip]
        short = xf[0].split("|")[-1]
        if "hm_sidebar/guide_" in name or "materializer_bar/guide_" in name or "thirds_overlay" in name or \
                short.startswith(GUIDE_NODE) or short.startswith("thirdsGuide"):
            found.append(xf[0])
    return found


def remove_guide():
    for node in _guide_planes():
        try:
            if cmds.objExists(node):
                cmds.delete(node)
        except Exception:
            pass


def set_guide(guide=None, frame=None):
    """Put a composition overlay on the active camera. guide='off' removes it."""
    guide = guide or _opt("guide", "thirds")
    frame = frame or _opt("frame", "none")
    remove_guide()
    if guide == "off" and frame == "none":
        _refresh_buttons()
        return
    cam = _active_camera()
    if not cam:
        _msg("Click inside a camera view first.")
        return
    path = _draw_guide(guide, frame)
    cam_xform = cmds.listRelatives(cam, parent=True, fullPath=True)[0]
    nodes = cmds.imagePlane(camera=cam_xform, fileName=path)
    xform = cmds.rename(nodes[0], GUIDE_NODE)
    ip = cmds.listRelatives(xform, shapes=True, fullPath=True)[0]

    # Size the plane to the resolution gate, whatever the camera's film fit is.
    hA = cmds.getAttr(cam + ".horizontalFilmAperture")
    vA = cmds.getAttr(cam + ".verticalFilmAperture")
    ar = _render_aspect()[2]
    fit = cmds.getAttr(cam + ".filmFit")  # 0 fill, 1 horizontal, 2 vertical, 3 overscan
    film_ar = hA / vA
    horizontal = {0: ar >= film_ar, 1: True, 2: False, 3: ar < film_ar}[fit]
    sx, sy = (hA, hA / ar) if horizontal else (vA * ar, vA)
    cmds.setAttr(ip + ".fit", 4)
    cmds.setAttr(ip + ".sizeX", sx)
    cmds.setAttr(ip + ".sizeY", sy)
    cmds.setAttr(ip + ".displayOnlyIfCurrent", 1)
    cmds.setAttr(ip + ".displayMode", 3)
    near = cmds.getAttr(cam + ".nearClipPlane")
    cmds.setAttr(ip + ".depth", max(near * 2.0, 0.5))
    cmds.setAttr(ip + ".overrideEnabled", 1)
    cmds.setAttr(ip + ".overrideDisplayType", 2)  # not selectable in the viewport
    try:
        cmds.setAttr(ip + ".hiddenInOutliner", 1)
    except Exception:
        pass
    _refresh_buttons()


def toggle_guide():
    if _guide_planes():
        remove_guide()
        _refresh_buttons()
    else:
        guide = _opt("guide", "thirds")
        set_guide("thirds" if guide == "off" else guide)


def _choose_guide(key):
    _set_opt("guide", key)
    set_guide(key, _opt("frame", "none"))


def _choose_frame(key):
    _set_opt("frame", key)
    set_guide(_opt("guide", "thirds"), key)


# ------------------------------------------------------------- offset helper
def _keyed_plugs(node):
    plugs = {}
    for curve in cmds.keyframe(node, q=True, name=True) or []:
        dest = cmds.listConnections(curve + ".output", plugs=True, source=False, destination=True) or []
        for plug in dest:
            if cmds.ls(plug.split(".")[0], long=True) == cmds.ls(node, long=True):
                plugs[plug] = curve
    return plugs


def arm_offset():
    """Remember the selected controls' keys. Move a control, then apply_offset()."""
    global _offset
    sel = cmds.ls(sl=True, long=True) or []
    snap = {}
    for node in sel:
        for plug, curve in _keyed_plugs(node).items():
            times = cmds.keyframe(curve, q=True, timeChange=True) or []
            vals = cmds.keyframe(curve, q=True, valueChange=True) or []
            snap[plug] = {"curve": curve, "value": cmds.getAttr(plug),
                          "keys": list(zip(times, vals))}
    if not snap:
        _msg("Select an animated control first.")
        _offset = None
    else:
        _offset = snap
        _msg("Offset armed. Move the control, then click Offset again.")
    _refresh_buttons()


def apply_offset():
    global _offset
    snap, _offset = _offset, None
    _refresh_buttons()
    if not snap:
        return
    mode = _opt("offsetRange", "all")
    now = cmds.currentTime(q=True)
    lo, hi = cmds.playbackOptions(q=True, min=True), cmds.playbackOptions(q=True, max=True)
    changed = 0
    cmds.undoInfo(openChunk=True, chunkName="hmOffset")
    try:
        for plug, data in snap.items():
            if not cmds.objExists(plug):
                continue
            delta = cmds.getAttr(plug) - data["value"]
            if abs(delta) < 1e-6:
                continue
            curve = data["curve"]
            orig_times = set(round(t, 4) for t, _ in data["keys"])
            # Drop keys that auto key added while the control was being moved.
            for t in cmds.keyframe(curve, q=True, timeChange=True) or []:
                if round(t, 4) not in orig_times:
                    cmds.cutKey(curve, time=(t, t), clear=True)
            for t, v in data["keys"]:
                inside = (mode == "all" or (mode == "range" and lo <= t <= hi)
                          or (mode == "after" and t >= now))
                new_v = v + delta if inside else v
                cmds.keyframe(curve, e=True, time=(t, t), absolute=True, valueChange=new_v)
            changed += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    _msg("Offset %d channel%s." % (changed, "" if changed == 1 else "s") if changed
         else "Nothing moved, so no keys changed.")


def toggle_offset():
    apply_offset() if _offset else arm_offset()


def _choose_offset_range(key):
    _set_opt("offsetRange", key)


# ------------------------------------------------------------------- shading
def _short(name):
    return name.split("|")[-1].split(":")[-1]


def _meshes_under(nodes):
    """Mesh transforms (long names) under the given nodes, deformed shapes only."""
    out = []
    for node in nodes:
        shapes = cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True,
                                    noIntermediate=True) or []
        if cmds.nodeType(node) == "mesh":
            shapes.append(node)
        for s in shapes:
            if cmds.getAttr(s + ".intermediateObject"):
                continue
            xf = cmds.listRelatives(s, parent=True, fullPath=True)[0]
            if xf not in out:
                out.append(xf)
    return out


def _shape(xform):
    shapes = cmds.listRelatives(xform, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    return shapes[0] if shapes else None


def _assignments(xform):
    """[(shadingEngine, None | [component suffixes])] for one mesh."""
    shape = _shape(xform)
    result = []
    for sg in sorted(set(cmds.listConnections(shape, type="shadingEngine") or [])):
        comps, whole = [], False
        for m in cmds.sets(sg, q=True) or []:
            obj = (cmds.ls(m, objectsOnly=True, long=True) or [""])[0]
            if obj not in (shape, xform):
                continue
            if "." in m:
                comps.append(m.split(".", 1)[1])
            else:
                whole = True
        if whole:
            result.append((sg, None))
        elif comps:
            result.append((sg, comps))
    return result


def _copy_one(src, dst):
    s_shape, d_shape = _shape(src), _shape(dst)
    same_topo = cmds.polyEvaluate(s_shape, face=True) == cmds.polyEvaluate(d_shape, face=True)
    assigns = _assignments(src)
    if not assigns:
        return False
    if not same_topo and any(c for _, c in assigns):
        cmds.transferShadingSets(src, dst, sampleSpace=0, searchMethod=3)
        return True
    for sg, comps in assigns:
        if comps is None:
            cmds.sets(d_shape, e=True, forceElement=sg)
        else:
            cmds.sets(["%s.%s" % (dst, c) for c in comps], e=True, forceElement=sg)
    return True


def _match(sources, targets):
    by_name = {}
    for s in sources:
        by_name.setdefault(_short(s), []).append(s)
    pairs = []
    for t in targets:
        cands = by_name.get(_short(t))
        if cands:
            pairs.append((cands[0], t))
    if not pairs and len(sources) == 1 and len(targets) == 1:
        pairs = [(sources[0], targets[0])]
    return pairs


def copy_shading():
    """Select the source (mesh or group) first, then one or more targets."""
    sel = cmds.ls(sl=True, long=True) or []
    if len(sel) < 2:
        _msg("Select the source first, then the target(s).")
        return
    sources = _meshes_under(sel[:1])
    done = 0
    cmds.undoInfo(openChunk=True, chunkName="hmCopyShading")
    try:
        for target in sel[1:]:
            for s, t in _match(sources, _meshes_under([target])):
                done += _copy_one(s, t)
    finally:
        cmds.undoInfo(closeChunk=True)
    _msg("Copied shading to %d mesh%s." % (done, "" if done == 1 else "es"))


def shading_from_file(path=None):
    """Take shader assignments from an original rig file and apply them to the
    selected meshes or groups (matched by mesh name, namespaces ignored)."""
    targets = cmds.ls(sl=True, long=True) or []
    if not targets:
        _msg("Select the meshes or rig group to fix first.")
        return
    if not path:
        picked = cmds.fileDialog2(fileMode=1, caption="Original rig with the right shading",
                                  fileFilter="Maya Files (*.ma *.mb)")
        if not picked:
            return
        path = picked[0]
    ns = "hmShadeSrc"
    while cmds.namespace(exists=ns):
        ns += "1"
    new = cmds.file(path, i=True, namespace=ns, returnNewNodes=True, ignoreVersion=True,
                    mergeNamespacesOnClash=False, preserveReferences=False) or []
    new_dag = [n for n in cmds.ls(new, long=True, dag=True) or []]
    sources = _meshes_under([n for n in new_dag if cmds.nodeType(n) in ("transform", "mesh")])
    pairs = _match(sources, _meshes_under(targets))
    used_sgs = set()
    for s, t in pairs:
        if _copy_one(s, t):
            used_sgs.update(sg for sg, _ in _assignments(s))

    # Keep only the materials that were used; drop the rest of the imported rig.
    keep = set()
    for sg in used_sgs:
        keep.update(cmds.ls(cmds.listHistory(sg) or [], long=True) or [])
        keep.add(sg)
    tops = cmds.ls(new, assemblies=True, long=True) or []
    if tops:
        cmds.delete(tops)
    leftovers = [n for n in cmds.ls(new, long=True) or []
                 if cmds.objExists(n) and n not in keep
                 and not cmds.lockNode(n, q=True, lock=True)[0]
                 and n.split(":")[-1] not in ("initialShadingGroup", "initialParticleSE")]
    for n in leftovers:
        try:
            if cmds.objExists(n):
                cmds.delete(n)
        except Exception:
            pass
    try:
        cmds.namespace(removeNamespace=ns, mergeNamespaceWithRoot=True)
    except Exception:
        pass
    _msg("Restored shading on %d of %d mesh%s." % (
        len(pairs), len(_meshes_under(targets)), "" if len(pairs) == 1 else "es"))


# ----------------------------------------------------------- character tool
def open_character_tool():
    try:
        import Character_Tool_Dock
        importlib.reload(Character_Tool_Dock)
        Character_Tool_Dock.show()
    except ImportError:
        _msg("Character Tool isn't installed.")


# ------------------------------------------------------------- materializer
MATERIALIZER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "materializer_tool")


def materializer(action="run"):
    if not os.path.isdir(MATERIALIZER_DIR):
        _msg("Materializer isn't installed.")
        return None
    import sys
    if MATERIALIZER_DIR not in sys.path:
        sys.path.insert(0, MATERIALIZER_DIR)
    import materializer as m
    return m.launch(action)


def remove_materializer_shelf():
    """The side toolbar replaces Materializer's old shelf tab. Maya asks to confirm;
    its own installer brings the tab back on the next update."""
    from maya import mel
    if cmds.shelfLayout("Materializer", exists=True):
        mel.eval('deleteShelfTab "Materializer"')


# ------------------------------------------------------------------------ UI
STYLE = """
QWidget#hmBar { background: #373737; }
QToolButton { border: none; border-radius: 5px; background: transparent; padding: 3px; }
QToolButton::menu-indicator { image: none; width: 0px; }
QToolButton:hover, QToolButton:pressed, QToolButton:checked { background: transparent; }
QMenu { background: #333; border: 0px; padding: 2px; }
QMenu::item { padding: 7px 35px 7px 25px; color: #ccc; }
QMenu::item:selected { background: #4a4a4a; color: #fff; }
QMenu::item:disabled { color: #777; }
QMenu::separator { height: 1px; background: #444; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; left: 8px; }
"""


class _Button(QtWidgets.QToolButton):
    """Click runs the action; right-click or click-and-hold opens its menu."""

    def __init__(self, icon, tip, action, menu=None, parent=None):
        super(_Button, self).__init__(parent)
        self._dim = _icon(icon)
        self._lit = _icon(icon, "#e6e6e6")
        self.setIcon(self._dim)
        self.toggled.connect(lambda *_: self._sync_icon())
        self.setIconSize(QtCore.QSize(24, 24))
        self.setFixedSize(36, 36)
        self.setToolTip(tip)
        self.setCheckable(True)
        self._menu = menu
        self.clicked.connect(lambda *_: (action(), _refresh_buttons()))
        if menu:
            self.setMenu(menu)
            self.setPopupMode(QtWidgets.QToolButton.DelayedPopup)

    def _sync_icon(self):
        lit = self.underMouse() or self.isChecked()
        self.setIcon(self._lit if lit else self._dim)

    def enterEvent(self, event):
        self.setIcon(self._lit)
        super(_Button, self).enterEvent(event)

    def leaveEvent(self, event):
        self._sync_icon()
        super(_Button, self).leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton and self._menu:
            getattr(self._menu, 'exec', None) and self._menu.exec(self.mapToGlobal(QtCore.QPoint(-self._menu.sizeHint().width() - 4, 0)))
            return
        super(_Button, self).mousePressEvent(event)


def _radio_menu(menu, items, current, callback):
    group = QtWidgets.QActionGroup(menu) if hasattr(QtWidgets, "QActionGroup") else QtGui.QActionGroup(menu)
    for key, label in items:
        a = menu.addAction(label)
        a.setCheckable(True)
        a.setChecked(key == current())
        a.triggered.connect(lambda *_, k=key: callback(k))
        group.addAction(a)
    menu.aboutToShow.connect(lambda: [a.setChecked(k == current()) for a, (k, _) in
                                      zip(group.actions(), items)])


class Sidebar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(Sidebar, self).__init__(parent)
        self.setObjectName("hmBar")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 8)
        lay.setSpacing(6)

        # Guides
        gm = QtWidgets.QMenu(self)
        gm.addSection("Guide") if hasattr(gm, "addSection") else None
        _radio_menu(gm, GUIDES, lambda: _opt("guide", "thirds") if _guide_planes() else "off",
                    _choose_guide)
        gm.addSeparator()
        _radio_menu(gm, FRAMES, lambda: _opt("frame", "none"), _choose_frame)
        self.guides = _Button("guides", "Composition guides\nClick: on/off on the active camera\n"
                              "Right-click: choose guide and frame", toggle_guide, gm)

        # Offset
        om = QtWidgets.QMenu(self)
        _radio_menu(om, [("all", "Shift all keys"), ("range", "Only keys in playback range"),
                         ("after", "Only keys from current frame on")],
                    lambda: _opt("offsetRange", "all"), _choose_offset_range)
        om.addSeparator()
        cancel = om.addAction("Cancel armed offset")
        cancel.triggered.connect(lambda *_: (globals().__setitem__("_offset", None), _refresh_buttons()))
        self.offset = _Button("offset", "Offset all keys\nClick, move the control, click again.\n"
                              "Every key on it shifts by that same move.", toggle_offset, om)

        # Shading group: one tool per job
        am = self._menu([("Undo last batch", lambda: materializer("undo")),
                         ("Review texture assignments", lambda: materializer("review"))])
        self.add_tex = _Button("materials", "Add textures\nClick: find and connect textures on the selected props\n"
                               "Right-click: undo last batch, review", materializer, am)
        mm = self._menu([("Copy from first selected to the rest", copy_shading),
                         ("Restore from original rig file...", shading_from_file)])
        self.move_tex = _Button("transfer", "Move textures\nClick: copy shading from the first selected to the rest\n"
                                "Right-click: restore from an original rig file", copy_shading, mm)
        wm = self._menu([("Graph selected meshes", lambda: materializer("graph"))])
        self.shade_ws = _Button("shading", "Shading workspace\nClick: switch to it and back\n"
                                "Right-click: graph selected meshes",
                                lambda: materializer("toggle_workspace"), wm)

        groups = [[self.guides], [self.offset], [self.add_tex, self.move_tex, self.shade_ws]]
        for i, group in enumerate(groups):
            if i:
                lay.addSpacing(2)
                lay.addWidget(self._divider(), 0, QtCore.Qt.AlignHCenter)
                lay.addSpacing(2)
            for btn in group:
                lay.addWidget(btn, 0, QtCore.Qt.AlignHCenter)
        lay.addStretch(1)
        logo = QtWidgets.QLabel()
        logo.setPixmap(_icon("logo").pixmap(20, 20))
        logo.setToolTip("Materializer")
        lay.addWidget(logo, 0, QtCore.Qt.AlignHCenter)
        self.refresh()

    def refresh(self):
        self.guides.setChecked(bool(_guide_planes()))
        self.offset.setChecked(bool(_offset))
        for b in (self.add_tex, self.move_tex, self.shade_ws):
            b.setChecked(False)

    def _menu(self, items):
        m = QtWidgets.QMenu(self)
        for label, fn in items:
            m.addAction(label).triggered.connect(lambda *_, f=fn: f())
        return m

    @staticmethod
    def _divider():
        line = QtWidgets.QFrame()
        line.setFixedSize(24, 1)
        line.setStyleSheet("background: #4f4f4f;")
        return line


def _refresh_buttons():
    if _ui is not None:
        try:
            _ui.refresh()
        except RuntimeError:
            pass


def build():
    global _ui
    parent = wrapInstance(int(omui.MQtUtil.getCurrentParent()), QtWidgets.QWidget)
    _ui = Sidebar()
    layout = parent.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(_ui)


def show():
    """Dock the bar on the far right edge, full height."""
    for c in (CTRL,) + OLD_CTRLS:
        if cmds.workspaceControl(c, q=True, exists=True):
            cmds.deleteUI(c)
        if cmds.workspaceControlState(c, q=True, exists=True):
            cmds.workspaceControlState(c, remove=True)
    _rename_shelf_buttons()
    # Always the outermost column on Maya's right edge, full height.
    dock = {"dockToMainWindow": ("right", False)}
    cmds.workspaceControl(
        CTRL, label="Materializer", **dock,
        initialWidth=BAR_WIDTH, minimumWidth=BAR_WIDTH, widthProperty="fixed",
        heightProperty="free", retain=False,
        uiScript="import materializer_bar; materializer_bar.build()",
    )


def _rename_shelf_buttons():
    """Point any old HM shelf button at Materializer."""
    from maya import mel
    try:
        top = mel.eval("global string $gShelfTopLevel; $hmTmp = $gShelfTopLevel")
        shelves = cmds.tabLayout(top, q=True, childArray=True) or []
    except Exception:
        return
    changed = False
    for shelf in shelves:
        for b in cmds.shelfLayout(shelf, q=True, childArray=True) or []:
            if not cmds.shelfButton(b, q=True, exists=True):
                continue
            cmd_txt = cmds.shelfButton(b, q=True, command=True) or ""
            if "hm_sidebar" in cmd_txt or "materializer_bar" in cmd_txt:
                img = _icon_path("logo", "#cccccc")
                cmds.shelfButton(b, e=True, label="Materializer", annotation="Materializer toolbar",
                                 imageOverlayLabel="", image=img, image1=img,
                                 command="import materializer_bar\nmaterializer_bar.show()")
                changed = True
    if changed:
        mel.eval("global string $gShelfTopLevel; saveAllShelves $gShelfTopLevel")


def install():
    """Add a Materializer button to the shelf (once) and open the bar."""
    from maya import mel
    top = mel.eval("global string $gShelfTopLevel; $hmTmp = $gShelfTopLevel")
    shelf = "CharacterTool" if cmds.shelfLayout("CharacterTool", exists=True) else \
        cmds.tabLayout(top, q=True, selectTab=True)
    cmd = "import materializer_bar\nmaterializer_bar.show()"
    for b in cmds.shelfLayout(shelf, q=True, childArray=True) or []:
        if cmds.shelfButton(b, q=True, exists=True) and cmds.shelfButton(b, q=True, command=True) == cmd:
            break
    else:
        cmds.shelfButton(parent=shelf, label="Materializer", annotation="Materializer toolbar",
                         image=_icon_path("logo", "#cccccc"), sourceType="python",
                         command=cmd)
        mel.eval("global string $gShelfTopLevel; saveAllShelves $gShelfTopLevel")
    show()
