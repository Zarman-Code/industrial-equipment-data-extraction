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


def extract_with_llm(payload):

    if not ENABLE_LLM:
        return {
            "method": "llm",
            "called": False,
            "message": "LLM disabled"
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