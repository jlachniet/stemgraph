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
    assert make_plan(g).files == ["Song center.wav", "Song side.wav", "Song.wav", "drums.wav"]


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
        "A Split Center/Side node has nothing connected to its input.",
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
        "Splitting Song into center and side",
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
    assert "Splitting Song side into center and side" in [s.label for s in make_plan(g).steps]


def add_invert(g: Graph, source: int | None, src_output=0, channels="") -> int:
    node = g.add_node("invert", 250, 0)
    g.set_value(node.id, "channels", channels)
    if source is not None:
        g.connect(source, src_output, node.id, 0)
    return node.id


def test_inverted_outputs_are_named_after_their_source(tmp_path):
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "", add_invert(g, song), y=0)
    add_output(g, "", add_invert(g, add_split(g, song), 0), y=100)
    add_output(g, "", add_invert(g, None), y=200)
    assert list(build.output_names(g).values()) == ["Song inverted", "Song center inverted", "Invert inverted"]


def add_align(g: Graph, source: int | None, reference: int | None) -> int:
    node = g.add_node("align", 250, 0)
    if source is not None:
        g.connect(source, 0, node.id, 0)
    if reference is not None:
        g.connect(reference, 0, node.id, 1)
    return node.id


def offset_copy(path, source, lag, frames=6000, invert=False) -> str:
    """A file holding `source` moved `lag` frames later (cut to fit), maybe inverted."""
    x = soundfile.read(source, dtype="float32")[0]
    y = np.zeros((frames, 2), dtype=np.float32)
    start, stop = max(lag, 0), min(frames, len(x) + lag)
    y[start:stop] = x[start - lag:stop - lag]
    soundfile.write(path, -y if invert else y, 44100, subtype="FLOAT")
    return str(path)


@pytest.mark.parametrize("alignment", ["", "gcc_phat", "cross_correlation"])
@pytest.mark.parametrize("lag", [700, -300])
def test_build_aligns_audio_to_the_reference(tmp_path, alignment, lag):
    out = tmp_path / "out"
    out.mkdir()
    stem = tone(tmp_path / "stem.wav")
    g = Graph()
    node = add_align(g, add_input(g, "Stem", stem), add_input(g, "Mix", offset_copy(tmp_path / "mix.wav", stem, lag)))
    g.set_value(node, "alignment", alignment)
    add_output(g, "Aligned", node)
    ok, labels, lines = run(make_plan(g), out)
    assert ok and [label for _, label in labels] == [
        "Loading stem.wav", "Loading mix.wav", "Aligning Stem to Mix", "Writing Aligned.wav"]
    x = soundfile.read(stem, dtype="float64")[0]
    assert np.array_equal(read(out / "Aligned.wav"), audio.shift(x, lag).astype(np.float32))
    moved = "later" if lag > 0 else "earlier"
    ms = abs(lag) * 1000 / 44100
    assert (build.INFO, f"Moved Stem {moved} by {abs(lag)} samples ({ms:.3f} ms).") in lines


@pytest.mark.parametrize("polarity, inverted", [("", True), ("keep", False)])
def test_align_matches_polarity_unless_told_to_keep_it(tmp_path, polarity, inverted):
    out = tmp_path / "out"
    out.mkdir()
    stem = tone(tmp_path / "stem.wav")
    g = Graph()
    mix = add_input(g, "Mix", offset_copy(tmp_path / "mix.wav", stem, 1, invert=True))
    node = add_align(g, add_input(g, "Stem", stem), mix)
    g.set_value(node, "polarity", polarity)
    add_output(g, "Aligned", node)
    ok, _, lines = run(make_plan(g), out)
    assert ok
    expected = audio.shift(soundfile.read(stem, dtype="float64")[0], 1)
    assert np.array_equal(read(out / "Aligned.wav"), (-expected if inverted else expected).astype(np.float32))
    assert (build.INFO, "Moved Stem later by 1 sample (0.023 ms).") in lines
    if inverted:
        assert (build.INFO, "Inverted Stem to match the polarity of Mix.") in lines
    else:
        assert (build.INFO, "Stem has the opposite polarity to Mix; left as it is.") in lines


