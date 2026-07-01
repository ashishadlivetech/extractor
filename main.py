import gc
import io
import logging
import os
import shutil
import sys
import time
import traceback
import platform

from dotenv import load_dotenv
load_dotenv()

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from parser import Form16Parser
from validators import Form16Validator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("form16")


# --------------------------------------------------
# AI Mode
# --------------------------------------------------

USE_AI = bool(os.getenv("GEMINI_API_KEY"))

if USE_AI:
    from ai_extractor import extract_with_ai
    log.info("[STARTUP] Google Gemini mode enabled")
else:
    log.info("[STARTUP] OCR mode enabled")


# --------------------------------------------------
# FastAPI
# --------------------------------------------------

app = FastAPI(
    title="Government Form16 Extractor",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Health
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Government Form16 Extractor",
        "mode": "Gemini AI" if USE_AI else "OCR"
    }


# --------------------------------------------------
# Debug
# --------------------------------------------------

@app.get("/debug")
def debug():

    result = {
        "mode": "Gemini AI" if USE_AI else "OCR"
    }

    packages = {}

    for pkg in [
        "pdfplumber",
        "pdf2image",
        "pytesseract",
        "google",
        "PIL"
    ]:

        try:
            module = __import__(pkg)
            packages[pkg] = getattr(module, "__version__", "Installed")

        except Exception as e:
            packages[pkg] = f"Missing ({e})"

    result["pythonPackages"] = packages

    binaries = {}

    for binary in [
        "tesseract",
        "pdftoppm"
    ]:

        path = shutil.which(binary)

        binaries[binary] = path if path else "Missing"

    result["systemBinaries"] = binaries

    result["geminiApiKey"] = bool(os.getenv("GEMINI_API_KEY"))
    result["pythonVersion"] = sys.version
    result["platform"] = platform.platform()

    return result


# --------------------------------------------------
# Detect PDF Type
# --------------------------------------------------

def is_text_based_pdf(file_bytes: bytes) -> bool:

    try:

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:

            for page in pdf.pages:

                try:

                    text = page.extract_text()

                    if text and len(text.strip()) > 20:
                        return True

                except Exception:
                    continue

    except Exception:
        return False

    return False


# --------------------------------------------------
# Extract Text Layer
# --------------------------------------------------

def extract_text_from_pdf(file_bytes: bytes) -> str:

    text = ""

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:

        for index, page in enumerate(pdf.pages):

            try:

                page_text = page.extract_text()

                if page_text:

                    log.info(
                        "[TEXT] Page %d -> %d chars",
                        index + 1,
                        len(page_text)
                    )

                    text += "\n" + page_text

                else:

                    log.warning(
                        "[TEXT] Empty page %d",
                        index + 1
                    )

            except Exception as e:

                log.error(
                    "[TEXT] Page %d failed : %s",
                    index + 1,
                    e
                )

    return text


# --------------------------------------------------
# OCR
# --------------------------------------------------

def extract_text_via_ocr(file_bytes: bytes):

    log.info("[OCR] Starting OCR...")

    start = time.time()

    try:

        pages = convert_from_bytes(
            file_bytes,
            dpi=200
        )

    except Exception as e:

        return "", str(e)

    full_text = ""

    for i, page in enumerate(pages):

        try:

            text = pytesseract.image_to_string(
                page,
                config="--psm 6"
            )

            full_text += text

            log.info(
                "[OCR] Page %d -> %d chars",
                i + 1,
                len(text)
            )

        except Exception as e:

            log.error(
                "[OCR] Page %d failed : %s",
                i + 1,
                e
            )

        finally:

            del page
            gc.collect()

    del pages
    gc.collect()

    log.info(
        "[OCR] Finished in %.2fs",
        time.time() - start
    )

    if not full_text.strip():

        return "", "OCR produced no readable text."

    return full_text, None
    

