from pathlib import Path
from src.ocr.preprocessor import preprocess_image, save_preprocessed
from src.ocr.gemini_client import GeminiClient
from src.utils.logger import setup_logger
import tempfile

logger = setup_logger("ocr_processor")


class OCRProcessor:
    """End-to-end OCR pipeline: image -> preprocess -> Gemini -> structured data."""

    def __init__(self, gemini_api_key: str = None, gemini_model: str = "gemini-3.5-flash"):
        self.client = GeminiClient(api_key=gemini_api_key, model=gemini_model)

    def process_image(self, image_path: str, preprocess: bool = True) -> dict:
        """Process a single form image and return extracted student data."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info(f"Processing image: {image_path.name}")

        if preprocess:
            logger.info("Preprocessing image (deskew, denoise, sharpen)...")
            processed = preprocess_image(
                str(image_path),
                do_deskew=True,
                do_sharpen=True,
                do_denoise=True,
            )
            tmp_dir = Path(tempfile.mkdtemp())
            processed_path = tmp_dir / f"processed_{image_path.name}"
            save_preprocessed(processed, str(processed_path))
            logger.info(f"Saved preprocessed image: {processed_path}")
        else:
            processed_path = image_path

        logger.info("Sending to Gemini Vision API for extraction...")
        data = self.client.extract_student_data(str(processed_path))

        non_null = {k: v for k, v in data.items() if v is not None}
        logger.info(f"Extracted {len(non_null)} fields from {image_path.name}")

        return data

    def process_batch(self, image_paths: list[str], preprocess: bool = True) -> list[dict]:
        """Process multiple form images."""
        results = []
        for path in image_paths:
            try:
                data = self.process_image(path, preprocess=preprocess)
                data["_source_file"] = str(path)
                data["_status"] = "success"
                results.append(data)
            except Exception as e:
                logger.error(f"Failed to process {path}: {e}")
                results.append({"_source_file": str(path), "_status": "error", "_error": str(e)})
        return results
