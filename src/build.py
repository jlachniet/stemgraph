"""Building: turning a graph into exported WAV files. No Qt.

make_plan() checks the graph and lists the steps; run() carries them out. Only nodes that feed an Output are
checked or computed. Files are written under temporary names and renamed into place only once every output has
been written, so a failed or cancelled build leaves the export folder as it was.
"""

import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import audio
import strings
from graph import Graph, Node

EXPORT_EXTENSION = ".wav"
MAX_FILE_NAME = 255  # characters, including the extension
INVALID_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in "123456789¹²³"}

# Log line kinds
INFO = "info"
WARNING = "warning"
ERROR = "error"


class BuildProblems(Exception):
    """The graph can't be built. `problems` are sentences shown to the user."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


# --- File names ---

def export_name(name: str) -> str | None:
    """The file name an Output called `name` is saved as, or None if the name is blank.

    Characters Windows doesn't allow in file names, and trailing dots and spaces, become "-". A name Windows
    reserves for devices (CON, NUL, COM1, …) gets "-" after it: "CON" is saved as "CON-.wav".
    """
    if not name.strip():
        return None
    name = INVALID_CHARACTERS.sub("-", name)
    stripped = name.rstrip(". ")
    name = stripped + "-" * (len(name) - len(stripped))
    first, dot, rest = name.partition(".")
    if first.rstrip(" ").upper() in RESERVED_NAMES:  # Windows ignores what follows the first dot, and spaces
        name = first + "-" + dot + rest
    return name + EXPORT_EXTENSION


# --- Plan ---

@dataclass
class Context:
    """What the steps of a running build share."""

    folder: str
    cancelled: Callable[[], bool]
    store: dict = field(default_factory=dict)      # results so far, by key
    temps: dict = field(default_factory=dict)      # export file name -> temporary file holding it


@dataclass
class Step:
    label: str                                      # shown as the current step and logged when it starts
    action: Callable[[Context], list]               # does the work; returns extra log lines as (kind, text)
    uses: tuple = ()                                # store keys it reads


@dataclass
class Plan:
    steps: list[Step]
    files: list[str]                                # export file names, in the order they are written


def _input_label(node: Node) -> str:
    name = node.values.get("name", "").strip()
    if name:
        return name
    file = node.values.get("file")
    return Path(file).name if file else strings.NODE_INPUT


def input_name(node: Node) -> str:
    """What an Input is called: its name, or for a blank one its file's name without the extension ("Song"),
    or "Input" if it has no file."""
    name = node.values.get("name", "").strip()
    if name:
        return name
    file = node.values.get("file")
    return Path(file).stem if file else strings.NODE_INPUT


def _source_name(graph: Graph, feeds: dict, node_id: int, output: int) -> str:
    """A name for what comes out of a node's output: "Song" for an Input, "Song mid" for a split of it."""
    node = graph.nodes[node_id]
    if node.type_key == "input":
        return input_name(node)
    source = feeds.get((node_id, 0))
    base = _source_name(graph, feeds, *source) if source else node.type.title
    return strings.SOURCE_OUTPUT.format(source=base, port=node.type.outputs[output])


def output_names(graph: Graph) -> dict[int, str]:
    """The name each Output is saved under, by node id.

    An Output with a name keeps it. A blank one is named after its source ("Song mid"), or "Output" if nothing
    is connected; " 2", " 3", … is added if that file name is already taken, so defaults never clash with each
    other or with named Outputs. Taken names are claimed in build order (top to bottom).
    """
    outputs = sorted((n for n in graph.nodes.values() if n.type_key == "output"), key=lambda n: (n.y, n.x, n.id))
    feeds = {(c.dst, c.dst_input): (c.src, c.src_output) for c in graph.connections}
    names: dict[int, str] = {}
    taken: set[str] = set()
    for node in outputs:
        name = node.values.get("name", "")
        if export_name(name) is not None:
            names[node.id] = name
            taken.add(export_name(name).casefold())
    for node in outputs:
        if node.id in names:
            continue
        source = feeds.get((node.id, 0))
        base = _source_name(graph, feeds, *source) if source else strings.NODE_OUTPUT
        name, number = base, 1
        while export_name(name).casefold() in taken:
            number += 1
            name = strings.NUMBERED_NAME.format(name=base, number=number)
        names[node.id] = name
        taken.add(export_name(name).casefold())
    return {node.id: names[node.id] for node in outputs}


def _file_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _needed(graph: Graph, outputs: list[Node]) -> set[int]:
    """Ids of the nodes whose results reach an Output."""
    sources = {}
    for c in graph.connections:
        sources.setdefault(c.dst, []).append(c.src)
    needed, stack = set(), [n.id for n in outputs]
    while stack:
        node_id = stack.pop()
        if node_id not in needed:
            needed.add(node_id)
            stack.extend(sources.get(node_id, []))
    return needed


