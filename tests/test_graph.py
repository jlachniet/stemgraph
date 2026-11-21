import pytest

from graph import GRID, Connection, Graph, load_fragment


def make(*type_keys):
    graph = Graph()
    return graph, [graph.add_node(key, 0, 0).id for key in type_keys]


def test_positions_snap_to_grid():
    graph = Graph()
    node = graph.add_node("output", GRID * 2 + 7, GRID * 3 - 4)
    assert (node.x, node.y) == (GRID * 2, GRID * 3)
    graph.move_node(node.id, 13, -29)
    assert (node.x, node.y) == (GRID, -GRID)


def test_connect_output_to_input():
    graph, (file, out) = make("input", "output")
    connection = graph.connect(file, 0, out, 0)
    assert connection is not None
    assert graph.connections == {connection}


def test_output_can_fan_out():
    graph, (file, out1, out2) = make("input", "output", "output")
    graph.connect(file, 0, out1, 0)
    graph.connect(file, 0, out2, 0)
    assert len(graph.connections) == 2


def test_new_wire_replaces_wire_on_occupied_input():
    graph, (file1, file2, out) = make("input", "input", "output")
    graph.connect(file1, 0, out, 0)
    replacement = graph.connect(file2, 0, out, 0)
    assert graph.connections == {replacement}


def test_rejects_invalid_ports_and_same_node():
    graph, (file, split, out) = make("input", "split_mid_side", "output")
    assert graph.connect(file, 1, split, 0) is None  # no such output
    assert graph.connect(file, 0, split, 1) is None  # no such input
    assert graph.connect(out, 0, file, 0) is None    # output node has no outputs
    assert graph.connect(split, 0, split, 0) is None
    assert graph.connect(file, 0, 999, 0) is None
    assert graph.connections == set()


def test_rejects_cycles():
    graph, (a, b, c) = make("split_mid_side", "split_mid_side", "split_mid_side")
    graph.connect(a, 0, b, 0)
    graph.connect(b, 1, c, 0)
    assert graph.connect(c, 0, a, 0) is None
    assert len(graph.connections) == 2


def test_rejected_connection_keeps_existing_wire():
    graph, (a, b) = make("split_mid_side", "split_mid_side")
    original = graph.connect(a, 0, b, 0)
    graph.connect(b, 0, a, 0)  # would be a cycle
    assert graph.connections == {original}


def test_removing_node_removes_its_wires():
    graph, (file, split, out) = make("input", "split_mid_side", "output")
    graph.connect(file, 0, split, 0)
    keep = graph.connect(split, 0, out, 0)
    graph.remove_node(file)
    assert file not in graph.nodes
    assert graph.connections == {keep}


def test_set_value():
    graph, (inp, out) = make("input", "output")
    graph.set_value(inp, "name", "Song A")
    graph.set_value(inp, "file", "C:/music/song.wav")
    graph.set_value(out, "name", "Monitor")
    assert graph.nodes[inp].values == {"name": "Song A", "file": "C:/music/song.wav"}
    assert graph.nodes[out].values == {"name": "Monitor"}


def test_set_value_rejects_unknown_field():
    graph, (out,) = make("output")
    with pytest.raises(ValueError):
        graph.set_value(out, "file", "song.wav")


def test_disconnect():
    graph, (file, out) = make("input", "output")
    connection = graph.connect(file, 0, out, 0)
    graph.disconnect(connection)
    assert graph.connections == set()


def test_add_node_with_saved_id():
    graph = Graph()
    graph.add_node("output", 0, 0, node_id=5)
    assert graph.add_node("output", 0, 0).id == 6
    with pytest.raises(ValueError):
        graph.add_node("output", 0, 0, node_id=5)


def test_algorithm_is_a_choice():
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    graph.set_value(split.id, "algorithm", "mid_side")
    assert split.values["algorithm"] == "mid_side"
    graph.set_value(split.id, "algorithm", "")  # Auto
    with pytest.raises(ValueError):
        graph.set_value(split.id, "algorithm", "fancy")


