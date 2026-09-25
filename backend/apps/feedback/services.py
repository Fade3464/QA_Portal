import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FEEDBACK_IMAGES = 3
MAX_FEEDBACK_IMAGE_BYTES = 3 * 1024 * 1024
MAX_FEEDBACK_IMAGE_PIXELS = 30_000_000
MAX_FEEDBACK_IMAGE_DIMENSION = 2400


def prepare_feedback_image(uploaded):
    if uploaded.size > MAX_FEEDBACK_IMAGE_BYTES:
        raise ValidationError(
            {"images": "Each feedback image must be 3 MB or smaller."}
        )

    Image.MAX_IMAGE_PIXELS = MAX_FEEDBACK_IMAGE_PIXELS
    try:
        image = Image.open(uploaded)
        image.verify()
        uploaded.seek(0)
        image = Image.open(uploaded)
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValidationError(
                {"images": "Upload JPEG, PNG, or WebP images only."}
            )
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            raise ValidationError(
                {"images": "Animated feedback images are not supported."}
            )
        image = image.convert("RGB")
        image.thumbnail(
            (MAX_FEEDBACK_IMAGE_DIMENSION, MAX_FEEDBACK_IMAGE_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=86, method=6)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(
            {"images": "Upload valid JPEG, PNG, or WebP images."}
        ) from exc

    filename = f"{uuid.uuid4().hex}.webp"
    return filename, ContentFile(output.getvalue())
