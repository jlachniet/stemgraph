import os

import numpy as np
import pytest
import soundfile
from PySide6.QtWidgets import QDialogButtonBox

import build
import strings
import window
from editor import app_settings
from graph import Graph
from progress import ProgressDialog
from window import MainWindow

# --- Fixtures ---


@pytest.fixture
def errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(window, "show_error", lambda parent, text: shown.append(text))
    return shown


@pytest.fixture
def builds(monkeypatch) -> list:
    """Replaces the progress window: records (plan, folder, title) instead of building."""
    started = []

    class FakeDialog:
        def __init__(self, parent, plan, folder, title) -> None:
            started.append((plan, folder, title))
            assert not parent.build_action.isEnabled() and not parent.view.build_button.isEnabled()

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(window, "ProgressDialog", FakeDialog)
    return started


@pytest.fixture
def folders(monkeypatch):
    """Call with the folder to choose in the next export folder prompt ("" cancels); records where it started."""
    starts: list[str] = []

    def choose(folder: str) -> None:
        def prompt(parent, start):
            starts.append(start)
            return folder
        monkeypatch.setattr(window, "choose_export_folder", prompt)

    choose.starts = starts
    return choose


@pytest.fixture
def win(qapp, errors):
    w = MainWindow()
    w.resize(800, 600)
    w.show()
    yield w
    w._saved = None  # skip the unsaved-changes prompt
    w.is_modified = lambda: False
    w.close()


def buildable(w: MainWindow, tmp_path, name: str = "Vocals") -> None:
    """Put Input (a short WAV) → Output `name` on the canvas."""
    path = tmp_path / "song.wav"
    soundfile.write(path, np.zeros((100, 2), dtype=np.float32), 44100, subtype="FLOAT")
    g = Graph()
    source = g.add_node("input", 0, 0)
    g.set_value(source.id, "file", str(path))
    out = g.add_node("output", 300, 0)
    g.set_value(out.id, "name", name)
    g.connect(source.id, 0, out.id, 0)
    w.view.set_graph(g, w.view.view_state())


# --- Starting a build ---


def test_build_menu_item_and_button(win):
    file_menu = win.menuBar().actions()[0].menu()
    items = [(a.text(), a.shortcut().toString()) for a in file_menu.actions() if not a.isSeparator()]
    assert items[-2:] == [("&Build…", "Ctrl+B"), ("E&xit", "Ctrl+Q")]
    button = win.view.build_button
    assert button.text() == "Build" and button.toolTip() == "Build (Ctrl+B)"
    assert button.x() == 12 and button.geometry().bottom() == win.view.height() - 12 - 1


def test_the_button_starts_a_build(win, tmp_path, folders, builds):
    buildable(win, tmp_path)
    folders(str(tmp_path))
    win.view.build_button.click()
    assert len(builds) == 1
    plan, folder, title = builds[0]
    assert plan.files == ["Vocals.wav"] and folder == str(tmp_path) and title == "Building Untitled"
    assert win.build_action.isEnabled() and win.view.build_button.isEnabled()


def test_problems_are_shown_before_the_folder_prompt(win, errors, folders, builds):
    folders("should not be asked")
    win.build()
    assert errors == [strings.CANT_BUILD_YET.format(problems="• " + strings.NOTHING_TO_BUILD)]
    assert folders.starts == [] and builds == []


def test_cancelling_the_folder_prompt_builds_nothing(win, tmp_path, folders, builds):
    buildable(win, tmp_path)
    folders("")
    win.build()
    assert builds == []


def test_existing_files_are_only_replaced_when_confirmed(win, tmp_path, folders, builds, monkeypatch):
    buildable(win, tmp_path)
    (tmp_path / "Vocals.wav").write_bytes(b"old")
    folders(str(tmp_path))
    asked = []
    monkeypatch.setattr(window, "ask_to_replace", lambda parent, names: asked.append(names) or False)
    win.build()
    assert asked == [["Vocals.wav"]] and builds == []

    monkeypatch.setattr(window, "ask_to_replace", lambda parent, names: True)
    win.build()
    assert len(builds) == 1


