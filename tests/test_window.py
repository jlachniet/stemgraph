import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QGraphicsProxyWidget, QLabel, QLineEdit

import window
from graph import Graph
from project import ViewState, save
from window import MainWindow, message, recent_labels

SAVE, DISCARD, CANCEL = QDialogButtonBox.Save, QDialogButtonBox.Discard, QDialogButtonBox.Cancel


# --- Fixtures: the window, with its dialogs replaced by scripted answers ---


class Prompts:
    """Answers for the unsaved-changes prompt, in order, and the project names it was asked about."""

    def __init__(self) -> None:
        self.answers: list = []
        self.asked: list[str] = []

    def __call__(self, parent, name: str):
        self.asked.append(name)
        return self.answers.pop(0)


@pytest.fixture
def prompts(monkeypatch) -> Prompts:
    prompts = Prompts()
    monkeypatch.setattr(window, "ask_to_save", prompts)
    return prompts


@pytest.fixture
def errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(window, "show_error", lambda parent, text: shown.append(text))
    return shown


@pytest.fixture
def file_dialogs(monkeypatch):
    """Call with open=/save= paths to choose in the next Open/Save As dialog ("" cancels)."""

    def choose(open: str | None = None, save: str | None = None) -> None:
        if open is not None:
            monkeypatch.setattr(window.QFileDialog, "getOpenFileName", lambda *args: (open, ""))
        if save is not None:
            monkeypatch.setattr(window.QFileDialog, "getSaveFileName", lambda *args: (save, ""))

    return choose


@pytest.fixture
def win(qapp, prompts, errors):
    w = MainWindow()
    w.resize(800, 600)
    w.show()
    qapp.processEvents()
    yield w
    w.hide()  # not close(): that would ask about unsaved changes
    w.deleteLater()


def add_node(w: MainWindow, key: str = "output", x: float = 0, y: float = 0) -> None:
    w.view.scene().add_node(key, QPointF(x, y))


def node_count(w: MainWindow) -> int:
    return len(w.view.scene().graph.nodes)


def saved_project(tmp_path, name: str = "song.sgp", nodes: int = 1, view: ViewState | None = None) -> str:
    graph = Graph()
    for i in range(nodes):
        graph.add_node("output", i * 240, 0)
    path = str(tmp_path / name)
    save(graph, view or ViewState(), path)
    return path.replace("\\", "/")


# --- Recent menu labels ---


def test_recent_labels_number_and_escape():
    paths = [f"C:/p/song{i}.sgp" for i in range(1, 11)]
    paths[0] = "C:/p/rock & roll.sgp"
    labels = recent_labels(paths)
    assert labels[0] == "&1 rock && roll"
    assert labels[1] == "&2 song2"
    assert labels[9] == "10 song10"


def test_recent_labels_disambiguate_same_name():
    labels = recent_labels(["C:/a/mix.sgp", "C:/b/mix.sgp", "C:/b/other.sgp"])
    assert labels == ["&1 mix (a)", "&2 mix (b)", "&3 other"]


# --- Title and unsaved changes ---


def test_starts_as_unmodified_untitled_project(win):
    assert win.windowTitle() == "Untitled[*] - stemgraph"
    assert not win.isWindowModified()
    assert node_count(win) == 0


def test_edits_mark_project_modified(win):
    add_node(win)
    assert win.isWindowModified()


def test_edits_undone_by_hand_clear_the_asterisk(win, file_dialogs, tmp_path):
    add_node(win)
    file_dialogs(save=str(tmp_path / "song.sgp"))
    win.save()
    scene = win.view.scene()
    node_id = next(iter(scene.graph.nodes))
    item = scene.node_items[node_id]

    scene.set_value(node_id, "name", "x")
    assert win.isWindowModified()
    scene.set_value(node_id, "name", "")
    assert not win.isWindowModified()

    item.setPos(240, 0)
    assert win.isWindowModified()
    item.setPos(0, 0)
    assert not win.isWindowModified()