def test_align_with_nothing_in_common_leaves_the_audio_alone(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    stem = tone(tmp_path / "stem.wav")
    silence = tmp_path / "silence.wav"
    soundfile.write(silence, np.zeros((1000, 2), dtype=np.float32), 44100, subtype="FLOAT")
    g = Graph()
    add_output(g, "Aligned", add_align(g, add_input(g, "Stem", stem), add_input(g, "Silence", str(silence))))
    ok, _, lines = run(make_plan(g), out)
    assert ok and np.array_equal(read(out / "Aligned.wav"), soundfile.read(stem, dtype="float32")[0])
    assert (build.WARNING, "Stem has nothing in common with Silence, so it was left as it is.") in lines


def test_aligned_outputs_are_named_after_their_audio(tmp_path):
    g = Graph()
    stem = add_input(g, "Vocals", tone(tmp_path / "vocals.wav"))
    add_output(g, "", add_align(g, stem, add_input(g, "Song", tone(tmp_path / "song.wav"))))
    assert list(build.output_names(g).values()) == ["Vocals aligned"]


def test_unconnected_align_inputs_are_named(tmp_path):
    g = Graph()
    add_output(g, "Out", add_align(g, add_input(g, "Stem", tone(tmp_path / "stem.wav")), None))
    assert problems(g) == ["The reference input of Align has nothing connected to it."]


def add_subtract(g: Graph, source: int | None, minus: int | None, align="") -> int:
    node = g.add_node("subtract", 250, 0)
    if source is not None:
        g.connect(source, 0, node.id, 0)
    if minus is not None:
        g.connect(minus, 0, node.id, 1)
    g.set_value(node.id, "align", align)
    return node.id


def noise(path, seed, frames=4410, data=None) -> str:
    data = np.random.default_rng(seed).uniform(-0.25, 0.25, (frames, 2)) if data is None else data
    soundfile.write(path, data.astype(np.float32), 44100, subtype="FLOAT")
    return str(path)


@pytest.mark.parametrize("alignment", ["", "cross_correlation"])
def test_subtract_aligns_minus_and_matches_its_polarity_first(tmp_path, alignment):
    out = tmp_path / "out"
    out.mkdir()
    vocals = soundfile.read(noise(tmp_path / "vocals.wav", 1), dtype="float64")[0]
    instrumental = noise(tmp_path / "instrumental.wav", 2)
    inst = soundfile.read(instrumental, dtype="float64")[0]
    master = noise(tmp_path / "master.wav", 0, data=vocals + inst)
    late = offset_copy(tmp_path / "late.wav", instrumental, 700, invert=True)
    g = Graph()
    node = add_subtract(g, add_input(g, "Master", master), add_input(g, "Instrumental", late))
    g.set_value(node, "alignment", alignment)
    add_output(g, "Vocals", node)
    ok, labels, lines = run(make_plan(g), out)
    assert ok and [label for _, label in labels] == [
        "Loading master.wav", "Loading late.wav", "Aligning Instrumental to Master",
        "Subtracting Instrumental from Master", "Writing Vocals.wav"]
    assert (build.INFO, "Moved Instrumental earlier by 700 samples (15.873 ms).") in lines
    assert (build.INFO, "Inverted Instrumental to match the polarity of Master.") in lines
    result = read(out / "Vocals.wav")
    assert np.allclose(result[:len(vocals)], vocals, atol=1e-6) and not result[len(vocals):].any()


def test_subtract_without_aligning_pads_the_shorter_input(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    song, vocals = tone(tmp_path / "song.wav"), tone(tmp_path / "vocals.wav", frames=2205)
    g = Graph()
    add_output(g, "Out", add_subtract(g, add_input(g, "Song", song), add_input(g, "Vocals", vocals), align="off"))
    plan = make_plan(g)
    assert [s.label for s in plan.steps] == [
        "Loading song.wav", "Loading vocals.wav", "Subtracting Vocals from Song", "Writing Out.wav"]
    assert run(plan, out)[0]
    expected = read(song).astype(np.float64)
    expected[:2205] -= read(vocals)
    assert np.array_equal(read(out / "Out.wav"), expected.astype(np.float32))


def test_subtracted_outputs_are_named_like_a_mix(tmp_path):
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "", add_subtract(g, song, add_input(g, "Instrumental", tone(tmp_path / "inst.wav"))))
    assert list(build.output_names(g).values()) == ["Song − Instrumental"]


def test_unconnected_subtract_inputs_are_named(tmp_path):
    g = Graph()
    add_output(g, "Out", add_subtract(g, add_input(g, "Song", tone(tmp_path / "song.wav")), None))
    assert problems(g) == ["The minus input of Subtract has nothing connected to it."]


def test_unconnected_invert_is_a_problem(tmp_path):
    g = Graph()
    add_output(g, "Out", add_invert(g, None))
    assert "Invert" in " ".join(problems(g))


def add_mix(g: Graph, *sources) -> int:
    """A Mix of the given (node, output) sources."""
    node = g.add_node("mix", 250, 0)
    for index, (source, output) in enumerate(sources):
        g.connect(source, output, node.id, index)
    return node.id


def test_mixed_outputs_are_named_after_their_sources(tmp_path):
    g = Graph()
    song, vocals, drums, bass, keys, pads = (add_input(g, name) for name in
                                             ("Song", "Vocals", "Drums", "Bass", "Keys", "Pads"))
    split = add_split(g, song)
    add_output(g, "", add_mix(g, (drums, 0), (bass, 0), (vocals, 0)), y=100)
    add_output(g, "", add_mix(g, (vocals, 0)), y=200)
    add_output(g, "", add_mix(g, (split, 0), (split, 1)), y=300)
    add_output(g, "", add_mix(g, *((n, 0) for n in (drums, bass, vocals, keys, pads, song))), y=400)
    add_output(g, "", add_mix(g), y=500)
    assert list(build.output_names(g).values()) == [
        "Drums + Bass + Vocals", "Vocals", "Song center + Song side",
        "Drums + Bass + 4 more", "Mix"]


def test_mix_with_nothing_connected_is_a_problem():
    g = Graph()
    add_output(g, "Out", add_mix(g))
    assert problems(g) == ["A Mix node has nothing connected to it."]


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
    expected_mid, expected_side = audio.split_paulus_torcoli(source)
    assert np.array_equal(mid, expected_mid.astype(np.float32))
    assert np.array_equal(side, expected_side.astype(np.float32))


@pytest.mark.parametrize("channels, signs", [("", (-1, -1)), ("left", (-1, 1)), ("right", (1, -1))])
def test_build_writes_the_inverted_audio(tmp_path, channels, signs):
    out = tmp_path / "out"
    out.mkdir()
    path = tone(tmp_path / "song.wav")
    g = Graph()
    add_output(g, "Out", add_invert(g, add_input(g, "Song", path), channels=channels))
    plan = make_plan(g)
    assert "Inverting Song" in [s.label for s in plan.steps]
    assert run(plan, out)[0]
    source = read(path)
    assert np.array_equal(read(out / "Out.wav"), source * np.array(signs, dtype=np.float32))


def test_build_writes_the_mix_padding_shorter_tracks(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    paths = [tone(tmp_path / f"{name}.wav", frames=frames)
             for name, frames in [("song", 4410), ("vocals", 2205), ("drums", 3000)]]
    g = Graph()
    names = ("Song", "Vocals", "Drums")
    song, vocals, drums = (add_input(g, name, path) for name, path in zip(names, paths, strict=True))
    add_output(g, "Out", add_mix(g, (song, 0), (vocals, 0), (drums, 0)))
    plan = make_plan(g)
    assert "Mixing Song + Vocals + Drums" in [s.label for s in plan.steps]
    assert run(plan, out)[0]
    song_data, vocals_data, drums_data = (read(path).astype(np.float64) for path in paths)
    expected = song_data.copy()
    expected[:len(vocals_data)] += vocals_data
    expected[:len(drums_data)] += drums_data
    assert np.array_equal(read(out / "Out.wav"), expected.astype(np.float32))


def test_subtracting_a_source_from_itself_is_silent(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    g = Graph()
    song = add_input(g, "Song", tone(tmp_path / "song.wav"))
    add_output(g, "Out", add_subtract(g, song, song, align="off"))
    assert run(make_plan(g), out)[0]
    data = read(out / "Out.wav")
    assert len(data) == 4410 and not data.any()


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


@pytest.mark.parametrize("algorithm, split", [
    ("", audio.split_paulus_torcoli),
    ("paulus_torcoli", audio.split_paulus_torcoli),
    ("mid_side", audio.split_mid_side),
])
def test_build_uses_the_chosen_algorithm(tmp_path, algorithm, split):
    out = tmp_path / "out"
    out.mkdir()
    path = tone(tmp_path / "song.wav")
    g = Graph()
    node = add_split(g, add_input(g, "Song", path))
    g.set_value(node, "algorithm", algorithm)
    add_output(g, "Side", node, 1)
    assert run(make_plan(g), out)[0]
    expected = split(soundfile.read(path, dtype="float64")[0])[1]
    assert np.array_equal(read(out / "Side.wav"), expected.astype(np.float32))