def make_plan(graph: Graph) -> Plan:
    """Check the graph and list the steps to build it. Raises BuildProblems listing everything that's wrong.

    Reads the header of each audio file used, to check it.
    """
    outputs = sorted((n for n in graph.nodes.values() if n.type_key == "output"), key=lambda n: (n.y, n.x, n.id))
    if not outputs:
        raise BuildProblems([strings.NOTHING_TO_BUILD])
    names = output_names(graph)
    needed = _needed(graph, outputs)
    feeds = {(c.dst, c.dst_input): (c.src, c.src_output) for c in graph.connections}
    problems: list[str] = []

    # Nodes with an input left unconnected.
    for node in sorted((graph.nodes[i] for i in needed), key=lambda n: n.id):
        for index in range(len(node.type.inputs)):
            if (node.id, index) not in feeds:
                if node.type_key == "output":
                    problems.append(strings.OUTPUT_NOT_CONNECTED.format(output=names[node.id].strip()))
                else:
                    problems.append(strings.NODE_NOT_CONNECTED.format(node=node.type.title))

    # Input files.
    file_info: dict[str, tuple[str, int, int]] = {}  # file key -> (path, rate, channels)
    for node in sorted((graph.nodes[i] for i in needed if graph.nodes[i].type_key == "input"), key=lambda n: n.id):
        path = node.values.get("file")
        label = _input_label(node)
        if not path:
            problems.append(strings.INPUT_NO_FILE.format(input=label))
            continue
        key = _file_key(path)
        if key in file_info:
            continue
        if not os.path.isfile(path):
            problem = strings.INPUT_FILE_NOT_FOUND.format(file=Path(path).name)
            problems.append(strings.INPUT_PROBLEM.format(input=label, problem=problem))
            continue
        try:
            rate, channels = audio.info(path)
        except audio.AudioError as error:
            problems.append(strings.INPUT_PROBLEM.format(input=label, problem=error))
            continue
        if channels > 2:
            problem = strings.AUDIO_TOO_MANY_CHANNELS.format(file=Path(path).name, channels=channels)
            problems.append(strings.INPUT_PROBLEM.format(input=label, problem=problem))
            continue
        file_info[key] = (path, rate, channels)

    # Output names. Blank names got defaults that can't clash, so only names the user typed can.
    claimed: dict[str, int] = {}  # case-folded file name -> first Output saved under it
    for node in outputs:
        file_name = export_name(names[node.id])
        if len(file_name) > MAX_FILE_NAME:
            problems.append(strings.OUTPUT_NAME_TOO_LONG.format(output=names[node.id].strip()))
            continue
        other = claimed.get(file_name.casefold())
        if other is not None:
            problems.append(strings.OUTPUTS_CLASH.format(
                first=names[other].strip(), second=names[node.id].strip(), file=export_name(names[other])))
        else:
            claimed[file_name.casefold()] = node.id

    if problems:
        raise BuildProblems(problems)
    return _steps(graph, outputs, feeds, file_info, names)


def _steps(graph: Graph, outputs: list[Node], feeds: dict, file_info: dict, names: dict[int, str]) -> Plan:
    """The steps for a graph that passed the checks: what each Output needs, computed as late as possible."""
    steps: list[Step] = []
    done: set = set()  # store keys some step already produces

    def describe(node_id: int, output: int) -> str:
        node = graph.nodes[node_id]
        if node.type_key == "input":
            return _input_label(node)
        source = feeds[(node_id, 0)]
        return strings.SOURCE_OUTPUT.format(source=describe(*source), port=node.type.outputs[output])

    def require(node_id: int, output: int) -> tuple:
        """Add the steps that produce this node output, if not already there; return its store key."""
        node = graph.nodes[node_id]
        if node.type_key == "input":
            path, rate, channels = file_info[_file_key(node.values["file"])]
            key = ("file", _file_key(path))
            if key not in done:
                done.add(key)
                steps.append(Step(strings.STEP_LOAD.format(file=Path(path).name),
                                  _load(path, key, rate != audio.RATE)))
                if rate != audio.RATE:
                    raw = ("raw", key[1])
                    label = strings.STEP_RESAMPLE.format(file=Path(path).name, rate=rate, target=audio.RATE)
                    steps.append(Step(label, _resample(path, raw, key, rate), uses=(raw,)))
            return key
        if node.type_key == "split_mid_side":
            keys = (("node", node_id, 0), ("node", node_id, 1))
            if keys[0] not in done:
                source = require(*feeds[(node_id, 0)])
                done.update(keys)
                label = strings.STEP_SPLIT.format(source=describe(*feeds[(node_id, 0)]))
                steps.append(Step(label, _split(source, keys), uses=(source,)))
            return keys[output]
        raise ValueError(f"can't compute a {node.type.title} node")

    files = []
    for node in outputs:
        file_name = export_name(names[node.id])
        key = require(*feeds[(node.id, 0)])
        steps.append(Step(strings.STEP_WRITE.format(file=file_name), _write(key, file_name), uses=(key,)))
        files.append(file_name)
    return Plan(steps, files)


