import json

from openai import OpenAI

from .config import OPENAI_API_KEY, LLM_MODEL
from .prompts import SECTION_CLASSIFICATION_PROMPT
from .schemas import SectionClassificationResult


client = OpenAI(api_key=OPENAI_API_KEY)


def classify_sections(document_sections):
    """
    Identify document sections that potentially contain
    useful equipment information.
    """

    input_json = json.dumps(
        document_sections,
        ensure_ascii=False,
        indent=2
    )

    prompt = SECTION_CLASSIFICATION_PROMPT.replace(
        "{{INPUT_JSON}}",
        input_json
    )

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": SECTION_CLASSIFICATION_PROMPT
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content

    return SectionClassificationResult.model_validate_json(content)