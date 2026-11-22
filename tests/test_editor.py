from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsProxyWidget

from editor import (
    FIT_MARGIN,
    INPUT_SPACING,
    KEEP_VISIBLE,
    PLACEHOLDER_TEXT,
    PORT,
    TARGET_PORT,
    CheckField,
    ChoiceField,
    EditorView,
    audio_files,
)
from graph import GRID, NODE_TYPES, Connection, Graph
from project import ViewState


@pytest.fixture
def view(qapp):
    v = EditorView(Graph())
    v.resize(800, 600)
    v.show()
    qapp.processEvents()
    yield v
    v.hide()
    v.deleteLater()


def add_node(view: EditorView, key: str = "output", x: float = 0, y: float = 0) -> None:
    view.scene().add_node(key, QPointF(x, y))


def on_screen(view: EditorView) -> QRect:
    """Where all the nodes are drawn, in viewport pixels."""
    return view.mapFromScene(view.scene().nodes_rect()).boundingRect()


# --- Zoom to Fit ---


def test_zoom_to_fit_without_nodes_goes_to_100_percent_at_origin(view):
    view.zoom_in()
    view.zoom_to_fit()
    assert view.view_state() == ViewState(1.0, 0, 0)


def test_zoom_to_fit_does_not_zoom_in_past_100_percent(view):
    add_node(view, x=480, y=240)
    view.zoom_out()
    view.zoom_to_fit()
    assert view.view_state().zoom == 1.0
    assert view.viewport().rect().contains(on_screen(view))


def test_zoom_to_fit_shows_all_nodes_with_a_margin(view):
    add_node(view, "input", 0, 0)
    add_node(view, "output", 2000, 1200)
    view.zoom_to_fit()
    assert view.view_state().zoom < 1.0
    inside = view.viewport().rect().adjusted(FIT_MARGIN, FIT_MARGIN, -FIT_MARGIN, -FIT_MARGIN)
    assert inside.contains(on_screen(view))


def test_zoom_to_fit_uses_the_largest_step_that_fits(view):
    add_node(view, "input", 0, 0)
    add_node(view, "output", 2000, 1200)
    view.zoom_to_fit()
    view.zoom_in()
    inside = view.viewport().rect().adjusted(FIT_MARGIN, FIT_MARGIN, -FIT_MARGIN, -FIT_MARGIN)
    assert not inside.contains(on_screen(view))


# --- Showing a loaded graph ---


def test_set_graph_shows_its_nodes_and_wires_at_the_saved_view(view):
    graph = Graph()
    a = graph.add_node("input", 0, 0)
    b = graph.add_node("output", 240, 0)
    graph.connect(a.id, 0, b.id, 0)
    view.set_graph(graph, ViewState(0.5, 120, 24))
    assert set(view.scene().node_items) == {a.id, b.id}
    assert len(view.scene().wire_items) == 1
    assert view.view_state() == ViewState(0.5, 120, 24)


# --- Right-click menu ---


def test_canvas_menu_keeps_node_types_in_a_submenu(view):
    menu = view.scene().canvas_menu(QPointF(0, 0))
    add_inputs, nodes, divider, paste = menu.actions()
    assert nodes.text() == "Add &Node" and add_inputs.text() == "Add &Inputs…"
    assert divider.isSeparator() and paste.text() == "&Paste"
    entries = [None if a.isSeparator() else a.data() for a in nodes.menu().actions()]
    assert entries == ["input", "output", None, "align", "invert", "mix", "split_mid_side", "subtract"]


# --- Node fields ---


def node_fields(view: EditorView) -> list:
    return [item.widget() for item in view.scene().items() if isinstance(item, QGraphicsProxyWidget)]


def test_node_fields_have_transparent_backgrounds(view):
    # Otherwise the square behind each box's rounded corners shows as dark specks on the node.
    add_node(view, "input")
    fields = node_fields(view)
    assert len(fields) == 2
    assert all(field.testAttribute(Qt.WA_TranslucentBackground) for field in fields)



