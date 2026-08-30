import json

from openai import OpenAI

from .config import OPENAI_API_KEY, LLM_MODEL
from .prompts import SECTION_CLASSIFICATION_PROMPT
from .schemas import SectionClassificationResult


# See src/llm/extractor.py for why a placeholder key is used when
# OPENAI_API_KEY is not configured (avoids crashing at import time).
client = OpenAI(api_key=OPENAI_API_KEY or "sk-disabled-placeholder")


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

    # BUGFIX: the substituted prompt (with the real input JSON) must be
    # the one actually sent to the model. Previously this variable was
    # computed but never used, so the model only ever saw the raw
    # template ending in the literal, unsubstituted "{{INPUT_JSON}}"
    # placeholder - i.e. it never received the document sections at
    # all, which is why its replies didn't match SectionClassificationResult.
    prompt = SECTION_CLASSIFICATION_PROMPT.replace(
        "{{INPUT_JSON}}",
        input_json
    )

    # BUGFIX: use the structured-outputs API (same pattern as
    # src/llm/extractor.py) so the response is guaranteed to match
    # SectionClassificationResult, instead of manually calling
    # model_validate_json() on free-form text that may include
    # markdown fences, missing fields, etc.
    response = client.beta.chat.completions.parse(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": prompt
            }
        ],
        temperature=0,
        response_format=SectionClassificationResult
    )

    return response.choices[0].message.parsed
