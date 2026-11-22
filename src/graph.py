"""Node graph model: node types, nodes, connections and the rules between them. No Qt."""

import re
from dataclasses import dataclass, field

import strings

GRID = 24


@dataclass(frozen=True)
class NodeType:
    title: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    # Editable values shown in the node: "name" (text), "file" (path), or a key of CHOICES (a dropdown).
    fields: tuple[str, ...] = ()


# Dropdown fields: the values each may hold, in menu order, with their labels and hover text. The first is the
# default and is stored as "", so that a node left on it saves the same as one never touched. For a field in
# AUTO_CHOICE that first choice is AUTO: whichever choice AUTO_CHOICE names, which may change between versions.
AUTO = ""
PAULUS_TORCOLI = "paulus_torcoli"
MID_SIDE = "mid_side"
BOTH = ""
LEFT = "left"
RIGHT = "right"
CHOICES = {
    "algorithm": (
        (AUTO, strings.ALGORITHM_AUTO, ""),
        (PAULUS_TORCOLI, strings.ALGORITHM_PAULUS_TORCOLI, strings.ALGORITHM_PAULUS_TORCOLI_TIP),
        (MID_SIDE, strings.ALGORITHM_MID_SIDE, strings.ALGORITHM_MID_SIDE_TIP),
    ),
    "channels": (
        (BOTH, strings.CHANNELS_BOTH, strings.CHANNELS_BOTH_TIP),
        (LEFT, strings.CHANNELS_LEFT, strings.CHANNELS_LEFT_TIP),
        (RIGHT, strings.CHANNELS_RIGHT, strings.CHANNELS_RIGHT_TIP),
    ),
}
AUTO_CHOICE = {"algorithm": PAULUS_TORCOLI}

NODE_TYPES = {
    "input": NodeType(strings.NODE_INPUT, (), (strings.PORT_AUDIO,), fields=("name", "file")),
    "split_mid_side": NodeType(
        strings.NODE_SPLIT_CENTER_SIDE, (strings.PORT_AUDIO,), (strings.PORT_CENTER, strings.PORT_SIDE),
        fields=("algorithm",),
    ),
    "invert": NodeType(strings.NODE_INVERT, (strings.PORT_AUDIO,), (strings.PORT_AUDIO,), fields=("channels",)),
    "subtract": NodeType(strings.NODE_SUBTRACT, (strings.PORT_AUDIO, strings.PORT_MINUS), (strings.PORT_AUDIO,)),
    "output": NodeType(strings.NODE_OUTPUT, (strings.PORT_AUDIO,), (), fields=("name",)),
}


def snap(value: float) -> int:
    """Round a coordinate to the nearest grid line."""
    return round(value / GRID) * GRID


@dataclass
class Node:
    id: int
    type_key: str
    x: int
    y: int
    values: dict[str, str] = field(default_factory=dict)

    @property
    def type(self) -> NodeType:
        return NODE_TYPES[self.type_key]

    def choice(self, name: str) -> str:
        """The value of a dropdown field, with AUTO resolved to the choice it currently stands for."""
        value = self.values.get(name, AUTO)
        return AUTO_CHOICE[name] if value == AUTO and name in AUTO_CHOICE else value


