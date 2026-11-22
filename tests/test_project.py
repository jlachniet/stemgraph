import json
import os

import pytest

from graph import Graph
from project import (
    FORMAT,
    VERSION,
    ProjectError,
    ViewState,
    dumps,
    load,
    loads,
    path_from_file,
    path_to_file,
    save,
    snapshot,
)


def sample(project_dir: str) -> Graph:
    graph = Graph()
    inp = graph.add_node("input", 0, 0)
    split = graph.add_node("split_mid_side", 240, 0)
    out = graph.add_node("output", 480, 0)
    graph.set_value(inp.id, "name", "Song")
    graph.set_value(inp.id, "file", f"{project_dir}/stems/song.wav")
    graph.set_value(out.id, "name", "Mid")
    graph.connect(inp.id, 0, split.id, 0)
    graph.connect(split.id, 0, out.id, 0)
    return graph


def project_text(**overrides) -> str:
    data = {"format": FORMAT, "version": VERSION, "nodes": [], "connections": []}
    data.update(overrides)
    return json.dumps(data)


def test_round_trip(tmp_path):
    path = str(tmp_path / "song.sgp")
    graph = sample(tmp_path.as_posix())
    save(graph, ViewState(1.5, 12.5, -48), path)
    loaded, view = load(path)
    assert snapshot(loaded) == snapshot(graph)
    assert view == ViewState(1.5, 12.5, -48)


def test_audio_paths_are_relative_in_file(tmp_path):
    path = str(tmp_path / "song.sgp")
    text = dumps(sample(tmp_path.as_posix()), ViewState(), path)
    values = json.loads(text)["nodes"][0]["values"]
    assert values["file"] == "stems/song.wav"


def test_save_as_elsewhere_recomputes_relative_paths(tmp_path):
    graph = sample(tmp_path.as_posix())
    text = dumps(graph, ViewState(), str(tmp_path / "sub" / "song.sgp"))
    assert json.loads(text)["nodes"][0]["values"]["file"] == "../stems/song.wav"


def test_path_helpers(tmp_path):
    project_dir = tmp_path.as_posix()
    assert path_to_file(f"{project_dir}/a/b.wav", project_dir) == "a/b.wav"
    assert path_from_file("a/b.wav", project_dir) == os.path.normpath(f"{project_dir}/a/b.wav").replace("\\", "/")
    absolute = f"{project_dir}/x.wav"
    assert path_from_file(absolute, "/somewhere/else") == os.path.normpath(absolute).replace("\\", "/")


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
def test_path_on_other_drive_stays_absolute():
    assert path_to_file("Z:/music/a.wav", "C:/projects") == "Z:/music/a.wav"


def test_ids_continue_after_highest_loaded_id():
    text = project_text(nodes=[{"id": 7, "type": "output", "x": 0, "y": 0}])
    graph, _ = loads(text, "p.sgp")
    assert graph.add_node("output", 0, 0).id == 8


def test_missing_view_uses_defaults():
    _, view = loads(project_text(), "p.sgp")
    assert view == ViewState()


def test_snapshot_ignores_edits_that_were_undone():
    graph = Graph()
    node = graph.add_node("output", 0, 0)
    before = snapshot(graph)
    graph.move_node(node.id, 240, 0)
    graph.set_value(node.id, "name", "x")
    assert snapshot(graph) != before
    graph.move_node(node.id, 0, 0)
    graph.set_value(node.id, "name", "")
    assert snapshot(graph) == before


def test_failed_save_keeps_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "song.sgp"
    path.write_text("original")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        save(Graph(), ViewState(), str(path))
    assert path.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["song.sgp"]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps([]),
        json.dumps({"format": "something-else", "version": 1}),
        project_text(version=VERSION + 1),
        project_text(nodes=[{"id": 1, "type": "reverb", "x": 0, "y": 0}]),
        project_text(nodes=[{"id": 1, "type": "output", "x": 0, "y": 0}] * 2),
        project_text(nodes=[{"id": 1, "type": "output", "x": "0", "y": 0}]),
        project_text(nodes=[{"id": True, "type": "output", "x": 0, "y": 0}]),
        project_text(nodes=[{"id": 1, "type": "output", "x": 0, "y": 0, "values": {"file": "a.wav"}}]),
        project_text(connections=[{"src": 1, "src_output": 0, "dst": 2, "dst_input": 0}]),  # no such nodes
        project_text(  # cycle
            nodes=[{"id": i, "type": "split_mid_side", "x": 0, "y": 0} for i in (1, 2)],
            connections=[
                {"src": 1, "src_output": 0, "dst": 2, "dst_input": 0},
                {"src": 2, "src_output": 0, "dst": 1, "dst_input": 0},
            ],
        ),
        project_text(  # two wires into one input
            nodes=[{"id": 1, "type": "input", "x": 0, "y": 0}, {"id": 2, "type": "input", "x": 0, "y": 0},
                   {"id": 3, "type": "output", "x": 0, "y": 0}],
            connections=[
                {"src": 1, "src_output": 0, "dst": 3, "dst_input": 0},
                {"src": 2, "src_output": 0, "dst": 3, "dst_input": 0},
            ],
        ),
        project_text(view={"zoom": 0, "center": [0, 0]}),
        project_text(view={"zoom": 1, "center": [0]}),
        project_text(view={"zoom": float("inf"), "center": [0, 0]}),
        project_text(view={"zoom": 1, "center": [float("nan"), 0]}),
    ],
)
def test_rejects_invalid_files(text):
    with pytest.raises(ProjectError):
        loads(text, "p.sgp")


def test_ignores_unknown_keys():
    loads(project_text(future_feature={"a": 1}), "p.sgp")


def test_algorithm_round_trips_and_auto_is_not_saved():
    graph = Graph()
    split = graph.add_node("split_mid_side", 0, 0)
    graph.set_value(split.id, "algorithm", "mid_side")
    loaded, _ = loads(dumps(graph, ViewState(), "."), ".")
    assert loaded.nodes[split.id].values["algorithm"] == "mid_side"

    untouched = Graph()
    untouched.add_node("split_mid_side", 0, 0)
    graph.set_value(split.id, "algorithm", "")  # back to Auto: saves the same as never choosing
    assert "algorithm" not in json.loads(dumps(graph, ViewState(), "."))["nodes"][0]["values"]
    assert snapshot(graph) == snapshot(untouched)


def test_invert_channels_round_trip_and_both_is_not_saved():
    graph = Graph()
    invert = graph.add_node("invert", 0, 0)
    assert json.loads(dumps(graph, ViewState(), "."))["nodes"][0]["values"] == {}
    graph.set_value(invert.id, "channels", "left")
    loaded, _ = loads(dumps(graph, ViewState(), "."), ".")
    assert loaded.nodes[invert.id].values["channels"] == "left"


def test_mix_with_signs_round_trips():
    graph = Graph()
    sources = [graph.add_node("input", 0, 96 * i) for i in range(3)]
    mix = graph.add_node("mix", 240, 0)
    # Wired bottom source first, so the file (sorted by source) doesn't list them in input order.
    for index, source in enumerate(reversed(sources)):
        graph.connect(source.id, 0, mix.id, index)
    graph.set_subtracts(mix.id, 1, True)
    loaded, _ = loads(dumps(graph, ViewState(), "."), ".")
    assert snapshot(loaded) == snapshot(graph)


def test_rejects_unknown_algorithm():
    node = {"id": 1, "type": "split_mid_side", "x": 0, "y": 0, "values": {"algorithm": "fancy"}}
    with pytest.raises(ProjectError):
        loads(project_text(nodes=[node]), ".")
