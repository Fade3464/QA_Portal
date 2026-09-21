import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PROFILE_PICTURE_BYTES = 5 * 1024 * 1024
MAX_PROFILE_PICTURE_PIXELS = 25_000_000
PROFILE_PICTURE_SIZE = 512


def replace_profile_picture(user, uploaded) -> None:
    if uploaded.size > MAX_PROFILE_PICTURE_BYTES:
        raise ValidationError({"avatar": "Profile pictures must be 5 MB or smaller."})

    Image.MAX_IMAGE_PIXELS = MAX_PROFILE_PICTURE_PIXELS
    try:
        image = Image.open(uploaded)
        image.verify()
        uploaded.seek(0)
        image = Image.open(uploaded)
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValidationError({"avatar": "Upload a JPEG, PNG, or WebP image."})
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            raise ValidationError({"avatar": "Animated profile pictures are not supported."})
        image = ImageOps.fit(
            image.convert("RGB"),
            (PROFILE_PICTURE_SIZE, PROFILE_PICTURE_SIZE),
            method=Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=88, method=6)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(
            {"avatar": "Upload a valid JPEG, PNG, or WebP image."}
        ) from exc

    old_picture = user.profile_picture
    filename = f"{user.pk}/{uuid.uuid4().hex}.webp"
    user.profile_picture.save(filename, ContentFile(output.getvalue()), save=False)
    user.save(update_fields=["profile_picture", "updated_at"])
    if old_picture and old_picture.name != user.profile_picture.name:
        old_picture.delete(save=False)
