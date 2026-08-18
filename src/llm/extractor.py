import json
from openai import OpenAI

from .config import OPENAI_API_KEY, LLM_MODEL, ENABLE_LLM
from .schemas import LLMExtraction
from .prompts import LLM_INSTRUCTIONS


client = OpenAI(api_key=OPENAI_API_KEY)


def get_text(result):
    """
    Accept either:
    - a string
    - a dictionary containing a 'text' field
    """

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        return result.get("text", "")

    return ""


def extract_with_llm(native_result, ocr_result, table_result):

    if not ENABLE_LLM:
        return {
            "method": "llm",
            "called": False,
            "message": "LLM disabled"
        }

    # Extract text
    native_text = get_text(native_result)
    ocr_text = get_text(ocr_result)

    # Extract tables
    tables = []

    if isinstance(table_result, dict):

        for table in table_result.get("tables", []):

            if hasattr(table, "fillna"):

                tables.append(
                    table
                    .fillna("")
                    .to_dict("records")
                )

            elif isinstance(table, dict):

                tables.append(table)

    # Build payload
    payload = {
        "native_text": native_text,
        "ocr_text": ocr_text,
        "tables": tables
    }

    # Call OpenAI with structured output
    try:

        response = client.beta.chat.completions.parse(

            model=LLM_MODEL,

            messages=[
                {
                    "role": "system",
                    "content": LLM_INSTRUCTIONS
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False
                    )
                }
            ],

            response_format=LLMExtraction
        )

        # Pydantic object
        parsed_result = response.choices[0].message.parsed

        return {
            "method": "llm",
            "called": True,
            "result": parsed_result.model_dump()
        }

    except Exception as e:

        return {
            "method": "llm",
            "called": False,
            "error": str(e)
        }