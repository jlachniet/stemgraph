import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import strings
import welcome
from test_window import errors, file_dialogs, prompts, saved_project, win  # noqa: F401 (fixtures)
from welcome import AboutPanel, StartPanel


@pytest.fixture
def start(win):  # noqa: F811
    win.activateWindow()
    win.show_start()
    QApplication.processEvents()
    return win.panel


def focused():
    return QApplication.focusWidget()


def press(key, modifier=Qt.NoModifier) -> None:
    QTest.keyClick(focused(), key, modifier)


def test_start_panel_lists_recent_projects(win, tmp_path):  # noqa: F811
    paths = [saved_project(tmp_path, "a.sgp"), saved_project(tmp_path, "b.sgp")]
    for path in paths:
        win._add_recent(path)
    win.show_start()
    panel = win.panel
    assert isinstance(panel, StartPanel)
    names = [panel.recent.item(i).text() for i in range(panel.recent.count())]
    assert names == ["b", "a"]
    assert not panel.no_recent.isVisibleTo(panel)


def test_start_panel_without_recent_projects(start):
    assert start.no_recent.isVisibleTo(start)
    assert not start.recent.isVisibleTo(start)


def test_start_panel_is_centered_and_follows_resizes(start, win):  # noqa: F811
    def offset() -> QPoint:
        return start.geometry().center() - win.centralWidget().geometry().center()

    assert offset().manhattanLength() <= 2
    win.resize(1000, 700)
    QApplication.processEvents()
    assert offset().manhattanLength() <= 2


def test_escape_closes_and_leaves_untitled_project(start, win):  # noqa: F811
    assert focused() is start
    press(Qt.Key_Escape)
    assert win.panel is None
    assert win.path is None


def test_click_outside_closes_but_click_inside_does_not(start, win):  # noqa: F811
    QTest.mouseClick(start, Qt.LeftButton, pos=QPoint(5, 5))
    assert win.panel is start
    QTest.mouseClick(win.view.viewport(), Qt.LeftButton, pos=QPoint(5, 5))
    assert win.panel is None


def test_new_button_closes(start, win):  # noqa: F811
    start.new_button.click()
    assert win.panel is None


def test_cancelled_open_keeps_panel(start, win, file_dialogs):  # noqa: F811
    file_dialogs(open="")
    start.open_button.click()
    assert win.panel is start


def test_open_button_opens_project(start, win, file_dialogs, tmp_path):  # noqa: F811
    path = saved_project(tmp_path)
    file_dialogs(open=path)
    start.open_button.click()
    assert win.path == path
    assert win.panel is None


def test_clicking_recent_project_opens_it(win, tmp_path):  # noqa: F811
    path = saved_project(tmp_path)
    win._add_recent(path)
    win.show_start()
    panel = win.panel
    rect = panel.recent.visualItemRect(panel.recent.item(0))
    QTest.mouseClick(panel.recent.viewport(), Qt.LeftButton, pos=rect.center())
    assert Path(win.path) == Path(path)
    assert win.panel is None


def test_missing_recent_project_is_removed_and_panel_stays(win, errors, tmp_path):  # noqa: F811
    path = saved_project(tmp_path)
    win._add_recent(path)
    win._add_recent(str(tmp_path / "gone.sgp"))
    win.show_start()
    panel = win.panel
    panel.recent.opened.emit(panel.recent.item(0).data(welcome.RecentDelegate.PATH_ROLE))
    assert len(errors) == 1
    assert win.panel is panel
    assert [panel.recent.item(i).text() for i in range(panel.recent.count())] == ["song"]


def test_arrow_keys_and_enter_open_recent_project(win, tmp_path):  # noqa: F811
    paths = [saved_project(tmp_path, "a.sgp"), saved_project(tmp_path, "b.sgp")]
    for path in paths:
        win._add_recent(path)
    win.activateWindow()
    win.show_start()
    panel = win.panel
    press(Qt.Key_Return)  # nothing chosen yet
    assert win.panel is panel
    press(Qt.Key_Down)
    assert focused() is panel.recent and panel.recent.currentRow() == 0
    press(Qt.Key_Down)
    assert panel.recent.currentRow() == 1
    press(Qt.Key_Return)
    assert Path(win.path) == Path(paths[0])
    assert win.panel is None


def test_tab_cycles_within_start_panel(win, tmp_path):  # noqa: F811
    win._add_recent(saved_project(tmp_path))
    win.activateWindow()
    win.show_start()
    panel = win.panel
    order = []
    for _ in range(5):
        press(Qt.Key_Tab)
        order.append(focused())
    assert order == [panel.new_button, panel.open_button, panel.recent, panel.credits, panel.new_button]
    press(Qt.Key_Backtab)
    assert focused() is panel.credits


def test_tab_skips_empty_recent_list(start):
    order = []
    for _ in range(3):
        press(Qt.Key_Tab)
        order.append(focused())
    assert order == [start.new_button, start.open_button, start.credits]


def test_enter_on_focused_button_clicks_it(start, win):  # noqa: F811
    press(Qt.Key_Tab)
    press(Qt.Key_Return)
    assert win.panel is None


def test_ctrl_n_closes_start_panel(start, win):  # noqa: F811
    press(Qt.Key_N, Qt.ControlModifier)
    assert win.panel is None


def test_about_panel(win):  # noqa: F811
    win.activateWindow()
    win.show_about()
    panel = win.panel
    assert isinstance(panel, AboutPanel)
    assert focused() is panel.ok
    press(Qt.Key_Tab)
    assert focused() is panel.links[0]
    press(Qt.Key_Backtab)
    press(Qt.Key_Return)
    assert win.panel is None


def test_about_replaces_start_panel(start, win):  # noqa: F811
    win.show_about()
    assert isinstance(win.panel, AboutPanel)
    assert not start.isVisible()


def test_credits_link_to_license():
    assert welcome.LICENSE_URL in welcome.credits_html()
    assert strings.LICENSE_NAME in welcome.credits_html()


def test_every_third_party_field_has_a_url():
    for text in strings.THIRD_PARTY:
        welcome.third_party_html(text)  # raises KeyError for a field without a URL


def test_enter_on_credits_link_opens_license(start, monkeypatch):
    opened = []
    monkeypatch.setattr(welcome.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    press(Qt.Key_Backtab)
    assert focused() is start.credits
    press(Qt.Key_Return)
    assert opened == [welcome.LICENSE_URL]


def test_tab_visits_each_link_in_about(win, monkeypatch):  # noqa: F811
    opened = []
    monkeypatch.setattr(welcome.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    win.activateWindow()
    win.show_about()
    for _ in range(1 + len(welcome.THIRD_PARTY_URLS)):
        press(Qt.Key_Tab)
        press(Qt.Key_Return)
    assert opened == [welcome.LICENSE_URL, *welcome.THIRD_PARTY_URLS.values()]
    press(Qt.Key_Tab)
    assert focused() is win.panel.ok


def test_software_credits_are_alphabetical():
    names = [re.sub(r"\{\w+\}", "", text).casefold() for text in strings.THIRD_PARTY_SOFTWARE]
    assert names == sorted(names)
