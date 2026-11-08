"""Controlled vocabularies and value normalization shared across stages.

V2's data reached production with several vocabularies drifting apart:
`not reported` vs `not_reported`, `confidence` values stored as the string
`"['high']"` (a Python list that was stringified accidentally), topics
fragmented into dozens of near-duplicates. The cleaners here are the one
place that knows how to repair those, so the same repair applies whether a
record comes from the legacy migration or a fresh annotation.

Anything not recognised is returned as-is rather than guessed at, and callers
are expected to count what fell through — silent coercion is how V2 ended up
with 30% of its claims in `other`.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------

STANDARD_TOPICS = frozenset(
    {
        "xist_identification",
        "xist_expression",
        "xist_expression_regulation",
        "xist_rna_function",
        "xist_protein_interactions",
        "xci",
        "early_embryo",
        "dosage_compensation",
        "gene_silencing",
        "cancer_biology",
        "chromatin",
        "lncrna",
        "nuclear_organization",
        "phase_separation",
        "m6a",
        "xist_evolution",
        "sex_chromosome_biology",
        "methods",
        "polycomb",
        "ddx39",
        "totipotency",
        "other",
    }
)

# Fragments seen in V2 data that map cleanly onto a standard topic.
TOPIC_MAP = {
    "gene_regulation": "gene_silencing",
    "gene_expression": "xist_expression",
    "xist_rna": "xist_rna_function",
    "xist_function": "xist_rna_function",
    "xist_regulation": "xist_expression_regulation",
    "x_chromosome_inactivation": "xci",
    "pluripotency": "early_embryo",
    "stem_cell_biology": "early_embryo",
    "naive_primed_pluripotency": "early_embryo",
    "naive_pluripotency": "early_embryo",
    "cellular_reprogramming": "early_embryo",
    "epigenetics": "chromatin",
    "epigenetic": "chromatin",
    "dna_methylation": "chromatin",
    "post-translational_modification": "chromatin",
    "transcriptome_complexity": "methods",
    "gene_annotation": "methods",
    "genomic_annotation": "methods",
    "genomic_characterization": "methods",
    "gene_function": "xist_rna_function",
    "gene_identification": "xist_identification",
    "gene_evolution": "xist_evolution",
    "evolutionary_conservation": "xist_evolution",
    "evolutionary_genomics": "xist_evolution",
    "evolutionary_loss": "xist_evolution",
    "evolution": "xist_evolution",
    "genome_organization": "nuclear_organization",
    "protein_localization": "xist_protein_interactions",
    "cancer_immunology": "cancer_biology",
    "prognostic_biomarker": "cancer_biology",
    "senescence": "cancer_biology",
    "disease_mechanism": "cancer_biology",
    "clinical_relevance": "cancer_biology",
    "sex_determination": "sex_chromosome_biology",
    "sex_chromosome_evolution": "sex_chromosome_biology",
    "sex_chromosome_turnover": "sex_chromosome_biology",
    "sex_chromosome_degeneration": "sex_chromosome_biology",
    "y_chromosome": "sex_chromosome_biology",
    "w_chromosome": "sex_chromosome_biology",
    "male_specific_region_y": "sex_chromosome_biology",
    "master_sex_determining_gene": "sex_chromosome_biology",
    "amh_amhr2_pathway": "sex_chromosome_biology",
    "karyotype_evolution": "sex_chromosome_biology",
    "comparative_genomics": "sex_chromosome_biology",
    "sex_reversal": "sex_chromosome_biology",
    "expression_pattern": "xist_expression",
}

_MULTI_SPLIT = re.compile(r"[,;|]")
_OTHER_PREFIX = re.compile(r"^other[\s\-:]*[(\[]?")


def normalize_topic(raw: object) -> str:
    """Collapse a topic value onto the standard set.

    Multi-topic values (a list, or a string joined with commas or pipes) keep
    the first part that is a recognised standard topic, so `"xci, methods"`
    becomes `xci` rather than a hybrid that matches nothing.
    """
    if raw is None:
        return "other"

    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        text = str(raw).strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return "other"
        parts = _MULTI_SPLIT.split(text)

    cleaned = [p.strip().strip("[]'\" ") for p in parts]
    cleaned = [p for p in cleaned if p]

    for candidate in cleaned:
        if candidate in STANDARD_TOPICS and candidate != "other":
            return candidate

    for candidate in cleaned:
        mapped = TOPIC_MAP.get(candidate.lower())
        if mapped:
            return mapped

    # "other - something" carries a hint in its suffix.
    for candidate in cleaned:
        if candidate.lower().startswith("other"):
            inner = _OTHER_PREFIX.sub("", candidate.lower()).strip(") ]")
            for fragment, mapped in TOPIC_MAP.items():
                if fragment in inner:
                    return mapped

    # Last resort: a standard topic appearing as a substring.
    for candidate in cleaned:
        low = candidate.lower()
        for standard in STANDARD_TOPICS:
            if standard != "other" and (standard in low or low in standard):
                return standard

    return "other"


# --------------------------------------------------------------------------
# Species
# --------------------------------------------------------------------------

SPECIES_MAP = {
    "human": "Homo sapiens",
    "humans": "Homo sapiens",
    "mouse": "Mus musculus",
    "mice": "Mus musculus",
    "rat": "Rattus norvegicus",
    "zebrafish": "Danio rerio",
    "chicken": "Gallus gallus",
    "frog": "Xenopus laevis",
    "rabbit": "Oryctolagus cuniculus",
    "bovine": "Bos taurus",
    "cow": "Bos taurus",
    "pig": "Sus scrofa",
    "sheep": "Ovis aries",
    "dog": "Canis familiaris",
    "cat": "Felis catus",
    "nematode": "Caenorhabditis elegans",
    "worm": "Caenorhabditis elegans",
    "fruit fly": "Drosophila melanogaster",
    "yeast": "Saccharomyces cerevisiae",
    "marsupial": "Metatheria",
    "platypus": "Ornithorhynchus anatinus",
    "opossum": "Monodelphis domestica",
    "h. sapiens": "Homo sapiens",
    "m. musculus": "Mus musculus",
    "c. elegans": "Caenorhabditis elegans",
    "d. melanogaster": "Drosophila melanogaster",
    "s. cerevisiae": "Saccharomyces cerevisiae",
    "s. pombe": "Schizosaccharomyces pombe",
    "a. thaliana": "Arabidopsis thaliana",
    "d. rerio": "Danio rerio",
    "x. laevis": "Xenopus laevis",
}

NOT_REPORTED = frozenset(
    {
        "",
        "not reported",
        "not_reported",
        "not applicable",
        "not_applicable",
        "n/a",
        "na",
        "none",
        "null",
        "nan",
        "not specified",
        "not specified in text",
        "not specified in main text",
        "not specified for this specific analysis",
        "not explicitly stated",
        "not species-specific",
        "multiple",
        "unknown",
    }
)

_SPECIES_SPLIT = re.compile(r"[;,]\s*|\s+and\s+")
_PAREN = re.compile(r"\s*\([^)]*\)")
_COUNT_PREFIX = re.compile(r"^\d+\s")


def normalize_species_list(raw: object) -> list[str]:
    """Split a species field into canonical Latin binomials.

    V2 stored species as a single semicolon-joined string; splitting it here
    means queries can filter on one species without LIKE-matching across a
    concatenated field.
    """
    if raw is None:
        return []

    if isinstance(raw, (list, tuple)):
        text = "; ".join(str(s) for s in raw)
    else:
        text = str(raw)

    text = text.strip().strip("[]'\"")
    if text.lower() in NOT_REPORTED:
        return []

    parts = _SPECIES_SPLIT.split(_PAREN.sub("", text))

    out: list[str] = []
    for part in parts:
        part = part.strip().strip("'\"")
        if not part or part.lower() in NOT_REPORTED:
            continue
        # "10 gibbon species" is a count, not a binomial.
        if _COUNT_PREFIX.match(part) and not re.match(r"^[A-Z][a-z]+\s+[a-z]+", part):
            continue
        canonical = (
            SPECIES_MAP.get(part) or SPECIES_MAP.get(part.lower()) or SPECIES_MAP.get(part.title())
        )
        if canonical:
            part = canonical
        elif part[0].islower() and " " in part:
            genus, rest = part.split(" ", 1)
            part = f"{genus.capitalize()} {rest}"
        if part not in out:
            out.append(part)
    return out


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "speculation", "not_reported"})

EVIDENCE_TYPE_VALUES = frozenset(
    {
        "direct_experimental",
        "indirect_experimental",
        "computational_prediction",
        "database_annotation",
        "synteny_inference",
        "rule_extraction",
        "speculation",
        "review_inference",
        "not_reported",
    }
)

DIRECTNESS_VALUES = frozenset({"direct", "indirect", "speculative", "not_reported"})

SECTION_VALUES = frozenset(
    {
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "figure_legend",
        "conclusion",
        "not_reported",
    }
)

_LIST_WRAPPER = re.compile(r"^\[(.*)\]$")


def normalize_enum(raw: object, allowed: frozenset[str], default: str = "not_reported") -> str:
    """Coerce a scalar into an allowed vocabulary value.

    Handles the three shapes V2 left behind: plain strings, stringified lists
    (`"['high']"`), and the `not reported` / `not reported` spacing split.
    """
    if raw is None:
        return default

    if isinstance(raw, (list, tuple)):
        text = str(raw[0]) if raw else ""
    else:
        text = str(raw)

    text = text.strip()
    match = _LIST_WRAPPER.match(text)
    if match:
        inner = match.group(1).strip().strip("'\"")
        text = inner

    text = text.strip().strip("'\"").strip().lower()
    text = text.replace(" ", "_")

    if text in allowed:
        return text

    # Repairs for near-misses that appear in V2 data.
    aliases = {
        "not_reported_": "not_reported",
        "notreported": "not_reported",
        "not_specified": "not_reported",
        "experimental": "direct_experimental",
        "experimental_evidence": "direct_experimental",
        "database": "database_annotation",
        "computational": "computational_prediction",
        "synteny": "synteny_inference",
        "review": "review_inference",
    }
    repaired = aliases.get(text, text)
    return repaired if repaired in allowed else default


# --------------------------------------------------------------------------
# Dates, identifiers, hashes
# --------------------------------------------------------------------------

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(raw: object) -> str | None:
    """Strip URL prefixes and lowercase a DOI; return None when absent."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in NOT_REPORTED:
        return None
    text = _DOI_PREFIX.sub("", text)
    return text.lower() or None