# --- Step actions ---

class BuildError(Exception):
    """A build that failed part way. The message is shown to the user."""


def _load(path: str, key: tuple, needs_resampling: bool):
    def action(ctx: Context) -> list:
        try:
            data, rate, channels = audio.read(path)
        except audio.AudioError as error:
            raise BuildError(str(error)) from None
        except MemoryError:
            raise BuildError(strings.NO_MEMORY_LOAD.format(file=Path(path).name)) from None
        ctx.store[("raw", key[1]) if needs_resampling else key] = data
        lines = []
        if channels == 1:
            lines.append((INFO, strings.LOG_MONO.format(file=Path(path).name)))
        return lines
    return action


def _resample(path: str, raw: tuple, key: tuple, rate: int):
    def action(ctx: Context) -> list:
        try:
            ctx.store[key] = audio.resample(ctx.store[raw], rate, audio.RATE, ctx.cancelled)
        except MemoryError:
            raise BuildError(strings.NO_MEMORY_RESAMPLE.format(file=Path(path).name)) from None
        return []
    return action


def _split(source: tuple, keys: tuple):
    def action(ctx: Context) -> list:
        ctx.store[keys[0]], ctx.store[keys[1]] = audio.split_mid_side(ctx.store[source])
        return []
    return action


def _write(key: tuple, file_name: str):
    def action(ctx: Context) -> list:
        samples = audio.to_float32(ctx.store[key])
        try:
            fd, temp = tempfile.mkstemp(prefix=".stemgraph-", suffix=".tmp", dir=ctx.folder)
            os.close(fd)
            ctx.temps[file_name] = temp
            audio.write_wav(temp, samples)
        except OSError as error:
            raise BuildError(strings.CANT_WRITE_FILE.format(file=file_name, reason=error.strerror or error)) from None
        peak = audio.peak_dbfs(samples)
        if peak > 0:
            return [(WARNING, strings.LOG_PEAK.format(file=file_name, db=math.floor(peak * 10 + 0.5) / 10))]
        return []
    return action


# --- Running ---

def run(plan: Plan, folder: str, step_started: Callable[[int, str], None], log: Callable[[str, str], None],
        cancelled: Callable[[], bool]) -> bool:
    """Carry out the plan, writing the files into `folder`. Returns True if every file was written.

    `step_started(index, label)` is called as each step starts (index from 0), and `log(kind, text)` for each log
    line. `cancelled()` is checked between steps and during long ones; a cancelled build writes nothing.
    """
    last_use: dict = {}
    for index, step in enumerate(plan.steps):
        for key in step.uses:
            last_use[key] = index

    ctx = Context(folder, cancelled)
    try:
        for index, step in enumerate(plan.steps):
            if cancelled():
                raise audio.Cancelled
            step_started(index, step.label)
            log(INFO, step.label)
            for kind, text in step.action(ctx):
                log(kind, text)
            for key in [k for k, last in last_use.items() if last == index]:
                ctx.store.pop(key, None)  # nothing later needs it; free the memory

        if cancelled():
            raise audio.Cancelled
        for file_name, temp in list(ctx.temps.items()):
            os.replace(temp, os.path.join(folder, file_name))
            del ctx.temps[file_name]
    except audio.Cancelled:
        log(INFO, strings.LOG_CANCELLED)
        return False
    except BuildError as error:
        log(ERROR, str(error))
        return False
    except OSError as error:
        log(ERROR, strings.CANT_WRITE_FOLDER.format(reason=error.strerror or error))
        return False
    except MemoryError:
        log(ERROR, strings.NO_MEMORY_BUILD)
        return False
    finally:
        for temp in ctx.temps.values():
            try:
                os.remove(temp)
            except OSError:
                pass
    count = len(plan.files)
    log(INFO, (strings.LOG_DONE_ONE if count == 1 else strings.LOG_DONE_MANY).format(count=count, folder=folder))
    return True


def existing_files(plan: Plan, folder: str) -> list[str]:
    """The plan's export files that already exist in `folder`."""
    return [name for name in plan.files if os.path.lexists(os.path.join(folder, name))]