def test_view_changes_do_not_mark_project_modified(win):
    win.view.zoom_in()
    win.view.zoom_to_fit()
    win.view.set_mode("drag")
    assert not win.isWindowModified()


# --- Saving ---


def test_save_untitled_asks_for_path_and_adds_extension(win, file_dialogs, tmp_path):
    add_node(win)
    file_dialogs(save=str(tmp_path / "song"))
    assert win.save()
    assert (tmp_path / "song.sgp").is_file()
    assert win.windowTitle() == "song[*] - stemgraph"
    assert not win.isWindowModified()
    assert win.recent_files() == [(tmp_path / "song.sgp").as_posix()]


def test_save_again_does_not_ask_for_path(win, file_dialogs, tmp_path):
    file_dialogs(save=str(tmp_path / "song.sgp"))
    win.save()
    file_dialogs(save="")  # would cancel, if it were asked
    add_node(win)
    assert win.save()
    assert not win.isWindowModified()


def test_cancelled_save_as_changes_nothing(win, file_dialogs):
    add_node(win)
    file_dialogs(save="")
    assert not win.save()
    assert win.path is None
    assert win.isWindowModified()


def test_failed_save_shows_error_and_stays_modified(win, file_dialogs, errors, tmp_path):
    add_node(win)
    file_dialogs(save=str(tmp_path / "missing folder" / "song.sgp"))
    assert not win.save()
    assert len(errors) == 1 and errors[0].startswith("Couldn't save song.sgp.")
    assert win.path is None
    assert win.isWindowModified()


# --- The unsaved-changes prompt ---


def test_no_prompt_without_unsaved_changes(win, prompts):
    win.new()
    assert prompts.asked == []


def test_cancel_keeps_the_project(win, prompts):
    add_node(win)
    prompts.answers = [CANCEL]
    win.new()
    assert prompts.asked == ["Untitled"]
    assert node_count(win) == 1


def test_dont_save_discards_changes(win, prompts):
    add_node(win)
    prompts.answers = [DISCARD]
    win.new()
    assert node_count(win) == 0
    assert not win.isWindowModified()


def test_save_from_prompt_saves_then_continues(win, prompts, file_dialogs, tmp_path):
    add_node(win)
    prompts.answers = [SAVE]
    file_dialogs(save=str(tmp_path / "song.sgp"))
    win.new()
    assert (tmp_path / "song.sgp").is_file()
    assert node_count(win) == 0
    assert win.path is None


def test_cancelling_save_as_from_prompt_cancels_everything(win, prompts, file_dialogs):
    add_node(win)
    prompts.answers = [SAVE]
    file_dialogs(save="")
    win.new()
    assert node_count(win) == 1


def test_close_is_cancelled_from_prompt(win, prompts):
    add_node(win)
    prompts.answers = [CANCEL]
    assert not win.close()
    assert win.isVisible()


def test_close_without_changes_needs_no_prompt(win, prompts):
    assert win.close()
    assert prompts.asked == []


# --- New and Open ---


def test_new_resets_graph_and_view(win, prompts):
    add_node(win)
    win.view.zoom_in()
    prompts.answers = [DISCARD]
    win.new()
    assert node_count(win) == 0
    assert win.view.view_state() == ViewState()
    assert win.windowTitle() == "Untitled[*] - stemgraph"


def test_open_restores_graph_view_and_title(win, file_dialogs, tmp_path):
    path = saved_project(tmp_path, nodes=2, view=ViewState(1.5, 120, 24))
    file_dialogs(open=path)
    win.open()
    assert node_count(win) == 2
    assert win.view.view_state() == ViewState(1.5, 120, 24)
    assert win.windowTitle() == "song[*] - stemgraph"
    assert not win.isWindowModified()
    assert win.recent_files() == [path]


