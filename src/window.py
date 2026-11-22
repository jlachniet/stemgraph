"""Main window: the menus, the title bar, dialogs, and keeping track of the open project file."""

import json
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QVBoxLayout,
)

import build
import strings
from editor import (
    DRAG,
    EDIT,
    EDIT_SHORTCUTS,
    ZOOM_LEVELS,
    EditorScene,
    EditorView,
    app_settings,
    audio_files,
    dropped_paths,
)
from graph import Graph
from progress import ProgressDialog
from project import EXTENSION, ProjectError, ViewState, load, save, snapshot
from welcome import AboutPanel, StartPanel

PROJECT_FILTER = strings.PROJECT_FILTER.format(extension=EXTENSION)
OPEN_FILTER = PROJECT_FILTER + ";;" + strings.ALL_FILES_FILTER  # loading checks the contents, so any file will do
MAX_RECENT = 10
RECENT_FILES_KEY = "recent_files"         # QSettings key: recently opened or saved projects, newest first
LAST_PROJECT_DIR_KEY = "last_project_dir"  # QSettings key: folder the project dialogs last used
EXPORT_DIRS_KEY = "export_dirs"  # QSettings key: JSON object, project file -> folder it was last built to
UNTITLED_EXPORT_DIR_KEY = "untitled_export_dir"  # QSettings key: folder untitled projects were last built to
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
            text = strings.RECENT_ITEM_FOLDER.format(name=name, folder=Path(path).parent.name or Path(path).parent)
        text = text.replace("&", "&&")
        number = f"&{i}" if i < 10 else str(i)
        labels.append(strings.RECENT_ITEM.format(number=number, name=text))
    return labels


