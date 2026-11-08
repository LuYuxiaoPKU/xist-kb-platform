"""The scope classification rule, independent of any database."""

from xist_kb.query.paper_scope import classify


def test_text_naming_xist_is_in_scope():
    assert classify(xist=12, phenomenon=3, text_chars=4000) == "xist"


def test_phenomenon_without_xist_is_still_in_scope():
    # Drosophila MSL work and older X-inactivation papers never name the gene.
    assert classify(xist=0, phenomenon=8, text_chars=30000) == "phenomenon_only"


def test_no_vocabulary_at_all_is_out_of_scope():
    assert classify(xist=0, phenomenon=0, text_chars=20000) == "out_of_scope"


def test_no_text_is_unknown_not_out_of_scope():
    # 283k registered papers have no PDF. Absence of text is not evidence that
    # the paper is about something else, so it must not be called out of scope.
    assert classify(xist=0, phenomenon=0, text_chars=0) == "unknown"


def test_xist_wins_over_phenomenon():
    # A paper that names both is Xist work, not merely phenomenon-adjacent.
    assert classify(xist=1, phenomenon=99, text_chars=5000) == "xist"


def test_one_mention_is_enough():
    # Threshold is set elsewhere for analysis; the classification itself only
    # asks whether the word appears, because "mentions Xist once" still means
    # the paper is about the subject rather than about something else.
    assert classify(xist=1, phenomenon=0, text_chars=100000) == "xist"
