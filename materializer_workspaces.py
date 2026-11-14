"""Native workspace switching and material graph navigation."""

SHADING = "Materializer Shading"
PREVIOUS = "sceneWorkspace"
MENU = "MaterializerWorkspaceMenu"
NODE_PANEL = "materializerNodePanel"
NODE_EDITOR = NODE_PANEL + "NodeEditorEd"


class WorkspaceSwitch:
    def __init__(self, cmds, settings, build):
        self.cmds = cmds
        self.settings = settings
        self.build = build
        self.switching = False

    def current(self):
        return self.cmds.workspaceLayoutManager(query=True, current=True)

    def enter(self):
        if self.switching:
            raise RuntimeError("A workspace switch is already in progress.")
        previous = self.current()
        if previous == SHADING:
            return False
        layouts = self.cmds.workspaceLayoutManager(listLayouts=True) or []
        base = "General" if "General" in layouts else None
        if SHADING not in layouts and base is None:
            raise RuntimeError("Maya's General workspace is required.")
        self.switching = True
        try:
            if self.cmds.workspaceLayoutManager(modified=previous):
                self.cmds.workspaceLayoutManager(save=True)
            self.settings.setValue(PREVIOUS, previous)
            self.settings.sync()
            if SHADING in layouts:
                self.cmds.workspaceLayoutManager(setCurrent=SHADING)
            else:
                self.cmds.workspaceLayoutManager(setCurrent=base)
                self.cmds.workspaceLayoutManager(saveAs=SHADING)
                self.build()
                self.cmds.workspaceLayoutManager(save=True)
        except Exception:
            self.cmds.workspaceLayoutManager(setCurrent=previous)
            if SHADING not in layouts and SHADING in (
                self.cmds.workspaceLayoutManager(listLayouts=True) or []
            ):
                self.cmds.workspaceLayoutManager(delete=SHADING)
            raise
        finally:
            self.switching = False
        return True

    def leave(self):
        if self.switching:
            raise RuntimeError("A workspace switch is already in progress.")
        if self.current() != SHADING:
            return False
        previous = self.settings.value(PREVIOUS, "General")
        if previous == SHADING or previous not in (
            self.cmds.workspaceLayoutManager(listLayouts=True) or []
        ):
            raise RuntimeError(
                "The previous workspace is unavailable. Choose one in Maya's workspace selector."
            )
        self.switching = True
        try:
            self.cmds.workspaceLayoutManager(save=True)
            self.cmds.workspaceLayoutManager(setCurrent=previous)
        except Exception:
            self.cmds.workspaceLayoutManager(setCurrent=SHADING)
            raise
        finally:
            self.switching = False
        return True


def build_layout(cmds):
    """Arrange native controls only on the first explicit entry into shading mode."""
    for name in ("MainPane", "Outliner"):
        if not cmds.workspaceControl(name, exists=True):
            raise RuntimeError("The base workspace is missing " + name + ".")
    control = "MaterializerNodes"
    script = (
        f'if (!`scriptedPanel -exists {NODE_PANEL}`) nodeEditorPanel("{NODE_PANEL}"); '
        f"scriptedPanel -edit -parent {control} {NODE_PANEL};"
    )
    if cmds.workspaceControl(control, exists=True):
        cmds.workspaceControl(control, edit=True, restore=True, visible=True)
    else:
        cmds.workspaceControl(
            control,
            label="Material graph",
            retain=True,
            dockToControl=("MainPane", "right"),
            uiScript="import maya.mel; maya.mel.eval(" + repr(script) + ")",
        )
    for name in (
        "MayaRenderSetupWindowWorkspaceControl",
        "MayaPropertyEditorWindowWorkspaceControl",
        "renderViewWindow",
        "unifiedRenderGlobalsWindow",
        "scriptEditorPanel1Window",
        "polyTexturePlacementPanel1Window",
        "SSEwindow",
        "outlinerPanel3Window",
        "ChannelBoxLayerEditor",
    ):
        if cmds.workspaceControl(name, exists=True):
            cmds.workspaceControl(name, edit=True, close=True)
    cmds.workspaceControl("Outliner", edit=True, restore=True, visible=True, collapse=False)
    cmds.workspaceControl(
        "Outliner", edit=True, dockToControl=("MainPane", "left"), resizeWidth=220
    )
    cmds.workspaceControl(control, edit=True, dockToControl=("MainPane", "right"), resizeWidth=850)
    cmds.workspaceControl(control, edit=True, visible=True, collapse=False)
    if cmds.workspaceControl("AttributeEditor", exists=True):
        cmds.workspaceControl(
            "AttributeEditor", edit=True, restore=True, visible=True, collapse=False
        )
        cmds.workspaceControl(
            "AttributeEditor", edit=True, dockToControl=(control, "right"), resizeWidth=350
        )
    cmds.workspaceControl("Outliner", edit=True, collapse=True)
    for panel in cmds.getPanel(visiblePanels=True) or []:
        if cmds.getPanel(typeOf=panel) == "modelPanel":
            cmds.modelEditor(panel, edit=True, displayTextures=True)


def material_graph_nodes(cmds, shapes):
    nodes = set()
    for shape in shapes:
        for group in cmds.listConnections(shape, type="shadingEngine") or []:
            shaders = (
                cmds.listConnections(group + ".surfaceShader", source=True, destination=False) or []
            )
            if shaders:
                nodes.add(group)
            for shader in shaders:
                nodes.add(shader)
                nodes.update(cmds.listHistory(shader, pruneDagObjects=True) or [])
    return sorted(nodes)


def install_menu(cmds, replace=False):
    if cmds.menu(MENU, exists=True):
        if not replace:
            return
        cmds.deleteUI(MENU)
    cmds.menu(MENU, label="Materializer", parent="MayaWindow", tearOff=False)
    for label, action in (
        ("Shading workspace", "shading"),
        ("Return to scene workspace", "scene"),
        ("Graph selected meshes", "graph"),
        ("Run on selected meshes", "run"),
        ("Review texture assignments…", "materials"),
        ("Choose textures…", "folder"),
        ("Apply checked assignments", "apply"),
        ("Undo material batch", "undo"),
    ):
        cmds.menuItem(
            label=label,
            parent=MENU,
            sourceType="python",
            command=f"import materializer; materializer.launch({action!r})",
        )
