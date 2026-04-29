import base64
import io
import streamlit as st
import numpy as np
from dataclasses import dataclass
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

# =========================================================
# 1. IMPORTS & COMPATIBILITY
# =========================================================
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

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


# =========================================================
# 2. CONFIGURATION
# =========================================================
@dataclass
class AppConfig:
    api_key: str = st.secrets.get("GEMINI_API_KEY", "")
    ai_model: str = st.secrets.get("GEMINI_MODEL", "gemini-3.1-flash-image-preview")
    app_name: str = st.secrets.get("APP_NAME", "Signature Studio Pro")
    max_calls: int = int(st.secrets.get("MAX_AI_CALLS_PER_SESSION", 3))
    stripe_sk: str = st.secrets.get("STRIPE_SECRET_KEY", "")
    stripe_price_id: str = st.secrets.get("STRIPE_PRICE_ID_SIGNATURE", "")
    paypal_url: str = st.secrets.get("PAYPAL_PAYMENT_URL", "")
    app_url: str = st.secrets.get("APP_URL", "")
    unlock_code: str = st.secrets.get("UNLOCK_CODE", "1234")
    price: str = st.secrets.get("PRICE_DISPLAY", "$3.99")


CONFIG = AppConfig()

st.set_page_config(
    page_title=CONFIG.app_name,
    page_icon="🖊️",
    layout="wide"
)