def message(parent, text: str, buttons, default, labels: dict | None = None) -> QDialogButtonBox.StandardButton:
    """Show `text` with the given standard buttons, optionally relabelled; returns the one clicked, or Cancel
    for Esc and ✕.

    A plain dialog rather than a QMessageBox, which keeps space for an icon even when it has none.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(strings.APP_NAME)
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
    labels = {QDialogButtonBox.Discard: strings.DONT_SAVE}
    return message(parent, strings.SAVE_CHANGES.format(name=name), buttons, QDialogButtonBox.Save, labels)


def show_error(parent, text: str) -> None:
    message(parent, text, QDialogButtonBox.Ok, QDialogButtonBox.Ok)


def ask_to_replace(parent, names: list[str]) -> bool:
    """Ask before replacing files in the export folder. True means replace them."""
    listed = "\n".join(strings.REPLACE_ITEM.format(file=name) for name in names)
    text = (strings.REPLACE_ONE if len(names) == 1 else strings.REPLACE_MANY).format(files=listed)
    labels = {QDialogButtonBox.Yes: strings.REPLACE_BUTTON}
    choice = message(parent, text, QDialogButtonBox.Yes | QDialogButtonBox.Cancel, QDialogButtonBox.Cancel, labels)
    return choice == QDialogButtonBox.Yes


def choose_export_folder(parent, start: str) -> str:
    """Ask for the folder to export to. Returns "" if cancelled."""
    return QFileDialog.getExistingDirectory(parent, strings.EXPORT_FOLDER_TITLE, start)


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).replace("\\", "/")


class MainWindow(QMainWindow):
    recent_changed = Signal()  # the recent files list changed

    def __init__(self) -> None:
        super().__init__()
        self.panel: StartPanel | AboutPanel | None = None  # the start or About panel, while one is open
        self.path: str | None = None  # the open project file; None while untitled
        self.view = EditorView(Graph())
        self.view.scene_replaced.connect(self._watch_scene)
        self.setCentralWidget(self.view)
        self._build_menu()
        self._watch_scene()
        self.view.build_requested.connect(self.build)
        self.view.files_dropped.connect(self.add_files)
        self.setAcceptDrops(True)  # files dropped outside the canvas, such as on the start panel
        self._saved = snapshot(self.view.scene().graph)
        self._export_dir: str | None = None  # folder the open project was built to in this session
        self._update_title()

    # --- Menu ---

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu(strings.MENU_FILE)
        self._action(menu, strings.MENU_NEW, "Ctrl+N", self.new)
        self._action(menu, strings.MENU_OPEN, "Ctrl+O", self.open)
        self.recent_menu = menu.addMenu(strings.MENU_OPEN_RECENT)
        self.recent_menu.setToolTipsVisible(True)
        menu.addSeparator()
        self._action(menu, strings.MENU_SAVE, "Ctrl+S", self.save)
        self._action(menu, strings.MENU_SAVE_AS, "Ctrl+Shift+S", self.save_as)
        menu.addSeparator()
        self.build_action = self._action(menu, strings.MENU_BUILD_ACTION, "Ctrl+B", self.build)
        menu.addSeparator()
        self._action(menu, strings.MENU_EXIT, "Ctrl+Q", self.close)
        self._update_recent_menu()

        menu = self.menuBar().addMenu(strings.MENU_EDIT)
        self.edit_actions: dict[str, QAction] = {}
        for group in [
            [("undo", strings.MENU_UNDO), ("redo", strings.MENU_REDO)],
            [("cut", strings.MENU_CUT), ("copy", strings.MENU_COPY), ("paste", strings.MENU_PASTE),
             ("duplicate", strings.MENU_DUPLICATE), ("delete", strings.MENU_DELETE)],
            [("select_all", strings.MENU_SELECT_ALL)],
        ]:
            if self.edit_actions:
                menu.addSeparator()
            for command, text in group:
                keys = EDIT_SHORTCUTS[command]
                slot = lambda checked=False, c=command: self.edit(c)  # noqa: E731
                self.edit_actions[command] = self._action(menu, text, keys[0], slot, *keys[1:])
        menu.aboutToShow.connect(self._update_edit_actions)
        QApplication.clipboard().dataChanged.connect(self._update_edit_actions)

        menu = self.menuBar().addMenu(strings.MENU_VIEW)
        self.zoom_in_action = self._action(menu, strings.MENU_ZOOM_IN, "Ctrl+=", self.view.zoom_in, "Ctrl++")
        self.zoom_out_action = self._action(menu, strings.MENU_ZOOM_OUT, "Ctrl+-", self.view.zoom_out)
        self._action(menu, strings.MENU_ACTUAL_SIZE, "Ctrl+0", self.view.reset_zoom)
        self._action(menu, strings.MENU_ZOOM_TO_FIT, "Ctrl+1", self.view.zoom_to_fit)
        menu.addSeparator()
        modes = QActionGroup(self)  # exactly one checked
        self.mode_actions = {}
        for mode, text, key in [(EDIT, strings.MENU_EDIT_MODE, "V"), (DRAG, strings.MENU_DRAG_MODE, "H")]:
            action = self._action(menu, text, key, lambda checked=False, m=mode: self.view.set_mode(m))
            action.setCheckable(True)
            modes.addAction(action)
            self.mode_actions[mode] = action
        menu = self.menuBar().addMenu(strings.MENU_HELP)
        menu.addAction(strings.MENU_ABOUT).triggered.connect(self.show_about)

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

    def edit(self, command: str) -> None:
        """Do an Edit menu command: on the text while typing in a Name box, otherwise on the graph."""
        field = self.view.text_field()
        if field:
            text_commands = {
                "undo": field.undo, "redo": field.redo, "cut": field.cut, "copy": field.copy,
                "paste": field.paste, "delete": field.del_, "select_all": field.selectAll,
            }
            if command in text_commands:
                text_commands[command]()
            return
        scene = self.view.scene()
        if command == "paste":
            scene.paste(self.view.mouse_scene_pos())
        else:
            getattr(scene, "delete_selected" if command == "delete" else command)()

    def _update_edit_actions(self) -> None:
        if not isinstance(self.view.scene(), EditorScene):
            return  # the scene is being destroyed as the app quits, and still sends selectionChanged
        field = self.view.text_field()
        if field:
            selected = field.hasSelectedText()
            enabled = {
                "undo": field.isUndoAvailable(), "redo": field.isRedoAvailable(), "cut": selected, "copy": selected,
                "paste": bool(QApplication.clipboard().text()), "duplicate": False, "delete": selected,
                "select_all": bool(field.text()),
            }
        else:
            scene = self.view.scene()
            nodes = scene.has_selected_nodes()
            enabled = {
                "undo": scene.can_undo(), "redo": scene.can_redo(), "cut": nodes, "copy": nodes,
                "paste": scene.can_paste(), "duplicate": nodes, "delete": bool(scene.selectedItems()),
                "select_all": bool(scene.graph.nodes),
            }
        for command, action in self.edit_actions.items():
            action.setEnabled(enabled[command])

    def _show_zoom(self, index: int) -> None:
        self.zoom_in_action.setEnabled(index < len(ZOOM_LEVELS) - 1)
        self.zoom_out_action.setEnabled(index > 0)

    def _show_mode(self, mode: str) -> None:
        self.mode_actions[mode].setChecked(True)

    # --- Title and unsaved changes ---

    def _watch_scene(self) -> None:
        scene = self.view.scene()
        scene.edited.connect(self._update_title)
        for signal in (scene.edited, scene.history_changed, scene.selectionChanged, scene.focusItemChanged):
            signal.connect(self._update_edit_actions)
        self._update_edit_actions()

    def is_modified(self) -> bool:
        return snapshot(self.view.scene().graph) != self._saved

    def _display_name(self) -> str:
        return Path(self.path).stem if self.path else strings.UNTITLED

    def _update_title(self) -> None:
        self.setWindowTitle(strings.WINDOW_TITLE.format(name=self._display_name(), app=strings.APP_NAME))
        self.setWindowModified(self.is_modified())

    def _show(self, graph: Graph, view: ViewState, path: str | None) -> None:
        """Make `graph` the open project, saved at `path`."""
        self._close_panel()
        self.view.set_graph(graph, view)
        self.path = path
        self._saved = snapshot(graph)
        self._export_dir = None
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

    # --- Start and About panels ---

    def show_start(self) -> None:
        """Show the start panel: New, Open… and the recent projects. Closed once a project is started or opened."""
        self._open_panel(StartPanel(self, MAX_RECENT))

    def show_about(self) -> None:
        self._open_panel(AboutPanel(self))

    def _open_panel(self, panel: StartPanel | AboutPanel) -> None:
        self._close_panel()
        self.panel = panel
        panel.closed.connect(lambda: self._forget_panel(panel))
        panel.open()

    def _forget_panel(self, panel) -> None:
        if self.panel is panel:
            self.panel = None

    def _close_panel(self) -> None:
        if self.panel:
            self.panel.dismiss()

    # --- Dropping files ---

    def dragEnterEvent(self, event) -> None:
        if dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event) -> None:
        paths = dropped_paths(event.mimeData())
        if paths:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.add_files(paths, None, None)

    def add_files(self, paths: list[str], pos: QPointF | None, target: int | None) -> None:
        """Files dropped on the window or chosen with Add Inputs…, in natural name order. A project among them is
        opened. Otherwise each audio file gets an Input in a column at scene point `pos` (or the middle of the
        canvas), except that a single file dropped on an Input (`target`) becomes its file. Dropped on the start
        panel, they start a new project."""
        projects = [path for path in paths if path.lower().endswith(EXTENSION) and os.path.isfile(path)]
        if projects:
            if self.maybe_save():
                self._open_path(projects[0])
            return
        files = audio_files(paths)
        if not files:
            show_error(self, strings.NO_AUDIO_FILES)
            return
        if isinstance(self.panel, StartPanel) and self.panel.isVisible():
            if not self.maybe_save():
                return
            self._show(Graph(), ViewState(), None)
            pos = target = None
        self._close_panel()
        scene = self.view.scene()
        if target is not None:
            scene.set_input_file(target, files[0])
            return
        if pos is None:
            pos = self.view.mapToScene(self.view.viewport().rect().center())
        scene.add_inputs(files, pos)

    # --- File actions ---

    def new(self) -> None:
        if self.maybe_save():
            self._show(Graph(), ViewState(), None)

    def open(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, strings.OPEN_PROJECT_TITLE, self._dialog_dir(), OPEN_FILTER)
        if path:
            self._remember_dir(path)
            self._open_path(path)

    def open_recent(self, path: str) -> None:
        if not os.path.isfile(path):
            show_error(self, strings.PROJECT_NOT_FOUND.format(file=Path(path).name, path=path))
            self._remove_recent(path)
            return
        if self.maybe_save():
            self._open_path(path)

    def _open_path(self, path: str) -> None:
        try:
            graph, view = load(path)
        except (ProjectError, OSError) as error:
            reason = error if isinstance(error, ProjectError) else (error.strerror or error)
            show_error(self, strings.CANT_OPEN.format(file=Path(path).name, reason=reason))
            return
        self._show(graph, view, path)
        self._add_recent(path)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._save_to(self.path)

    def save_as(self) -> bool:
        name = Path(self.path).name if self.path else strings.UNTITLED + EXTENSION
        start = os.path.join(self._dialog_dir(), name)
        path, _ = QFileDialog.getSaveFileName(self, strings.SAVE_PROJECT_TITLE, start, PROJECT_FILTER)
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
            show_error(self, strings.CANT_SAVE.format(file=Path(path).name, reason=error.strerror or error))
            return False
        if self.path is None or not _same_file(self.path, path):
            folder = self._export_dir or (self._stored_export_dir(self.path) if self.path else None)
            if folder:
                self._store_export_dir(path, folder)  # Save As keeps the export folder
        self.path = path
        self._saved = snapshot(graph)
        self._update_title()
        self._add_recent(path)
        return True

    # --- Build ---

    def build(self) -> None:
        """Check the graph, ask where to export, confirm replacing files, then build with a progress window."""
        try:
            plan = build.make_plan(self.view.scene().graph)
        except build.BuildProblems as error:
            listed = "\n".join(strings.PROBLEM_ITEM.format(problem=p) for p in error.problems)
            show_error(self, strings.CANT_BUILD_YET.format(problems=listed))
            return
        folder = choose_export_folder(self, self._export_dir_start())
        if not folder:
            return
        existing = build.existing_files(plan, folder)
        if existing and not ask_to_replace(self, existing):
            return
        self._export_dir = folder
        if self.path:
            self._store_export_dir(self.path, folder)
        else:
            app_settings().setValue(UNTITLED_EXPORT_DIR_KEY, folder)

        self.build_action.setEnabled(False)
        self.view.build_button.setEnabled(False)
        try:
            ProgressDialog(self, plan, folder, strings.PROGRESS_TITLE.format(name=self._display_name())).exec()
        finally:
            self.build_action.setEnabled(True)
            self.view.build_button.setEnabled(True)

    def _export_dir_start(self) -> str:
        """Where the export folder prompt starts: the folder this project was last built to, if it still exists;
        otherwise the project's folder (Documents for untitled projects)."""
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        if self.path:
            remembered, default = self._stored_export_dir(self.path), str(Path(self.path).parent)
        else:
            remembered, default = app_settings().value(UNTITLED_EXPORT_DIR_KEY), documents
        for folder in (self._export_dir, remembered, default, documents):
            if folder and os.path.isdir(folder):
                return folder
        return documents

    def _export_dirs(self) -> dict[str, str]:
        try:
            value = json.loads(app_settings().value(EXPORT_DIRS_KEY, "{}"))
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _stored_export_dir(self, project: str) -> str | None:
        folder = self._export_dirs().get(_path_key(project))
        return folder if isinstance(folder, str) else None

    def _store_export_dir(self, project: str, folder: str) -> None:
        folders = self._export_dirs()
        folders[_path_key(project)] = folder
        app_settings().setValue(EXPORT_DIRS_KEY, json.dumps(folders, ensure_ascii=False))

    # --- Dialog folder ---

    def _dialog_dir(self) -> str:
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        folder = app_settings().value(LAST_PROJECT_DIR_KEY, documents)
        return folder if os.path.isdir(folder) else documents

    def _remember_dir(self, path: str) -> None:
        app_settings().setValue(LAST_PROJECT_DIR_KEY, str(Path(path).parent))

    # --- Recent files ---

    def recent_files(self) -> list[str]:
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
        self.recent_changed.emit()

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path).replace("\\", "/")
        self._set_recent_files([path] + [p for p in self.recent_files() if not _same_file(p, path)])

    def _remove_recent(self, path: str) -> None:
        self._set_recent_files([p for p in self.recent_files() if not _same_file(p, path)])

    def _update_recent_menu(self) -> None:
        menu = self.recent_menu
        menu.clear()
        paths = self.recent_files()
        for path, label in zip(paths, recent_labels(paths), strict=True):
            action = menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: self.open_recent(p))
        if paths:
            menu.addSeparator()
            menu.addAction(strings.MENU_CLEAR_RECENT).triggered.connect(lambda: self._set_recent_files([]))
        menu.setEnabled(bool(paths))
