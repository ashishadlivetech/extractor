FROM python:3.11-slim

# -------------------------------------------------------
# ALL system packages that ocrmypdf + pdfplumber need.
# If ANY of these are missing, scanned PDF processing breaks.
#   tesseract-ocr        → the actual OCR engine
#   tesseract-ocr-eng    → English language model (REQUIRED)
#   poppler-utils        → pdftoppm, pdfinfo used by pdfplumber + ocrmypdf
#   ghostscript          → used by ocrmypdf for PDF operations
#   pngquant             → used by ocrmypdf for image compression
#   libglib2.0-0         → required by Pillow in headless containers
# -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    ghostscript \
    pngquant \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && tesseract --version \
    && tesseract --list-langs \
    && pdftoppm -v 2>&1 | head -1 \
    && gs --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", \
     "--bind", "0.0.0.0:10000", \
     "--timeout", "300"]
