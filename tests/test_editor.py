import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsProxyWidget, QLabel, QMenu, QWidgetAction

from editor import FIT_MARGIN, PLACEHOLDER_TEXT, ChoiceField, EditorView, add_menu_heading
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


# --- Right-click menu heading ---


def test_menu_heading_is_a_divided_off_title_that_cannot_be_chosen(qapp):
    menu = QMenu()
    add_menu_heading(menu, "Add Node")
    menu.addAction("Input")
    heading, divider, first = menu.actions()
    assert isinstance(heading, QWidgetAction) and not heading.isEnabled()
    label = heading.defaultWidget()
    assert isinstance(label, QLabel) and label.text() == "Add Node"
    assert label.font().pointSizeF() < menu.font().pointSizeF()
    assert divider.isSeparator()
    assert first.text() == "Input"


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
