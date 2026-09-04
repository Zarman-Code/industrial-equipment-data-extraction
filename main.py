from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.pipeline import run_pipeline


# LOGGING
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# FASTAPI APP
app = FastAPI(
    title="PDF Information Extraction API",
    description="Three-stage PDF processing pipeline.",
    version="1.0.0",
)


# CORS
# Allows the frontend to call the backend.
# For production, replace "*" with the actual frontend URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# HEALTH CHECK
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "pdf-information-extraction",
    }


# PDF UPLOAD + PIPELINE
@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
):
    """
    Upload a PDF and run the complete pipeline.

    Flow:

        Frontend
            ↓
        POST /upload
            ↓
        Save temporary PDF
            ↓
        Stage 1: document structure
            ↓
        Stage 2: LLM section classification
            ↓
        Stage 3: information extraction
            ↓
        JSON response
    """

    # Validate filename
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No filename provided.",
        )

    filename = Path(file.filename).name

    # Validate PDF
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported.",
        )

    # Create temporary directory
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="pdf_pipeline_"
        )
    )

    pdf_path = temp_dir / filename

    try:
        # Save uploaded file
        with pdf_path.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer,
            )

        logger.info(
            "Received PDF: %s",
            filename,
        )

        # Run complete pipeline
        result = run_pipeline(
            pdf_path=pdf_path,
            max_workers=4,
            dpi=300,
            min_text_length=50,
        )

        logger.info(
            "Pipeline completed successfully: %s",
            filename,
        )

        return {
            "success": True,
            "filename": filename,
            "result": result,
        }

    except FileNotFoundError as exc:

        logger.exception(
            "PDF file not found.",
        )

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:

        logger.exception(
            "Invalid PDF or pipeline input.",
        )

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        logger.exception(
            "Pipeline failed.",
        )

        raise HTTPException(
            status_code=500,
            detail=f"PDF processing failed: {exc}",
        ) from exc

    finally:
        # Close uploaded file
        await file.close()

        # Remove temporary files
        try:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )
        except Exception:
            logger.warning(
                "Could not remove temporary directory: %s",
                temp_dir,
            )


# RUN DIRECTLY
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )