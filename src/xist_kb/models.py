"""Pydantic models shared across ingest, annotate, build and query.

These models are the contract between pipeline stages: anything written to
Parquet must validate against them, so a schema drift fails at write time
instead of surfacing as a confusing query error weeks later.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Status(StrEnum):
    REGISTERED = "registered"  # metadata only
    TEXT_AVAILABLE = "text_available"  # full text extracted
    ANNOTATED = "annotated"  # claims extracted
    REVIEWED = "reviewed"  # human-verified


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SPECULATION = "speculation"


class EvidenceType(StrEnum):
    DIRECT_EXPERIMENTAL = "direct_experimental"
    INDIRECT_EXPERIMENTAL = "indirect_experimental"
    COMPUTATIONAL_PREDICTION = "computational_prediction"
    DATABASE_ANNOTATION = "database_annotation"
    SYNTHENY_INFERENCE = "synteny_inference"
    RULE_EXTRACTION = "rule_extraction"
    SPECULATION = "speculation"


class Directness(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    SPECULATIVE = "speculative"


class AnnotationMethod(StrEnum):
    LLM = "llm"
    RULE = "rule"
    MANUAL = "manual"


class Paper(BaseModel):
    paper_id: str
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None
    title: str
    abstract: str | None = None
    year: int | None = None
    journal: str | None = None
    first_author: str | None = None
    authors: list[str] = Field(default_factory=list)
    species: list[str] = Field(default_factory=list)
    taxonomic_group: str | None = None
    status: Status = Status.REGISTERED
    has_text: bool = False
    has_pdf: bool = False
    source: str
    retrieved_at: datetime


class Chunk(BaseModel):
    chunk_id: str  # "{paper_id}:{offset_start}"
    paper_id: str
    text: str
    offset_start: int
    offset_end: int
    section: str | None = None
    paragraph_index: int


class Provenance(BaseModel):
    provenance_id: str
    paper_id: str
    method: AnnotationMethod
    model: str | None = None
    prompt_template: str | None = None
    prompt_hash: str | None = None
    runtime_seconds: float | None = None
    created_at: datetime
    source_checksum: str  # sha256 of input text; guards against stale annotations


class Claim(BaseModel):
    claim_id: str
    paper_id: str
    chunk_id: str | None = None
    quote: str | None = None
    quote_offset_start: int | None = None
    quote_offset_end: int | None = None
    claim: str
    topic: str
    evidence_type: EvidenceType
    directness: Directness
    section: str
    species: list[str] = Field(default_factory=list)
    cell_type: str | None = None
    confidence: Confidence
    caveat: str | None = None
    provenance_id: str


class Citation(BaseModel):
    source_paper_id: str
    target_paper_id: str | None = None
    target_doi: str | None = None
    direction: str  # "cites" | "cited_by"
    source_db: str
    retrieved_at: datetime


class Interactor(BaseModel):
    paper_id: str
    protein: str
    xist_domain: str | None = None
    method: str | None = None
    function: str | None = None
    species: list[str] = Field(default_factory=list)
    cell_type: str | None = None
    direct_or_indirect: str | None = None
    confidence: Confidence
    claim_id: str | None = None
    provenance_id: str | None = None


class Regulation(BaseModel):
    paper_id: str
    regulator: str
    target: str = "XIST"
    direction: str | None = None
    species: list[str] = Field(default_factory=list)
    cell_type: str | None = None
    developmental_stage: str | None = None
    evidence_type: EvidenceType | None = None
    directness: Directness | None = None
    confidence: Confidence
    claim_id: str | None = None
    provenance_id: str | None = None


class XciStatus(BaseModel):
    paper_id: str
    species: list[str] = Field(default_factory=list)
    cell_type: str | None = None
    developmental_stage: str | None = None
    xci_type: str | None = None
    xist_status: str | None = None
    chromatin_marks: list[str] = Field(default_factory=list)
    confidence: Confidence
    claim_id: str | None = None
    provenance_id: str | None = None


class SpeciesXist(BaseModel):
    paper_id: str
    species: str
    taxonomic_group: str | None = None
    xist_reported: bool | None = None
    confidence: Confidence
    experimental_validation: str | None = None
    synteny_evidence: str | None = None
    claim_id: str | None = None
    provenance_id: str | None = None
