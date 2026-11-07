from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xist_kb.models import Claim, Confidence, EvidenceType, Paper, Status


def test_paper_minimal():
    p = Paper(
        paper_id="deng2011_abc",
        title="Xist",
        source="openalex",
        retrieved_at=datetime.now(UTC),
    )
    assert p.status is Status.REGISTERED
    assert p.species == []


def test_paper_rejects_bad_status():
    with pytest.raises(ValidationError):
        Paper(
            paper_id="x",
            title="t",
            source="openalex",
            retrieved_at=datetime.now(UTC),
            status="not_a_status",
        )


def test_claim_requires_provenance():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            paper_id="p1",
            claim="Xist coats the inactive X",
            topic="xci",
            evidence_type=EvidenceType.DIRECT_EXPERIMENTAL,
            directness="direct",
            section="results",
            confidence=Confidence.HIGH,
        )


def test_claim_accepts_optional_quote_offsets():
    c = Claim(
        claim_id="c1",
        paper_id="p1",
        claim="Xist coats the inactive X",
        topic="xci",
        evidence_type=EvidenceType.DIRECT_EXPERIMENTAL,
        directness="direct",
        section="results",
        confidence=Confidence.HIGH,
        provenance_id="prov1",
    )
    assert c.chunk_id is None
    assert c.quote_offset_start is None