@dataclass(frozen=True)
class Connection:
    src: int         # source node id
    src_output: int  # output index on the source node
    dst: int         # destination node id
    dst_input: int   # input index on the destination node


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.connections: set[Connection] = set()
        self._next_id = 1

    def add_node(self, type_key: str, x: float, y: float, node_id: int | None = None) -> Node:
        """Add a node. `node_id` is for restoring a saved graph; new nodes get the next free id."""
        if type_key not in NODE_TYPES:
            raise ValueError(f"unknown node type {type_key!r}")
        if node_id is None:
            node_id = self._next_id
        elif node_id < 1 or node_id in self.nodes:
            raise ValueError(f"node id {node_id} is invalid or already used")
        self._next_id = max(self._next_id, node_id + 1)
        node = Node(node_id, type_key, snap(x), snap(y))
        self.nodes[node.id] = node
        return node

    def move_node(self, node_id: int, x: float, y: float) -> None:
        node = self.nodes[node_id]
        node.x, node.y = snap(x), snap(y)

    def set_value(self, node_id: int, name: str, value: str) -> None:
        node = self.nodes[node_id]
        if name not in node.type.fields:
            raise ValueError(f"{node.type.title} has no field {name!r}")
        if name in CHOICES and value not in (choice[0] for choice in CHOICES[name]):
            raise ValueError(f"{value!r} is not a choice for {name!r}")
        node.values[name] = value

    def remove_node(self, node_id: int) -> None:
        del self.nodes[node_id]
        self.connections = {c for c in self.connections if node_id not in (c.src, c.dst)}

    def connect(self, src: int, src_output: int, dst: int, dst_input: int) -> Connection | None:
        """Connect an output to an input, replacing any wire already on that input.

        Returns None and changes nothing if the connection isn't allowed.
        """
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return None
        if not 0 <= src_output < len(self.nodes[src].type.outputs):
            return None
        if not 0 <= dst_input < len(self.nodes[dst].type.inputs):
            return None
        if self._reaches(dst, src):
            return None

        self.connections = {
            c for c in self.connections if (c.dst, c.dst_input) != (dst, dst_input)
        }
        connection = Connection(src, src_output, dst, dst_input)
        self.connections.add(connection)
        return connection

    def disconnect(self, connection: Connection) -> None:
        self.connections.discard(connection)

    # --- Whole-graph state, for undo ---

    def state(self) -> tuple:
        """Everything about the graph that saving would record, as a hashable value. Blank values are left out, so
        a value cleared again counts as never set. `set_state` puts a graph back to a state."""
        nodes = tuple(
            (n.id, n.type_key, n.x, n.y, tuple(sorted((k, v) for k, v in n.values.items() if v)))
            for n in sorted(self.nodes.values(), key=lambda n: n.id)
        )
        connections = tuple(sorted((c.src, c.src_output, c.dst, c.dst_input) for c in self.connections))
        return nodes, connections

    def set_state(self, state: tuple) -> None:
        nodes, connections = state
        self.nodes = {
            node_id: Node(node_id, type_key, x, y, dict(values)) for node_id, type_key, x, y, values in nodes
        }
        self.connections = {Connection(*c) for c in connections}
        self._next_id = max([self._next_id, *(node_id + 1 for node_id in self.nodes)])

    # --- Copy and paste ---

    def fragment(self, node_ids) -> dict:
        """The given nodes and the connections between them, as JSON-ready data for the clipboard."""
        ids = set(node_ids)
        nodes = [
            {"id": n.id, "type": n.type_key, "x": n.x, "y": n.y, "values": {k: v for k, v in n.values.items() if v}}
            for n in sorted(self.nodes.values(), key=lambda n: n.id) if n.id in ids
        ]
        connections = [
            [c.src, c.src_output, c.dst, c.dst_input]
            for c in sorted(self.connections, key=lambda c: (c.src, c.src_output, c.dst, c.dst_input))
            if c.src in ids and c.dst in ids
        ]
        return {"format": FRAGMENT_FORMAT, "nodes": nodes, "connections": connections}

    def paste(self, piece: "Graph", x: float, y: float) -> list[int]:
        """Add a copy of every node and connection in `piece`, with the top-left node corner at (x, y). Typed names
        that are already taken get numbered ("Vocals 2"). Returns the new nodes' ids."""
        if not piece.nodes:
            return []
        left = min(n.x for n in piece.nodes.values())
        top = min(n.y for n in piece.nodes.values())
        new_ids = {}
        for old in sorted(piece.nodes.values(), key=lambda n: n.id):
            node = self.add_node(old.type_key, old.x - left + x, old.y - top + y)
            new_ids[old.id] = node.id
            for name, value in old.values.items():
                if name == "name" and value:
                    value = self._free_name(old.type_key, value)
                self.set_value(node.id, name, value)
        for c in piece.connections:
            self.connect(new_ids[c.src], c.src_output, new_ids[c.dst], c.dst_input)
        return list(new_ids.values())

    def _free_name(self, type_key: str, name: str) -> str:
        """`name`, or if another node of that type already has it, the first free numbered version of it."""
        taken = {n.values.get("name", "").casefold() for n in self.nodes.values() if n.type_key == type_key}
        if name.casefold() not in taken:
            return name
        match = re.fullmatch(r"(.*\S) (\d+)", name)
        base, number = (match[1], int(match[2]) + 1) if match else (name, 2)
        while (candidate := strings.NUMBERED_NAME.format(name=base, number=number)).casefold() in taken:
            number += 1
        return candidate

    def _reaches(self, start: int, target: int) -> bool:
        """True if target is start or is downstream of it."""
        stack, seen = [start], set()
        while stack:
            node_id = stack.pop()
            if node_id == target:
                return True
            if node_id not in seen:
                seen.add(node_id)
                stack.extend(c.dst for c in self.connections if c.src == node_id)
        return False


FRAGMENT_FORMAT = "stemgraph-nodes"


def load_fragment(data) -> Graph | None:
    """The nodes and connections in clipboard data made by `Graph.fragment`, or None if it isn't valid. The data
    may come from another copy of stemgraph, maybe another version, so nothing about it is trusted."""
    try:
        if data.get("format") != FRAGMENT_FORMAT:
            return None
        piece = Graph()
        for entry in data["nodes"]:
            ints = [entry["id"], entry["x"], entry["y"]]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in ints):
                return None
            node = piece.add_node(entry["type"], entry["x"], entry["y"], node_id=entry["id"])
            for name, value in entry["values"].items():
                if not isinstance(value, str):
                    return None
                piece.set_value(node.id, name, value)
        for entry in data["connections"]:
            if len(entry) != 4 or piece.connect(*entry) is None:
                return None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return piece if piece.nodes else None
