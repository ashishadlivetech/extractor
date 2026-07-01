"""
Google Gemini AI Form 16 Extractor

Workflow

PDF
   │
   ▼
Gemini 2.5 Flash
   │
   ▼
JSON
   │
   ▼
main.py

No OCR.
No pdf2image.
No page splitting.
Gemini reads the PDF directly.
"""

import json
import logging
import os
import re

from google import genai
from google.genai import types

log = logging.getLogger("form16")

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

EXTRACTION_PROMPT = """
You are an expert at reading Indian Income Tax Form 16 documents.

The uploaded file is a PDF.

It may contain:

- Part A
- Part B
- Both Part A and Part B

Read EVERY page before answering.

Merge all information into ONE JSON object.

Rules:

- Return ONLY JSON.
- Never return markdown.
- Never explain.
- Missing values must be null.
- Preserve numbers exactly.
- Preserve PAN/TAN exactly.

Return exactly this structure:

{
  "certificateNo": null,
  "assessmentYear": null,
  "periodFrom": null,
  "periodTo": null,

  "employer": {
    "name": null,
    "pan": null,
    "tan": null,
    "address": null
  },

  "employee": {
    "name": null,
    "pan": null,
    "address": null
  },

  "salary": {
    "grossSalary17_1": null,
    "perquisites17_2": null,
    "profits17_3": null,
    "totalGross": null,
    "standardDeduction": null,
    "incomeChargeable": null,
    "totalTaxableIncome": null
  },

  "taxes": {
    "taxOnIncome": null,
    "healthEducationCess": null,
    "taxPayable": null,
    "netTaxPayable": null,
    "totalTaxDeducted": null,
    "totalTaxDeposited": null
  },

  "quarterly": [
    {
      "quarter":"Q1",
      "receiptNo":null,
      "amountPaid":null,
      "taxDeducted":null,
      "taxDeposited":null
    },
    {
      "quarter":"Q2",
      "receiptNo":null,
      "amountPaid":null,
      "taxDeducted":null,
      "taxDeposited":null
    },
    {
      "quarter":"Q3",
      "receiptNo":null,
      "amountPaid":null,
      "taxDeducted":null,
      "taxDeposited":null
    },
    {
      "quarter":"Q4",
      "receiptNo":null,
      "amountPaid":null,
      "taxDeducted":null,
      "taxDeposited":null
    }
  ],

  "deductions80C": null,
  "deductions80D": null,

  "partType": null
}
"""


def extract_with_ai(file_bytes: bytes):
    """
    Sends the whole PDF directly to Gemini.
    Returns:
        (dict, None)
    or
        (None, error_string)
    """

    log.info("[AI] Sending PDF to Gemini...")

    try:

        response = client.models.generate_content(

            model="gemini-2.5-flash-lite",

            contents=[
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type="application/pdf",
                ),
                EXTRACTION_PROMPT,
            ],

            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        if not response.text:
            return None, "Gemini returned an empty response."

        raw = response.text.strip()

        # response_mime_type="application/json" should already give clean
        # JSON, but keep the fence-strip as a safety net in case the model
        # still wraps it in markdown.
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        log.info("[AI] Gemini extraction successful")

        return data, None

    except json.JSONDecodeError as e:

        log.error("Invalid JSON returned by Gemini")

        return None, (
            f"Gemini returned invalid JSON.\n\n"
            f"Error: {e}\n\n"
            f"Response:\n{raw}"
        )

    except Exception as e:

        log.exception("Gemini extraction failed")

        return None, str(e)