# =========================================================
# 3. SESSION STATE
# =========================================================
defaults = {
    "paid": False,
    "ai_calls_used": 0,
    "base_image": None,
    "final_clean_rgba": None,
    "uploaded_filename": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# 4. CSS
# =========================================================
st.markdown("""
<style>
    .stApp {
        background: #F8FAFC;
    }

    .compact-header {
        background: linear-gradient(135deg, #0F172A 0%, #6366F1 100%);
        border-radius: 16px;
        padding: 1.25rem 2rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .compact-header h1 {
        color: white;
        font-size: 1.75rem;
        font-weight: 800;
        margin: 0;
    }

    .compact-header p {
        color: rgba(255,255,255,0.85);
        margin: 0;
        font-size: 0.85rem;
    }

    .logo-icon {
        font-size: 2.5rem;
    }

    .compact-card {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.25rem;
    }

    .preview-box {
        background: #FFFFFF;
        border: 2px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.5rem;
        min-height: 300px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        position: relative;
    }

    .preview-box.watermarked::after {
        content: "PREVIEW";
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%) rotate(-25deg);
        font-size: 2rem;
        font-weight: 800;
        color: rgba(150, 150, 150, 0.55);
        white-space: nowrap;
        pointer-events: none;
        letter-spacing: 0.45rem;
        z-index: 2;
    }

    .payment-strip {
        background: linear-gradient(90deg, #FFF7ED, #FFFBEB);
        border: 1px solid #FED7AA;
        border-radius: 12px;
        padding: 1rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.25rem 0.75rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .badge-warning {
        background: #FEF3C7;
        color: #92400E;
    }

    .badge-success {
        background: #D1FAE5;
        color: #065F46;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0F172A, #1E293B);
        border-right: none;
    }

    [data-testid="stSidebar"] * {
        color: #E2E8F0 !important;
    }

    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# =========================================================
# 5. BASIC IMAGE HELPERS
# =========================================================
def fix_image_orientation(image: Image.Image) -> Image.Image:
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def ensure_pil_image(obj) -> Image.Image:
    if isinstance(obj, Image.Image):
        return obj.convert("RGBA")
    if hasattr(obj, "convert"):
        return obj.convert("RGBA")
    raise TypeError(f"Unsupported image object: {type(obj)}")


def smart_resize_for_processing(image: Image.Image, max_pixels: int = 2400) -> Image.Image:
    w, h = image.size
    if max(w, h) <= max_pixels:
        return image.copy()

    ratio = max_pixels / max(w, h)
    return image.resize(
        (int(w * ratio), int(h * ratio)),
        Image.Resampling.LANCZOS
    )


def png_bytes_to_base64(img_bytes: bytes) -> str:
    return base64.b64encode(img_bytes).decode("utf-8")


def preview_html_image(img_bytes: bytes, width: int = 520, height: int = 260) -> str:
    b64 = png_bytes_to_base64(img_bytes)
    wclass = " watermarked" if not st.session_state.paid else ""

    return f"""
    <div class="preview-box{wclass}">
        <img
            src="data:image/png;base64,{b64}"
            style="
                width: {width}px;
                height: {height}px;
                object-fit: contain;
                background: white;
                display: block;
                margin: auto;
            "
        />
    </div>
    """


# =========================================================
# 6. COMPONENT DETECTION
# =========================================================
def connected_components(mask: np.ndarray):
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = []

    for y in range(h):
        for x in range(w):
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
                        if 0 <= ny < h and 0 <= nx < w:
                            if mask[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((ny, nx))

            components.append(pixels)

    return components


def detect_signature_bbox(
    image: Image.Image,
    darkness_threshold: int = 170,
    padding: int = 35
) -> Image.Image:
    """
    Attempts to crop around the signature area only.
    Avoids large dark borders and solid background blocks.
    """
    image = image.convert("RGB")
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
        return image

    best_pixels = max(candidates, key=lambda t: t[0])[1]

    ys = [p[0] for p in best_pixels]
    xs = [p[1] for p in best_pixels]

    y1, y2 = min(ys), max(ys)
    x1, x2 = min(xs), max(xs)

    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)

    return image.crop((x1, y1, x2, y2))


def enhance_crop_before_extraction(image: Image.Image, min_width: int = 1200) -> Image.Image:
    img = image.convert("RGB")

    if img.width < min_width:
        ratio = min_width / max(1, img.width)
        img = img.resize(
            (int(img.width * ratio), int(img.height * ratio)),
            Image.Resampling.LANCZOS
        )

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


# =========================================================
# 7. BACKGROUND AND TRANSPARENCY PIPELINE
# =========================================================
def force_black_ink_on_white(image: Image.Image, threshold: int = 180) -> Image.Image:
    """
    Converts any AI/local output into a safe white-background base image.
    This prevents black opaque backgrounds from entering the preview.
    """
    img = image.convert("RGB")
    arr = np.array(img, dtype=np.uint8)

    gray = (
        0.299 * arr[:, :, 0]
        + 0.587 * arr[:, :, 1]
        + 0.114 * arr[:, :, 2]
    )

    ink = gray < threshold

    output = np.full_like(arr, 255)
    output[ink] = [0, 0, 0]

    return Image.fromarray(output, mode="RGB").convert("RGBA")


def white_to_transparent_soft(
    image: Image.Image,
    threshold: int = 248,
    softness: int = 18
) -> Image.Image:
    """
    Slider-controlled transparency:
    - threshold removes white/light background
    - softness controls edge blending
    """
    image = ensure_pil_image(image)
    arr = np.array(image, dtype=np.uint8)

    rgb = arr[:, :, :3]
    brightness = rgb.mean(axis=2)

    soft_start = max(0, threshold - softness)
    denom = max(1, threshold - soft_start)

    alpha = np.where(
        brightness >= threshold,
        0,
        np.where(
            brightness <= soft_start,
            255,
            ((threshold - brightness) / denom * 255)
        )
    ).astype(np.uint8)

    arr[:, :, 3] = alpha

    ink = alpha > 0
    arr[ink, 0:3] = 0

    return Image.fromarray(arr, mode="RGBA")


def remove_small_noise(image: Image.Image, alpha_cutoff: int = 25) -> Image.Image:
    image = image.convert("RGBA")
    arr = np.array(image, dtype=np.uint8)

    alpha = arr[:, :, 3]
    alpha[alpha < alpha_cutoff] = 0
    arr[:, :, 3] = alpha

    ink = arr[:, :, 3] > 0
    arr[ink, 0:3] = 0

    return Image.fromarray(arr, mode="RGBA")


def keep_signature_cluster_only(
    image: Image.Image,
    min_area: int = 20,
    margin: int = 45
) -> Image.Image:
    image = image.convert("RGBA")
    arr = np.array(image, dtype=np.uint8)

    mask = arr[:, :, 3] > 0
    components = [c for c in connected_components(mask) if len(c) >= min_area]

    if not components:
        return image

    main = max(components, key=len)

    main_ys = [p[0] for p in main]
    main_xs = [p[1] for p in main]

    my1, my2 = min(main_ys), max(main_ys)
    mx1, mx2 = min(main_xs), max(main_xs)

    keep = np.zeros_like(mask, dtype=bool)

    for comp in components:
        ys = [p[0] for p in comp]
        xs = [p[1] for p in comp]

        y1, y2 = min(ys), max(ys)
        x1, x2 = min(xs), max(xs)

        close_to_main = not (
            x2 < mx1 - margin or
            x1 > mx2 + margin or
            y2 < my1 - margin or
            y1 > my2 + margin
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

    l, t, r, b = bbox

    return image.crop((
        max(0, l - padding),
        max(0, t - padding),
        min(image.width, r + padding),
        min(image.height, b + padding)
    ))


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
    max_w: int = 700,
    max_h: int = 240
) -> Image.Image:
    img = image.copy()
    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return img


def finalize_signature_only(image: Image.Image) -> Image.Image:
    image = ensure_pil_image(image)

    image = remove_small_noise(image, 25)
    image = keep_signature_cluster_only(image, 20, 45)
    image = tight_crop_alpha(image, 10)
    image = center_signature_canvas(image)
    image = resize_signature_only(image, 700, 240)

    image = remove_small_noise(image, 18)
    image = keep_signature_cluster_only(image, 12, 35)
    image = tight_crop_alpha(image, 8)
    image = center_signature_canvas(image)

    return image


def render_signature_on_white(
    sig_img: Image.Image,
    box_w: int = 520,
    box_h: int = 260
) -> bytes:
    """
    Creates a clean white preview image so transparent areas never appear black.
    The signature keeps its natural aspect ratio.
    """
    sig = sig_img.convert("RGBA")

    bbox = sig.getchannel("A").getbbox()
    if bbox:
        sig = sig.crop(bbox)

    sig.thumbnail((box_w - 40, box_h - 40), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (box_w, box_h), "white")
    x = (box_w - sig.width) // 2
    y = (box_h - sig.height) // 2

    canvas.paste(sig, (x, y), sig)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


# =========================================================
# 8. AI EXTRACTION
# =========================================================
def ask_ai_extract_signature_only(
    cropped_image: Image.Image,
    model_name: str
) -> Image.Image:
    client = genai.Client(api_key=CONFIG.api_key)

    prompt = """
Extract ONLY the handwritten signature ink.
Remove paper, background, shadows, borders, and objects.
Return black signature ink on a clean white background.
Keep the original signature shape and proportions.
"""

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, cropped_image]
    )

    st.session_state.ai_calls_used += 1

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

    raise RuntimeError("AI did not return an image.")


# =========================================================
# 9. MAIN EXTRACTION
# =========================================================
def extract_base_image(original: Image.Image) -> Image.Image | None:
    """
    Extracts a safe black-ink-on-white base image once.
    Sliders then update transparency live without using more AI calls.
    """
    image = fix_image_orientation(original)
    image = smart_resize_for_processing(image, 2400)

    crop = detect_signature_bbox(image, 170, 35)
    enhanced = enhance_crop_before_extraction(crop, 1200)

    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            cleaned = ask_ai_extract_signature_only(enhanced, CONFIG.ai_model)
            return force_black_ink_on_white(cleaned, threshold=180)
        except Exception:
            pass

    return force_black_ink_on_white(enhanced, threshold=180)


def build_final_from_sliders(
    base_image: Image.Image,
    threshold: int,
    softness: int
) -> Image.Image:
    transparent = white_to_transparent_soft(
        base_image,
        threshold=threshold,
        softness=softness
    )

    final_rgba = finalize_signature_only(transparent)
    return final_rgba


# =========================================================
# 10. SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    a_thresh = st.slider(
        "Threshold",
        200,
        255,
        248,
        help="Higher values remove more white background."
    )

    softness = st.slider(
        "Smoothing",
        5,
        45,
        18,
        help="Higher values make the signature edges softer."
    )

    st.divider()

    st.markdown(
        f"🖊️ AI calls: **{st.session_state.ai_calls_used}/{CONFIG.max_calls}**"
    )

    if st.button("🔄 Reset", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# =========================================================
# 11. HEADER
# =========================================================
st.markdown(f"""
<div class="compact-header">
    <div class="logo-icon">🖊️</div>
    <div>
        <h1>{CONFIG.app_name}</h1>
        <p>Professional signature background remover and document-ready exporter</p>
    </div>
</div>
""", unsafe_allow_html=True)


# =========================================================
# 12. PAYMENT RETURN CHECK
# =========================================================
query_params = st.query_params

if query_params.get("paid") == "1":
    st.session_state.paid = True


# =========================================================
# 13. MAIN LAYOUT
# =========================================================
col1, col2 = st.columns([1, 1], gap="medium")

with col1:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)

    st.markdown("#### 📤 Upload Signature Photo")
    st.caption("Use a clear photo of your signature on white paper.")

    file = st.file_uploader(
        "",
        type=["png", "jpg", "jpeg", "webp"],
        label_visibility="collapsed"
    )

    if file:
        if st.session_state.uploaded_filename != file.name:
            st.session_state.uploaded_filename = file.name
            st.session_state.base_image = None
            st.session_state.final_clean_rgba = None

        original = Image.open(file).convert("RGB")

        if st.button(
            "✨ Process Signature",
            type="primary",
            use_container_width=True
        ):
            with st.spinner("Extracting signature..."):
                base = extract_base_image(original)

                if base is not None:
                    st.session_state.base_image = base
                    st.success("✅ Done! Adjust the sliders to fine-tune.")
                else:
                    st.error("Extraction failed. Please try a clearer image.")

    st.markdown('</div>', unsafe_allow_html=True)


with col2:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)

    st.markdown("#### 🎯 Preview")

    if st.session_state.base_image is not None:
        final_rgba = build_final_from_sliders(
            st.session_state.base_image,
            a_thresh,
            softness
        )

        st.session_state.final_clean_rgba = final_rgba

        preview_bytes = render_signature_on_white(
            final_rgba,
            box_w=520,
            box_h=260
        )

        st.markdown(
            preview_html_image(preview_bytes, width=520, height=260),
            unsafe_allow_html=True
        )

        if st.session_state.paid:
            st.markdown(
                '<br><span class="badge badge-success">✅ Unlocked — Full Quality</span>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<br><span class="badge badge-warning">🔒 Preview Only — Unlock for clean download</span>',
                unsafe_allow_html=True
            )
    else:
        st.markdown("""
        <div class="preview-box">
            <p style="color:#94A3B8; text-align:center;">
                Upload a photo and click<br>
                <b>Process Signature</b> to see preview
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# 14. PAYMENT AND DOWNLOAD
# =========================================================
if st.session_state.final_clean_rgba is not None:
    st.markdown("<br>", unsafe_allow_html=True)

    if st.session_state.paid:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)
        st.markdown(
            '<b style="color:#065F46; font-size:1.1rem;">✅ Payment Confirmed — Download Your Files</b>',
            unsafe_allow_html=True
        )

        c1, c2 = st.columns(2)

        with c1:
            png_buf = io.BytesIO()
            st.session_state.final_clean_rgba.save(
                png_buf,
                format="PNG",
                optimize=True
            )

            st.download_button(
                "⬇ PNG",
                png_buf.getvalue(),
                "signature.png",
                "image/png",
                use_container_width=True,
                type="primary"
            )

        with c2:
            if DOCX_AVAILABLE:
                doc = Document()
                doc.add_heading("Signature Asset", level=1)
                doc.add_paragraph(
                    "Place this image above your signature line. "
                    "In Microsoft Word, use Layout → In Front of Text if needed."
                )

                img_s = io.BytesIO()
                st.session_state.final_clean_rgba.save(img_s, format="PNG")
                img_s.seek(0)

                doc.add_picture(img_s, width=Inches(2.5))

                doc_buf = io.BytesIO()
                doc.save(doc_buf)

                st.download_button(
                    "⬇ DOCX",
                    doc_buf.getvalue(),
                    "signature.docx",
                    use_container_width=True,
                    type="secondary"
                )
            else:
                st.info("DOCX export unavailable. Install python-docx.")

        st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)

        st.markdown(
            f'<b style="font-size:1.1rem;">🔓 Unlock clean download — {CONFIG.price}</b>',
            unsafe_allow_html=True
        )

        bc1, bc2, bc3 = st.columns([1, 1, 1.5], gap="small")

        with bc1:
            if st.button("💳 Pay with Card", use_container_width=True):
                if STRIPE_AVAILABLE and CONFIG.stripe_sk and CONFIG.stripe_price_id:
                    try:
                        stripe.api_key = CONFIG.stripe_sk

                        session = stripe.checkout.Session.create(
                            mode="payment",
                            line_items=[
                                {
                                    "price": CONFIG.stripe_price_id,
                                    "quantity": 1
                                }
                            ],
                            success_url=(
                                f"{CONFIG.app_url}"
                                "?paid=1&session_id={CHECKOUT_SESSION_ID}"
                            ),
                            cancel_url=CONFIG.app_url
                        )

                        st.markdown(
                            f"""
                            <meta http-equiv="refresh" content="0;URL='{session.url}'" />
                            """,
                            unsafe_allow_html=True
                        )

                    except Exception:
                        st.error("Card payment is currently unavailable.")
                else:
                    st.warning("Card payment is not configured.")

        with bc2:
            if CONFIG.paypal_url:
                st.link_button(
                    "🔵 PayPal",
                    CONFIG.paypal_url,
                    use_container_width=True
                )
            else:
                st.warning("PayPal is not configured.")

        with bc3:
            with st.popover("🔑 Use Code"):
                code = st.text_input(
                    "Access code",
                    type="password",
                    key="unlock_code_input"
                )

                if st.button("Unlock", use_container_width=True):
                    if code.strip() == CONFIG.unlock_code.strip():
                        st.session_state.paid = True
                        st.success("Unlocked!")
                        st.rerun()
                    else:
                        st.error("Invalid code.")

        st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# 15. FOOTER
# =========================================================
st.markdown(
    """
    <div style="
        text-align:center;
        color:#94A3B8;
        font-size:0.75rem;
        padding:1rem 0;
        border-top:1px solid #E2E8F0;
        margin-top:1rem;">
        © 2026 Technoworks Pty Ltd · Signature Studio Pro
    </div>
    """,
    unsafe_allow_html=True
)