import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

LLM_MODEL = "gpt-4o-mini"
ENABLE_LLM = True

if ENABLE_LLM and not OPENAI_API_KEY:
    raise ValueError(
        "OPENAI_API_KEY is not configured."
    )