"""Reading and writing .sgp project files. No Qt.

A project file is UTF-8 JSON:

    {
      "format": "stemgraph-project",
      "version": 1,
      "nodes": [{"id": 1, "type": "input", "x": 0, "y": 0, "values": {"name": "Song", "file": "stems/a.wav"}}],
      "connections": [{"src": 1, "src_output": 0, "dst": 2, "dst_input": 0}],
      "view": {"zoom": 1.0, "center": [0, 0]}
    }

File paths in node values are stored relative to the project file where possible, so a project folder can be
moved together with its audio. In memory they are always absolute.
"""

import json
import math
import os
import tempfile
from dataclasses import dataclass

import strings
from graph import NODE_TYPES, Graph

EXTENSION = ".sgp"
FORMAT = "stemgraph-project"
VERSION = 1
PATH_FIELDS = ("file",)  # node fields that hold a file path


class ProjectError(Exception):
    """A project file that can't be loaded. The message is shown to the user."""


@dataclass
class ViewState:
    zoom: float = 1.0
    center_x: float = 0.0
    center_y: float = 0.0


def snapshot(graph: Graph) -> tuple:
    """Everything about a graph that saving would record. Two graphs with equal snapshots save the same."""
    return graph.state()


# --- Paths ---

def _slashes(path: str) -> str:
    return path.replace("\\", "/")


def path_to_file(path: str, project_dir: str) -> str:
    """An absolute path as stored in a project file in `project_dir`: relative if possible."""
    try:
        return _slashes(os.path.relpath(path, project_dir))
    except ValueError:  # on another drive
        return _slashes(path)


def path_from_file(path: str, project_dir: str) -> str:
    """A path read from a project file in `project_dir`, made absolute."""
    return _slashes(os.path.normpath(os.path.join(project_dir, path)))


# --- Writing ---

def dumps(graph: Graph, view: ViewState, project_path: str) -> str:
    project_dir = os.path.dirname(os.path.abspath(project_path))
    nodes = []
    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        values = {}
        for name in node.type.value_names:  # in the type's field order, for stable files
            value = node.values.get(name)
            if value:
                values[name] = path_to_file(value, project_dir) if name in PATH_FIELDS else value
        nodes.append({"id": node.id, "type": node.type_key, "x": node.x, "y": node.y, "values": values})
    connections = [
        {"src": c.src, "src_output": c.src_output, "dst": c.dst, "dst_input": c.dst_input}
        for c in sorted(graph.connections, key=lambda c: (c.src, c.src_output, c.dst, c.dst_input))
    ]
    data = {
        "format": FORMAT,
        "version": VERSION,
        "nodes": nodes,
        "connections": connections,
        "view": {"zoom": view.zoom, "center": [round(view.center_x, 2), round(view.center_y, 2)]},
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def save(graph: Graph, view: ViewState, path: str) -> None:
    """Write a project file. Writes a temporary file first, so a failed save never damages an existing file.

    Raises OSError if the file can't be written.
    """
    text = dumps(graph, view, path)
    directory = os.path.dirname(os.path.abspath(path))
    fd, temp = tempfile.mkstemp(prefix=".", suffix=EXTENSION + ".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise


# --- Reading ---

def _int(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectError(strings.INVALID_VALUE)
    return value


def _number(value) -> float:
    # json accepts NaN and Infinity, which no position or zoom can be.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProjectError(strings.INVALID_VALUE)
    return float(value)


def _dict(value) -> dict:
    if not isinstance(value, dict):
        raise ProjectError(strings.INVALID_VALUE)
    return value


def _list(value) -> list:
    if not isinstance(value, list):
        raise ProjectError(strings.INVALID_VALUE)
    return value


def loads(text: str, project_path: str) -> tuple[Graph, ViewState]:
    """Parse a project file. Raises ProjectError if it isn't a valid project this version can read."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ProjectError(strings.NOT_A_PROJECT_OR_DAMAGED) from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ProjectError(strings.NOT_A_PROJECT)
    if _int(data.get("version")) > VERSION:
        raise ProjectError(strings.NEWER_VERSION)

    project_dir = os.path.dirname(os.path.abspath(project_path))
    graph = Graph()
    for entry in _list(data.get("nodes", [])):
        entry = _dict(entry)
        type_key = entry.get("type")
        if type_key not in NODE_TYPES:
            raise ProjectError(strings.UNKNOWN_NODE.format(type=type_key))
        node_id = _int(entry.get("id"))
        if node_id < 1 or node_id in graph.nodes:
            raise ProjectError(strings.INVALID_NODE)
        node = graph.add_node(type_key, _int(entry.get("x")), _int(entry.get("y")), node_id=node_id)
        for name, value in _dict(entry.get("values", {})).items():
            if name not in node.type.value_names or not isinstance(value, str):
                raise ProjectError(strings.INVALID_NODE)
            try:
                graph.set_value(node.id, name, path_from_file(value, project_dir) if name in PATH_FIELDS else value)
            except ValueError:  # not one of a dropdown's choices, or not signs
                raise ProjectError(strings.INVALID_NODE) from None

    connections = []
    for entry in _list(data.get("connections", [])):
        entry = _dict(entry)
        connections.append([_int(entry.get(key)) for key in ("src", "src_output", "dst", "dst_input")])
    # By destination input: a growing node's input only exists once the inputs above it are connected.
    for ends in sorted(connections, key=lambda ends: (ends[2], ends[3], ends[0], ends[1])):
        before = len(graph.connections)
        # Graph.connect enforces the same rules as the editor; it also silently replaces a wire on the same
        # input, which a valid file never needs.
        if graph.connect(*ends) is None or len(graph.connections) != before + 1:
            raise ProjectError(strings.INVALID_CONNECTION)

    view = ViewState()
    if "view" in data:
        view_data = _dict(data["view"])
        view.zoom = _number(view_data.get("zoom", 1.0))
        center = _list(view_data.get("center", [0, 0]))
        if len(center) != 2 or view.zoom <= 0:
            raise ProjectError(strings.INVALID_VALUE)
        view.center_x, view.center_y = (_number(v) for v in center)
    return graph, view


def load(path: str) -> tuple[Graph, ViewState]:
    """Read a project file. Raises ProjectError for invalid files and OSError if it can't be read."""
    with open(path, "rb") as file:
        raw = file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProjectError(strings.NOT_A_PROJECT_OR_DAMAGED) from None
    return loads(text, path)