def test_replace_prompt_lists_the_files(monkeypatch):
    shown = []

    def fake_message(parent, text, buttons, default, labels=None):
        shown.append((text, labels))
        return QDialogButtonBox.Yes

    monkeypatch.setattr(window, "message", fake_message)
    assert window.ask_to_replace(None, ["A.wav", "B.wav"])
    assert shown == [("These files already exist in the export folder:\n\n    A.wav\n    B.wav\n\nReplace them?",
                      {QDialogButtonBox.Yes: "Replace"})]


# --- Export folder memory ---


def test_untitled_projects_start_in_documents_then_the_last_untitled_folder(win, tmp_path, folders, builds):
    buildable(win, tmp_path)
    folders(str(tmp_path))
    win.build()
    win._show(Graph(), win.view.view_state(), None)  # File > New
    buildable(win, tmp_path)
    win.build()
    assert os.path.normcase(folders.starts[0]) != os.path.normcase(str(tmp_path))  # Documents at first
    assert folders.starts[1] == str(tmp_path)
    assert app_settings().value(window.UNTITLED_EXPORT_DIR_KEY) == str(tmp_path)


def test_saved_projects_remember_their_own_folder(win, tmp_path, folders, builds):
    project = tmp_path / "song.sgp"
    export = tmp_path / "exports"
    export.mkdir()
    buildable(win, tmp_path)
    assert win._save_to(str(project))

    folders(str(export))
    win.build()
    assert folders.starts[0] == str(tmp_path)  # the project's folder by default
    assert win._stored_export_dir(str(project)) == str(export)

    win._open_path(str(project))  # a fresh session with the same project
    win.build()
    assert folders.starts[1] == str(export)
    assert not win.is_modified()  # the folder isn't part of the project


def test_save_as_keeps_the_export_folder(win, tmp_path, folders, builds):
    export = tmp_path / "exports"
    export.mkdir()
    buildable(win, tmp_path)
    folders(str(export))
    win.build()  # untitled
    assert win._save_to(str(tmp_path / "a.sgp"))
    assert win._save_to(str(tmp_path / "b.sgp"))
    assert win._stored_export_dir(str(tmp_path / "a.sgp")) == str(export)
    assert win._stored_export_dir(str(tmp_path / "b.sgp")) == str(export)


def test_a_remembered_folder_that_was_deleted_falls_back_to_the_project_folder(win, tmp_path, folders, builds):
    project = tmp_path / "song.sgp"
    buildable(win, tmp_path)
    assert win._save_to(str(project))
    win._store_export_dir(str(project), str(tmp_path / "gone"))
    folders("")
    win.build()
    assert folders.starts == [str(tmp_path)]


# --- Progress window ---


def run_dialog(qapp, dialog: ProgressDialog) -> None:
    dialog.thread.start()
    dialog.thread.wait()
    qapp.processEvents()  # deliver the thread's queued signals


def test_progress_window_shows_steps_log_and_done(qapp, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    w = MainWindow()
    buildable(w, tmp_path)
    plan = build.make_plan(w.view.scene().graph)
    dialog = ProgressDialog(w, plan, str(out), "Building Untitled")
    assert dialog.count.text() == strings.STEP_COUNT.format(done=0, total=2) and dialog.close_button.isHidden()

    run_dialog(qapp, dialog)
    assert dialog.succeeded and dialog.step.text() == strings.DONE
    assert dialog.count.text() == strings.STEP_COUNT.format(done=2, total=2)
    assert dialog.log.toPlainText().splitlines() == [
        "Loading song.wav", "Writing Vocals.wav", f"Done. Wrote 1 file to {out}."]
    assert not dialog.open_button.isHidden() and not dialog.close_button.isHidden()
    assert dialog.cancel_button.isHidden()
    assert os.listdir(out) == ["Vocals.wav"]
    w._saved = None
    w.is_modified = lambda: False
    w.close()


def test_progress_window_cancel(qapp, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    w = MainWindow()
    buildable(w, tmp_path)
    dialog = ProgressDialog(w, build.make_plan(w.view.scene().graph), str(out), "Building")
    dialog.reject()  # Esc before it starts running: cancels rather than closing
    assert dialog.thread.cancel_requested.is_set()
    run_dialog(qapp, dialog)
    assert not dialog.succeeded and dialog.step.text() == "Cancelled"
    assert dialog.open_button.isHidden() and os.listdir(out) == []
    w._saved = None
    w.is_modified = lambda: False
    w.close()
