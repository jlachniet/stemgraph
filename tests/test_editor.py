import pytest
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsProxyWidget, QLabel, QMenu, QWidgetAction

from editor import FIT_MARGIN, PLACEHOLDER_TEXT, EditorView, add_menu_heading
from graph import Graph
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
