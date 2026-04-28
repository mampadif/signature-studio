"""
Signature Studio Pro
Corrected version:
- Signature-only extraction
- Soft transparency conversion
- Preserves pen strokes
- Avoids broken/thin signature artifacts
- Gemini-first, local fallback
- Protected preview for unpaid users
- Word-ready DOCX export

requirements.txt:
streamlit
pillow
numpy
google-genai>=1.0.0
python-docx
"""

from __future__ import annotations

import base64
import io
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, PngImagePlugin

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

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
    gemini_api_key: str
    gemini_model: str
    app_name: str
    gemini_enabled: bool
    max_calls_per_session: int


def load_config() -> AppConfig:
    if "GEMINI_API_KEY" not in st.secrets:
        raise RuntimeError(
            """
GEMINI_API_KEY missing in Streamlit secrets.

Add:
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
    "gemini_calls_used": 0,
    "final_clean_rgba": None,
    "method_used": None,
    "quality_reason": None,
}

for key, value in DEFAULT_SESSION_KEYS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# CSS
# =========================================================

st.markdown("""
<style>
.block-container {
    max-width: 1050px;
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
.tip-box {
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
.footer-note {
    text-align: center;
    color: #667085;
    font-size: 0.9rem;
    margin-top: 1.2rem;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# GEMINI
# =========================================================

def get_genai_client():
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
    return image.resize(
        (int(width * ratio), int(height * ratio)),
        Image.Resampling.LANCZOS,
    )


def detect_signature_bbox(
    image: Image.Image,
    darkness_threshold: int = 150,
    padding: int = 25,
) -> Image.Image:
    rgb = image.convert("RGB")

    if HAS_NUMPY:
        arr = np.array(rgb, dtype=np.uint8)
        gray = (
            0.299 * arr[:, :, 0]
            + 0.587 * arr[:, :, 1]
            + 0.114 * arr[:, :, 2]
        ).astype(np.uint8)

        mask = gray < darkness_threshold
        coords = np.argwhere(mask)

        if coords.size == 0:
            return image.copy()

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
            return image.copy()

    x1 = max(0, int(x_min) - padding)
    y1 = max(0, int(y_min) - padding)
    x2 = min(image.width, int(x_max) + padding)
    y2 = min(image.height, int(y_max) + padding)

    return image.crop((x1, y1, x2, y2))


def enhance_crop_before_gemini(image: Image.Image, min_width: int = 1200) -> Image.Image:
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
    """
    Soft conversion from white to transparency.
    Preserves anti-aliased pen edges.
    """
    image = image.convert("RGBA")
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

    new_pixels = []
    for r, g, b, a in image.getdata():
        brightness = (r + g + b) / 3

        if brightness >= threshold:
            new_alpha = 0
        elif brightness <= soft_start:
            new_alpha = 255
        else:
            new_alpha = int((threshold - brightness) / max(1, threshold - soft_start) * 255)

        if new_alpha > 0:
            new_pixels.append((0, 0, 0, new_alpha))
        else:
            new_pixels.append((255, 255, 255, 0))

    image.putdata(new_pixels)
    return image


def remove_small_noise(image: Image.Image, alpha_cutoff: int = 30) -> Image.Image:
    """
    Removes faint background residue without destroying pen strokes.
    Do NOT use alpha_cutoff=255 for signatures.
    """
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

    new_data = []

    for r, g, b, a in image.getdata():
        if a < alpha_cutoff:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((0, 0, 0, a))

    image.putdata(new_data)
    return image


def remove_small_alpha_components(
    image: Image.Image,
    min_area: int = 20,
) -> Image.Image:
    """
    Removes isolated specks while keeping small real signature details.
    """
    image = image.convert("RGBA")

    if not HAS_NUMPY:
        return image

    arr = np.array(image, dtype=np.uint8)
    mask = arr[:, :, 3] > 0

    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            q = deque([(y, x)])
            visited[y, x] = True
            pixels = []

            while q:
                cy, cx = q.popleft()
                pixels.append((cy, cx))

                for ny in (cy - 1, cy, cy + 1):
                    for nx in (cx - 1, cx, cx + 1):
                        if ny == cy and nx == cx:
                            continue
                        if 0 <= ny < height and 0 <= nx < width:
                            if mask[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                q.append((ny, nx))

            components.append(pixels)

    if not components:
        return image

    keep = np.zeros_like(mask, dtype=bool)

    # Keep largest component always
    largest = max(components, key=len)
    for y, x in largest:
        keep[y, x] = True

    # Keep nearby/sufficient small components such as dots
    for comp in components:
        if len(comp) >= min_area:
            for y, x in comp:
                keep[y, x] = True

    arr[~keep, 3] = 0

    return Image.fromarray(arr, mode="RGBA")


def tight_crop_alpha(image: Image.Image, padding: int = 6) -> Image.Image:
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
    """
    Safe final cleanup:
    preserves strokes, removes noise, crops tightly.
    """
    image = image.convert("RGBA")

    image = remove_small_noise(image, alpha_cutoff=30)
    image = remove_small_alpha_components(image, min_area=20)

    image = tight_crop_alpha(image, padding=8)
    image = center_signature_canvas(image)

    image = resize_signature_only(image, max_width=700, max_height=240)

    image = remove_small_noise(image, alpha_cutoff=20)
    image = remove_small_alpha_components(image, min_area=12)

    image = center_signature_canvas(image)
    image = tight_crop_alpha(image, padding=6)

    return image


# =========================================================
# GEMINI EXTRACTION
# =========================================================

def ask_gemini_extract_signature_only(
    cropped_image: Image.Image,
    model_name: str,
) -> Image.Image:
    client = get_genai_client()

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


# =========================================================
# LOCAL FALLBACK
# =========================================================

def local_signature_cutout(image: Image.Image, threshold: int = 150) -> Image.Image:
    """
    Local fallback using dark ink segmentation.
    """
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

    new_data = []

    for r, g, b, a in image.getdata():
        gray = 0.299 * r + 0.587 * g + 0.114 * b

        if gray < threshold:
            new_data.append((0, 0, 0, 255))
        else:
            new_data.append((255, 255, 255, 0))

    image.putdata(new_data)
    return finalize_signature_only(image)


def process_signature_only(
    image: Image.Image,
    model_name: str,
    darkness_threshold: int,
    crop_padding: int,
    alpha_threshold: int,
    alpha_softness: int,
) -> Tuple[Image.Image, str, str]:
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=2400)

    crop = detect_signature_bbox(
        image=image,
        darkness_threshold=darkness_threshold,
        padding=crop_padding,
    )

    crop_for_gemini = enhance_crop_before_gemini(crop, min_width=1200)

    if CONFIG.gemini_enabled and st.session_state.gemini_calls_used < CONFIG.max_calls_per_session:
        try:
            gemini_white = ask_gemini_extract_signature_only(
                cropped_image=crop_for_gemini,
                model_name=model_name,
            )

            transparent = white_to_transparent_soft(
                gemini_white,
                threshold=alpha_threshold,
                softness=alpha_softness,
            )

            final = finalize_signature_only(transparent)

            return final, "Gemini", "Signature extracted with soft edge preservation."

        except Exception as e:
            fallback = local_signature_cutout(crop_for_gemini, threshold=150)
            return fallback, "Local fallback", f"Gemini failed: {e}"

    fallback = local_signature_cutout(crop_for_gemini, threshold=150)
    return fallback, "Local fallback", "Gemini disabled or session limit reached."


# =========================================================
# DOWNLOADS
# =========================================================

def png_bytes_with_metadata(img: Image.Image) -> bytes:
    meta = PngImagePlugin.PngInfo()
    meta.add_text("SignatureUse", "Insert as image. In Word/Google Docs, set layout to In Front of Text.")
    meta.add_text("Background", "Transparent PNG")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, pnginfo=meta)
    return buf.getvalue()


def pil_png_download_link(img: Image.Image, filename: str, label: str) -> str:
    png_bytes = png_bytes_with_metadata(img)
    b64 = base64.b64encode(png_bytes).decode()

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
            margin:0.25rem;
       ">
       {label}
    </a>
    """


def create_word_ready_docx(signature_img: Image.Image) -> bytes:
    if not DOCX_AVAILABLE:
        raise RuntimeError("python-docx is not installed.")

    doc = Document()

    doc.add_heading("Word-ready signature", level=1)
    doc.add_paragraph(
        "Copy this signature image and paste it into your document. "
        "In Microsoft Word, click the image and choose Layout Options → In Front of Text."
    )

    img_stream = io.BytesIO(png_bytes_with_metadata(signature_img))
    doc.add_picture(img_stream, width=Inches(2.2))

    doc.add_paragraph("")
    doc.add_paragraph("Tip: Resize from the corner handles to keep the signature proportions.")

    out = io.BytesIO()
    doc.save(out)
    out.seek(0)
    return out.getvalue()


def docx_download_link(docx_bytes: bytes, filename: str, label: str) -> str:
    b64 = base64.b64encode(docx_bytes).decode()

    return f"""
    <a href="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}"
       download="{filename}"
       style="
            display:inline-block;
            text-decoration:none;
            background:linear-gradient(90deg,#2563EB 0%, #1D4ED8 100%);
            color:white;
            padding:0.75rem 1rem;
            border-radius:999px;
            font-weight:700;
            font-size:0.95rem;
            margin:0.25rem;
       ">
       {label}
    </a>
    """


# =========================================================
# PREVIEW PROTECTION
# =========================================================

def add_preview_protection(
    image: Image.Image,
    text: str = "PREVIEW • PAY TO UNLOCK",
    opacity: int = 80,
    spacing: int = 120,
    angle: float = -30,
) -> Image.Image:
    img = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font_size = max(16, img.width // 14)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tile = Image.new("RGBA", (tw + spacing, th + spacing), (255, 255, 255, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.text(
        (spacing // 3, spacing // 3),
        text,
        fill=(90, 90, 90, opacity),
        font=font,
    )

    rotated = tile.rotate(angle, expand=True)

    for y in range(-rotated.height, img.height + rotated.height, rotated.height):
        for x in range(-rotated.width, img.width + rotated.width, rotated.width):
            overlay.alpha_composite(rotated, (x, y))

    return Image.alpha_composite(img, overlay)


def get_user_visible_preview(image: Image.Image, paid: bool) -> Image.Image:
    return image if paid else add_preview_protection(image)


# =========================================================
# UI
# =========================================================

st.markdown(f"""
<div class="hero">
    <h1>🖊️ {CONFIG.app_name}</h1>
    <p>
        Upload a signature photo and get only the cropped-out signature as a clean transparent PNG.
        This version preserves strokes better and avoids the broken-line effect.
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="tip-box">
<strong>Why AI sometimes fails:</strong><br>
Gemini is generative, so it may redraw or simplify the signature. This app now uses Gemini only for cleanup,
then applies local soft transparency and stroke-preserving cleanup.
</div>
""", unsafe_allow_html=True)

top_left, top_right = st.columns([1, 1])

with top_left:
    st.session_state.paid = st.toggle(
        "Paid / unlocked mode",
        value=st.session_state.paid,
        help="Demo switch. Replace with real payment status later.",
    )

with top_right:
    st.caption(
        f"Gemini calls used: {st.session_state.gemini_calls_used} / "
        f"{CONFIG.max_calls_per_session}"
    )

uploaded_file = st.file_uploader(
    "Upload signature photo",
    type=["jpg", "jpeg", "png", "webp"],
)

if uploaded_file:
    original = Image.open(uploaded_file)
    original = fix_image_orientation(original)

    with st.expander("Processing settings", expanded=False):
        model_name = st.text_input("Gemini model", value=CONFIG.gemini_model)
        darkness_threshold = st.slider("Ink detection threshold", 100, 190, 150, 2)
        crop_padding = st.slider("Crop padding", 5, 80, 25, 5)
        alpha_threshold = st.slider("White removal threshold", 235, 254, 248, 1)
        alpha_softness = st.slider("Edge softness", 6, 35, 18, 1)

    if st.button("✨ Extract signature only", type="primary", use_container_width=True):
        start = time.time()

        try:
            with st.spinner("Extracting signature only..."):
                final_img, method, reason = process_signature_only(
                    image=original,
                    model_name=model_name,
                    darkness_threshold=darkness_threshold,
                    crop_padding=crop_padding,
                    alpha_threshold=alpha_threshold,
                    alpha_softness=alpha_softness,
                )

                st.session_state.final_clean_rgba = final_img
                st.session_state.method_used = method
                st.session_state.quality_reason = reason

            elapsed = time.time() - start
            st.success(f"Done in {elapsed:.2f} seconds.")

        except Exception as e:
            st.error(f"Processing failed: {e}")

if st.session_state.final_clean_rgba is not None:
    st.markdown("---")

    st.info(
        f"Method used: {st.session_state.method_used} — "
        f"{st.session_state.quality_reason}"
    )

    preview_img = get_user_visible_preview(
        st.session_state.final_clean_rgba,
        paid=st.session_state.paid,
    )

    st.markdown('<div class="result-card">', unsafe_allow_html=True)

    st.image(
        preview_transparent_image(preview_img),
        caption=(
            f"Signature only — "
            f"{st.session_state.final_clean_rgba.width}px × "
            f"{st.session_state.final_clean_rgba.height}px"
        ),
        use_container_width=False,
    )

    if st.session_state.paid:
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
        st.warning("Unlock to download the clean transparent PNG and Word-ready file.")
        st.caption("Preview is watermarked to discourage screenshot reuse.")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.markdown(
    '<div class="footer-note">Signature-only transparent PNG extractor with stroke-preserving cleanup</div>',
    unsafe_allow_html=True,
)