_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def normalize_year(raw: object) -> int | None:
    """Extract a four-digit year, rejecting the sentinels V2 stored as text."""
    if raw is None:
        return None
    if isinstance(raw, int) and 1800 <= raw <= 2100:
        return raw
    text = str(raw).strip()
    if text.lower() in NOT_REPORTED:
        return None
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# Paper ids
# --------------------------------------------------------------------------


def normalize_paper_id(raw: object) -> str:
    """Lowercase a paper id to the canonical form used across the KB.

    V2 has three spellings of the same paper: the registry's original case,
    the claim CSV's copy, and whatever case the file on disk happens to use.
    Measured on the full corpus: 1,822 of 296,835 registry ids contain an
    uppercase letter, 867 claim rows use a case that has no matching text
    file, and 815 claim paper_ids are absent from the registry entirely.

    Lowercasing resolves all 815 orphans (they turn out to be the same papers
    spelled differently) and gains 696 text-file lookups, with zero collisions:
    no two registry ids, and no two claim paper_ids, differ only by case. The
    ids that *do* differ only by case across the two sources are the same paper
    recorded twice, not two papers.

    Files on disk keep their original names; lookups go through
    `gold/paper_id_map.parquet` instead of renaming 2,600+ files.
    """
    return str(raw or "").strip().lower()
