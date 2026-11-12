"""Minimal Maya host for Qt-only CI; scene behavior is tested separately in mayapy."""

import sys
from types import ModuleType, SimpleNamespace


def install_if_needed():
    try:
        import maya.cmds  # noqa: F401
    except ModuleNotFoundError:
        names = ("maya", "maya.cmds", "maya.app", "maya.app.general", "maya.app.general.mayaMixin")
        for name in names:
            sys.modules[name] = ModuleType(name)
        sys.modules["maya"].OpenMayaUI = SimpleNamespace(
            MQtUtil=SimpleNamespace(mainWindow=lambda: None)
        )
        sys.modules["maya"].cmds = sys.modules["maya.cmds"]
        sys.modules["maya.app.general.mayaMixin"].MayaQWidgetDockableMixin = type(
            "DockableMixin", (), {}
        )
