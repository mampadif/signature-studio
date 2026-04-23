"""
Signature Studio Pro
Gemini-first signature cleanup with automatic local fallback
Protected watermark preview for unpaid users
Configuration source: Streamlit Cloud Secrets ONLY

Required Streamlit secrets:

GEMINI_API_KEY = "your_key_here"
GEMINI_MODEL = "gemini-3.1-flash-image-preview"
APP_NAME = "Signature Studio Pro"
GEMINI_ENABLED = true
MAX_GEMINI_CALLS_PER_SESSION = 3

Recommended requirements.txt:

streamlit
pillow
numpy
google-genai>=1.0.0
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# =========================================================
# CONFIG
# =========================================================

@dataclass
class AppConfig:
    gemini_api_key: str
    gemini_model: str
    app_name: str
    gemini_enabled: bool
    max_calls_per_session: int


def load_config() -> AppConfig:
    """
    Production config loader using Streamlit Cloud Secrets only.
    """
    if "GEMINI_API_KEY" not in st.secrets:
        raise RuntimeError(
            """
GEMINI_API_KEY missing in Streamlit secrets.

Add these in Streamlit Cloud -> Manage App -> Secrets:

GEMINI_API_KEY = "your_key_here"
GEMINI_MODEL = "gemini-3.1-flash-image-preview"
APP_NAME = "Signature Studio Pro"
GEMINI_ENABLED = true
MAX_GEMINI_CALLS_PER_SESSION = 3
"""
        )

    return AppConfig(
        gemini_api_key=st.secrets["GEMINI_API_KEY"],
        gemini_model=st.secrets.get("GEMINI_MODEL", "gemini-3.1-flash-image-preview"),
        app_name=st.secrets.get("APP_NAME", "Signature Studio Pro"),
        gemini_enabled=bool(st.secrets.get("GEMINI_ENABLED", True)),
        max_calls_per_session=int(st.secrets.get("MAX_GEMINI_CALLS_PER_SESSION", 3)),
    )


CONFIG = load_config()


# =========================================================
# STREAMLIT
# =========================================================

st.set_page_config(
    page_title=CONFIG.app_name,
    page_icon="🖊️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Session state
DEFAULT_SESSION_KEYS = {
    "paid": False,  # replace later with real payment state
    "gemini_calls_used": 0,
    "debug_crop": None,
    "gemini_result_white": None,
    "local_result_rgba": None,
    "final_clean_rgba": None,
    "method_used": None,
    "quality_reason": None,
}

for key, value in DEFAULT_SESSION_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# STYLES
# =========================================================

st.markdown("""
<style>
.block-container {
    max-width: 1220px;
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
    letter-spacing: -0.03em;
}
.hero p {
    margin: 0;
    color: rgba(255,255,255,0.88);
    line-height: 1.6;
    max-width: 860px;
}
.card {
    background: white;
    border: 1px solid #EAECF0;
    border-radius: 18px;
    padding: 1rem;
    box-shadow: 0 8px 24px rgba(16,24,40,0.05);
    height: 100%;
}
.card h3 {
    margin: 0 0 0.35rem 0;
    font-size: 1.05rem;
    font-weight: 760;
    color: #101828;
}
.card p {
    margin: 0;
    color: #475467;
    line-height: 1.55;
    font-size: 0.95rem;
}
.tip-box {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #7C3AED;
    padding: 1rem;
    border-radius: 14px;
    margin-bottom: 1rem;
    color: #334155;
    line-height: 1.55;
}
.footer-note {
    text-align: center;
    color: #667085;
    font-size: 0.9rem;
    margin-top: 1.2rem;
}
.small-note {
    color: #667085;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# GEMINI HELPERS
# =========================================================

def get_genai_client():
    """
    Lazy import so the app can still run local fallback logic even if
    google-genai is missing or Gemini is disabled.
    """
    if not CONFIG.gemini_enabled:
        raise RuntimeError("Gemini disabled via configuration.")

    if st.session_state.gemini_calls_used >= CONFIG.max_calls_per_session:
        raise RuntimeError("Gemini session usage limit reached.")

    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "google-genai package missing. Add 'google-genai>=1.0.0' to requirements.txt."
        ) from e

    return genai.Client(api_key=CONFIG.gemini_api_key)