def test_open_dialog_offers_all_files(win, monkeypatch, tmp_path):
    filters = []

    def cancelled_dialog(parent, title, folder, file_filter):
        filters.append(file_filter)
        return "", ""

    monkeypatch.setattr(window.QFileDialog, "getOpenFileName", cancelled_dialog)
    win.open()
    assert filters == ["stemgraph Project Files (*.sgp);;All Files (*)"]


def test_invalid_file_shows_error_and_keeps_project(win, prompts, errors, file_dialogs, tmp_path):
    (tmp_path / "bad.sgp").write_text("not json")
    add_node(win)
    prompts.answers = [DISCARD]
    file_dialogs(open=str(tmp_path / "bad.sgp"))
    win.open()
    assert errors == ["Couldn't open bad.sgp.\n\nThe file isn't a stemgraph project, or it is damaged."]
    assert node_count(win) == 1
    assert win.isWindowModified()
    assert win.recent_files() == []


def test_opening_the_open_file_reloads_it(win, prompts, tmp_path):
    path = saved_project(tmp_path)
    win.open_recent(path)
    add_node(win, x=480)
    prompts.answers = [DISCARD]
    win.open_recent(path)
    assert node_count(win) == 1
    assert not win.isWindowModified()


def test_missing_recent_file_shows_error_and_is_removed(win, prompts, errors, tmp_path):
    missing = (tmp_path / "gone.sgp").as_posix()
    win._add_recent(missing)
    add_node(win)
    win.open_recent(missing)
    assert errors == [f"gone.sgp couldn't be found.\n\n{missing}"]
    assert prompts.asked == []  # nothing would be replaced, so no need to ask
    assert win.recent_files() == []


# --- Recent files ---


def test_recent_files_newest_first_without_duplicates_and_capped(win, tmp_path):
    paths = [(tmp_path / f"p{i}.sgp").as_posix() for i in range(12)]
    for path in paths:
        win._add_recent(path)
    win._add_recent(paths[5])
    expected = [paths[5]] + [p for p in reversed(paths) if p != paths[5]][:9]
    assert win.recent_files() == expected
    labels = [a.text() for a in win.recent_menu.actions()]
    assert labels[:2] == ["&1 p5", "&2 p11"]
    assert labels[-2:] == ["", "&Clear Recent"]  # separator, then Clear


def test_clear_recent_empties_and_disables_menu(win, tmp_path):
    assert not win.recent_menu.isEnabled()
    win._add_recent((tmp_path / "a.sgp").as_posix())
    assert win.recent_menu.isEnabled()
    win.recent_menu.actions()[-1].trigger()
    assert win.recent_files() == []
    assert not win.recent_menu.isEnabled()


# --- View menu ---


def view_menu(w: MainWindow):
    return w.menuBar().actions()[1].menu()


def test_menu_bar_has_file_view_then_help(win):
    assert [a.text() for a in win.menuBar().actions()] == ["&File", "&View", "&Help"]


def test_view_menu_items_and_shortcuts(win):
    items = [(a.text(), a.shortcut().toString()) for a in view_menu(win).actions()]
    assert items == [
        ("Zoom &In", "Ctrl+="),
        ("Zoom &Out", "Ctrl+-"),
        ("&100%", "Ctrl+0"),
        ("Zoom to &Fit", "Ctrl+1"),
        ("", ""),
        ("&Edit Mode", "V"),
        ("&Drag Mode", "H"),
    ]


def test_zoom_shortcuts(win, qapp):
    view = win.view
    for key, modifier, zoom in [
        (Qt.Key_Equal, Qt.ControlModifier, 1.1),
        (Qt.Key_Plus, Qt.ControlModifier, 1.25),
        (Qt.Key_Minus, Qt.ControlModifier, 1.1),
        (Qt.Key_0, Qt.ControlModifier, 1.0),
    ]:
        QTest.keyClick(view, key, modifier)
        assert view.view_state().zoom == zoom


