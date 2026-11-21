from window import recent_labels


def test_recent_labels_number_and_escape():
    paths = [f"C:/p/song{i}.sgp" for i in range(1, 11)]
    paths[0] = "C:/p/rock & roll.sgp"
    labels = recent_labels(paths)
    assert labels[0] == "&1 rock && roll"
    assert labels[1] == "&2 song2"
    assert labels[9] == "10 song10"


def test_recent_labels_disambiguate_same_name():
    labels = recent_labels(["C:/a/mix.sgp", "C:/b/mix.sgp", "C:/b/other.sgp"])
    assert labels == ["&1 mix (a)", "&2 mix (b)", "&3 other"]