def increment_gemini_usage() -> None:
    st.session_state.gemini_calls_used += 1


# =========================================================
# IMAGE HELPERS
# =========================================================

def fix_image_orientation(image: Image.Image) -> Image.Image:
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def smart_resize_for_processing(image: Image.Image, max_pixels: int = 2400) -> Image.Image:
    width, height = image.size
    if max(width, height) <= max_pixels:
        return image.copy()

    ratio = max_pixels / max(width, height)
    new_size = (int(width * ratio), int(height * ratio))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def create_checkerboard_bg(size: tuple[int, int], square_size: int = 18) -> Image.Image:
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


def pil_png_download_link(img: Image.Image, filename: str, label: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return f"""
    <a href="data:image/png;base64,{b64}" download="{filename}"
       style="
            display:inline-block;
            text-decoration:none;
            background:linear-gradient(90deg,#111827 0%, #374151 100%);
            color:white;
            padding:0.75rem 1rem;
            border-radius:999px;
            font-weight:700;
            font-size:0.95rem;
       ">
       {label}
    </a>
    """


def add_preview_protection(
    image: Image.Image,
    text: str = "PREVIEW • PAY TO UNLOCK • PREVIEW",
    opacity: int = 70,
    spacing: int = 180,
    angle: float = -30,
    preview_max_width: int = 900
) -> Image.Image:
    """
    Strong preview protection for unpaid users.
    """
    img = image.convert("RGBA").copy()

    if img.width > preview_max_width:
        ratio = preview_max_width / img.width
        img = img.resize(
            (int(img.width * ratio), int(img.height * ratio)),
            Image.Resampling.LANCZOS
        )

    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font_size = max(22, img.width // 18)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    tile_w = text_w + spacing
    tile_h = text_h + spacing

    tile = Image.new("RGBA", (tile_w, tile_h), (255, 255, 255, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.text(
        (spacing // 3, spacing // 3),
        text,
        fill=(90, 90, 90, opacity),
        font=font,
    )

    rotated_tile = tile.rotate(angle, expand=True)

    for y in range(-rotated_tile.height, img.height + rotated_tile.height, rotated_tile.height):
        for x in range(-rotated_tile.width, img.width + rotated_tile.width, rotated_tile.width):
            overlay.alpha_composite(rotated_tile, (x, y))

    return Image.alpha_composite(img, overlay)


def get_user_visible_preview(image: Image.Image, paid: bool) -> Image.Image:
    return image if paid else add_preview_protection(image)


def detect_signature_bbox(
    image: Image.Image,
    darkness_threshold: int = 150,
    padding: int = 80,
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    Conservative crop around likely ink.
    """
    rgb = image.convert("RGB")

    if HAS_NUMPY:
        arr = np.array(rgb, dtype=np.uint8)
        gray = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.uint8)
        ink_mask = gray < darkness_threshold
        coords = np.argwhere(ink_mask)

        if coords.size == 0:
            return image.copy(), (0, 0, image.width, image.height)

        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
    else:
        gray = rgb.convert("L")
        px = gray.load()
        x_min, y_min = image.width, image.height
        x_max, y_max = 0, 0
        found = False

        for y in range(image.height):
            for x in range(image.width):
                if px[x, y] < darkness_threshold:
                    found = True
                    x_min = min(x_min, x)
                    y_min = min(y_min, y)
                    x_max = max(x_max, x)
                    y_max = max(y_max, y)

        if not found:
            return image.copy(), (0, 0, image.width, image.height)

    x1 = max(0, x_min - padding)
    y1 = max(0, y_min - padding)
    x2 = min(image.width, x_max + padding)
    y2 = min(image.height, y_max + padding)

    return image.crop((x1, y1, x2, y2)), (x1, y1, x2, y2)


def enhance_crop_before_processing(image: Image.Image, min_width: int = 1200) -> Image.Image:
    img = image.convert("RGB")
    width, height = img.size

    if width < min_width:
        ratio = min_width / max(1, width)
        img = img.resize(
            (int(width * ratio), int(height * ratio)),
            Image.Resampling.LANCZOS
        )

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


# =========================================================
# GEMINI PATH
# =========================================================

def ask_gemini_to_clean_signature(
    cropped_image: Image.Image,
    model_name: str,
) -> Image.Image:
    """
    Ask Gemini to reconstruct the signature cleanly on white.
    """
    client = get_genai_client()

    prompt = """
Clean this photographed handwritten signature.

Strict requirements:
- Preserve the original signature shape as faithfully as possible.
- Preserve stroke path, proportions, position, angle, and relative stroke thickness.
- Remove paper texture, shadows, blur haze, compression artifacts, and lighting gradients.
- Output the signature in solid black ink only.
- Put it on a PURE WHITE background only.
- Do not stylize it.
- Do not embellish it.
- Do not add glow, shadow, decorative effects, or extra flourishes.
- Do not transform it into a different handwriting style.
- Keep comfortable white margins around the signature.

Goal:
A clean, crisp, high-resolution version of the same signature on plain white background.
""".strip()

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, cropped_image],
    )

    increment_gemini_usage()

    parts = getattr(response, "parts", None)
    if parts:
        for part in parts:
            if getattr(part, "inline_data", None) is not None:
                return part.as_image().convert("RGBA")

    candidates = getattr(response, "candidates", None)
    if candidates:
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content and getattr(content, "parts", None):
                for part in content.parts:
                    if getattr(part, "inline_data", None) is not None:
                        return part.as_image().convert("RGBA")

    raise RuntimeError("Gemini did not return an image.")


def white_to_transparent_soft(
    image: Image.Image,
    threshold: int = 246,
    softness: int = 14,
) -> Image.Image:
    image = image.convert("RGBA")
    soft_start = max(0, threshold - softness)

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        rgb = arr[:, :, :3].astype(np.float32)
        brightness = rgb.mean(axis=2)

        alpha = np.where(
            brightness >= threshold,
            0,
            np.where(
                brightness <= soft_start,
                255,
                ((threshold - brightness) / max(1, threshold - soft_start) * 255),
            ),
        )

        arr[:, :, 3] = alpha.astype(np.uint8)
        return Image.fromarray(arr, mode="RGBA")

    new_data = []
    for r, g, b, a in image.getdata():
        bright = (r + g + b) / 3
        if bright >= threshold:
            new_alpha = 0
        elif bright <= soft_start:
            new_alpha = 255
        else:
            new_alpha = int((threshold - bright) / max(1, threshold - soft_start) * 255)
        new_data.append((r, g, b, new_alpha))

    image.putdata(new_data)
    return image


# =========================================================
# LOCAL FALLBACK PATH
# =========================================================

def estimate_background_level(image: Image.Image) -> int:
    rgb = image.convert("RGB")

    if HAS_NUMPY:
        arr = np.array(rgb, dtype=np.uint8)
        brightness = arr.mean(axis=2).reshape(-1)

        if brightness.size == 0:
            return 245

        top_cut = np.percentile(brightness, 90)
        bright_pixels = brightness[brightness >= top_cut]

        if bright_pixels.size == 0:
            return 245

        return int(np.median(bright_pixels))

    pixels = list(rgb.getdata())
    if not pixels:
        return 245

    brightness = sorted(int((r + g + b) / 3) for (r, g, b) in pixels)
    start_idx = int(len(brightness) * 0.9)
    bright_pixels = brightness[start_idx:] if start_idx < len(brightness) else brightness

    if not bright_pixels:
        return 245

    mid = len(bright_pixels) // 2
    if len(bright_pixels) % 2 == 0:
        return (bright_pixels[mid - 1] + bright_pixels[mid]) // 2
    return bright_pixels[mid]


def remove_paper_background_soft(
    image: Image.Image,
    threshold: Optional[int] = None,
    softness: int = 22
) -> Tuple[Image.Image, int]:
    image = image.convert("RGBA")

    if threshold is None:
        bg_level = estimate_background_level(image)
        threshold = max(205, min(250, bg_level - 8))

    soft_start = max(0, threshold - softness)

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        rgb = arr[:, :, :3].astype(np.float32)
        brightness = rgb.mean(axis=2)

        alpha = np.where(
            brightness >= threshold,
            0,
            np.where(
                brightness <= soft_start,
                255,
                ((threshold - brightness) / max(1, threshold - soft_start) * 255)
            )
        )

        arr[:, :, 3] = alpha.astype(np.uint8)
        return Image.fromarray(arr, mode="RGBA"), int(threshold)

    new_data = []
    for r, g, b, a in image.getdata():
        bright = (r + g + b) / 3
        if bright >= threshold:
            new_alpha = 0
        elif bright <= soft_start:
            new_alpha = 255
        else:
            new_alpha = int((threshold - bright) / max(1, threshold - soft_start) * 255)
        new_data.append((r, g, b, new_alpha))

    image.putdata(new_data)
    return image, int(threshold)


def clean_alpha_noise(image: Image.Image, min_alpha: int = 8) -> Image.Image:
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3]
        alpha[alpha < min_alpha] = 0
        arr[:, :, 3] = alpha
        return Image.fromarray(arr, mode="RGBA")

    new_data = []
    for r, g, b, a in image.getdata():
        if a < min_alpha:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    image.putdata(new_data)
    return image


def auto_crop_transparent(image: Image.Image, padding: int = 40) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()

    if not bbox:
        return image

    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)

    return image.crop((left, top, right, bottom))


def upscale_final_if_small(image: Image.Image, min_width: int = 1000) -> Image.Image:
    width, height = image.size
    if width >= min_width:
        return image

    ratio = min_width / max(1, width)
    return image.resize(
        (int(width * ratio), int(height * ratio)),
        Image.Resampling.LANCZOS
    )


# =========================================================
# QUALITY SCORING
# =========================================================

def rgba_ink_bbox(image: Image.Image, alpha_cutoff: int = 20) -> Optional[Tuple[int, int, int, int]]:
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3]
        coords = np.argwhere(alpha > alpha_cutoff)
        if coords.size == 0:
            return None
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        return (x_min, y_min, x_max, y_max)

    alpha = image.getchannel("A")
    return alpha.point(lambda a: 255 if a > alpha_cutoff else 0).getbbox()


def score_result_quality(
    image: Image.Image,
    min_ink_pixels: int = 1200,
    min_fill_ratio: float = 0.02,
    max_fill_ratio: float = 0.70,
) -> Tuple[bool, str]:
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3]
        ink_pixels = int((alpha > 20).sum())
    else:
        ink_pixels = sum(1 for *_, a in image.getdata() if a > 20)

    total_pixels = max(1, image.width * image.height)
    fill_ratio = ink_pixels / total_pixels

    bbox = rgba_ink_bbox(image)
    if bbox is None:
        return False, "No visible signature found."

    x1, y1, x2, y2 = bbox
    bbox_w = max(1, x2 - x1)
    bbox_h = max(1, y2 - y1)

    if ink_pixels < min_ink_pixels:
        return False, "Too little visible ink after extraction."
    if fill_ratio < min_fill_ratio:
        return False, "Signature is too faint or too small."
    if fill_ratio > max_fill_ratio:
        return False, "Too much non-background content remained."
    if bbox_w < 80 or bbox_h < 40:
        return False, "Extracted signature bounds are too small."

    return True, "Quality passed."


# =========================================================
# PIPELINES
# =========================================================

def run_gemini_pipeline(
    crop_for_processing: Image.Image,
    model_name: str,
    alpha_threshold: int,
    alpha_softness: int,
    final_padding: int,
    upscale_final: bool,
) -> Tuple[Image.Image, Image.Image]:
    gemini_white = ask_gemini_to_clean_signature(
        cropped_image=crop_for_processing,
        model_name=model_name,
    )

    rgba = white_to_transparent_soft(
        gemini_white,
        threshold=alpha_threshold,
        softness=alpha_softness,
    )
    rgba = clean_alpha_noise(rgba, min_alpha=8)
    rgba = auto_crop_transparent(rgba, padding=final_padding)

    if upscale_final:
        rgba = upscale_final_if_small(rgba, min_width=1000)

    return gemini_white, rgba


def run_local_fallback_pipeline(
    crop_for_processing: Image.Image,
    final_padding: int,
    upscale_final: bool,
) -> Image.Image:
    rgba, _used_threshold = remove_paper_background_soft(
        crop_for_processing,
        threshold=None,
        softness=22,
    )
    rgba = clean_alpha_noise(rgba, min_alpha=10)
    rgba = auto_crop_transparent(rgba, padding=final_padding)

    if upscale_final:
        rgba = upscale_final_if_small(rgba, min_width=1000)

    return rgba


def process_signature_with_fallback(
    image: Image.Image,
    model_name: str,
    darkness_threshold: int,
    crop_padding: int,
    alpha_threshold: int,
    alpha_softness: int,
    final_padding: int,
    upscale_final: bool,
) -> Tuple[Image.Image, Optional[Image.Image], Image.Image, Image.Image, str, str]:
    """
    Try Gemini first; if Gemini fails or result is weak, use local fallback.
    Returns:
        crop_for_processing,
        gemini_white_or_none,
        local_result_rgba,
        final_clean_rgba,
        method_used,
        quality_reason
    """
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=2400)

    crop, _bbox = detect_signature_bbox(
        image=image,
        darkness_threshold=darkness_threshold,
        padding=crop_padding,
    )

    crop_for_processing = enhance_crop_before_processing(crop, min_width=1200)

    # Always prepare local fallback
    local_rgba = run_local_fallback_pipeline(
        crop_for_processing=crop_for_processing,
        final_padding=final_padding,
        upscale_final=upscale_final,
    )

    # Skip Gemini immediately if disabled or quota reached
    if (not CONFIG.gemini_enabled) or (st.session_state.gemini_calls_used >= CONFIG.max_calls_per_session):
        reason = "Gemini unavailable or session limit reached."
        return crop_for_processing, None, local_rgba, local_rgba, "Local fallback", reason

    # Try Gemini
    try:
        gemini_white, gemini_rgba = run_gemini_pipeline(
            crop_for_processing=crop_for_processing,
            model_name=model_name,
            alpha_threshold=alpha_threshold,
            alpha_softness=alpha_softness,
            final_padding=final_padding,
            upscale_final=upscale_final,
        )

        passed, reason = score_result_quality(gemini_rgba)
        if passed:
            return crop_for_processing, gemini_white, local_rgba, gemini_rgba, "Gemini", reason

        return crop_for_processing, gemini_white, local_rgba, local_rgba, "Local fallback", f"Gemini rejected: {reason}"

    except Exception as e:
        return crop_for_processing, None, local_rgba, local_rgba, "Local fallback", f"Gemini failed: {e}"


# =========================================================
# UI
# =========================================================

st.markdown(f"""
<div class="hero">
    <h1>🖊️ {CONFIG.app_name}</h1>
    <p>
        Gemini-first signature cleanup with automatic local fallback. The app tries Gemini
        for a cleaner reconstruction, then falls back to deterministic local extraction if Gemini
        fails, is disabled, hits the session cap, or returns a weak result.
    </p>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""
    <div class="card">
        <h3>Gemini first</h3>
        <p>Uses Gemini on a cropped signature region instead of the full photo for better cleanup focus.</p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="card">
        <h3>Automatic fallback</h3>
        <p>If Gemini fails, is weak, or is unavailable, local non-AI cleanup takes over automatically.</p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="card">
        <h3>Protected preview</h3>
        <p>Unpaid users see a strong watermarked preview. Paid users get the clean transparent PNG.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

st.markdown("""
<div class="tip-box">
<strong>Best photo tips:</strong><br>
• Take the photo closer so the signature fills more of the frame<br>
• Use dark ink on plain white paper<br>
• Avoid blur and strong shadows<br>
• Keep the phone straight above the page
</div>
""", unsafe_allow_html=True)

top_left, top_right = st.columns([1, 1])
with top_left:
    st.session_state.paid = st.toggle(
        "Paid / unlocked mode",
        value=st.session_state.paid,
        help="Demo switch. Replace with your real payment state."
    )

with top_right:
    st.caption(
        f"Gemini calls used this session: {st.session_state.gemini_calls_used} / "
        f"{CONFIG.max_calls_per_session}"
    )

uploaded_file = st.file_uploader(
    "Choose signature image",
    type=["jpg", "jpeg", "png", "webp"],
)

if uploaded_file:
    original = Image.open(uploaded_file)
    original = fix_image_orientation(original)

    left, right = st.columns([1, 1.05])

    with left:
        st.image(original, caption="Original upload", use_container_width=True)

    with right:
        model_name = st.text_input("Gemini model", value=CONFIG.gemini_model)
        darkness_threshold = st.slider("Ink detection threshold", 100, 190, 150, 2)
        crop_padding = st.slider("Initial crop padding", 20, 160, 80, 5)
        alpha_threshold = st.slider("White-to-alpha threshold", 235, 254, 246, 1)
        alpha_softness = st.slider("Alpha edge softness", 6, 30, 14, 1)
        final_padding = st.slider("Final transparent padding", 10, 100, 40, 5)
        upscale_final = st.toggle("Upscale final PNG", value=True)

        run_btn = st.button("✨ Clean signature", type="primary", use_container_width=True)

    if run_btn:
        start = time.time()
        try:
            with st.spinner("Processing signature..."):
                (
                    debug_crop,
                    gemini_white,
                    local_rgba,
                    final_clean_rgba,
                    method_used,
                    quality_reason,
                ) = process_signature_with_fallback(
                    image=original,
                    model_name=model_name,
                    darkness_threshold=darkness_threshold,
                    crop_padding=crop_padding,
                    alpha_threshold=alpha_threshold,
                    alpha_softness=alpha_softness,
                    final_padding=final_padding,
                    upscale_final=upscale_final,
                )

                st.session_state.debug_crop = debug_crop
                st.session_state.gemini_result_white = gemini_white
                st.session_state.local_result_rgba = local_rgba
                st.session_state.final_clean_rgba = final_clean_rgba
                st.session_state.method_used = method_used
                st.session_state.quality_reason = quality_reason

            elapsed = time.time() - start
            st.success(f"Done in {elapsed:.2f} seconds.")
        except Exception as e:
            st.error(f"Processing failed: {e}")

if st.session_state.final_clean_rgba is not None:
    st.markdown("---")
    st.info(f"Method used: {st.session_state.method_used} — {st.session_state.quality_reason}")

    user_visible_preview = get_user_visible_preview(
        st.session_state.final_clean_rgba,
        paid=st.session_state.paid
    )

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.image(
            st.session_state.debug_crop,
            caption="1) Local crop used for processing",
            use_container_width=True
        )

    with col_b:
        if st.session_state.gemini_result_white is not None:
            st.image(
                st.session_state.gemini_result_white,
                caption="2) Gemini white-background result",
                use_container_width=True
            )
        else:
            st.warning("Gemini result unavailable. Local fallback was used.")

    with col_c:
        st.image(
            preview_transparent_image(user_visible_preview),
            caption="3) User-visible preview",
            use_container_width=True
        )

    dl_left, dl_right = st.columns([1, 1])

    with dl_left:
        if st.session_state.paid:
            st.markdown(
                pil_png_download_link(
                    st.session_state.final_clean_rgba,
                    "signature_transparent.png",
                    "⬇️ Download clean transparent PNG"
                ),
                unsafe_allow_html=True,
            )
        else:
            st.warning("Unlock to download the clean transparent PNG.")
            st.caption("The preview is intentionally watermarked to discourage screenshot reuse.")

    with dl_right:
        st.info(
            f"Final clean size: {st.session_state.final_clean_rgba.width}px × "
            f"{st.session_state.final_clean_rgba.height}px"
        )

    with st.expander("Show local fallback result"):
        st.image(
            preview_transparent_image(st.session_state.local_result_rgba),
            caption="Local fallback transparent preview",
            use_container_width=True
        )

st.markdown("---")
st.markdown(
    '<div class="footer-note">Gemini-first cleanup with automatic local fallback and protected previews</div>',
    unsafe_allow_html=True
)