def test_zoom_items_disabled_at_limits(win):
    for _ in range(20):
        win.view.zoom_in()
    assert not win.zoom_in_action.isEnabled() and win.zoom_out_action.isEnabled()
    for _ in range(20):
        win.view.zoom_out()
    assert win.zoom_in_action.isEnabled() and not win.zoom_out_action.isEnabled()


def test_mode_items_follow_keys_and_corner_buttons(win):
    edit, drag = win.mode_actions["edit"], win.mode_actions["drag"]
    assert edit.isChecked() and not drag.isChecked()
    QTest.keyClick(win.view, Qt.Key_H)
    assert win.view.mode() == "drag" and drag.isChecked()
    QTest.keyClick(win.view, Qt.Key_V)
    assert win.view.mode() == "edit" and edit.isChecked()
    drag.trigger()
    assert win.view.mode() == "drag"
    win.view.controls.edit_mode.click()
    assert edit.isChecked() and not drag.isChecked()


def test_typing_mode_keys_in_a_name_box_types_them(win, qapp):
    # V and H switch cursor modes, but not while typing in a node.
    add_node(win)
    view = win.view
    proxy = next(item for item in view.scene().items() if isinstance(item, QGraphicsProxyWidget))
    name_box = proxy.widget()
    assert isinstance(name_box, QLineEdit)
    click_at = view.mapFromScene(proxy.sceneBoundingRect().center())
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, click_at)
    for key in (Qt.Key_V, Qt.Key_H):
        QTest.keyClick(qapp.focusWidget(), key)
    assert name_box.text() == "vh"
    assert view.mode() == "edit"


# --- The app's own dialogs ---


def answer_next_dialog(qapp, action) -> None:
    """Once the next modal dialog is open, do `action` to it."""
    QTimer.singleShot(0, lambda: action(qapp.activeModalWidget()))


@pytest.mark.parametrize("click, result", [(SAVE, SAVE), (DISCARD, DISCARD), (CANCEL, CANCEL)])
def test_save_prompt_buttons(qapp, click, result):
    answer_next_dialog(qapp, lambda d: d.findChild(QDialogButtonBox).button(click).click())
    assert window.ask_to_save(None, "song") == result


@pytest.mark.parametrize("key, result", [(Qt.Key_Escape, CANCEL), (Qt.Key_Return, SAVE)])
def test_save_prompt_keys(qapp, key, result):
    answer_next_dialog(qapp, lambda d: QTest.keyClick(d, key))
    assert window.ask_to_save(None, "song") == result


def test_save_prompt_text_and_labels(qapp):
    seen = {}

    def inspect(dialog):
        seen["text"] = dialog.findChild(QLabel).text()
        seen["buttons"] = [b.text() for b in dialog.findChild(QDialogButtonBox).buttons()]
        dialog.reject()

    answer_next_dialog(qapp, inspect)
    window.ask_to_save(None, "song")
    assert seen["text"] == "Save changes to song?"
    assert sorted(seen["buttons"]) == ["Cancel", "Don't Save", "Save"]


def test_error_dialog_has_only_ok(qapp):
    seen = {}

    def inspect(dialog):
        seen["buttons"] = [b.text() for b in dialog.findChild(QDialogButtonBox).buttons()]
        dialog.reject()

    answer_next_dialog(qapp, inspect)
    window.show_error(None, "Couldn't open song.sgp.")
    assert seen["buttons"] == ["OK"]


def test_dialog_text_is_never_treated_as_html(qapp):
    seen = {}

    def inspect(dialog):
        label = dialog.findChild(QLabel)
        seen["format"] = label.textFormat()
        dialog.reject()

    answer_next_dialog(qapp, inspect)
    message(None, "Couldn't open <b>mix</b>.sgp.", QDialogButtonBox.Ok, QDialogButtonBox.Ok)
    assert seen["format"] == Qt.PlainText
