import fitz  # PyMuPDF
import pdfplumber
import io
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PDFExtractor")

class PDFExtractor:
    @staticmethod
    def extract_text_from_bytes(pdf_bytes: bytes) -> str:
        """
        Extracts plain text from raw PDF bytes.
        Uses PyMuPDF primary engine with fallback to pdfplumber for complex layouts.
        """
        text = ""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                page_text = page.get_text("text")
                if page_text:
                    text += page_text + "\n"
            doc.close()
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed: {str(e)}. Falling back to pdfplumber.")

        # Fallback to pdfplumber if PyMuPDF returned no text (scanned or complex vector PDF)
        if not text.strip():
            try:
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    for page in pdf.pages:
                        extracted = page.extract_text()
                        if extracted:
                            text += extracted + "\n"
            except Exception as e:
                logger.error(f"pdfplumber extraction also failed: {str(e)}")

        return text.strip()