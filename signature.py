"""
🖊️ Signature Studio Pro
Polished Streamlit app for:
- Uploading a signature photo
- Automatically removing white background
- Producing true transparent PNGs
- Auto-detecting best threshold
- Auto-cropping to signature bounds
- Generating signature-style text from a name
- Practicing on a canvas
- Optional free preview watermark + paid unlock

Author: Final upgraded version
"""

import streamlit as st
import io
import base64
import os
import time
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageChops

# ---------------------------
# Optional dependencies
# ---------------------------
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
    from streamlit_drawable_canvas import st_canvas
    CANVAS_AVAILABLE = True
except ImportError:
    CANVAS_AVAILABLE = False


# ---------------------------
# Streamlit config
# ---------------------------
st.set_page_config(
    page_title="Signature Studio Pro",
    page_icon="🖊️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------
# App secrets / config
# ---------------------------
STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", ""))
STRIPE_PRICE_ID_SIGNATURE = st.secrets.get(
    "STRIPE_PRICE_ID_SIGNATURE",
    os.getenv("STRIPE_PRICE_ID_SIGNATURE", "")
)
PAYPAL_EMAIL = st.secrets.get("PAYPAL_EMAIL", os.getenv("PAYPAL_EMAIL", "mampadif@gmail.com"))
APP_URL = st.secrets.get("APP_URL", os.getenv("APP_URL", "http://localhost:8501"))
UNLOCK_CODE_SECRET = st.secrets.get("UNLOCK_CODE", os.getenv("UNLOCK_CODE", "signature2026"))

PAYPAL_LINK = (
    f"https://paypal.me/{PAYPAL_EMAIL.split('@')[0]}/3.99"
    if PAYPAL_EMAIL and "@" in PAYPAL_EMAIL
    else "https://paypal.me/mampadif/3.99"
)

if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ---------------------------
# Session state
# ---------------------------
if "signature_paid" not in st.session_state:
    st.session_state.signature_paid = False

if "last_processed" not in st.session_state:
    st.session_state.last_processed = None

if "last_generated" not in st.session_state:
    st.session_state.last_generated = None

if "last_practice" not in st.session_state:
    st.session_state.last_practice = None

query_params = st.query_params
if "signature_success" in query_params:
    st.session_state.signature_paid = True
    st.query_params.clear()
    st.rerun()


# ---------------------------
# CSS
# ---------------------------
st.markdown("""
<style>
    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }

    .hero {
        padding: 2.2rem 2rem;
        border-radius: 28px;
        background: linear-gradient(135deg, #101828 0%, #1d2939 40%, #344054 100%);
        color: white;
        margin-bottom: 1.2rem;
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 18px 50px rgba(16,24,40,0.22);
    }

    .hero h1 {
        margin: 0 0 0.55rem 0;
        font-size: 2.6rem;
        font-weight: 800;
        letter-spacing: -0.03em;
    }

    .hero p {
        margin: 0;
        font-size: 1.05rem;
        color: rgba(255,255,255,0.88);
        line-height: 1.6;
        max-width: 850px;
    }

    .status-pill {
        display: inline-block;
        margin-top: 1rem;
        padding: 0.5rem 0.95rem;
        border-radius: 999px;
        font-size: 0.92rem;
        font-weight: 700;
    }

    .status-free {
        background: #FEF3F2;
        color: #B42318;
        border: 1px solid #FECDCA;
    }

    .status-paid {
        background: #ECFDF3;
        color: #027A48;
        border: 1px solid #ABEFC6;
    }

    .glass-card {
        background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.88));
        border: 1px solid rgba(16,24,40,0.08);
        box-shadow: 0 10px 30px rgba(16,24,40,0.06);
        border-radius: 22px;
        padding: 1.15rem 1.15rem;
        height: 100%;
    }

    .mini-card {
        background: white;
        border: 1px solid #EAECF0;
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 8px 24px rgba(16,24,40,0.05);
        height: 100%;
    }

    .mini-card h3 {
        margin: 0 0 0.4rem 0;
        font-size: 1.08rem;
        font-weight: 750;
        color: #101828;
    }

    .mini-card p {
        margin: 0;
        color: #475467;
        line-height: 1.55;
        font-size: 0.95rem;
    }

    .section-title {
        margin-top: 0.4rem;
        margin-bottom: 0.2rem;
        font-size: 1.3rem;
        font-weight: 780;
        color: #101828;
    }

    .section-sub {
        color: #475467;
        margin-bottom: 0.85rem;
    }

    .tip-box {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #7C3AED;
        padding: 1rem 1rem;
        border-radius: 14px;
        margin-bottom: 1rem;
        color: #334155;
        line-height: 1.55;
    }

    .price-box {
        padding: 1.1rem;
        border-radius: 20px;
        background: linear-gradient(180deg, #FFFFFF, #F8FAFC);
        border: 1px solid #EAECF0;
        box-shadow: 0 8px 25px rgba(16,24,40,0.06);
    }

    .price {
        font-size: 2.2rem;
        font-weight: 800;
        color: #101828;
        line-height: 1;
        margin-bottom: 0.4rem;
    }

    .price small {
        color: #667085;
        font-size: 0.95rem;
        font-weight: 500;
    }

    .soft-note {
        color: #667085;
        font-size: 0.93rem;
    }

    .divider-space {
        margin-top: 0.6rem;
        margin-bottom: 0.6rem;
    }

    .footer-note {
        text-align: center;
        color: #667085;
        font-size: 0.9rem;
        margin-top: 1.2rem;
    }

    @media (max-width: 900px) {
        .hero h1 {
            font-size: 2rem;
        }
        .hero {
            padding: 1.5rem 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------
# Helper functions
# ---------------------------
def smart_resize_for_processing(image: Image.Image, max_pixels: int = 1500) -> Image.Image:
    """Resize very large images for faster processing while preserving quality."""
    width, height = image.size
    if max(width, height) <= max_pixels:
        return image.copy()

    ratio = max_pixels / max(width, height)
    new_size = (int(width * ratio), int(height * ratio))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def fix_image_orientation(image: Image.Image) -> Image.Image:
    """Respect EXIF orientation from mobile photos."""
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def estimate_optimal_white_threshold(image: Image.Image) -> int:
    """
    Estimate a good threshold for removing white/near-white paper background.
    Uses bright-pixel analysis.
    """
    rgb = image.convert("RGB")

    if HAS_NUMPY:
        arr = np.array(rgb, dtype=np.uint8)
        brightness = arr.max(axis=2).reshape(-1)

        if brightness.size == 0:
            return 220

        cutoff = np.percentile(brightness, 80)
        bright_pixels = brightness[brightness >= cutoff]

        if bright_pixels.size == 0:
            return 220

        bg_level = int(np.median(bright_pixels))
        threshold = bg_level - 12
        threshold = max(200, min(245, threshold))
        return int(threshold)

    pixels = list(rgb.getdata())
    if not pixels:
        return 220

    brightness = sorted(max(r, g, b) for (r, g, b) in pixels)
    start_idx = int(len(brightness) * 0.8)
    bright_pixels = brightness[start_idx:] if start_idx < len(brightness) else brightness

    if not bright_pixels:
        return 220

    mid = len(bright_pixels) // 2
    if len(bright_pixels) % 2 == 0:
        bg_level = (bright_pixels[mid - 1] + bright_pixels[mid]) // 2
    else:
        bg_level = bright_pixels[mid]

    threshold = bg_level - 12
    threshold = max(200, min(245, threshold))
    return int(threshold)


def reduce_shadows(image: Image.Image) -> Image.Image:
    """
    Light cleanup for uneven paper lighting before thresholding.
    """
    rgb = image.convert("RGB")
    gray = rgb.convert("L")
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=18))

    # Subtract low-frequency shading
    normalized = ImageChops.screen(gray, ImageOps.invert(blurred))
    normalized = ImageOps.autocontrast(normalized)

    # Merge normalized luminance back into RGB-ish form
    cleaned = Image.merge("RGB", (normalized, normalized, normalized))
    return cleaned


def remove_white_background_fast(
    image: Image.Image,
    threshold: Optional[int] = None,
    auto_detect: bool = True
) -> Tuple[Image.Image, int]:
    """
    Remove white/near-white background and return:
    - transparent RGBA image
    - threshold used
    """
    image = image.convert("RGBA")

    if auto_detect or threshold is None:
        threshold = estimate_optimal_white_threshold(image)

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)

        white_mask = (
            (arr[:, :, 0] >= threshold) &
            (arr[:, :, 1] >= threshold) &
            (arr[:, :, 2] >= threshold)
        )

        arr[white_mask, 3] = 0
        arr[~white_mask, 3] = 255

        cleaned = Image.fromarray(arr, mode="RGBA")
        return cleaned, int(threshold)

    data = image.getdata()
    new_data = []
    for r, g, b, a in data:
        if r >= threshold and g >= threshold and b >= threshold:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append((r, g, b, 255))

    image.putdata(new_data)
    return image, int(threshold)


def refine_signature_edges(image: Image.Image) -> Image.Image:
    """
    Remove fringe artifacts and make visible signature strokes solid.
    """
    image = image.convert("RGBA")

    if HAS_NUMPY:
        arr = np.array(image, dtype=np.uint8)
        alpha = arr[:, :, 3]

        alpha[alpha < 18] = 0
        alpha[alpha >= 18] = 255

        arr[:, :, 3] = alpha
        out = Image.fromarray(arr, mode="RGBA")
        return out.filter(ImageFilter.SHARPEN)

    data = image.getdata()
    new_data = []
    for r, g, b, a in data:
        if a < 18:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, 255))
    image.putdata(new_data)
    return image.filter(ImageFilter.SHARPEN)


def auto_crop_transparent(image: Image.Image, padding: int = 24) -> Image.Image:
    """
    Crop transparent margins around signature.
    """
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()

    if not bbox:
        return image

    left, upper, right, lower = bbox
    left = max(0, left - padding)
    upper = max(0, upper - padding)
    right = min(image.width, right + padding)
    lower = min(image.height, lower + padding)

    return image.crop((left, upper, right, lower))


def resize_image(image: Image.Image, size_preset: str, custom_width: Optional[int] = None) -> Image.Image:
    """
    Resize image based on preset while preserving aspect ratio.
    """
    if size_preset == "Original":
        return image.copy()
    elif size_preset == "Small":
        max_size = (320, 140)
    elif size_preset == "Medium":
        max_size = (500, 180)
    elif size_preset == "Large":
        max_size = (700, 250)
    elif size_preset == "Custom" and custom_width:
        max_size = (custom_width, 1000)
    else:
        return image.copy()

    img = image.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return img


def create_checkerboard_bg(size: tuple, square_size: int = 16) -> Image.Image:
    """
    Create checkerboard background to show transparency clearly.
    """
    bg = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(bg)

    light = (242, 244, 247, 255)
    dark = (220, 223, 228, 255)

    for y in range(0, size[1], square_size):
        for x in range(0, size[0], square_size):
            fill = light if ((x // square_size + y // square_size) % 2 == 0) else dark
            draw.rectangle([x, y, x + square_size, y + square_size], fill=fill)

    return bg


def preview_transparent_image(sig_img: Image.Image) -> Image.Image:
    """
    Show transparency properly by pasting over checkerboard background.
    """
    sig_img = sig_img.convert("RGBA")
    bg = create_checkerboard_bg(sig_img.size)
    preview = bg.copy()
    preview.paste(sig_img, (0, 0), sig_img)
    return preview


def add_watermark(image: Image.Image, text: str = "PREVIEW") -> Image.Image:
    """
    Add a subtle watermark to preview image.
    """
    img = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font_size = max(18, img.width // 10)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = img.width - text_w - 12
    y = img.height - text_h - 10

    draw.text((x, y), text, fill=(120, 120, 120, 160), font=font)
    return Image.alpha_composite(img, overlay)


def pil_to_download_link(img: Image.Image, filename: str, label: str) -> str:
    """
    Return HTML download link for PNG.
    """
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    return f"""
        <a href="data:image/png;base64,{data}" download="{filename}"
           style="
                display:inline-block;
                text-decoration:none;
                background:linear-gradient(90deg, #111827 0%, #374151 100%);
                color:white;
                padding:0.75rem 1rem;
                border-radius:999px;
                font-weight:700;
                font-size:0.95rem;
            ">{label}</a>
    """


def locate_font_file(candidates) -> Optional[str]:
    """
    Find a usable font file from a list of candidate paths.
    """
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def generate_signature_from_text(
    text: str,
    font_style: str = "Elegant Script",
    size: int = 90,
    color_hex: str = "#000000"
) -> Image.Image:
    """
    Generate transparent signature-style text image.
    """
    color_hex = color_hex.lstrip("#")
    color = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))

    font_map = {
        "Elegant Script": [
            "fonts/GreatVibes-Regular.ttf",
            "fonts/DancingScript-Regular.ttf",
            "fonts/AlexBrush-Regular.ttf",
            "C:/Windows/Fonts/segoesc.ttf",
            "C:/Windows/Fonts/script.ttf",
        ],
        "Smooth Cursive": [
            "fonts/DancingScript-Regular.ttf",
            "fonts/GreatVibes-Regular.ttf",
            "C:/Windows/Fonts/segoesc.ttf",
        ],
        "Bold Signature": [
            "fonts/Pacifico-Regular.ttf",
            "fonts/DancingScript-Regular.ttf",
            "C:/Windows/Fonts/segoesc.ttf",
        ],
        "Classic Hand": [
            "fonts/AlexBrush-Regular.ttf",
            "fonts/GreatVibes-Regular.ttf",
            "C:/Windows/Fonts/segoesc.ttf",
        ],
    }

    font_path = locate_font_file(font_map.get(font_style, []))

    try:
        if font_path:
            font = ImageFont.truetype(font_path, size)
        else:
            font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()

    temp = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    d = ImageDraw.Draw(temp)
    bbox = d.textbbox((0, 0), text, font=font)

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img = Image.new("RGBA", (text_w + 80, text_h + 50), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((40, 20), text, fill=color + (255,), font=font)

    img = auto_crop_transparent(img, padding=12)
    img = refine_signature_edges(img)
    return img


def process_signature_image(
    image: Image.Image,
    auto_threshold: bool = True,
    manual_threshold: Optional[int] = None,
    enable_shadow_cleanup: bool = True,
    enable_auto_crop: bool = True,
    size_preset: str = "Original",
    custom_width: Optional[int] = None
) -> Tuple[Image.Image, int]:
    """
    Full end-to-end signature cleanup pipeline.
    """
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=1500)

    if enable_shadow_cleanup:
        prepped = reduce_shadows(image)
    else:
        prepped = image.convert("RGB")

    cleaned, used_threshold = remove_white_background_fast(
        prepped,
        threshold=manual_threshold,
        auto_detect=auto_threshold
    )

    cleaned = refine_signature_edges(cleaned)

    if enable_auto_crop:
        cleaned = auto_crop_transparent(cleaned, padding=24)

    cleaned = resize_image(cleaned, size_preset, custom_width)
    return cleaned, used_threshold


# ---------------------------
# Hero
# ---------------------------
st.markdown("""
<div class="hero">
    <h1>🖊️ Signature Studio Pro</h1>
    <p>
        Turn a photo of your signature into a clean transparent PNG in seconds.
        Upload, auto-clean, crop, preview on a checkerboard, and download.
        You can also generate a cursive signature from your name or practice directly on canvas.
    </p>
    <div class="status-pill %s">%s</div>
</div>
""" % (
    "status-paid" if st.session_state.signature_paid else "status-free",
    "✅ Full access unlocked — watermark free downloads"
    if st.session_state.signature_paid
    else "🔒 Free preview mode — watermark applied to downloads"
), unsafe_allow_html=True)

# ---------------------------
# Feature cards
# ---------------------------
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""
    <div class="mini-card">
        <h3>📸 Capture & Clean</h3>
        <p>Upload a phone photo of your signature and automatically remove the paper background with true transparency.</p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="mini-card">
        <h3>✍️ Generate from Name</h3>
        <p>Create a polished script-style signature from typed text with multiple signature looks and transparent export.</p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="mini-card">
        <h3>🎨 Practice & Preview</h3>
        <p>Draw directly in the app and instantly preview how your strokes look on a transparent background.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)

# ---------------------------
# Unlock section
# ---------------------------
if not st.session_state.signature_paid:
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("""
        <div class="price-box">
            <div class="section-title">Unlock watermark-free exports</div>
            <div class="section-sub">Pay once and keep full access.</div>
            <div class="price">$3.99 <small>USD one-time</small></div>
            <div class="soft-note">Transparent PNG downloads without the PREVIEW watermark.</div>
        </div>
        """, unsafe_allow_html=True)

    with right:
        pay_col1, pay_col2 = st.columns(2)

        with pay_col1:
            if STRIPE_AVAILABLE and STRIPE_PRICE_ID_SIGNATURE:
                if st.button("💳 Pay with Stripe", use_container_width=True):
                    try:
                        session = stripe.checkout.Session.create(
                            payment_method_types=["card"],
                            line_items=[{"price": STRIPE_PRICE_ID_SIGNATURE, "quantity": 1}],
                            mode="payment",
                            success_url=APP_URL + "?signature_success=true",
                            cancel_url=APP_URL,
                        )
                        st.markdown(
                            f'<meta http-equiv="refresh" content="0; url={session.url}">',
                            unsafe_allow_html=True
                        )
                        st.success("Redirecting to Stripe checkout...")
                    except Exception as e:
                        st.error(f"Stripe error: {e}")
            else:
                st.info("Stripe is not configured. Use PayPal or unlock code.")

        with pay_col2:
            st.markdown(
                f"""
                <a href="{PAYPAL_LINK}" target="_blank" style="text-decoration:none;">
                    <div style="
                        text-align:center;
                        background:#0070BA;
                        color:white;
                        font-weight:700;
                        padding:0.75rem 1rem;
                        border-radius:999px;
                        margin-top:0.1rem;">
                        🅿️ Pay with PayPal
                    </div>
                </a>
                """,
                unsafe_allow_html=True
            )

        st.markdown("##### 🔓 Have an unlock code?")
        code_col1, code_col2 = st.columns([3, 1])
        with code_col1:
            unlock_input = st.text_input(
                "Unlock code",
                type="password",
                label_visibility="collapsed",
                placeholder="Enter your unlock code"
            )
        with code_col2:
            if st.button("Redeem", use_container_width=True):
                if unlock_input and unlock_input == UNLOCK_CODE_SECRET:
                    st.session_state.signature_paid = True
                    st.success("Code accepted. Full access unlocked.")
                    st.rerun()
                else:
                    st.error("Invalid code.")
else:
    done_col1, done_col2 = st.columns([3, 1])
    with done_col1:
        st.success("Full access is active. All downloads are watermark-free.")
    with done_col2:
        if st.button("Reset access", use_container_width=True):
            st.session_state.signature_paid = False
            st.rerun()

st.markdown("---")

# ---------------------------
# Tabs
# ---------------------------
tab1, tab2, tab3 = st.tabs([
    "📸 Capture & Clean",
    "✍️ Generate from Name",
    "🎨 Practice Mode"
])

# ---------------------------
# Tab 1: Capture & Clean
# ---------------------------
with tab1:
    st.markdown('<div class="section-title">Upload and clean your signature</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Best for real signatures written on white paper.</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="tip-box">
        <strong>Best results:</strong><br>
        • Sign on clean white paper<br>
        • Use dark ink<br>
        • Take the photo in even light<br>
        • Keep the paper flat and fill most of the frame
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Choose a JPG or PNG image",
        type=["jpg", "jpeg", "png"],
        key="signature_upload"
    )

    if uploaded_file:
        original = Image.open(uploaded_file)
        original = fix_image_orientation(original)

        preview_col1, preview_col2 = st.columns([1, 1.1])

        with preview_col1:
            st.image(original, caption="Original image", use_container_width=True)

        with preview_col2:
            st.markdown("##### Processing options")
            auto_threshold = st.toggle("Auto-detect best threshold", value=True)
            shadow_cleanup = st.toggle("Reduce paper shadows", value=True)
            auto_crop = st.toggle("Auto-crop to signature", value=True)

            size_preset = st.selectbox(
                "Output size",
                ["Original", "Small", "Medium", "Large", "Custom"],
                index=1
            )

            manual_threshold = None
            if not auto_threshold:
                manual_threshold = st.slider("Manual threshold", 180, 255, 220, 5)

            custom_width = None
            if size_preset == "Custom":
                custom_width = st.number_input(
                    "Custom width (pixels)",
                    min_value=100,
                    max_value=2000,
                    value=600,
                    step=50
                )

            process_now = st.button("✨ Process signature", use_container_width=True, type="primary")

        if process_now:
            start_time = time.time()

            with st.spinner("Cleaning signature..."):
                cleaned, used_threshold = process_signature_image(
                    original,
                    auto_threshold=auto_threshold,
                    manual_threshold=manual_threshold,
                    enable_shadow_cleanup=shadow_cleanup,
                    enable_auto_crop=auto_crop,
                    size_preset=size_preset,
                    custom_width=custom_width
                )

                final_download = cleaned
                if not st.session_state.signature_paid:
                    final_download = add_watermark(final_download)

                preview_img = preview_transparent_image(final_download)
                elapsed = time.time() - start_time

            st.session_state.last_processed = final_download

            st.success(f"Done in {elapsed:.2f} seconds")
            st.caption(
                f"Threshold used: {used_threshold} "
                f"({'auto-detected' if auto_threshold else 'manual'})"
            )

            out_col1, out_col2 = st.columns([1, 1.1])
            with out_col1:
                st.image(preview_img, caption="Processed preview (checkerboard = transparent)", use_container_width=True)
            with out_col2:
                st.markdown("##### Download")
                st.markdown(
                    pil_to_download_link(final_download, "signature.png", "⬇️ Download transparent PNG"),
                    unsafe_allow_html=True
                )
                st.markdown("")
                st.metric("Output width", f"{final_download.width}px")
                st.metric("Output height", f"{final_download.height}px")
                st.info("PNG keeps transparency. Do not export as JPG if you want a transparent background.")

# ---------------------------
# Tab 2: Generate from Name
# ---------------------------
with tab2:
    st.markdown('<div class="section-title">Generate a signature from your name</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Best for mockups, form previews, and stylized signatures.</div>', unsafe_allow_html=True)

    gcol1, gcol2 = st.columns([1, 1])

    with gcol1:
        name = st.text_input("Enter full name", value="John Doe")
        font_style = st.selectbox(
            "Signature style",
            ["Elegant Script", "Smooth Cursive", "Bold Signature", "Classic Hand"]
        )
        size = st.slider("Text size", 40, 160, 92, 2)
        color = st.color_picker("Ink color", "#000000")
        generate_now = st.button("✍️ Generate signature", use_container_width=True, type="primary")

    if generate_now:
        sig_img = generate_signature_from_text(name, font_style, size, color)

        final_generated = sig_img
        if not st.session_state.signature_paid:
            final_generated = add_watermark(final_generated)

        st.session_state.last_generated = final_generated

    with gcol2:
        target_generated = st.session_state.last_generated
        if target_generated is not None:
            st.image(
                preview_transparent_image(target_generated),
                caption="Generated signature preview",
                use_container_width=True
            )
            st.markdown(
                pil_to_download_link(
                    target_generated,
                    "generated_signature.png",
                    "⬇️ Download transparent PNG"
                ),
                unsafe_allow_html=True
            )
            st.caption("This is a stylized text rendering, not a secure cryptographic signature.")
        else:
            st.info("Generate a signature to preview it here.")

# ---------------------------
# Tab 3: Practice Mode
# ---------------------------
with tab3:
    st.markdown('<div class="section-title">Practice your signature</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Draw directly below and export it as a transparent PNG.</div>', unsafe_allow_html=True)

    if CANVAS_AVAILABLE:
        canvas_result = st_canvas(
            fill_color="rgba(255,255,255,0)",
            stroke_width=3,
            stroke_color="#000000",
            background_color="#ffffff",
            height=220,
            width=800,
            drawing_mode="freedraw",
            key="practice_canvas"
        )

        pcol1, pcol2 = st.columns([1, 1])

        with pcol1:
            if st.button("🧹 Convert canvas to transparent PNG", use_container_width=True):
                if canvas_result.image_data is not None:
                    img = Image.fromarray(canvas_result.image_data.astype("uint8"), mode="RGBA")

                    processed, _ = process_signature_image(
                        img,
                        auto_threshold=True,
                        manual_threshold=None,
                        enable_shadow_cleanup=False,
                        enable_auto_crop=True,
                        size_preset="Medium",
                        custom_width=None
                    )

                    if not st.session_state.signature_paid:
                        processed = add_watermark(processed)

                    st.session_state.last_practice = processed
                else:
                    st.warning("Draw something first.")

        with pcol2:
            if st.button("Clear canvas preview memory", use_container_width=True):
                st.session_state.last_practice = None
                st.rerun()

        if st.session_state.last_practice is not None:
            st.image(
                preview_transparent_image(st.session_state.last_practice),
                caption="Practice signature preview",
                use_container_width=False
            )
            st.markdown(
                pil_to_download_link(
                    st.session_state.last_practice,
                    "practice_signature.png",
                    "⬇️ Download transparent PNG"
                ),
                unsafe_allow_html=True
            )
    else:
        st.warning(
            "Practice mode needs streamlit-drawable-canvas.\n\n"
            "Install it with:\n\n"
            "`pip install streamlit-drawable-canvas`"
        )

# ---------------------------
# Footer
# ---------------------------
st.markdown("---")
st.markdown(
    '<div class="footer-note">© 2026 Signature Studio Pro · Clean signatures with real transparency</div>',
    unsafe_allow_html=True
)