"""Main window: the File and View menus, the title bar, dialogs, and keeping track of the open project file."""

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QVBoxLayout,
)

from editor import DRAG, EDIT, ZOOM_LEVELS, EditorView, app_settings
from graph import Graph
from project import EXTENSION, ProjectError, ViewState, load, save, snapshot

APP_NAME = "stemgraph"
UNTITLED = "Untitled"
PROJECT_FILTER = f"stemgraph Project Files (*{EXTENSION})"
OPEN_FILTER = PROJECT_FILTER + ";;All Files (*)"  # loading checks the contents, so any file is safe to try
MAX_RECENT = 10
RECENT_FILES_KEY = "recent_files"         # QSettings key: recently opened or saved projects, newest first
LAST_PROJECT_DIR_KEY = "last_project_dir"  # QSettings key: folder the project dialogs last used
DIALOG_MARGIN = 16  # space around and between the contents of the app's own dialogs


def _same_file(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def recent_labels(paths: list[str]) -> list[str]:
    """Menu labels for the recent files: "&1 name", with the parent folder added when names clash."""
    names = [Path(p).stem for p in paths]
    labels = []
    for i, (path, name) in enumerate(zip(paths, names, strict=True), start=1):
        text = name
        if names.count(name) > 1:
            text += f" ({Path(path).parent.name or Path(path).parent})"
        text = text.replace("&", "&&")
        number = f"&{i}" if i < 10 else str(i)
        labels.append(f"{number} {text}")
    return labels


def message(parent, text: str, buttons, default, labels: dict | None = None) -> QDialogButtonBox.StandardButton:
    """Show `text` with the given standard buttons, optionally relabelled; returns the one clicked, or Cancel
    for Esc and ✕.

    A plain dialog rather than a QMessageBox, which keeps space for an icon even when it has none.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(APP_NAME)
    box = QDialogButtonBox(buttons)
    for button, label in (labels or {}).items():
        box.button(button).setText(label)
    box.button(default).setDefault(True)
    choice = QDialogButtonBox.Cancel
    def chosen(button) -> None:
        nonlocal choice
        choice = box.standardButton(button)
        dialog.accept()
    box.clicked.connect(chosen)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
    layout.setSpacing(DIALOG_MARGIN)
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)  # file names could otherwise be taken for HTML
    layout.addWidget(label)
    layout.addWidget(box)
    dialog.setFixedSize(dialog.sizeHint())
    dialog.exec()
    return choice


def ask_to_save(parent, name: str) -> QDialogButtonBox.StandardButton:
    """Ask "Save changes to <name>?". Returns Save, Discard ("Don't Save") or Cancel (also for Esc and ✕)."""
    buttons = QDialogButtonBox.Save | QDialogButtonBox.Discard | QDialogButtonBox.Cancel
    labels = {QDialogButtonBox.Discard: "Don't Save"}
    return message(parent, f"Save changes to {name}?", buttons, QDialogButtonBox.Save, labels)


def show_error(parent, text: str) -> None:
    message(parent, text, QDialogButtonBox.Ok, QDialogButtonBox.Ok)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.path: str | None = None  # the open project file; None while untitled
        self.view = EditorView(Graph())
        self.view.scene_replaced.connect(self._watch_scene)
        self.setCentralWidget(self.view)
        self._watch_scene()
        self._saved = snapshot(self.view.scene().graph)
        self._build_menu()
        self._update_title()

    # --- Menu ---

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        self._action(menu, "&New", "Ctrl+N", self.new)
        self._action(menu, "&Open…", "Ctrl+O", self.open)
        self.recent_menu = menu.addMenu("Open &Recent")
        self.recent_menu.setToolTipsVisible(True)
        menu.addSeparator()
        self._action(menu, "&Save", "Ctrl+S", self.save)
        self._action(menu, "Save &As…", "Ctrl+Shift+S", self.save_as)
        menu.addSeparator()
        self._action(menu, "E&xit", "Ctrl+Q", self.close)
        self._update_recent_menu()

        menu = self.menuBar().addMenu("&View")
        self.zoom_in_action = self._action(menu, "Zoom &In", "Ctrl+=", self.view.zoom_in, "Ctrl++")
        self.zoom_out_action = self._action(menu, "Zoom &Out", "Ctrl+-", self.view.zoom_out)
        self._action(menu, "&100%", "Ctrl+0", self.view.reset_zoom)
        self._action(menu, "Zoom to &Fit", "Ctrl+1", self.view.zoom_to_fit)
        menu.addSeparator()
        modes = QActionGroup(self)  # exactly one checked
        self.mode_actions = {}
        for mode, text, key in [(EDIT, "&Edit Mode", "V"), (DRAG, "&Drag Mode", "H")]:
            action = self._action(menu, text, key, lambda checked=False, m=mode: self.view.set_mode(m))
            action.setCheckable(True)
            modes.addAction(action)
            self.mode_actions[mode] = action
        self.view.zoom_changed.connect(self._show_zoom)
        self.view.mode_changed.connect(self._show_mode)
        self._show_zoom(self.view.zoom_index())
        self._show_mode(self.view.mode())

    def _action(self, menu: QMenu, text: str, keys: str, slot, *more_keys: str) -> QAction:
        action = QAction(text, self)
        action.setShortcuts([QKeySequence(k) for k in (keys, *more_keys)])
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _show_zoom(self, index: int) -> None:
        self.zoom_in_action.setEnabled(index < len(ZOOM_LEVELS) - 1)
        self.zoom_out_action.setEnabled(index > 0)

    def _show_mode(self, mode: str) -> None:
        self.mode_actions[mode].setChecked(True)

    # --- Title and unsaved changes ---

    def _watch_scene(self) -> None:
        self.view.scene().edited.connect(self._update_title)

    def is_modified(self) -> bool:
        return snapshot(self.view.scene().graph) != self._saved

    def _display_name(self) -> str:
        return Path(self.path).stem if self.path else UNTITLED

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self._display_name()}[*] - {APP_NAME}")
        self.setWindowModified(self.is_modified())

    def _show(self, graph: Graph, view: ViewState, path: str | None) -> None:
        """Make `graph` the open project, saved at `path`."""
        self.view.set_graph(graph, view)
        self.path = path
        self._saved = snapshot(graph)
        self._update_title()

    def maybe_save(self) -> bool:
        """Before throwing away the open project: offer to save unsaved changes. False means don't go ahead."""
        if not self.is_modified():
            return True
        choice = ask_to_save(self, self._display_name())
        if choice == QDialogButtonBox.Save:
            return self.save()
        return choice == QDialogButtonBox.Discard

    def closeEvent(self, event) -> None:
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

    # --- File actions ---

    def new(self) -> None:
        if self.maybe_save():
            self._show(Graph(), ViewState(), None)

    def open(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", self._dialog_dir(), OPEN_FILTER)
        if path:
            self._remember_dir(path)
            self._open_path(path)

    def open_recent(self, path: str) -> None:
        if not os.path.isfile(path):
            show_error(self, f"{Path(path).name} couldn't be found.\n\n{path}")
            self._remove_recent(path)
            return
        if self.maybe_save():
            self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            graph, view = load(path)
        except (ProjectError, OSError) as error:
            reason = error if isinstance(error, ProjectError) else (error.strerror or error)
            show_error(self, f"Couldn't open {Path(path).name}.\n\n{reason}")
            return
        self._show(graph, view, path)
        self._add_recent(path)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._save_to(self.path)

    def save_as(self) -> bool:
        name = Path(self.path).name if self.path else UNTITLED + EXTENSION
        start = os.path.join(self._dialog_dir(), name)
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", start, PROJECT_FILTER)
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        self._remember_dir(path)
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        graph = self.view.scene().graph
        try:
            save(graph, self.view.view_state(), path)
        except OSError as error:
            show_error(self, f"Couldn't save {Path(path).name}.\n\n{error.strerror or error}")
            return False
        self.path = path
        self._saved = snapshot(graph)
        self._update_title()
        self._add_recent(path)
        return True

    # --- Dialog folder ---

    def _dialog_dir(self) -> str:
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        folder = app_settings().value(LAST_PROJECT_DIR_KEY, documents)
        return folder if os.path.isdir(folder) else documents

    def _remember_dir(self, path: str) -> None:
        app_settings().setValue(LAST_PROJECT_DIR_KEY, str(Path(path).parent))

    # --- Recent files ---

    def _recent_files(self) -> list[str]:
        value = app_settings().value(RECENT_FILES_KEY, [])
        if isinstance(value, str):  # QSettings returns a one-item list as a plain string
            value = [value]
        return [str(p) for p in value or []]

    def _set_recent_files(self, paths: list[str]) -> None:
        settings = app_settings()
        if paths:
            settings.setValue(RECENT_FILES_KEY, paths[:MAX_RECENT])
        else:
            settings.remove(RECENT_FILES_KEY)
        self._update_recent_menu()

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path).replace("\\", "/")
        self._set_recent_files([path] + [p for p in self._recent_files() if not _same_file(p, path)])

    def _remove_recent(self, path: str) -> None:
        self._set_recent_files([p for p in self._recent_files() if not _same_file(p, path)])

    def _update_recent_menu(self) -> None:
        menu = self.recent_menu
        menu.clear()
        paths = self._recent_files()
        for path, label in zip(paths, recent_labels(paths), strict=True):
            action = menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: self.open_recent(p))
        if paths:
            menu.addSeparator()
            menu.addAction("&Clear Recent").triggered.connect(lambda: self._set_recent_files([]))
        menu.setEnabled(bool(paths))
