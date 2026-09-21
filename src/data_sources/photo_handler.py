from pathlib import Path
from src.ocr.processor import OCRProcessor
from src.utils.logger import setup_logger

logger = setup_logger("photo_handler")


class PhotoHandler:
    """Read student data from photos/images of printed forms."""

    EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

    def __init__(self, gemini_api_key: str = None, gemini_model: str = "gemini-1.5-flash"):
        self.processor = OCRProcessor(gemini_api_key=gemini_api_key, gemini_model=gemini_model)

    def find_images(self, directory: str) -> list[str]:
        """Find all image files in a directory."""
        directory = Path(directory)
        images = []
        for ext in self.EXTENSIONS:
            images.extend(directory.glob(f"*{ext}"))
            images.extend(directory.glob(f"*{ext.upper()}"))
        return sorted(str(p) for p in images)

    def process_single(self, image_path: str) -> dict:
        """Process a single photo and return student data."""
        return self.processor.process_image(image_path)

    def process_directory(self, directory: str) -> list[dict]:
        """Process all images in a directory."""
        images = self.find_images(directory)
        if not images:
            logger.warning(f"No images found in {directory}")
            return []

        logger.info(f"Found {len(images)} images in {directory}")
        return self.processor.process_batch(images)
