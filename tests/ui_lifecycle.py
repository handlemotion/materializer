"""Exercise production widgets in a disposable process using Maya's Cocoa Qt build.
The scene backend is a small fixture; no Maya session or artist files are touched.
"""

import gc
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtGui, QtWidgets
from qt_host import install_if_needed

base = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(base))
app = QtWidgets.QApplication([])
app.setApplicationName("Materializer UI Regression")
install_if_needed()
m = runpy.run_path(str(base / "materializer.py"))
m = m["QuickBar"].__init__.__globals__
m["OpenMayaUI"] = SimpleNamespace(MQtUtil=SimpleNamespace(mainWindow=lambda: None))
shapes = ["|fixture|propA|shapeA", "|fixture|propB|shapeB"]
m["cmds"] = SimpleNamespace(
    ls=lambda **_: ["|fixture"], objExists=lambda _: True, select=lambda *a, **k: None
)
m["scene_meshes"] = lambda *_: shapes
root = QtWidgets.QWidget()
root.setWindowTitle("Materializer — disposable UI regression")
root.resize(550, 70)
layout = QtWidgets.QVBoxLayout(root)
root.show()
QtGui.QAccessible.setActive(True)
results = {
    "qt": QtCore.qVersion(),
    "platform": app.platformName(),
    "rebuilds": 0,
    "previewOpens": 0,
    "expansions": 0,
    "accessibleNodes": 0,
    "itemViews": 0,
}
state = {"cycle": 0, "bar": None, "controller": None}


def ax_walk(widget):
    iface = QtGui.QAccessible.queryAccessibleInterface(widget)
    if iface is None:
        return
    pending = [iface]
    seen = set()
    while pending:
        current = pending.pop()
        key = QtGui.QAccessible.uniqueId(current)
        if key in seen:
            continue
        seen.add(key)
        results["accessibleNodes"] += 1
        assert current.role() not in (QtGui.QAccessible.Role.Table, QtGui.QAccessible.Role.Tree), (
            current.role()
        )
        for i in range(current.childCount()):
            child = current.child(i)
            if child is not None:
                pending.append(child)


def flush():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def geometry_check():
    window = QtWidgets.QWidget()
    vertical = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
    viewport = QtWidgets.QWidget()
    row = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    own = QtWidgets.QTabWidget()
    neighbor = QtWidgets.QTabWidget()
    control = QtWidgets.QWidget()
    own.addTab(control, "Materializer")
    neighbor.addTab(QtWidgets.QWidget(), "Other toolbar")
    bar = QtWidgets.QWidget(control)
    bar._row_limits = []
    row.addWidget(own)
    row.addWidget(neighbor)
    vertical.addWidget(viewport)
    vertical.addWidget(row)
    QtWidgets.QVBoxLayout(window).addWidget(vertical)
    window.resize(800, 900)
    window.show()
    vertical.setSizes([450, 450])
    app.processEvents()
    before = viewport.height()
    m["fit_toolbar_row"](bar)
    app.processEvents()
    assert row.height() <= 48, row.height()
    assert viewport.height() > before
    m["release_row_limits"](bar)
    assert row.maximumHeight() == 16777215
    window.close()
    window.deleteLater()
    flush()
    results["geometryCollapsed"] = True


def cycle():
    try:
        w = m["Materializer"](root)
        w.scanned_meshes = shapes
        w.plans = [
            {
                "shader": f"Shader_{i}",
                "type": "phong" if i < 2 else "aiStandardSurface",
                "state": "Ready" if i < 2 else "Existing shader",
                "shapes": shapes,
                "maps": {"Base color": str(base / "work/fixture_BaseColor.png")},
                "reasons": {},
                "issues": [],
            }
            for i in range(3)
        ]
        w.render_plans()
        bar = m["QuickBar"](w)
        bar._disableAutoParentingToMainWindow = True
        layout.addWidget(bar)
        QtWidgets.QWidget.show(bar)
        state.update(bar=bar, controller=w)
        for repeat in range(5):
            bar.open_preview()
            p = bar.preview
            results["previewOpens"] += 1
            assert len(p.sections) == 3 and not p.findChildren(QtWidgets.QAbstractItemView)
            for section in p.sections:
                section["disclosure"].click()
                assert section["details"].isVisible()
                results["expansions"] += 1
            ax_walk(p)
            ax_walk(w)
            p.sections[0]["check"].click()
            assert not w.table.is_checked(0)
            p.sections[0]["check"].click()
            assert w.table.is_checked(0)
            app.sendEvent(
                p,
                QtGui.QKeyEvent(
                    QtCore.QEvent.Type.KeyPress,
                    QtCore.Qt.Key.Key_Right,
                    QtCore.Qt.KeyboardModifier.NoModifier,
                ),
            )
            app.sendEvent(
                p,
                QtGui.QKeyEvent(
                    QtCore.QEvent.Type.KeyPress,
                    QtCore.Qt.Key.Key_Escape,
                    QtCore.Qt.KeyboardModifier.NoModifier,
                ),
            )
            assert not p.isVisible()
            w.render_plans()
            flush()
        bar.close()
        bar.deleteLater()
        w.close()
        w.deleteLater()
        state.update(bar=None, controller=None)
        flush()
        state["cycle"] += 1
        results["rebuilds"] = state["cycle"]
        if state["cycle"] < 25:
            QtCore.QTimer.singleShot(10, cycle)
        else:
            print("PASS", json.dumps(results), flush=True)
            root.close()
            app.quit()
    except Exception:
        import traceback

        traceback.print_exc()
        results["failed"] = True
        app.exit(1)


geometry_check()
QtCore.QTimer.singleShot(100, cycle)
raise SystemExit(app.exec())
