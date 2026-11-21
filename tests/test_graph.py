import pytest

from graph import GRID, Graph


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
