from typing import List, Optional
from pydantic import BaseModel, Field


class SectionClassification(BaseModel):
    section_id: str

    relevance_score: int = Field(
        ge=0,
        le=100,
        description="Estimated probability (0-100) that this section "
        "contains information relevant to equipment extraction.",
    )

    reason: str
    potential_information: List[str]


class SectionClassificationResult(BaseModel):
    sections: List[SectionClassification]
    selected_sections: List[str]


class FieldExtraction(BaseModel):

    value: Optional[str] = None

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0
    )

    page: Optional[int] = None


class LLMExtraction(BaseModel):
    """
    Single-equipment extraction result (LLM #2, single-machine form).

    Kept for backward compatibility / single-machine callers. For
    documents that may contain several machines, use
    `MachineExtractionResult` below instead.
    """

    family: FieldExtraction

    asset_name: FieldExtraction

    reference: FieldExtraction

    power: FieldExtraction

    outlier: FieldExtraction

    manufacturer: FieldExtraction

    asset_diagram: FieldExtraction


class MachineFields(LLMExtraction):
    """Identical field set to LLMExtraction; named separately so a machine's
    field bundle reads clearly inside MachineExtraction."""


class MachineExtraction(BaseModel):
    """One machine detected in the document, with its i-Sense-relevant fields."""

    machine_id: str
    name: Optional[str] = Field(
        default=None,
        description="Short human-readable label for this machine, e.g. 'Pump P-101'. "
        "May be null if no distinguishing name/tag was found.",
    )
    fields: MachineFields


class MachineExtractionResult(BaseModel):
    """
    LLM #2 output when a document may describe multiple machines.

    The model must never merge data belonging to two different
    machines into a single entry.
    """

    machines: List[MachineExtraction]
