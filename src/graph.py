"""Node graph model: node types, nodes, connections and the rules between them. No Qt."""

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


# Dropdown fields: the values each may hold, in menu order, with their labels and hover text. The first is AUTO,
# the default:
# whichever choice AUTO_CHOICE names, which may change between versions. It's stored as "" so that a node left on
# it saves the same as one never touched.
AUTO = ""
PAULUS_TORCOLI = "paulus_torcoli"
MID_SIDE = "mid_side"
CHOICES = {
    "algorithm": (
        (AUTO, strings.ALGORITHM_AUTO, ""),
        (PAULUS_TORCOLI, strings.ALGORITHM_PAULUS_TORCOLI, strings.ALGORITHM_PAULUS_TORCOLI_TIP),
        (MID_SIDE, strings.ALGORITHM_MID_SIDE, strings.ALGORITHM_MID_SIDE_TIP),
    ),
}
AUTO_CHOICE = {"algorithm": PAULUS_TORCOLI}

NODE_TYPES = {
    "input": NodeType(strings.NODE_INPUT, (), (strings.PORT_AUDIO,), fields=("name", "file")),
    "split_mid_side": NodeType(
        strings.NODE_SPLIT_CENTER_SIDE, (strings.PORT_AUDIO,), (strings.PORT_CENTER, strings.PORT_SIDE),
        fields=("algorithm",),
    ),
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
        return AUTO_CHOICE[name] if value == AUTO else value


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