@app.post("/extract")
async def extract(file: UploadFile = File(...)):

    start = time.time()

    log.info("=" * 70)
    log.info("[REQUEST] %s", file.filename)

    try:

        # --------------------------------------------------
        # Read uploaded PDF
        # --------------------------------------------------

        file_bytes = await file.read()

        if not file_bytes:
            return {
                "success": False,
                "error": "Uploaded file is empty."
            }

        pdf_type = (
            "text-based"
            if is_text_based_pdf(file_bytes)
            else "scanned"
        )

        log.info("PDF Type : %s", pdf_type)

        extraction_mode = None
        ocr_used = False

        # ==================================================
        # TEXT PDF
        # ==================================================

        if pdf_type == "text-based":

            extraction_mode = "pdfplumber"

            text = extract_text_from_pdf(file_bytes)

            if not text.strip():

                return {
                    "success": False,
                    "error": "No readable text found."
                }

            parsed_data, validation = _parse_and_validate(text)

            return {
                "success": True,
                "filename": file.filename,
                "pdfType": pdf_type,
                "extractionMode": extraction_mode,
                "ocrUsed": False,
                "documentType": parsed_data.get("documentType"),
                "confidence": validation.get("confidence"),
                "validation": validation,
                "dynamicFields": parsed_data.get(
                    "dynamicFields",
                    {}
                ),
                "structuredData": parsed_data.get(
                    "structuredData",
                    {}
                )
            }

        # ==================================================
        # SCANNED PDF
        # ==================================================

        if USE_AI:

            extraction_mode = "gemini-pdf"

            log.info("[AI] Sending PDF to Gemini...")

            ai_data, error = extract_with_ai(file_bytes)

            if error:

                return {
                    "success": False,
                    "error": error
                }

            validation = {
                "isValid": True,
                "warnings": []
            }

            # -------------------------------
            # Basic validation
            # -------------------------------

            employee = ai_data.get("employee", {})
            employer = ai_data.get("employer", {})

            if not employee.get("pan"):
                validation["warnings"].append(
                    "Employee PAN missing."
                )

            if not employer.get("tan"):
                validation["warnings"].append(
                    "Employer TAN missing."
                )

            if not ai_data.get("assessmentYear"):
                validation["warnings"].append(
                    "Assessment Year missing."
                )

            confidence = 95

            if len(validation["warnings"]) >= 2:
                confidence = 85

            if len(validation["warnings"]) >= 4:
                confidence = 70

            log.info("[AI] Extraction completed.")

            return {

                "success": True,
                "filename": file.filename,

                "pdfType": pdf_type,

                "extractionMode": extraction_mode,

                "ocrUsed": False,

                "documentType": _detect_doc_type(ai_data),

                "confidence": confidence,

                "validation": validation,

                "structuredData": ai_data

            }

        # ==================================================
        # FALLBACK OCR
        # ==================================================

        extraction_mode = "tesseract"

        log.info("[OCR] AI disabled. Using OCR...")

        text, error = extract_text_via_ocr(file_bytes)

        if error:

            return {
                "success": False,
                "error": error
            }

        parsed_data, validation = _parse_and_validate(text)

        return {

            "success": True,

            "filename": file.filename,

            "pdfType": pdf_type,

            "extractionMode": extraction_mode,

            "ocrUsed": True,

            "documentType": parsed_data.get(
                "documentType"
            ),

            "confidence": validation.get(
                "confidence"
            ),

            "validation": validation,

            "dynamicFields": parsed_data.get(
                "dynamicFields",
                {}
            ),

            "structuredData": parsed_data.get(
                "structuredData",
                {}
            )

        }

    except Exception as e:

        log.exception(e)

        return {

            "success": False,

            "error": str(e),

            "trace": traceback.format_exc()

        }

    finally:

        log.info(
            "Completed in %.2f seconds",
            time.time() - start
        )


# --------------------------------------------------
# Parser
# --------------------------------------------------

def _parse_and_validate(text: str):

    parser = Form16Parser(text)

    parsed = parser.parse()

    validator = Form16Validator(parsed)

    validation = validator.validate()

    log.info(
        "[PARSER] %s",
        parsed.get("documentType")
    )

    return parsed, validation


# --------------------------------------------------
# Detect document type
# --------------------------------------------------

def _detect_doc_type(data: dict):

    part = str(
        data.get(
            "partType",
            ""
        )
    ).upper()

    if "PART A" in part:
        return "FORM16_PART_A"

    if "PART B" in part:
        return "FORM16_PART_B"

    if "A" == part:
        return "FORM16_PART_A"

    if "B" == part:
        return "FORM16_PART_B"

    return "FORM16"
