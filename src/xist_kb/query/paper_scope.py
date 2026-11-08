"""Paper-level scope: is this paper about XIST/XCI at all?

The corpus was assembled by keyword search over 296k papers, and annotation
extracted claims from whatever it found. Some of those papers are about MALAT1,
TERRA, DDX39B in mRNA export, or radiotherapy dosimetry -- the query matched an
abstract that mentioned X in passing, and the claims extracted from them are
faithful statements about something that is not this knowledge base's subject.

That is a scope problem, not a classification one. Saying "ROS production
belongs in a different topic" presupposes a topic for ROS production exists;
the claim genuinely is what its paper says, and no relabelling makes it about
XIST. So scope is recorded per paper, from the paper's own full text:

``xist``
    The full text names Xist. Claims may be phrased as "Repeat A RNA" or "the
    A-repeat"; they are still about this subject.
``phenomenon_only``
    Xist is never named, but the text discusses X inactivation, the inactive X,
    Tsix, the Xic, dosage compensation or lyonization. Drosophila MSL work and
    older X-inactivation papers live here.
``out_of_scope``
    Neither. No claim from such a paper can be about the subject.
``unknown``
    No extracted text, so no judgement. 283k registered papers have no PDF;
    absence of evidence is not evidence of absence.

The filter defaults to the first two. It never deletes rows: a reader who wants
the background statements can ask for them, and a judgement made from a regex
should stay reversible.
"""

from __future__ import annotations

import pyarrow as pa

PAPER_SCOPE_SCHEMA = pa.schema(
    [
        ("paper_id", pa.string()),
        ("scope", pa.string()),
        ("xist_mentions", pa.int32()),
        ("phenomenon_mentions", pa.int32()),
        ("text_chars", pa.int32()),
        ("xist_per_10k", pa.float32()),
        ("reason", pa.string()),
    ]
)

# Scope values, in the order the overview page lists them.
SCOPES = ("xist", "phenomenon_only", "out_of_scope", "unknown")

# What a search shows by default: claims whose paper is about the subject.
IN_SCOPE = ("xist", "phenomenon_only")

SCOPE_LABELS = {
    "xist": "全文提到 Xist",
    "phenomenon_only": "只讨论 X 失活，未点名 Xist",
    "out_of_scope": "全文无 XIST/XCI 词汇",
    "unknown": "无全文，未判定",
}

SCOPE_REASONS = {
    "xist": "full text names Xist",
    "phenomenon_only": "discusses X inactivation without naming Xist",
    "out_of_scope": "full text contains no XIST/XCI vocabulary",
    "unknown": "no extracted text; scope not judged",
}

# Words that name the phenomenon without naming the transcript. Case-insensitive
# and hyphenation-agnostic: publishers write "X chromosome inactivation",
# "X-chromosome inactivation" and "Xchromosome inactivation" for the same thing,
# and matching only one form is how an earlier version of this measurement
# declared "X chromosome inactivation in mammals" out of scope.
XIST_PATTERN = "(?i)xist"
PHENOMENON_PATTERN = (
    r"(?i)(tsix|xic|x[\s-]?chromosome inactivation|x[\s-]?inactivation|"
    r"inactive x|dosage compensation|lyoniz|barr body)"
)


def classify(xist: int, phenomenon: int, text_chars: int) -> str:
    """The scope of one paper from its term counts.

    Separated from the SQL that produces the counts so the rule is testable
    without a database. `text_chars == 0` means the paper has no text at all and
    is left unjudged rather than called out of scope.
    """
    if not text_chars:
        return "unknown"
    if xist:
        return "xist"
    if phenomenon:
        return "phenomenon_only"
    return "out_of_scope"
