from typing import Optional

from pydantic import BaseModel, Field


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