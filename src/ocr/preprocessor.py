import cv2
import numpy as np
from pathlib import Path


def deskew(image: np.ndarray) -> np.ndarray:
    """Straighten a skewed image."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 200, minLineLength=100, maxLineGap=10)

    if lines is None:
        return image

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) < 10:
            angles.append(angle)

    if not angles:
        return image

    median_angle = np.median(angles)
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def sharpen(image: np.ndarray) -> np.ndarray:
    """Sharpen image using unsharp masking."""
    blurred = cv2.GaussianBlur(image, (0, 0), 3)
    return cv2.addWeighted(image, 1.5, blurred, -0.5, 0)


def denoise(image: np.ndarray) -> np.ndarray:
    """Remove noise from image."""
    return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)


def binarize(image: np.ndarray) -> np.ndarray:
    """Apply adaptive thresholding for binary output."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)


def preprocess_image(
    image_path: str,
    do_deskew: bool = True,
    do_sharpen: bool = True,
    do_denoise: bool = True,
    do_binarize: bool = False,
) -> np.ndarray:
    """Full preprocessing pipeline for a form image."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    if do_deskew:
        image = deskew(image)
    if do_denoise:
        image = denoise(image)
    if do_sharpen:
        image = sharpen(image)
    if do_binarize:
        image = binarize(image)

    return image


def save_preprocessed(image: np.ndarray, output_path: str) -> str:
    """Save preprocessed image to disk."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, image)
    return output_path
