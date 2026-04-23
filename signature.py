"""
🖊️ Signature Studio Pro
Clean a photographed signature into a transparent PNG, generate a stylized
signature from a name, or practice on a canvas.

Key improvements:
- Soft background removal to avoid jagged/distorted signatures
- Automatic threshold detection
- Generous auto-crop
- True transparent PNG output
- Checkerboard transparency preview
- Polished Streamlit UI/UX
"""

import base64
import io
import os
import time
from typing import Optional, Tuple

import streamlit as st
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

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
# Secrets / environment
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

if "last_processed_upload" not in st.session_state:
    st.session_state.last_processed_upload = None

if "last_generated_signature" not in st.session_state:
    st.session_state.last_generated_signature = None

if "last_practice_signature" not in st.session_state:
    st.session_state.last_practice_signature = None

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
        max-width: 1200px;
        padding-top: 1.3rem;
        padding-bottom: 2rem;
    }

    .hero {
        padding: 2.2rem 2rem;
        border-radius: 28px;
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 45%, #334155 100%);
        color: white;
        margin-bottom: 1.2rem;
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 18px 55px rgba(15,23,42,0.24);
    }

    .hero h1 {
        margin: 0 0 0.55rem 0;
        font-size: 2.55rem;
        font-weight: 800;
        letter-spacing: -0.03em;
    }

    .hero p {
        margin: 0;
        font-size: 1.03rem;
        color: rgba(255,255,255,0.88);
        line-height: 1.62;
        max-width: 860px;
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

    .mini-card {
        background: white;
        border: 1px solid #EAECF0;
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 8px 24px rgba(16,24,40,0.05);
        height: 100%;
    }

    .mini-card h3 {
        margin: 0 0 0.35rem 0;
        font-size: 1.08rem;
        font-weight: 760;
        color: #101828;
    }

    .mini-card p {
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

    .price-box {
        padding: 1.1rem;
        border-radius: 20px;
        background: linear-gradient(180deg, #FFFFFF, #F8FAFC);
        border: 1px solid #EAECF0;
        box-shadow: 0 8px 25px rgba(16,24,40,0.06);
    }

    .price {
        font-size: 2.15rem;
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
            padding: 1.45rem 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------
# Helper functions
# ---------------------------
def fix_image_orientation(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation for mobile photos."""
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def smart_resize_for_processing(image: Image.Image, max_pixels: int = 2200) -> Image.Image:
    """
    Resize only very large images.
    Small images remain untouched to avoid distortion.
    """
    width, height = image.size
    if max(width, height) <= max_pixels:
        return image.copy()

    ratio = max_pixels / max(width, height)
    new_size = (int(width * ratio), int(height * ratio))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def estimate_background_level(image: Image.Image) -> int:
    """
    Estimate paper brightness using the brightest 10% of the image.
    """
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
    auto_detect: bool = True,
    manual_threshold: Optional[int] = None,
    softness: int = 22
) -> Tuple[Image.Image, int]:
    """
    Soft alpha-based background removal.
    This preserves pen edges better than a harsh binary threshold.
    """
    image = image.convert("RGBA")

    if auto_detect or manual_threshold is None:
        bg_level = estimate_background_level(image)
        threshold = max(205, min(250, bg_level - 8))
    else:
        threshold = manual_threshold

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
        cleaned = Image.fromarray(arr, mode="RGBA")
        return cleaned, int(threshold)

    new_data = []
    for r, g, b, a in image.getdata():
        brightness = (r + g + b) / 3

        if brightness >= threshold:
            new_alpha = 0
        elif brightness <= soft_start:
            new_alpha = 255
        else:
            new_alpha = int((threshold - brightness) / max(1, threshold - soft_start) * 255)

        new_data.append((r, g, b, new_alpha))

    image.putdata(new_data)
    return image, int(threshold)


def clean_alpha_noise(image: Image.Image, min_alpha: int = 10) -> Image.Image:
    """
    Remove faint residual paper noise while keeping soft edges.
    """
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
    """
    Crop transparent margins with generous padding.
    """
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


def resize_image(image: Image.Image, size_preset: str, custom_width: Optional[int] = None) -> Image.Image:
    """Resize while keeping aspect ratio."""
    if size_preset == "Original":
        return image.copy()
    if size_preset == "Small":
        max_size = (500, 220)
    elif size_preset == "Medium":
        max_size = (700, 300)
    elif size_preset == "Large":
        max_size = (1000, 420)
    elif size_preset == "Custom" and custom_width:
        max_size = (custom_width, 2000)
    else:
        return image.copy()

    img = image.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return img


def create_checkerboard_bg(size: tuple, square_size: int = 18) -> Image.Image:
    """Create checkerboard background to preview transparency."""
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
    """Overlay transparent signature on checkerboard."""
    sig_img = sig_img.convert("RGBA")
    bg = create_checkerboard_bg(sig_img.size)
    preview = bg.copy()
    preview.paste(sig_img, (0, 0), sig_img)
    return preview


def add_watermark(image: Image.Image, text: str = "PREVIEW") -> Image.Image:
    """Add subtle watermark in free mode."""
    img = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font_size = max(18, img.width // 9)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    x = img.width - tw - 12
    y = img.height - th - 10

    draw.text((x, y), text, fill=(110, 110, 110, 145), font=font)
    return Image.alpha_composite(img, overlay)


def pil_to_download_link(img: Image.Image, filename: str, label: str) -> str:
    """Create HTML download link for PNG."""
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


def locate_font_file(candidates) -> Optional[str]:
    """Find first available font file from candidate paths."""
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def generate_signature_from_text(
    text: str,
    font_style: str = "Elegant Script",
    size: int = 92,
    color_hex: str = "#000000"
) -> Image.Image:
    """
    Generate a transparent stylized signature from text.
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
    draw = ImageDraw.Draw(temp)
    bbox = draw.textbbox((0, 0), text, font=font)

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img = Image.new("RGBA", (text_w + 80, text_h + 50), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((40, 20), text, fill=color + (255,), font=font)

    return auto_crop_transparent(img, padding=14)


def process_signature_image(
    image: Image.Image,
    auto_threshold: bool = True,
    manual_threshold: Optional[int] = None,
    auto_crop: bool = True,
    size_preset: str = "Original",
    custom_width: Optional[int] = None
) -> Tuple[Image.Image, int]:
    """
    Final non-distorting cleanup pipeline for photographed signatures.
    """
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=2200)

    cleaned, used_threshold = remove_paper_background_soft(
        image,
        auto_detect=auto_threshold,
        manual_threshold=manual_threshold,
        softness=22
    )

    cleaned = clean_alpha_noise(cleaned, min_alpha=10)

    if auto_crop:
        cleaned = auto_crop_transparent(cleaned, padding=40)

    cleaned = resize_image(cleaned, size_preset, custom_width)
    return cleaned, used_threshold


# ---------------------------
# Hero
# ---------------------------
st.markdown("""
<div class="hero">
    <h1>🖊️ Signature Studio Pro</h1>
    <p>
        Turn a real signature photo into a clean transparent PNG without harsh clipping,
        or generate a polished script-style signature from your name. Built for a smoother,
        more convincing result.
    </p>
    <div class="status-pill %s">%s</div>
</div>
""" % (
    "status-paid" if st.session_state.signature_paid else "status-free",
    "✅ Full access unlocked — watermark-free downloads"
    if st.session_state.signature_paid
    else "🔒 Free preview mode — watermark applied"
), unsafe_allow_html=True)

# ---------------------------
# Feature cards
# ---------------------------
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""
    <div class="mini-card">
        <h3>📸 Capture & Clean</h3>
        <p>Upload a photo of your real signature and remove the paper background with soft-edge transparency.</p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="mini-card">
        <h3>✍️ Generate from Name</h3>
        <p>Create a neat script-style signature from typed text for mockups, previews, and forms.</p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="mini-card">
        <h3>🎨 Practice Mode</h3>
        <p>Draw inside the app and instantly turn your strokes into a transparent PNG preview.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("")

# ---------------------------
# Unlock section
# ---------------------------
if not st.session_state.signature_paid:
    left, right = st.columns([1.1, 1])

    with left:
        st.markdown("""
        <div class="price-box">
            <div style="font-size:1.25rem;font-weight:780;color:#101828;margin-bottom:0.2rem;">
                Unlock watermark-free exports
            </div>
            <div style="color:#475467;margin-bottom:0.8rem;">
                Pay once and keep full access.
            </div>
            <div class="price">$3.99 <small>USD one-time</small></div>
            <div class="soft-note">
                Download transparent PNGs without the preview watermark.
            </div>
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
# Tab 1
# ---------------------------
with tab1:
    st.subheader("Upload and clean your real signature")
    st.markdown("""
    <div class="tip-box">
        <strong>Best results:</strong><br>
        • Sign on white paper with dark ink<br>
        • Take the photo close enough so the signature fills more of the frame<br>
        • Avoid strong shadows and blur<br>
        • Keep the phone straight above the paper
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Choose signature image",
        type=["jpg", "jpeg", "png"],
        key="signature_upload"
    )

    if uploaded_file:
        original = Image.open(uploaded_file)
        original = fix_image_orientation(original)

        col1, col2 = st.columns([1, 1.1])

        with col1:
            st.image(original, caption="Original", use_container_width=True)

        with col2:
            st.markdown("#### Processing settings")
            auto_threshold = st.toggle("Auto-detect best threshold", value=True)
            auto_crop = st.toggle("Auto-crop around signature", value=True)

            size_preset = st.selectbox(
                "Output size",
                ["Original", "Small", "Medium", "Large", "Custom"],
                index=1
            )

            manual_threshold = None
            if not auto_threshold:
                manual_threshold = st.slider("Manual threshold", 180, 255, 225, 5)

            custom_width = None
            if size_preset == "Custom":
                custom_width = st.number_input(
                    "Custom width (pixels)",
                    min_value=100,
                    max_value=2000,
                    value=800,
                    step=50
                )

            process_now = st.button("✨ Process signature", type="primary", use_container_width=True)

        if process_now:
            start = time.time()

            with st.spinner("Cleaning signature..."):
                cleaned, used_threshold = process_signature_image(
                    original,
                    auto_threshold=auto_threshold,
                    manual_threshold=manual_threshold,
                    auto_crop=auto_crop,
                    size_preset=size_preset,
                    custom_width=custom_width
                )

                download_img = cleaned
                if not st.session_state.signature_paid:
                    download_img = add_watermark(download_img)

                preview = preview_transparent_image(download_img)
                st.session_state.last_processed_upload = download_img

            elapsed = time.time() - start

            st.success(f"Done in {elapsed:.2f} seconds")
            st.caption(
                f"Threshold used: {used_threshold} "
                f"({'auto' if auto_threshold else 'manual'})"
            )

            out1, out2 = st.columns([1, 1.1])

            with out1:
                st.image(
                    preview,
                    caption="Processed preview (checkerboard = transparency)",
                    use_container_width=True
                )

            with out2:
                st.markdown("#### Download")
                st.markdown(
                    pil_to_download_link(
                        download_img,
                        "signature.png",
                        "⬇️ Download transparent PNG"
                    ),
                    unsafe_allow_html=True
                )
                st.metric("Output width", f"{download_img.width}px")
                st.metric("Output height", f"{download_img.height}px")
                st.info("PNG keeps transparency. JPG does not.")

# ---------------------------
# Tab 2
# ---------------------------
with tab2:
    st.subheader("Generate a signature from your name")
    st.caption("Useful for stylized previews, not as a secure cryptographic signature.")

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

        if not st.session_state.signature_paid:
            sig_img = add_watermark(sig_img)

        st.session_state.last_generated_signature = sig_img

    with gcol2:
        if st.session_state.last_generated_signature is not None:
            st.image(
                preview_transparent_image(st.session_state.last_generated_signature),
                caption="Generated signature preview",
                use_container_width=True
            )
            st.markdown(
                pil_to_download_link(
                    st.session_state.last_generated_signature,
                    "generated_signature.png",
                    "⬇️ Download transparent PNG"
                ),
                unsafe_allow_html=True
            )
        else:
            st.info("Generate a signature to preview it here.")

# ---------------------------
# Tab 3
# ---------------------------
with tab3:
    st.subheader("Practice your signature")
    st.caption("Draw directly below and export it as a transparent PNG.")

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
                        auto_crop=True,
                        size_preset="Medium",
                        custom_width=None
                    )

                    if not st.session_state.signature_paid:
                        processed = add_watermark(processed)

                    st.session_state.last_practice_signature = processed
                else:
                    st.warning("Draw something first.")

        with pcol2:
            if st.button("Clear canvas preview memory", use_container_width=True):
                st.session_state.last_practice_signature = None
                st.rerun()

        if st.session_state.last_practice_signature is not None:
            st.image(
                preview_transparent_image(st.session_state.last_practice_signature),
                caption="Practice signature preview",
                use_container_width=False
            )
            st.markdown(
                pil_to_download_link(
                    st.session_state.last_practice_signature,
                    "practice_signature.png",
                    "⬇️ Download transparent PNG"
                ),
                unsafe_allow_html=True
            )
    else:
        st.warning(
            "Practice mode requires streamlit-drawable-canvas.\n\n"
            "Install it with:\n\n"
            "`pip install streamlit-drawable-canvas`"
        )

# ---------------------------
# Footer
# ---------------------------
st.markdown("---")
st.markdown(
    '<div class="footer-note">© 2026 Signature Studio Pro · Soft-edge transparent signature cleanup</div>',
    unsafe_allow_html=True
)