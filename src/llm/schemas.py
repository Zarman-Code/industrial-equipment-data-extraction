from typing import List, Literal, Optional
from pydantic import BaseModel, Field



class SectionClassification(BaseModel):
    section_id: str
    relevance: Literal["high", "medium", "low", "none"]
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

    family: FieldExtraction

    asset_name: FieldExtraction

    reference: FieldExtraction

    power: FieldExtraction

    outlier: FieldExtraction

    manufacturer: FieldExtraction

    asset_diagram: FieldExtraction


class SectionClassification(BaseModel):
    section_id: str
    relevance: Literal["high", "medium", "low", "none"]
    reason: str
    potential_information: List[str]


class SectionClassificationResult(BaseModel):
    sections: List[SectionClassification]
    selected_sections: List[str]