def test_blank_output_names_show_their_default_greyed_out(view):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    graph.set_value(song.id, "name", "Song")
    out = graph.add_node("output", 480, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    field = scene.node_items[out.id].name_field
    assert field.text() == "" and field.placeholderText() == "Output"
    assert field.palette().color(QPalette.PlaceholderText) == PLACEHOLDER_TEXT

    scene.connect_ports(scene.node_items[song.id].outputs[0], scene.node_items[out.id].inputs[0])
    assert field.placeholderText() == "Song"  # follows the wiring
    scene.node_items[song.id].name_field.setText("Lead")
    assert field.placeholderText() == "Lead"  # and the source's name
    field.setText("Vocals")
    assert graph.nodes[out.id].values["name"] == "Vocals"


def test_blank_input_names_show_their_file_name_greyed_out(view, tmp_path):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    field = scene.node_items[song.id].name_field
    assert field.text() == "" and field.placeholderText() == "Input"
    scene.set_value(song.id, "file", str(tmp_path / "Want You Gone.mp3"))  # what choosing a file does
    assert field.placeholderText() == "Want You Gone"


def test_split_algorithm_is_a_dropdown_defaulting_to_auto(view):
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    edits = []
    scene.edited.connect(lambda: edits.append(True))
    (proxy,) = scene.node_items[split.id].fields
    field = proxy.widget()
    assert isinstance(field, ChoiceField)
    # The opened list says what Auto currently stands for; the closed box just says "Auto".
    assert [field.itemText(i) for i in range(field.count())] == ["Auto (Paulus–Torcoli)", "Paulus–Torcoli", "Mid/side"]
    assert field.currentIndex() == 0 and field.currentData(ChoiceField.SHORT_LABEL_ROLE) == "Auto" and not edits
    field.setCurrentIndex(2)
    assert graph.nodes[split.id].values["algorithm"] == "mid_side" and edits
    field.setCurrentIndex(0)
    assert graph.nodes[split.id].values["algorithm"] == ""


def test_invert_channels_is_a_dropdown_defaulting_to_both(view):
    graph = Graph()
    invert = graph.add_node("invert", 0, 0)
    view.set_graph(graph, ViewState())
    (proxy,) = view.scene().node_items[invert.id].fields
    field = proxy.widget()
    assert [field.itemText(i) for i in range(field.count())] == ["Both", "Left", "Right"]
    assert field.currentIndex() == 0
    field.setCurrentIndex(2)
    assert graph.nodes[invert.id].values["channels"] == "right"


def test_unchecking_align_first_hides_the_algorithm_and_moves_the_ports_up(view):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    subtract = graph.add_node("subtract", 240, 0)
    graph.connect(song.id, 0, subtract.id, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    item = scene.node_items[subtract.id]
    check, algorithm = item.fields
    assert isinstance(check.widget(), CheckField) and check.widget().isChecked()
    height, port_y = item.rect.height(), item.inputs[0].y()
    wire = scene.wire_items[Connection(song.id, 0, subtract.id, 0)]

    click(view, check.mapToScene(check.widget().rect().center()))  # on the label, not just the box
    assert graph.nodes[subtract.id].values["align"] == "off" and not check.widget().isChecked()
    assert item.fields == [check] and not algorithm.isVisible()
    assert item.rect.height() == height - GRID and item.inputs[0].y() == port_y - GRID
    assert wire.path().pointAtPercent(1) == wire.mapFromScene(item.inputs[0].scenePos())
    assert scene.fields_in_order()[-1] is check  # Tab skips the hidden field

    scene.undo()  # rebuilds the node as it was
    item = scene.node_items[subtract.id]
    assert len(item.fields) == 2 and item.rect.height() == height and item.fields[0].widget().isChecked()


@pytest.mark.parametrize("key", NODE_TYPES)
def test_every_node_has_a_body_fitting_its_rows(view, key):
    graph = Graph()
    node = graph.add_node(key, 0, 0)
    view.set_graph(graph, ViewState())
    item = view.scene().node_items[node.id]
    rows = 1 + len(node.type.fields) + max(graph.input_count(node.id), len(node.type.outputs))
    assert item.rect == QRectF(0, 0, item.rect.width(), rows * GRID) and item.rect.width() > 0


def test_mix_inputs_grow_and_shrink_with_its_wires(view):
    graph = Graph()
    a, b = graph.add_node("input", 0, 0), graph.add_node("input", 0, 96)
    mix = graph.add_node("mix", 240, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    item = scene.node_items[mix.id]
    assert [port.is_open for port in item.inputs] == [True] and not item.signs  # just the empty input
    height = item.rect.height()
    scene.connect_ports(scene.node_items[a.id].outputs[0], item.inputs[0])
    assert len(item.inputs) == 2 and len(item.signs) == 1
    scene.connect_ports(scene.node_items[b.id].outputs[0], item.inputs[1])
    assert len(item.inputs) == 3 and len(item.signs) == 2
    assert [port.is_open for port in item.inputs] == [False, False, True]  # only the new empty one
    assert item.rect.height() == height + 2 * GRID
    scene.wire_items[Connection(a.id, 0, mix.id, 0)].setSelected(True)
    scene.delete_selected()
    assert len(item.inputs) == 2 and len(item.signs) == 1
    assert scene.wire_items[Connection(b.id, 0, mix.id, 0)].dst is item.inputs[0]  # moved up to close the gap


def test_clicking_a_sign_chooses_it_as_one_undo_step(view):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    mix = graph.add_node("mix", 240, 0)
    graph.connect(song.id, 0, mix.id, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()

    def click(minus: bool) -> None:
        sign = scene.node_items[mix.id].signs[0]
        point = sign.mapToScene(sign._half(minus).center())
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, view.mapFromScene(point))

    click(minus=False)  # already added
    assert not graph.nodes[mix.id].subtracts(0) and not scene.can_undo()
    click(minus=True)
    assert graph.nodes[mix.id].subtracts(0)
    click(minus=True)  # choosing it again changes nothing
    assert graph.nodes[mix.id].subtracts(0)
    scene.undo()
    assert not graph.nodes[mix.id].subtracts(0)
    assert not scene.node_items[mix.id].signs[0].subtracts()


def test_open_dropdown_is_drawn_above_ports_and_other_nodes(view):
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    graph.add_node("output", 216, 0)  # right next to it, where the opened list overlaps
    view.set_graph(graph, ViewState())
    item = view.scene().node_items[split.id]
    proxy = item.fields[0]
    others = [i for i in view.scene().node_items.values() if i is not item]
    proxy.widget().showPopup()
    assert all(item.zValue() > other.zValue() for other in others)
    assert all(proxy.zValue() > port.zValue() for port in item.inputs + item.outputs)
    proxy.widget().hidePopup()
    assert item.zValue() == proxy.zValue() == 0


def test_saved_algorithm_shows_in_its_dropdown(view):
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    graph.set_value(split.id, "algorithm", "paulus_torcoli")
    view.set_graph(graph, ViewState())
    assert view.scene().node_items[split.id].fields[0].widget().currentText() == "Paulus–Torcoli"


def test_tab_moves_between_fields_in_reading_order(view):
    graph = Graph()
    below = graph.add_node("output", 480, 0)    # added first, but below and right of the others
    song = graph.add_node("input", 0, 0)
    above = graph.add_node("output", 480, -240)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    name, file = scene.node_items[song.id].fields
    order = [scene.node_items[above.id].fields[0], name, file, scene.node_items[below.id].fields[0]]
    assert scene.fields_in_order() == order

    QTest.keyClick(view, Qt.Key_Tab)  # from the canvas: the first field
    seen = [scene.focusItem()]
    for _ in range(4):
        QTest.keyClick(view, Qt.Key_Tab)
        seen.append(scene.focusItem())
    assert seen == order + order[:1]  # wraps around
    QTest.keyClick(view, Qt.Key_Backtab, Qt.ShiftModifier)
    assert scene.focusItem() is order[-1]


# --- Undo ---


def state(view: EditorView) -> tuple:
    return view.scene().graph.state()


def node_items(view: EditorView) -> list:
    return sorted(view.scene().node_items.values(), key=lambda item: item.node.id)


def drag(view: EditorView, start: QPointF, end: QPointF, modifiers=Qt.NoModifier) -> None:
    """Left-drag between two scene points, in a few steps."""
    a, b = view.mapFromScene(start), view.mapFromScene(end)
    QTest.mousePress(view.viewport(), Qt.LeftButton, modifiers, a)
    for i in range(1, 5):
        QTest.mouseMove(view.viewport(), a + (b - a) * i / 4)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifiers, b)


def click(view: EditorView, at: QPointF, modifiers=Qt.NoModifier) -> None:
    QTest.mouseClick(view.viewport(), Qt.LeftButton, modifiers, view.mapFromScene(at))


def title_point(item) -> QPointF:
    return item.scenePos() + QPointF(GRID, GRID / 2)


def test_each_edit_is_one_undo_step_and_redo_replays_it(view):
    scene = view.scene()
    empty = state(view)
    add_node(view, "input")
    one = state(view)
    add_node(view, "output", 480, 0)
    two = state(view)
    scene.undo()
    assert state(view) == one and scene.can_redo()
    scene.undo()
    assert state(view) == empty and not scene.can_undo()
    scene.redo()
    scene.redo()
    assert state(view) == two and not scene.can_redo()


def test_a_new_edit_clears_redo(view):
    scene = view.scene()
    add_node(view)
    scene.undo()
    add_node(view, "input")
    assert not scene.can_redo()


def test_dragging_several_nodes_is_one_undo_step(view):
    add_node(view, "output", 0, 0)
    add_node(view, "output", 0, 240)
    before = state(view)
    view.scene().select_all()
    first = node_items(view)[0]
    drag(view, title_point(first), title_point(first) + QPointF(4 * GRID, 2 * GRID))
    assert [(i.node.x, i.node.y) for i in node_items(view)] == [(96, 48), (96, 288)]
    view.scene().undo()
    assert state(view) == before


def test_typing_a_name_is_one_undo_step_ending_when_the_box_is_left(view, qapp):
    add_node(view)
    before = state(view)
    proxy = node_items(view)[0].fields[0]
    click(view, proxy.sceneBoundingRect().center())
    QTest.keyClicks(qapp.focusWidget(), "Vox")
    assert view.text_field().text() == "Vox"
    click(view, QPointF(-400, -400))  # empty canvas
    assert view.text_field() is None
    view.scene().undo()
    assert state(view) == before


def test_choosing_an_algorithm_is_one_undo_step(view):
    add_node(view, "split_mid_side")
    before = state(view)
    node_fields(view)[0].setCurrentIndex(2)
    view.scene().undo()
    assert state(view) == before


def test_undo_selects_what_it_changed_and_shows_it(view):
    add_node(view, "output", 0, 0)
    add_node(view, "output", 0, 240)
    scene = view.scene()
    scene.select_all()
    scene.delete_selected()
    view.centerOn(QPointF(5000, 5000))
    scene.undo()
    assert len(scene.selectedItems()) == 2
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert visible.intersects(scene.nodes_rect())


def test_undo_restores_wires(view):
    add_node(view, "input", 0, 0)
    add_node(view, "output", 480, 0)
    scene = view.scene()
    a, b = node_items(view)
    scene.connect_ports(a.outputs[0], b.inputs[0])
    scene.clearSelection()
    a.setSelected(True)
    scene.delete_selected()
    assert not scene.wire_items
    scene.undo()
    assert len(scene.wire_items) == 1


# --- Clipboard ---


def test_copy_and_paste_steps_further_each_time(view):
    add_node(view, "output", 0, 0)
    scene = view.scene()
    scene.select_all()
    scene.copy()
    scene.paste()
    scene.paste()
    assert sorted((n.x, n.y) for n in scene.graph.nodes.values()) == [(0, 0), (24, 24), (48, 48)]
    assert [item.node.id for item in scene.selectedItems()] == [3]
    scene.copy()  # a new copy starts again from its own position
    scene.paste()
    assert scene.graph.nodes[4].x == 72


def test_paste_at_a_point_and_cut(view):
    add_node(view, "input", 0, 0)
    add_node(view, "output", 480, 0)
    scene = view.scene()
    a, b = node_items(view)
    scene.connect_ports(a.outputs[0], b.inputs[0])
    scene.select_all()
    scene.cut()
    assert not scene.graph.nodes
    scene.paste(QPointF(250, 100))
    assert sorted((n.x, n.y) for n in scene.graph.nodes.values()) == [(240, 96), (720, 96)]
    assert len(scene.graph.connections) == 1
    assert len(scene.selectedItems()) == 3  # both nodes and their wire
    scene.undo()
    assert not scene.graph.nodes


def test_pasting_into_another_project(view):
    add_node(view, "output")
    view.scene().set_value(1, "name", "Vocals")
    view.scene().select_all()
    view.scene().copy()
    graph = Graph()
    graph.set_value(graph.add_node("output", 0, 0).id, "name", "Vocals")
    view.set_graph(graph, ViewState())
    assert view.scene().can_paste()
    view.scene().paste()
    assert graph.nodes[2].values["name"] == "Vocals 2"


def test_duplicate_leaves_the_clipboard_alone(view, qapp):
    qapp.clipboard().setText("hello")
    add_node(view, "output", 0, 0)
    scene = view.scene()
    scene.select_all()
    scene.duplicate()
    assert sorted((n.x, n.y) for n in scene.graph.nodes.values()) == [(0, 0), (24, 24)]
    assert qapp.clipboard().text() == "hello" and not scene.can_paste()


# --- Selecting ---


def selected_ids(view: EditorView) -> set:
    return {item.node.id for item in view.scene().selectedItems() if hasattr(item, "node")}


def three_nodes(view: EditorView) -> list:
    for x in (0, 480, 960):
        add_node(view, "output", x, 0)
    view.scene().clearSelection()
    view.zoom_to_fit()
    return node_items(view)


def test_click_shift_click_and_ctrl_click(view):
    a, b, c = three_nodes(view)
    click(view, title_point(a))
    assert selected_ids(view) == {1}
    click(view, title_point(b), Qt.ShiftModifier)
    click(view, title_point(b), Qt.ShiftModifier)  # Shift only adds
    assert selected_ids(view) == {1, 2}
    click(view, title_point(c), Qt.ControlModifier)
    click(view, title_point(a), Qt.ControlModifier)
    assert selected_ids(view) == {2, 3}
    click(view, title_point(b))
    assert selected_ids(view) == {2}


def test_selection_box_selects_what_it_touches(view):
    three_nodes(view)
    drag(view, QPointF(-12, -12), QPointF(500, 12))  # touches the first two
    assert selected_ids(view) == {1, 2}
    assert view._band_start is None


def test_selection_box_with_shift_adds_and_with_ctrl_toggles(view):
    a, b, c = three_nodes(view)
    a.setSelected(True)
    drag(view, QPointF(960 - 12, -12), QPointF(960 + 12, 12), Qt.ShiftModifier)
    assert selected_ids(view) == {1, 3}
    drag(view, QPointF(-12, -12), QPointF(500, 12), Qt.ControlModifier)
    assert selected_ids(view) == {2, 3}


def test_click_on_empty_canvas_and_escape_clear_the_selection(view):
    three_nodes(view)
    view.scene().select_all()
    click(view, QPointF(400, 200))
    assert not selected_ids(view)
    view.scene().select_all()
    QTest.keyClick(view, Qt.Key_Escape)
    assert not selected_ids(view)


def test_selection_box_scrolls_at_the_window_edge(view):
    add_node(view, "output", 0, 0)
    add_node(view, "output", 3000, 0)
    viewport = view.viewport()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(viewport.width() // 2, 10))
    QTest.mouseMove(viewport, QPoint(viewport.width() - 2, 10))
    before = view.horizontalScrollBar().value()
    view._band_scroll()
    assert view.horizontalScrollBar().value() > before
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(viewport.width() - 2, 10))


# --- Adding Inputs from files ---


def touch(folder, *names) -> list[str]:
    for name in names:
        (folder / name).write_bytes(b"")
    return [str(folder / name) for name in names]


def test_audio_files_expand_folders_one_level_in_natural_order(tmp_path):
    stems = tmp_path / "stems"
    (stems / "old takes").mkdir(parents=True)
    touch(stems, "10 Vox.wav", "2 Bass.FLAC", "notes.txt", "1 Kick.mp3")
    touch(stems / "old takes", "Vox take 1.wav")
    (loose,) = touch(tmp_path, "Song.wav")
    found = audio_files([str(stems), loose, loose, str(tmp_path / "missing.wav")])
    assert [Path(path).name for path in found] == ["1 Kick.mp3", "2 Bass.FLAC", "10 Vox.wav", "Song.wav"]


def test_add_inputs_makes_a_selected_column_in_one_undo_step(view, tmp_path):
    paths = touch(tmp_path, "a.wav", "b.wav", "c.wav")
    add_node(view, "output", 480, 0)
    scene = view.scene()
    scene.add_inputs(paths, QPointF(5, 10))
    inputs = sorted((n for n in scene.graph.nodes.values() if n.type_key == "input"), key=lambda n: n.y)
    assert [n.values for n in inputs] == [{"file": path} for path in paths]  # names left blank
    assert {(n.x, n.y) for n in inputs} == {(0, 0), (0, INPUT_SPACING), (0, 2 * INPUT_SPACING)}
    assert {item.node.id for item in scene.selectedItems()} == {n.id for n in inputs}
    bottom = scene.node_items[inputs[0].id].sceneBoundingRect().bottom()
    assert bottom < scene.node_items[inputs[1].id].sceneBoundingRect().top()  # they don't overlap
    scene.undo()
    assert [n.type_key for n in scene.graph.nodes.values()] == ["output"]


def drop(view: EditorView, paths: list[str], at: QPointF) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    point = QPointF(view.mapFromScene(at))
    view.dropEvent(QDropEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))


def test_a_drop_reports_its_files_place_and_the_input_a_single_file_landed_on(view, tmp_path):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    view.set_graph(graph, ViewState())
    dropped = []
    view.files_dropped.connect(lambda *args: dropped.append(args))
    one = touch(tmp_path, "b.wav")
    two = touch(tmp_path, "c.wav", "a.wav")
    on_song = QPointF(30, 30)
    drop(view, one, on_song)
    drop(view, two, on_song)  # several files: added, not put in the Input
    drop(view, [str(tmp_path)], on_song)  # a folder, even with one file in it
    drop(view, one, QPointF(480, 240))
    assert [([Path(p) for p in paths], target) for paths, _, target in dropped] == [
        ([Path(one[0])], song.id), ([Path(p) for p in sorted(two)], None), ([tmp_path], None), ([Path(one[0])], None)]
    assert abs(dropped[-1][1].x() - 480) <= 1 and abs(dropped[-1][1].y() - 240) <= 1


def test_set_input_file_shows_the_new_file(view, tmp_path):
    graph = Graph()
    song = graph.add_node("input", 0, 0)
    view.set_graph(graph, ViewState())
    (path,) = touch(tmp_path, "Song.wav")
    view.scene().set_input_file(song.id, path)
    assert graph.nodes[song.id].values["file"] == path
    assert view.scene().node_items[song.id].file_button.text() == "Song.wav"


# --- Dragging several outputs at once ---


def drag_wire(view: EditorView, start, end) -> None:
    """Drag a wire from one port to another with the mouse."""
    drag(view, start.scenePos(), end.scenePos())


def stems_and_mix(view: EditorView, count: int, wired: tuple = ()):
    """Stems in a column, a Mix and an Output; the stems numbered in `wired` already feed the Mix."""
    graph = Graph()
    stems = [graph.add_node("input", 0, i * INPUT_SPACING) for i in range(count)]
    mix = graph.add_node("mix", 288, 0)
    out = graph.add_node("output", 288, 240)
    for index, stem in enumerate(wired):
        graph.connect(stems[stem].id, 0, mix.id, index)
    view.set_graph(graph, ViewState(0.5, 200, 200))
    return graph, view.scene(), stems, mix, out


def test_dragging_one_of_several_selected_outputs_wires_them_all_into_a_mix(view):
    graph, scene, stems, mix, _ = stems_and_mix(view, 3, wired=(2,))  # already in: skipped
    for stem in stems:
        scene.node_items[stem.id].setSelected(True)
    scene.node_items[mix.id].setSelected(True)  # selected, but can't feed itself
    mix_item = scene.node_items[mix.id]
    drag_wire(view, scene.node_items[stems[1].id].outputs[0], mix_item.inputs[-1])
    assert [c.src for c in graph.sources(mix.id)] == [stems[2].id, stems[0].id, stems[1].id]  # top to bottom
    assert len(mix_item.inputs) == 4
    scene.undo()
    assert [c.src for c in graph.sources(mix.id)] == [stems[2].id]  # one undo step


def test_several_outputs_dropped_on_an_ordinary_input_connect_nothing(view):
    graph, scene, stems, _, out = stems_and_mix(view, 2)
    for stem in stems:
        scene.node_items[stem.id].setSelected(True)
    drag_wire(view, scene.node_items[stems[0].id].outputs[0], scene.node_items[out.id].inputs[0])
    assert not graph.connections


def test_an_unselected_output_drags_just_itself(view):
    graph, scene, stems, mix, _ = stems_and_mix(view, 2)
    scene.node_items[stems[0].id].setSelected(True)
    drag_wire(view, scene.node_items[stems[1].id].outputs[0], scene.node_items[mix.id].inputs[0])
    assert [c.src for c in graph.sources(mix.id)] == [stems[1].id]


# --- Empty canvas ---


def test_empty_canvas_shows_a_hint_that_panning_keeps_in_reach(view):
    scene = view.scene()
    hint = scene.hint_rect()
    assert scene.content_rect() == hint and hint.center() == QPointF(0, 0) and hint.width() > 0
    view.centerOn(QPointF(50000, 50000))
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert visible.intersected(hint).width() * view.transform().m11() >= KEEP_VISIBLE - 1
    add_node(view, "output", 2400, 2400)
    assert scene.content_rect() == scene.nodes_rect()  # nodes take over from the hint


def test_dragging_a_wire_shows_where_it_can_go(view):
    graph, scene, stems, mix, out = stems_and_mix(view, 2)
    graph.connect(mix.id, 0, out.id, 0)
    split = graph.add_node("split_mid_side", 600, 0)
    graph.connect(mix.id, 0, split.id, 0)
    view.set_graph(graph, ViewState())
    scene = view.scene()
    items = scene.node_items

    def lit(node) -> list[bool]:
        return [port.is_target for port in items[node.id].inputs + items[node.id].outputs]

    scene.show_targets([items[stems[0].id].outputs[0]])  # one stem's output
    assert lit(mix) == [True, False] and lit(out) == [True] and lit(split) == [True, False, False]
    assert items[stems[1].id].opacity() < 1 and items[stems[0].id].opacity() == 1  # nothing to plug into
    scene.show_targets([items[mix.id].inputs[-1]])  # backwards, from the Mix's empty input
    assert lit(stems[0]) == [True] and lit(stems[1]) == [True]
    assert lit(split) == [False, False, False] and items[split.id].opacity() < 1  # it's fed by the Mix: a loop
    scene.show_targets([items[s.id].outputs[0] for s in stems])  # several outputs: only a Mix
    assert lit(mix) == [True, False] and items[out.id].opacity() < 1 and items[split.id].opacity() < 1
    scene.show_targets([])
    assert all(item.opacity() == 1 and not any(p.is_target for p in item.inputs + item.outputs)
               for item in items.values())


def test_ports_grow_and_shrink_smoothly(view):
    graph, scene, stems, mix, _ = stems_and_mix(view, 1)
    port = scene.node_items[mix.id].inputs[0]
    scene.show_targets([scene.node_items[stems[0].id].outputs[0]])
    assert port.scale() < 1.25 and port.pen().color() != TARGET_PORT  # on its way
    QTest.qWait(250)
    assert port.scale() == 1.25 and port.pen().color() == TARGET_PORT  # the empty input's ring
    scene.show_targets([])
    QTest.qWait(250)
    assert port.scale() == 1 and port.pen().color() == PORT
