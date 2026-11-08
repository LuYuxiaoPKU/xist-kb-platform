from __future__ import annotations

from xist_kb.extract.chunks import (
    MIN_CHARS,
    TARGET_CHARS,
    make_windows,
    split_sentences,
    window_for_offset,
)

PAPER = (
    "Xist is a long non-coding RNA. It coats the inactive X chromosome in cis. "
    "Recruitment of silencing factors follows coating. "
    "This process is essential for dosage compensation in female mammals. "
    "Deletion of the A-repeat abolishes silencing. "
    "The repeat A region binds several proteins."
)


def test_split_sentences_offsets_are_exact():
    spans = split_sentences(PAPER)
    for start, end in spans:
        assert not PAPER[start].isspace()
        assert not PAPER[end - 1].isspace()


def test_split_sentences_covers_all_text():
    spans = split_sentences(PAPER)
    joined = " ".join(PAPER[s:e] for s, e in spans)
    assert joined.split() == PAPER.split()


def test_windows_are_verbatim_slices():
    for w in make_windows(PAPER, target=60):
        assert PAPER[w.start : w.end] == w.text


def test_windows_are_indexed_in_order():
    windows = make_windows(PAPER, target=60)
    assert [w.index for w in windows] == list(range(len(windows)))
    assert windows[0].start == 0


def test_windows_do_not_overlap():
    windows = make_windows(PAPER, target=60)
    for a, b in zip(windows, windows[1:], strict=False):
        assert a.end <= b.start


def test_window_starts_at_sentence_boundary():
    windows = make_windows(PAPER, target=60)
    # every window begins with a capital, not mid-sentence
    for w in windows:
        assert w.text[0].isupper() or w.text[0] in "XYZ"


def test_target_size_is_respected_when_sentences_allow():
    long_text = " ".join(f"Sentence number {i} is here." for i in range(200))
    windows = make_windows(long_text, target=200)
    if len(windows) > 3:  # only meaningful with several windows
        sizes = sorted(len(w.text) for w in windows[:-1])
        assert sizes[len(sizes) // 2] <= 260


def test_single_long_sentence_is_not_truncated():
    sentence = "word " * 500  # 2500 chars, no terminal punctuation
    windows = make_windows(sentence)
    assert len(windows) == 1
    assert windows[0].text == sentence.strip()


def test_trailing_fragment_folds_into_previous_window():
    text = "A" * 400 + ". " + "B" * 300 + ". Tiny."
    windows = make_windows(text, target=400)
    assert windows[-1].text.endswith("Tiny.")
    assert len(windows[-1].text) >= MIN_CHARS or len(windows) == 1


def test_empty_text_has_no_windows():
    assert make_windows("") == []
    assert make_windows("   \n\n  ") == []


def test_short_text_is_one_window():
    text = "Xist coats the X."
    windows = make_windows(text)
    assert len(windows) == 1
    assert windows[0].text == text


def test_window_for_offset_finds_containing_window():
    windows = make_windows(PAPER, target=60)
    for w in windows:
        assert window_for_offset(windows, w.start) is w
        assert window_for_offset(windows, w.end - 1) is w


def test_window_for_offset_returns_none_when_outside():
    windows = make_windows(PAPER, target=60)
    assert window_for_offset(windows, 10_000) is None
    assert window_for_offset([], 0) is None


def test_default_target_is_700():
    assert TARGET_CHARS == 700


def test_real_text_median_window_near_target():
    # a journal-style paragraph: many shortish sentences
    text = " ".join(
        "We observed that Xist RNA localises to the inactive X in this assay. "
        for _ in range(60)
    )
    windows = make_windows(text)
    sizes = sorted(len(w.text) for w in windows)
    assert 500 <= sizes[len(sizes) // 2] <= 900