def test_auto_resolves_to_its_current_choice():
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    assert split.choice("algorithm") == "paulus_torcoli"
    graph.set_value(split.id, "algorithm", "mid_side")
    assert split.choice("algorithm") == "mid_side"


# --- Undo state ---


def test_set_state_restores_nodes_values_and_connections():
    graph, (file, out) = make("input", "output")
    graph.set_value(file, "name", "Song")
    graph.connect(file, 0, out, 0)
    state = graph.state()
    graph.remove_node(file)
    graph.move_node(out, 240, 0)
    graph.set_state(state)
    assert graph.state() == state
    assert graph.nodes[file].values == {"name": "Song"}
    assert graph.add_node("output", 0, 0).id == 3  # ids already handed out aren't reused


# --- Copy and paste ---


def pasted(graph: Graph, source: Graph, ids, x=0, y=0) -> list:
    piece = load_fragment(source.fragment(ids))
    return [graph.nodes[i] for i in graph.paste(piece, x, y)]


def test_fragment_keeps_only_wires_between_copied_nodes():
    graph, (file, split, out) = make("input", "split_mid_side", "output")
    graph.connect(file, 0, split, 0)
    graph.connect(split, 0, out, 0)
    piece = load_fragment(graph.fragment([split, out]))
    assert len(piece.nodes) == 2
    assert piece.connections == {Connection(split, 0, out, 0)}


def test_paste_places_top_left_corner_and_keeps_layout_and_wires():
    source = Graph()
    a = source.add_node("input", 48, 96)
    b = source.add_node("output", 288, 144)
    source.connect(a.id, 0, b.id, 0)
    graph = Graph()
    new_a, new_b = pasted(graph, source, [a.id, b.id], 480, 0)
    assert (new_a.x, new_a.y, new_b.x, new_b.y) == (480, 0, 720, 48)
    assert graph.connections == {Connection(new_a.id, 0, new_b.id, 0)}


def test_paste_numbers_typed_names_only_when_taken():
    graph = Graph()
    for name in ("Vocals", "Vocals 2"):
        graph.set_value(graph.add_node("output", 0, 0).id, "name", name)
    source = Graph()
    for name in ("vocals", "Drums", "Vocals 2", ""):
        node = source.add_node("output", 0, 0)
        if name:
            source.set_value(node.id, "name", name)
    named = source.add_node("input", 0, 0)
    source.set_value(named.id, "name", "Vocals")  # another type of node: no clash
    names = [n.values.get("name", "") for n in pasted(graph, source, source.nodes)]
    assert names == ["vocals 3", "Drums", "Vocals 4", "", "Vocals"]


def test_paste_keeps_values():
    source, (file, split) = make("input", "split_mid_side")
    source.set_value(file, "file", "C:/a.wav")
    source.set_value(split, "algorithm", "mid_side")
    new_file, new_split = pasted(Graph(), source, [file, split])
    assert new_file.values == {"file": "C:/a.wav"}
    assert new_split.values == {"algorithm": "mid_side"}


@pytest.mark.parametrize("data", [
    None,
    [],
    {"format": "other", "nodes": [], "connections": []},
    {"format": "stemgraph-nodes", "nodes": [], "connections": []},  # nothing to paste
    {"format": "stemgraph-nodes", "nodes": [{"id": 1, "type": "nope", "x": 0, "y": 0, "values": {}}],
     "connections": []},
    {"format": "stemgraph-nodes", "nodes": [{"id": 1, "type": "output", "x": "0", "y": 0, "values": {}}],
     "connections": []},
    {"format": "stemgraph-nodes", "nodes": [{"id": 1, "type": "output", "x": 0, "y": 0, "values": {"file": "a"}}],
     "connections": []},
    {"format": "stemgraph-nodes", "nodes": [{"id": 1, "type": "output", "x": 0, "y": 0, "values": {}}],
     "connections": [[1, 0, 1, 0]]},
    {"format": "stemgraph-nodes", "nodes": [{"id": 1, "type": "output", "x": 0, "y": 0}], "connections": []},
])
def test_load_fragment_rejects_invalid_data(data):
    assert load_fragment(data) is None
