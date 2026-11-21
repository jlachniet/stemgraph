import os

import numpy as np
import pytest
import soundfile

import audio
import build
import strings
from build import BuildProblems, export_name, make_plan
from graph import Graph

# --- Helpers ---


def tone(path, rate=44100, channels=2, frames=4410) -> str:
    rng = np.random.default_rng(len(str(path)))
    data = rng.uniform(-0.5, 0.5, (frames, channels)).astype(np.float32)
    soundfile.write(path, data, rate, subtype="FLOAT")
    return str(path)


def add_input(g: Graph, name: str = "", file: str | None = None, x=0, y=0) -> int:
    node = g.add_node("input", x, y)
    if name:
        g.set_value(node.id, "name", name)
    if file:
        g.set_value(node.id, "file", file)
    return node.id


def add_output(g: Graph, name: str, source: int | None = None, src_output=0, y=0) -> int:
    node = g.add_node("output", 500, y)
    g.set_value(node.id, "name", name)
    if source is not None:
        g.connect(source, src_output, node.id, 0)
    return node.id


def add_split(g: Graph, source: int | None) -> int:
    node = g.add_node("split_mid_side", 250, 0)
    if source is not None:
        g.connect(source, 0, node.id, 0)
    return node.id


def problems(g: Graph) -> list[str]:
    with pytest.raises(BuildProblems) as raised:
        make_plan(g)
    return raised.value.problems


def run(plan, folder, cancel_at: int | None = None):
    labels, lines = [], []

    def started(index, label):
        labels.append((index, label))

    ok = build.run(plan, str(folder), started, lambda kind, text: lines.append((kind, text)),
                   lambda: cancel_at is not None and len(labels) > cancel_at)
    return ok, labels, lines


# --- File names ---


@pytest.mark.parametrize("name, file_name", [
    ("Vocals", "Vocals.wav"),
    ("  Lead vox ", "  Lead vox-.wav"),
    ("a/b\\c:d*e?f\"g<h>i|j", "a-b-c-d-e-f-g-h-i-j.wav"),
    ("tab\there", "tab-here.wav"),
    ("Vocals.", "Vocals-.wav"),
    ("Mix. .", "Mix---.wav"),
    ("CON", "CON-.wav"),
    ("con", "con-.wav"),
    ("nul.mix", "nul-.mix.wav"),
    ("COM1", "COM1-.wav"),
    ("CONSOLE", "CONSOLE.wav"),
    ("", None),
    ("   ", None),
])
def test_export_name(name, file_name):
    assert export_name(name) == file_name


def test_blank_outputs_are_named_after_their_source(tmp_path):
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav"))
    split = add_split(g, song)
    add_output(g, "", split, 0, y=0)
    add_output(g, "  ", split, 1, y=100)
    add_output(g, "", song, y=200)
    add_output(g, "", add_input(g, "", tone(tmp_path / "drums.wav")), y=300)  # unnamed Input: its file's name
    assert make_plan(g).files == ["Song mid.wav", "Song side.wav", "Song.wav", "drums.wav"]


def test_default_names_are_numbered_instead_of_clashing(tmp_path):
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "", song, y=0)
    add_output(g, "", song, y=100)
    add_output(g, "song", song, y=200)  # a typed name keeps it, even below the blank ones
    assert make_plan(g).files == ["Song 2.wav", "Song 3.wav", "song.wav"]


def test_unconnected_blank_outputs_are_called_output():
    g = Graph()
    add_output(g, "", y=0)
    add_output(g, "", y=100)
    assert build.output_names(g) == {1: "Output", 2: "Output 2"}
    assert problems(g) == ['Output "Output" has nothing connected to it.',
                           'Output "Output 2" has nothing connected to it.']


# --- Checks ---


def test_nothing_to_build_without_outputs():
    g = Graph()
    add_input(g, "Song")
    assert problems(g) == [strings.NOTHING_TO_BUILD]


def test_all_problems_are_listed_together(tmp_path):
    g = Graph()
    add_output(g, "Vocals")
    split = add_split(g, None)
    add_output(g, "Mid", split)
    add_output(g, "Drums", add_input(g, "Drums"))
    add_output(g, "Bass", add_input(g, "Bass", str(tmp_path / "missing.wav")))
    assert problems(g) == [
        'Output "Vocals" has nothing connected to it.',
        "A Split Mid/Side node has nothing connected to its input.",
        'Input "Drums" has no file chosen.',
        'Input "Bass": missing.wav couldn\'t be found.',
    ]


def test_unreadable_and_surround_files_are_problems(tmp_path):
    g = Graph()
    text = tmp_path / "notes.wav"
    text.write_text("hello")
    add_output(g, "A", add_input(g, "", str(text)))
    add_output(g, "B", add_input(g, "Surround", tone(tmp_path / "surround.wav", channels=6)))
    assert problems(g) == [
        'Input "notes.wav": notes.wav couldn\'t be read as audio.',
        'Input "Surround": surround.wav has too many channels: (has 6, expected 1 or 2)',
    ]


def test_names_that_end_up_as_the_same_file_clash(tmp_path):
    g = Graph()
    source = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "Vocals?", source, y=0)
    add_output(g, "Vocals*", source, y=100)
    add_output(g, "drums", source, y=200)
    add_output(g, "Drums", source, y=300)
    assert problems(g) == [
        'Outputs "Vocals?" and "Vocals*" would both be saved as Vocals-.wav.',
        'Outputs "drums" and "Drums" would both be saved as drums.wav.',
    ]


