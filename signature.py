"""
Signature Studio Pro

requirements.txt:
streamlit
pillow
numpy
google-genai>=1.0.0
python-docx
stripe

Streamlit Cloud secrets:
GEMINI_API_KEY = ""
GEMINI_MODEL = "gemini-3.1-flash-image-preview"
APP_NAME = "Signature Studio Pro"
STRIPE_SECRET_KEY = ""
STRIPE_PRICE_ID_SIGNATURE = ""
PAYPAL_EMAIL = "mampadif@gmail.com"
PAYPAL_PAYMENT_URL = "https://www.paypal.com/paypalme/YOURNAME/3.99"
APP_URL = "https://signature-studio.streamlit.app/"
UNLOCK_CODE = ""
PRICE_DISPLAY = "$3.99"
MAX_AI_CALLS_PER_SESSION = 3
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, PngImagePlugin

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

try:
    from docx import Document
    from docx.shared import Inches
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False


# =========================================================
# CONFIG
# =========================================================

@dataclass
class AppConfig:
    api_key: str
    ai_model: str
    app_name: str
    max_ai_calls_per_session: int
    stripe_secret_key: str
    stripe_price_id_signature: str
    paypal_email: str
    paypal_payment_url: str
    app_url: str
    unlock_code: str
    price_display: str


def load_config() -> AppConfig:
    return AppConfig(
        api_key=st.secrets.get("GEMINI_API_KEY", ""),
        ai_model=st.secrets.get("GEMINI_MODEL", "gemini-3.1-flash-image-preview"),
        app_name=st.secrets.get("APP_NAME", "Signature Studio Pro"),
        max_ai_calls_per_session=int(st.secrets.get("MAX_AI_CALLS_PER_SESSION", 3)),
        stripe_secret_key=st.secrets.get("STRIPE_SECRET_KEY", ""),
        stripe_price_id_signature=st.secrets.get("STRIPE_PRICE_ID_SIGNATURE", ""),
        paypal_email=st.secrets.get("PAYPAL_EMAIL", ""),
        paypal_payment_url=st.secrets.get("PAYPAL_PAYMENT_URL", ""),
        app_url=st.secrets.get("APP_URL", ""),
        unlock_code=st.secrets.get("UNLOCK_CODE", ""),
        price_display=st.secrets.get("PRICE_DISPLAY", "$3.99"),
    )


CONFIG = load_config()


# =========================================================
# STREAMLIT SETUP
# =========================================================

st.set_page_config(
    page_title=CONFIG.app_name,
    page_icon="🖊️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DEFAULT_SESSION_KEYS = {
    "paid": False,
    "ai_calls_used": 0,
    "final_clean_rgba": None,
    "method_used": None,
    "quality_reason": None,
    "validation_status": None,
}

for key, value in DEFAULT_SESSION_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# PAYMENT
# =========================================================

def verify_card_payment_from_query() -> bool:
    if not STRIPE_AVAILABLE:
        return False

    paid_flag = st.query_params.get("paid")
    session_id = st.query_params.get("session_id")

    if paid_flag != "1" or not session_id:
        return False

    if not CONFIG.stripe_secret_key:
        return False

    try:
        stripe.api_key = CONFIG.stripe_secret_key
        session = stripe.checkout.Session.retrieve(session_id)
        return session.payment_status == "paid"
    except Exception:
        return False


def create_card_checkout_url() -> str | None:
    if not STRIPE_AVAILABLE:
        return None

    if not CONFIG.stripe_secret_key or not CONFIG.stripe_price_id_signature or not CONFIG.app_url:
        return None

    try:
        stripe.api_key = CONFIG.stripe_secret_key

        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price": CONFIG.stripe_price_id_signature,
                    "quantity": 1,
                }
            ],
            success_url=f"{CONFIG.app_url}?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CONFIG.app_url}?cancelled=1",
        )

        return session.url

    except Exception:
        return None


if verify_card_payment_from_query():
    st.session_state.paid = True


# =========================================================
# CSS
# =========================================================

st.markdown("""
<style>
.block-container {
    max-width: 1100px;
    padding-top: 1.1rem;
    padding-bottom: 2rem;
}
.hero {
    padding: 2rem;
    border-radius: 28px;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 45%, #334155 100%);
    color: white;
    margin-bottom: 1rem;
    box-shadow: 0 18px 55px rgba(15,23,42,0.24);
}
.hero h1 {
    margin: 0 0 0.5rem 0;
    font-size: 2.35rem;
    font-weight: 800;
}
.hero p {
    margin: 0;
    color: rgba(255,255,255,0.88);
    line-height: 1.6;
}
.guide-box {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #7C3AED;
    padding: 1rem;
    border-radius: 14px;
    margin-bottom: 1rem;
    color: #334155;
}
.result-card {
    background: white;
    border: 1px solid #EAECF0;
    border-radius: 22px;
    padding: 1.25rem;
    box-shadow: 0 10px 28px rgba(16,24,40,0.06);
    text-align: center;
}
.payment-card {
    margin-top: 1.25rem;
    padding: 1.35rem;
    border-radius: 24px;
    background: linear-gradient(135deg, #fff7ed 0%, #fffbeb 100%);
    border: 1px solid #fed7aa;
    box-shadow: 0 10px 26px rgba(154,52,18,0.08);
    text-align: left;
}
.payment-card h3 {
    color: #9a3412;
    margin: 0 0 0.45rem 0;
}
.payment-card p {
    color: #7c2d12;
    margin: 0 0 1rem 0;
    line-height: 1.55;
}
.payment-options {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-top: 1rem;
    margin-bottom: 1rem;
}
.payment-btn {
    display: inline-block;
    background: linear-gradient(90deg, #111827 0%, #374151 100%);
    color: white !important;
    padding: 0.85rem 1.15rem;
    border-radius: 999px;
    text-decoration: none !important;
    font-weight: 800;
    font-size: 0.98rem;
    text-align: center;
}
.payment-btn:hover {
    background: linear-gradient(90deg, #1f2937 0%, #4b5563 100%);
    color: white !important;
    text-decoration: none !important;
}
.paypal-btn {
    display: inline-block;
    background: linear-gradient(90deg, #0070ba 0%, #003087 100%);
    color: white !important;
    padding: 0.85rem 1.15rem;
    border-radius: 999px;
    text-decoration: none !important;
    font-weight: 800;
    font-size: 0.98rem;
    text-align: center;
}
.paypal-btn:hover {
    background: linear-gradient(90deg, #009cde 0%, #005ea6 100%);
    color: white !important;
    text-decoration: none !important;
}
.payment-secondary {
    color: #9a3412;
    font-size: 0.9rem;
    margin-top: 0.8rem;
}
.footer-note {
    text-align: center;
    color: #667085;
    font-size: 0.9rem;
    margin-top: 1.2rem;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# AI CLIENT
# =========================================================

def get_ai_client():
    if not CONFIG.api_key:
        raise RuntimeError("Enhanced cleanup is not configured.")

    if st.session_state.ai_calls_used >= CONFIG.max_ai_calls_per_session:
        raise RuntimeError("Enhanced cleanup session limit reached.")

    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "google-genai package missing. Add 'google-genai>=1.0.0' to requirements.txt."
        ) from e

    return genai.Client(api_key=CONFIG.api_key)


def increment_ai_usage() -> None:
    st.session_state.ai_calls_used += 1


# =========================================================
# IMAGE HELPERS
# =========================================================

def ensure_pil_image(obj) -> Image.Image:
    if isinstance(obj, Image.Image):
        return obj.convert("RGBA")

    if hasattr(obj, "convert"):
        return obj.convert("RGBA")

    raise TypeError(f"Unsupported image object returned: {type(obj)}")


def fix_image_orientation(image: Image.Image) -> Image.Image:
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def make_upload_preview(image: Image.Image, max_size: int = 420) -> Image.Image:
    preview = image.copy()
    preview.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return preview


def smart_resize_for_processing(image: Image.Image, max_pixels: int = 2400) -> Image.Image:
    width, height = image.size

    if max(width, height) <= max_pixels:
        return image.copy()

    ratio = max_pixels / max(width, height)
    return image.resize(
        (int(width * ratio), int(height * ratio)),
        Image.Resampling.LANCZOS,
    )


def connected_components(mask):
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            stack = [(y, x)]
            visited[y, x] = True
            pixels = []

            while stack:
                cy, cx = stack.pop()
                pixels.append((cy, cx))

                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if 0 <= ny < height and 0 <= nx < width:
                            if mask[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((ny, nx))

            components.append(pixels)

    return components


def validate_upload_quality(image: Image.Image) -> Tuple[bool, str]:
    if not HAS_NUMPY:
        return True, "Validation skipped because NumPy is unavailable."

    img = image.convert("RGB")
    arr = np.array(img, dtype=np.uint8)

    h, w, _ = arr.shape

    if w < 250 or h < 250:
        return False, "Image is too small. Please upload a clearer, larger photo."

    gray = (
        0.299 * arr[:, :, 0]
        + 0.587 * arr[:, :, 1]
        + 0.114 * arr[:, :, 2]
    ).astype(np.uint8)

    dark_ratio = float((gray < 80).sum()) / max(1, w * h)
    ink_ratio = float((gray < 170).sum()) / max(1, w * h)
    contrast = int(gray.max()) - int(gray.min())

    if dark_ratio > 0.15:
        return False, (
            "The photo contains a large dark object or shadow. "
            "Retake the photo with only white paper and the signature in frame."
        )

    if ink_ratio < 0.0003:
        return False, (
            "The signature appears too small or too faint. "
            "Move closer and use a darker pen."
        )

    if contrast < 45:
        return False, (
            "The image contrast is too low. Use darker ink and brighter lighting."
        )

    return True, "Upload quality looks acceptable."


def detect_signature_bbox(
    image: Image.Image,
    darkness_threshold: int = 170,
    padding: int = 35,
) -> Image.Image:
    image = image.convert("RGB")

    if not HAS_NUMPY:
        return image.copy()

    arr = np.array(image, dtype=np.uint8)
    gray = (
        0.299 * arr[:, :, 0]
        + 0.587 * arr[:, :, 1]
        + 0.114 * arr[:, :, 2]
    ).astype(np.uint8)

    mask = gray < darkness_threshold
    h, w = mask.shape

    components = connected_components(mask)
    candidates = []

    for pixels in components:
        if len(pixels) < 20:
            continue

        ys = [p[0] for p in pixels]
        xs = [p[1] for p in pixels]

        y1, y2 = min(ys), max(ys)
        x1, x2 = min(xs), max(xs)

        comp_w = x2 - x1 + 1
        comp_h = y2 - y1 + 1
        box_area = max(1, comp_w * comp_h)
        fill_ratio = len(pixels) / box_area

        touches_border = (
            x1 <= 3 or y1 <= 3 or
            x2 >= w - 4 or y2 >= h - 4
        )

        too_large = box_area > (w * h * 0.08)
        too_solid = fill_ratio > 0.45

        if touches_border or too_large or too_solid:
            continue

        aspect = comp_w / max(1, comp_h)
        score = len(pixels)

        if aspect > 1.0:
            score *= 1.4

        if comp_w < 20 or comp_h < 8:
            continue

        candidates.append((score, pixels))

    if not candidates:
        return image.copy()

    best_pixels = max(candidates, key=lambda item: item[0])[1]

    ys = [p[0] for p in best_pixels]
    xs = [p[1] for p in best_pixels]

    y1, y2 = min(ys), max(ys)
    x1, x2 = min(xs), max(xs)

    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)

    return image.crop((x1, y1, x2, y2))


def enhance_crop_before_ai(image: Image.Image, min_width: int = 1200) -> Image.Image:
    img = image.convert("RGB")

    if img.width < min_width:
        ratio = min_width / max(1, img.width)
        img = img.resize(
            (int(img.width * ratio), int(img.height * ratio)),
            Image.Resampling.LANCZOS,
        )

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def create_checkerboard_bg(size: tuple[int, int], square_size: int = 16) -> Image.Image:
    bg = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(bg)

    light = (242, 244, 247, 255)
    dark = (222, 226, 231, 255)

    for y in range(0, size[1], square_size):
        for x in range(0, size[0], square_size):
            fill = light if ((x // square_size + y // square_size) % 2 == 0) else dark
            draw.rectangle([x, y, x + square_size, y + square_size], fill=fill)

    return bg


def preview_transparent_image(sig_img: Image.Image) -> Image.Image:
    sig_img = sig_img.convert("RGBA")
    bg = create_checkerboard_bg(sig_img.size)
    out = bg.copy()
    out.paste(sig_img, (0, 0), sig_img)
    return out


# =========================================================
# TRANSPARENCY + CLEANUP
# =========================================================

def white_to_transparent_soft(
    image: Image.Image,
    threshold: int = 248,
    softness: int = 18,
) -> Image.Image:
    image = ensure_pil_image(image)
    soft_start = max(0, threshold - softness)

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        brightness = arr[:, :, :3].mean(axis=2)

        alpha = np.where(
            brightness >= threshold,
            0,
            np.where(
                brightness <= soft_start,
                255,
                ((threshold - brightness) / max(1, threshold - soft_start) * 255),
            ),
        ).astype(np.uint8)

        arr[:, :, 3] = alpha

        ink = alpha > 0
        arr[ink, 0] = np.minimum(arr[ink, 0], 20)
        arr[ink, 1] = np.minimum(arr[ink, 1], 20)
        arr[ink, 2] = np.minimum(arr[ink, 2], 20)

        return Image.fromarray(arr, mode="RGBA")

    return image


def remove_small_noise(image: Image.Image, alpha_cutoff: int = 25) -> Image.Image:
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3]

        alpha[alpha < alpha_cutoff] = 0
        arr[:, :, 3] = alpha

        ink = alpha > 0
        arr[ink, 0] = np.minimum(arr[ink, 0], 20)
        arr[ink, 1] = np.minimum(arr[ink, 1], 20)
        arr[ink, 2] = np.minimum(arr[ink, 2], 20)

        return Image.fromarray(arr, mode="RGBA")

    return image


def keep_signature_cluster_only(
    image: Image.Image,
    min_area: int = 20,
    margin: int = 45,
) -> Image.Image:
    image = image.convert("RGBA")

    if not HAS_NUMPY:
        return image

    arr = np.array(image, dtype=np.uint8)
    alpha = arr[:, :, 3]
    mask = alpha > 0

    components = connected_components(mask)
    components = [c for c in components if len(c) >= min_area]

    if not components:
        return image

    main = max(components, key=len)

    main_ys = [p[0] for p in main]
    main_xs = [p[1] for p in main]

    main_y1, main_y2 = min(main_ys), max(main_ys)
    main_x1, main_x2 = min(main_xs), max(main_xs)

    keep = np.zeros_like(mask, dtype=bool)

    for comp in components:
        ys = [p[0] for p in comp]
        xs = [p[1] for p in comp]

        y1, y2 = min(ys), max(ys)
        x1, x2 = min(xs), max(xs)

        close_to_main = not (
            x2 < main_x1 - margin or
            x1 > main_x2 + margin or
            y2 < main_y1 - margin or
            y1 > main_y2 + margin
        )

        if close_to_main:
            for y, x in comp:
                keep[y, x] = True

    arr[~keep, 3] = 0
    return Image.fromarray(arr, mode="RGBA")


def tight_crop_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()

    if not bbox:
        return image

    left, top, right, bottom = bbox

    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)

    return image.crop((left, top, right, bottom))


def center_signature_canvas(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()

    if not bbox:
        return image

    cropped = image.crop(bbox)
    canvas = Image.new("RGBA", cropped.size, (0, 0, 0, 0))
    canvas.paste(cropped, (0, 0), cropped)
    return canvas


def resize_signature_only(
    image: Image.Image,
    max_width: int = 700,
    max_height: int = 240,
) -> Image.Image:
    img = image.copy()
    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return img


def finalize_signature_only(image: Image.Image) -> Image.Image:
    image = ensure_pil_image(image)

    image = remove_small_noise(image, alpha_cutoff=25)
    image = keep_signature_cluster_only(image, min_area=20, margin=45)

    image = tight_crop_alpha(image, padding=10)
    image = center_signature_canvas(image)

    image = resize_signature_only(image, max_width=700, max_height=240)

    image = remove_small_noise(image, alpha_cutoff=18)
    image = keep_signature_cluster_only(image, min_area=12, margin=35)

    image = tight_crop_alpha(image, padding=8)
    image = center_signature_canvas(image)

    return image


def score_output_quality(image: Image.Image) -> Tuple[bool, str]:
    if not HAS_NUMPY:
        return True, "Output quality check skipped."

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    alpha = arr[:, :, 3]
    mask = alpha > 0

    visible_pixels = int(mask.sum())
    total = image.width * image.height

    if visible_pixels < 80:
        return False, "Too little signature ink was detected."

    fill_ratio = visible_pixels / max(1, total)

    if fill_ratio > 0.35:
        return False, (
            "The output contains too much dark content and looks like noise or a shadow, "
            "not a clean signature."
        )

    components = connected_components(mask)
    useful_components = [c for c in components if len(c) >= 8]

    if len(useful_components) > 15:
        return False, (
            "The output contains too many disconnected ink fragments. "
            "This usually means the photo has shadows, paper texture, or dark objects."
        )

    largest = max(useful_components, key=len) if useful_components else []
    largest_ratio = len(largest) / max(1, visible_pixels)

    if largest_ratio < 0.45:
        return False, (
            "The detected ink is scattered instead of forming one clear signature. "
            "Please retake the photo closer to the signature."
        )

    if image.width > 900 or image.height > 350:
        return False, "The output is too large and may include background artifacts."

    return True, "Output quality passed."


# =========================================================
# ENHANCED EXTRACTION
# =========================================================

def ask_ai_extract_signature_only(
    cropped_image: Image.Image,
    model_name: str,
) -> Image.Image:
    client = get_ai_client()

    prompt = """
Extract ONLY the handwritten signature ink from this image.

Create a clean signature asset:
- Keep only the signature strokes.
- Remove all paper, texture, shadows, background, lighting, and noise.
- Recreate the signature as clean black ink.
- Preserve the original signature shape, stroke path, proportions, and angle.
- Do not add new flourishes.
- Do not transform it into another handwriting style.
- Do not include any page, rectangle, border, glow, shadow, or background.
- Put the result on a pure white background only.
- Keep a small margin around the signature.

The result should look like a cropped signature PNG, not a photo of paper.
""".strip()

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, cropped_image],
    )

    increment_ai_usage()

    parts = getattr(response, "parts", None)

    if parts:
        for part in parts:
            if getattr(part, "inline_data", None) is not None:
                return ensure_pil_image(part.as_image())

    candidates = getattr(response, "candidates", None)

    if candidates:
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content and getattr(content, "parts", None):
                for part in content.parts:
                    if getattr(part, "inline_data", None) is not None:
                        return ensure_pil_image(part.as_image())

    raise RuntimeError("Enhanced cleanup did not return an image.")


# =========================================================
# LOCAL FALLBACK
# =========================================================

def local_signature_cutout(image: Image.Image, threshold: int = 150) -> Image.Image:
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        rgb = arr[:, :, :3]

        gray = (
            0.299 * rgb[:, :, 0]
            + 0.587 * rgb[:, :, 1]
            + 0.114 * rgb[:, :, 2]
        )

        ink = gray < threshold

        arr[:, :, 3] = np.where(ink, 255, 0).astype(np.uint8)

        arr[ink, 0] = 0
        arr[ink, 1] = 0
        arr[ink, 2] = 0

        return finalize_signature_only(Image.fromarray(arr, mode="RGBA"))

    return image


def process_signature_only(
    image: Image.Image,
    model_name: str,
    darkness_threshold: int,
    crop_padding: int,
    alpha_threshold: int,
    alpha_softness: int,
) -> Tuple[Image.Image | None, str, str]:
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=2400)

    valid, validation_message = validate_upload_quality(image)
    st.session_state.validation_status = validation_message

    if not valid:
        return None, "Rejected", validation_message

    crop = detect_signature_bbox(
        image=image,
        darkness_threshold=darkness_threshold,
        padding=crop_padding,
    )

    crop_for_processing = enhance_crop_before_ai(crop, min_width=1200)

    if CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_ai_calls_per_session:
        try:
            cleaned_white = ask_ai_extract_signature_only(
                cropped_image=crop_for_processing,
                model_name=model_name,
            )

            transparent = white_to_transparent_soft(
                cleaned_white,
                threshold=alpha_threshold,
                softness=alpha_softness,
            )

            final = finalize_signature_only(transparent)
            ok, reason = score_output_quality(final)

            if ok:
                return final, "Enhanced cleanup", "Signature extracted successfully."

            return None, "Rejected", reason

        except Exception as e:
            fallback = local_signature_cutout(crop_for_processing, threshold=150)
            ok, reason = score_output_quality(fallback)

            if ok:
                return fallback, "Standard cleanup", f"Enhanced cleanup unavailable: {e}"

            return None, "Rejected", reason

    fallback = local_signature_cutout(crop_for_processing, threshold=150)
    ok, reason = score_output_quality(fallback)

    if ok:
        return fallback, "Standard cleanup", "Enhanced cleanup unavailable."

    return None, "Rejected", reason


# =========================================================
# DOWNLOADS
# =========================================================

def png_bytes_with_metadata(img: Image.Image) -> bytes:
    meta = PngImagePlugin.PngInfo()
    meta.add_text(
        "SignatureUse",
        "Insert as image. In Word/Google Docs, set layout to In Front of Text.",
    )
    meta.add_text("Background", "Transparent PNG")

    img = finalize_signature_only(img)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, pnginfo=meta)
    return buf.getvalue()


def pil_png_download_link(img: Image.Image, filename: str, label: str) -> str:
    png_bytes = png_bytes_with_metadata(img)
    b64 = base64.b64encode(png_bytes).decode()
    return '<a href="data:image/png;base64,' + b64 + '" download="' + filename + '" style="display:inline-block;text-decoration:none;background:linear-gradient(90deg,#111827 0%, #374151 100%);color:white;padding:0.75rem 1rem;border-radius:999px;font-weight:700;font-size:0.95rem;margin:0.25rem;">' + label + '</a>'


def create_word_ready_docx(signature_img: Image.Image) -> bytes:
    if not DOCX_AVAILABLE:
        raise RuntimeError("python-docx is not installed.")

    signature_img = finalize_signature_only(signature_img)

    doc = Document()
    doc.add_heading("Word-ready signature", level=1)
    doc.add_paragraph(
        "Copy this signature image and paste it into your document. "
        "In Microsoft Word, click the image and choose Layout Options → In Front of Text."
    )

    img_stream = io.BytesIO(png_bytes_with_metadata(signature_img))
    doc.add_picture(img_stream, width=Inches(2.0))

    doc.add_paragraph("")
    doc.add_paragraph("Tip: Resize from the corner handles to keep the signature proportions.")

    out = io.BytesIO()
    doc.save(out)
    out.seek(0)
    return out.getvalue()


def docx_download_link(docx_bytes: bytes, filename: str, label: str) -> str:
    b64 = base64.b64encode(docx_bytes).decode()
    return '<a href="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,' + b64 + '" download="' + filename + '" style="display:inline-block;text-decoration:none;background:linear-gradient(90deg,#2563EB 0%, #1D4ED8 100%);color:white;padding:0.75rem 1rem;border-radius:999px;font-weight:700;font-size:0.95rem;margin:0.25rem;">' + label + '</a>'


# =========================================================
# PREVIEW PROTECTION + PAYMENT
# =========================================================

def add_preview_protection(
    image: Image.Image,
    text: str = "PREVIEW • UNLOCK CLEAN PNG",
    opacity: int = 95,
    spacing: int = 90,
    angle: float = -28,
) -> Image.Image:
    img = image.convert("RGBA").copy()

    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font_size = max(14, img.width // 18)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tile = Image.new("RGBA", (tw + spacing, th + spacing), (255, 255, 255, 0))
    tile_draw = ImageDraw.Draw(tile)

    tile_draw.text(
        (spacing // 4, spacing // 4),
        text,
        fill=(90, 90, 90, opacity),
        font=font,
    )

    rotated = tile.rotate(angle, expand=True)

    step_y = max(1, rotated.height // 2)
    step_x = max(1, rotated.width // 2)

    for y in range(-rotated.height, img.height + rotated.height, step_y):
        for x in range(-rotated.width, img.width + rotated.width, step_x):
            overlay.alpha_composite(rotated, (x, y))

    return Image.alpha_composite(img, overlay)


def get_user_visible_preview(image: Image.Image, paid: bool) -> Image.Image:
    return image if paid else add_preview_protection(image)


def payment_cta() -> None:
    checkout_url = create_card_checkout_url()
    
    # Open payment card container
    st.markdown('<div class="payment-card">', unsafe_allow_html=True)
    
    # Heading
    st.markdown('<h3>🔓 Unlock clean signature files</h3>', unsafe_allow_html=True)
    
    # Description
    st.markdown(
        '<p>Your preview is watermarked. Pay <strong>' + CONFIG.price_display + 
        '</strong> once to download the clean transparent PNG and Word-ready signature file.</p>',
        unsafe_allow_html=True
    )
    
    # Open payment options container
    st.markdown('<div class="payment-options">', unsafe_allow_html=True)
    
    # Card payment button (Stripe)
    if checkout_url:
        card_html = (
            '<a class="payment-btn" href="' + checkout_url + '" target="_self">'
            '💳 Pay with Card — ' + CONFIG.price_display + '</a>'
        )
        st.markdown(card_html, unsafe_allow_html=True)
    
    # PayPal payment button
    if CONFIG.paypal_payment_url:
        paypal_html = (
            '<a class="paypal-btn" href="' + CONFIG.paypal_payment_url + '" target="_blank">'
            'Pay with PayPal — ' + CONFIG.price_display + '</a>'
        )
        st.markdown(paypal_html, unsafe_allow_html=True)
    elif CONFIG.paypal_email:
        paypal_html = (
            '<div class="payment-secondary">Pay with PayPal to <strong>' + 
            CONFIG.paypal_email + '</strong>, then enter your unlock code.</div>'
        )
        st.markdown(paypal_html, unsafe_allow_html=True)
    
    # If no payment methods configured
    if not checkout_url and not CONFIG.paypal_payment_url and not CONFIG.paypal_email:
        st.markdown(
            '<div class="payment-secondary">Payment options are not configured yet.</div>',
            unsafe_allow_html=True
        )
    
    # Close payment options container
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer note
    st.markdown(
        '<div class="payment-secondary">Choose your preferred payment method. Downloads unlock after payment.</div>',
        unsafe_allow_html=True
    )
    
    # Close payment card container
    st.markdown('</div>', unsafe_allow_html=True)

    # Unlock code section
    if CONFIG.unlock_code:
        with st.expander("Already paid? Enter unlock code"):
            code = st.text_input("Unlock code", type="password")
            if st.button("Unlock downloads"):
                if code.strip() == CONFIG.unlock_code.strip():
                    st.session_state.paid = True
                    st.success("Downloads unlocked.")
                    st.rerun()
                else:
                    st.error("Invalid unlock code.")


# =========================================================
# UI
# =========================================================

hero_html = '<div class="hero"><h1>🖊️ ' + CONFIG.app_name + '</h1><p>Upload a signature photo, preview the result for free, then unlock clean downloads for ' + CONFIG.price_display + '.</p></div>'
st.markdown(hero_html, unsafe_allow_html=True)

guide_html = '<div class="guide-box"><h3>📸 Upload Guide</h3><ul><li>Sign on clean white paper.</li><li>Use a dark black or blue pen.</li><li>Take the photo close to the signature.</li><li>Keep only the signature and paper in the frame.</li><li>Avoid shadows, laptops, phones, tables, or dark objects in the photo.</li><li>Make sure the signature is not too faint.</li></ul></div>'
st.markdown(guide_html, unsafe_allow_html=True)

left, right = st.columns([1, 1])

with left:
    st.caption("Preview is free. Clean downloads unlock after payment.")

with right:
    st.caption(
        "Processing attempts used: " + str(st.session_state.ai_calls_used) + " / " +
        str(CONFIG.max_ai_calls_per_session)
    )

uploaded_file = st.file_uploader(
    "Upload signature photo",
    type=["jpg", "jpeg", "png", "webp"],
)

if uploaded_file:
    original = Image.open(uploaded_file)
    original = fix_image_orientation(original)

    with st.expander("View uploaded photo preview", expanded=False):
        preview = make_upload_preview(original, max_size=420)
        st.image(
            preview,
            caption="Uploaded photo preview — original size " + str(original.width) + "px × " + str(original.height) + "px",
            use_container_width=False,
        )

    with st.expander("Processing settings", expanded=False):
        darkness_threshold = st.slider("Ink detection threshold", 100, 220, 170, 2)
        crop_padding = st.slider("Crop padding", 5, 100, 35, 5)
        alpha_threshold = st.slider("White removal threshold", 235, 254, 248, 1)
        alpha_softness = st.slider("Edge softness", 6, 35, 18, 1)

    if st.button("✨ Create signature preview", type="primary", use_container_width=True):
        try:
            with st.spinner("Checking photo and preparing preview..."):
                final_img, method, reason = process_signature_only(
                    image=original,
                    model_name=CONFIG.ai_model,
                    darkness_threshold=darkness_threshold,
                    crop_padding=crop_padding,
                    alpha_threshold=alpha_threshold,
                    alpha_softness=alpha_softness,
                )

            if final_img is None or method == "Rejected":
                st.session_state.final_clean_rgba = None
                st.session_state.method_used = "Rejected"
                st.session_state.quality_reason = reason

                st.error(reason)
                st.warning(
                    "Please retake the photo closer to the signature, with brighter lighting, "
                    "white paper only, darker ink, and no dark objects or shadows."
                )
            else:
                st.session_state.final_clean_rgba = final_img
                st.session_state.method_used = method
                st.session_state.quality_reason = reason
                st.success("Preview ready.")

        except Exception as e:
            st.session_state.final_clean_rgba = None
            st.session_state.method_used = "Rejected"
            st.session_state.quality_reason = str(e)
            st.error("Processing failed: " + str(e))

if st.session_state.final_clean_rgba is not None and st.session_state.method_used != "Rejected":
    st.markdown("---")

    preview_img = get_user_visible_preview(
        st.session_state.final_clean_rgba,
        paid=st.session_state.paid,
    )

    st.markdown('<div class="result-card">', unsafe_allow_html=True)

    st.image(
        preview_transparent_image(preview_img),
        caption=(
            "Signature preview — " +
            str(st.session_state.final_clean_rgba.width) + "px × " +
            str(st.session_state.final_clean_rgba.height) + "px"
        ),
        use_container_width=False,
    )

    if st.session_state.paid:
        st.success("Unlocked. Your clean signature files are ready.")

        st.markdown(
            pil_png_download_link(
                st.session_state.final_clean_rgba,
                "signature_only_transparent.png",
                "⬇️ Download transparent signature PNG",
            ),
            unsafe_allow_html=True,
        )

        if DOCX_AVAILABLE:
            docx_bytes = create_word_ready_docx(st.session_state.final_clean_rgba)
            st.markdown(
                docx_download_link(
                    docx_bytes,
                    "word_ready_signature.docx",
                    "⬇️ Download Word-ready signature",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.warning("Install python-docx to enable Word-ready download.")
    else:
        payment_cta()

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")

usage_html = '<div class="guide-box"><h3>📝 How to Use Your Digital PNG Signature</h3><b>In Microsoft Word:</b><ol><li>Open your document.</li><li>Go to <b>Insert → Pictures</b>.</li><li>Select the downloaded transparent PNG.</li><li>Click the image, then choose <b>Layout Options → In Front of Text</b>.</li><li>Resize from the corner handles only.</li></ol><b>In Google Docs:</b><ol><li>Go to <b>Insert → Image → Upload from computer</b>.</li><li>Select the PNG.</li><li>Click the image and choose <b>In front of text</b>.</li></ol><b>In PDF editors:</b><ol><li>Use <b>Add Image</b>, <b>Stamp</b>, or <b>Fill & Sign</b>.</li><li>Select the transparent PNG.</li><li>Place it above the signature line.</li></ol><p><b>Important:</b> This PNG is a visual signature image, not a certificate-based digital signature.</p></div>'
st.markdown(usage_html, unsafe_allow_html=True)

st.markdown(
    '<div class="footer-note">Signature-only transparent PNG extractor with card and PayPal unlock options</div>',
    unsafe_allow_html=True,
)