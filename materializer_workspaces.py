"""Native workspace switching and material graph navigation."""

SHADING = "Materializer Shading"
PREVIOUS = "sceneWorkspace"
MENU = "MaterializerWorkspaceMenu"


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
        base = next((name for name in ("Rendering - Standard", "General") if name in layouts), None)
        if SHADING not in layouts and base is None:
            raise RuntimeError("Maya's Rendering - Standard or General workspace is required.")
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


def build_layout(cmds, mel):
    """Arrange native controls only on the first explicit entry into shading mode."""
    mel.eval("HypershadeWindow;")
    panel = mel.eval("hyperShadePanelName();")
    control = cmds.workspaceLayoutManager(parentWorkspaceControl=panel)
    if not control:
        raise RuntimeError("Maya did not create Hypershade's workspace control.")
    for name in ("MainPane", "Outliner"):
        if not cmds.workspaceControl(name, exists=True):
            raise RuntimeError("The base workspace is missing " + name + ".")
    for name in (
        "MayaRenderSetupWindowWorkspaceControl",
        "MayaPropertyEditorWindowWorkspaceControl",
        "renderViewWindow",
        "unifiedRenderGlobalsWindow",
        "scriptEditorPanel1Window",
        "polyTexturePlacementPanel1Window",
        "SSEwindow",
        "outlinerPanel3Window",
        "AttributeEditor",
        "ChannelBoxLayerEditor",
    ):
        if cmds.workspaceControl(name, exists=True):
            cmds.workspaceControl(name, edit=True, close=True)
    cmds.workspaceControl("Outliner", edit=True, restore=True, visible=True, collapse=False)
    cmds.workspaceControl(
        "Outliner", edit=True, dockToControl=("MainPane", "left"), resizeWidth=220
    )
    cmds.workspaceControl(control, edit=True, floating=False, visible=True, collapse=False)
    cmds.workspaceControl(control, edit=True, dockToControl=("MainPane", "right"), resizeWidth=850)
    for panel in cmds.getPanel(visiblePanels=True) or []:
        if cmds.getPanel(typeOf=panel) == "modelPanel":
            cmds.modelEditor(panel, edit=True, displayTextures=True)


def graph_selection(cmds):
    selection = cmds.ls(selection=True, long=True) or []
    shapes = []
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        candidates = (
            [node]
            if cmds.nodeType(node) == "mesh"
            else (cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True) or [])
        )
        shapes.extend(s for s in candidates if not cmds.getAttr(s + ".intermediateObject"))
    if not shapes:
        raise RuntimeError("Select meshes or a geometry group first.")
    try:
        cmds.select(list(dict.fromkeys(shapes)), replace=True)
        cmds.hyperShade(shaderNetworks=True)
    finally:
        if selection:
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)


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
        ("Material toolbar", "materials"),
    ):
        cmds.menuItem(
            label=label,
            parent=MENU,
            sourceType="python",
            command=f"import materializer; materializer.launch({action!r})",
        )