def test_nodes_that_feed_no_output_are_not_checked(tmp_path):
    g = Graph()
    add_output(g, "Out", add_input(g, "Song", tone(tmp_path / "song.wav")))
    add_input(g, "Unused, no file")
    add_split(g, None)
    add_split(g, add_input(g, "Unused, missing", str(tmp_path / "missing.wav")))
    assert make_plan(g).files == ["Out.wav"]


# --- Steps ---


def test_steps_compute_only_what_reaches_an_output(tmp_path):
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav", rate=48000))
    split = add_split(g, song)
    add_output(g, "Side", split, 1, y=0)
    add_output(g, "Mid", split, 0, y=100)
    add_output(g, "Song", song, y=200)
    unused = add_input(g, "Other", tone(tmp_path / "other.wav"))
    add_split(g, unused)

    plan = make_plan(g)
    assert [s.label for s in plan.steps] == [
        "Loading song.wav",
        "Resampling song.wav from 48000 Hz to 44100 Hz",
        "Splitting Song into mid and side",
        "Writing Side.wav",
        "Writing Mid.wav",
        "Writing Song.wav",
    ]
    assert plan.files == ["Side.wav", "Mid.wav", "Song.wav"]


def test_a_file_used_by_two_inputs_is_loaded_once(tmp_path):
    g = Graph()
    path = tone(tmp_path / "song.wav")
    add_output(g, "A", add_input(g, "One", path), y=0)
    add_output(g, "B", add_input(g, "Two", path), y=100)
    assert [s.label for s in make_plan(g).steps] == ["Loading song.wav", "Writing A.wav", "Writing B.wav"]


def test_chained_splits_are_described_by_their_source(tmp_path):
    g = Graph()
    first = add_split(g, add_input(g, "Song", tone(tmp_path / "song.wav")))
    second = g.add_node("split_mid_side", 0, 0).id
    g.connect(first, 1, second, 0)
    add_output(g, "Out", second, 0)
    assert "Splitting Song side into mid and side" in [s.label for s in make_plan(g).steps]


# --- Running ---


def read(path) -> np.ndarray:
    data, rate = soundfile.read(path, dtype="float32")
    assert rate == audio.RATE
    return data


def test_build_writes_the_split(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    path = tone(tmp_path / "song.wav")
    g = Graph()
    split = add_split(g, add_input(g, "Song", path))
    add_output(g, "Mid", split, 0, y=0)
    add_output(g, "Side", split, 1, y=100)

    ok, labels, lines = run(make_plan(g), out)
    assert ok
    assert [i for i, _ in labels] == [0, 1, 2, 3]
    assert lines[-1] == (build.INFO, f"Done. Wrote 2 files to {out}.")
    assert sorted(os.listdir(out)) == ["Mid.wav", "Side.wav"]  # and no temporary files left

    source = soundfile.read(path, dtype="float64")[0]
    mid, side = read(out / "Mid.wav"), read(out / "Side.wav")
    expected_mid, expected_side = audio.split_mid_side(source)
    assert np.array_equal(mid, expected_mid.astype(np.float32))
    assert np.array_equal(side, expected_side.astype(np.float32))


def test_mono_input_is_logged_and_copied(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    g = Graph()
    add_output(g, "Out", add_input(g, "Mono", tone(tmp_path / "mono.wav", channels=1)))
    ok, _, lines = run(make_plan(g), out)
    assert ok and (build.INFO, "mono.wav is mono; using it on both channels.") in lines
    data = read(out / "Out.wav")
    assert np.array_equal(data[:, 0], data[:, 1])


def test_resampled_input_is_written_at_44_1_khz(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    g = Graph()
    add_output(g, "Out", add_input(g, "Song", tone(tmp_path / "song.wav", rate=48000, frames=4800)))
    assert run(make_plan(g), out)[0]
    assert len(read(out / "Out.wav")) == 4410


def test_loud_outputs_are_written_unchanged_with_a_warning(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    path = tmp_path / "loud.wav"
    soundfile.write(path, np.full((100, 2), 2.0, dtype=np.float32), 44100, subtype="FLOAT")
    g = Graph()
    add_output(g, "Loud", add_input(g, "Loud", str(path)))
    ok, _, lines = run(make_plan(g), out)
    assert ok and (build.WARNING, "Loud.wav peaks at +6.0 dBFS.") in lines
    assert np.all(read(out / "Loud.wav") == 2.0)


def test_cancelling_writes_nothing_and_keeps_old_files(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "A.wav").write_bytes(b"old")
    g = Graph()
    source = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "A", source, y=0)
    add_output(g, "B", source, y=100)

    ok, labels, lines = run(make_plan(g), out, cancel_at=1)  # after writing A, before B
    assert not ok and len(labels) == 2
    assert lines[-1] == (build.INFO, "Cancelled. No files were written.")
    assert os.listdir(out) == ["A.wav"] and (out / "A.wav").read_bytes() == b"old"


def test_a_failed_build_writes_nothing(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    g = Graph()
    good = add_input(g, "Good", tone(tmp_path / "good.wav"))
    bad = tmp_path / "bad.wav"
    tone(bad)
    add_output(g, "A", good, y=0)
    add_output(g, "B", add_input(g, "Bad", str(bad)), y=100)
    plan = make_plan(g)
    bad.write_text("damaged after the check")

    ok, _, lines = run(plan, out)
    assert not ok and lines[-1] == (build.ERROR, "bad.wav couldn't be read as audio.")
    assert os.listdir(out) == []


def test_existing_files(tmp_path):
    g = Graph()
    source = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "A", source, y=0)
    add_output(g, "B", source, y=100)
    (tmp_path / "B.wav").write_bytes(b"")
    assert build.existing_files(make_plan(g), str(tmp_path)) == ["B.wav"]
