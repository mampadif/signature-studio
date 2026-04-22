# signature.py
"""
🖊️ Signature Studio – Fast, Transparent, Monetized
- Upload signature photo → remove background → transparent PNG
- Generate cursive signature from name
- Practice canvas with checkerboard transparency preview
- Free watermark preview; one‑time payment (Stripe/PayPal) or unlock code
- Optimized with NumPy for speed (falls back to pure PIL)
"""

import streamlit as st
import io
import base64
import os
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Try to import numpy for fast background removal
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Optional: Stripe integration
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

# Optional: Drawing canvas
try:
    from streamlit_drawable_canvas import st_canvas
    CANVAS_AVAILABLE = True
except ImportError:
    CANVAS_AVAILABLE = False

st.set_page_config(page_title="Signature Studio", page_icon="🖊️", layout="wide")

# ---------------------------
# Custom CSS for Beautiful UI
# ---------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        text-align: center;
        padding: 2rem 1rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        margin-bottom: 2rem;
        color: white;
    }
    
    .main-header h1 {
        font-size: 2.8rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    .main-header p {
        font-size: 1.2rem;
        opacity: 0.95;
    }
    
    .feature-card {
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
        border: 1px solid #e9eef3;
        transition: transform 0.2s ease;
        height: 100%;
    }
    
    .feature-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 20px 30px -10px rgba(0, 0, 0, 0.15);
    }
    
    .price-tag {
        font-size: 2.5rem;
        font-weight: 700;
        color: #4a5568;
        margin: 1rem 0;
    }
    
    .price-tag small {
        font-size: 1rem;
        font-weight: 400;
        color: #718096;
    }
    
    .watermark-badge {
        background: #fed7d7;
        color: #c53030;
        padding: 0.5rem 1rem;
        border-radius: 40px;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 1rem;
    }
    
    .unlocked-badge {
        background: #c6f6d5;
        color: #276749;
        padding: 0.5rem 1rem;
        border-radius: 40px;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 1rem;
    }
    
    .stButton > button {
        border-radius: 40px;
        font-weight: 600;
        padding: 0.5rem 1.5rem;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
    }
    
    .tip-box {
        background: #f7fafc;
        border-left: 4px solid #667eea;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    @media (prefers-color-scheme: dark) {
        .feature-card {
            background: #1e293b;
            border-color: #334155;
        }
        .price-tag {
            color: #f1f5f9;
        }
        .tip-box {
            background: #1e293b;
            border-left-color: #8b5cf6;
        }
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------
# Configuration (Set in .streamlit/secrets.toml or env vars)
# ---------------------------
STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", ""))
STRIPE_PRICE_ID_SIGNATURE = st.secrets.get("STRIPE_PRICE_ID_SIGNATURE", os.getenv("STRIPE_PRICE_ID_SIGNATURE", ""))
PAYPAL_EMAIL = st.secrets.get("PAYPAL_EMAIL", "mampadif@gmail.com")
APP_URL = st.secrets.get("APP_URL", os.getenv("APP_URL", "http://localhost:8501"))
UNLOCK_CODE_SECRET = st.secrets.get("UNLOCK_CODE", os.getenv("UNLOCK_CODE", "signature2026"))

PAYPAL_LINK = f"https://paypal.me/{PAYPAL_EMAIL.split('@')[0]}/3.99" if PAYPAL_EMAIL else "https://paypal.me/mampadif/3.99"

if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ---------------------------
# Session State
# ---------------------------
if "signature_paid" not in st.session_state:
    st.session_state.signature_paid = False

query_params = st.query_params
if "signature_success" in query_params:
    st.session_state.signature_paid = True
    st.query_params.clear()
    st.rerun()

# ---------------------------
# Helper Functions
# ---------------------------
def smart_resize_for_processing(image: Image.Image, max_pixels: int = 1200) -> Image.Image:
    """Resize image if larger than max_pixels to speed up processing."""
    width, height = image.size
    if max(width, height) > max_pixels:
        ratio = max_pixels / max(width, height)
        new_size = (int(width * ratio), int(height * ratio))
        return image.resize(new_size, Image.Resampling.LANCZOS)
    return image.copy()

def remove_white_background_fast(image: Image.Image, threshold: int = 240) -> Image.Image:
    """Remove white/near-white pixels. Uses NumPy if available for speed."""
    image = image.convert("RGBA")
    
    if HAS_NUMPY:
        arr = np.array(image)
        white_mask = (arr[:,:,0] > threshold) & (arr[:,:,1] > threshold) & (arr[:,:,2] > threshold)
        arr[white_mask, 3] = 0
        return Image.fromarray(arr, mode="RGBA")
    else:
        data = image.getdata()
        new_data = []
        for item in data:
            if item[0] > threshold and item[1] > threshold and item[2] > threshold:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        image.putdata(new_data)
        return image

def resize_image(image: Image.Image, size_preset: str, custom_width: int = None) -> Image.Image:
    """Resize based on preset or keep original."""
    if size_preset == "Original":
        return image.copy()
    elif size_preset == "Small":
        max_size = (300, 100)
    elif size_preset == "Medium":
        max_size = (450, 150)
    elif size_preset == "Large":
        max_size = (600, 200)
    elif size_preset == "Custom" and custom_width:
        max_size = (custom_width, 1000)  # Height will be proportional
    else:
        return image.copy()
    
    img = image.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return img

def create_checkerboard_bg(size: tuple, square_size: int = 15) -> Image.Image:
    """Create a checkerboard pattern to preview transparency."""
    bg = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(0, size[1], square_size):
        for x in range(0, size[0], square_size):
            if (x // square_size + y // square_size) % 2 == 0:
                draw.rectangle([x, y, x+square_size, y+square_size], fill=(220, 220, 220, 255))
    return bg

def preview_transparent_image(sig_img: Image.Image) -> Image.Image:
    """Overlay signature on checkerboard background for clear transparency preview."""
    bg = create_checkerboard_bg(sig_img.size)
    bg.paste(sig_img, (0, 0), sig_img)
    return bg

def add_watermark(image: Image.Image, text: str = "PREVIEW") -> Image.Image:
    """Add a semi-transparent watermark to the bottom-right."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    try:
        font_size = max(16, img.width // 20)
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    width, height = img.size
    x = width - text_width - 10
    y = height - text_height - 10
    draw.text((x, y), text, fill=(128, 128, 128, 180), font=font)
    return img

def get_image_download_link(img: Image.Image, filename: str, text: str) -> str:
    """Generate an HTML download link for a PIL image."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    href = f'<a href="data:image/png;base64,{b64}" download="{filename}" style="text-decoration:none; background:#667eea; color:white; padding:0.5rem 1rem; border-radius:40px; font-weight:600;">{text}</a>'
    return href

def generate_signature_from_text(
    text: str,
    font_style: str = "DancingScript",
    size: int = 80,
    color: tuple = (0, 0, 0)
) -> Image.Image:
    """Generate a high-quality signature image from text."""
    font_paths = {
        "DancingScript": "fonts/DancingScript-Regular.ttf",
        "GreatVibes": "fonts/GreatVibes-Regular.ttf",
        "Pacifico": "fonts/Pacifico-Regular.ttf",
        "AlexBrush": "fonts/AlexBrush-Regular.ttf",
    }
    try:
        font = ImageFont.truetype(font_paths.get(font_style, "arial.ttf"), size)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", size)
        except:
            font = ImageFont.load_default()

    temp_img = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    draw = ImageDraw.Draw(temp_img)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    img = Image.new("RGBA", (text_width + 60, text_height + 30), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((30, 15), text, fill=color, font=font)
    return img

# ---------------------------
# Main UI
# ---------------------------
st.markdown("""
<div class="main-header">
    <h1>🖊️ Signature Studio</h1>
    <p>Create a clean, transparent signature for your documents — in seconds.</p>
</div>
""", unsafe_allow_html=True)

# Payment Status Indicator
if not st.session_state.signature_paid:
    st.markdown('<div class="watermark-badge">🔒 FREE PREVIEW — Watermark Applied</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="unlocked-badge">✅ FULL ACCESS — No Watermark</div>', unsafe_allow_html=True)

# Three feature cards
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("""
    <div class="feature-card">
        <h3>📸 Capture & Clean</h3>
        <p>Upload a photo of your signature. Adjust threshold and size, then download a transparent PNG.</p>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown("""
    <div class="feature-card">
        <h3>✍️ Generate from Name</h3>
        <p>Type your name and choose from elegant cursive fonts. Crisp, high‑quality output.</p>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown("""
    <div class="feature-card">
        <h3>🎨 Practice Mode</h3>
        <p>Use the canvas to rehearse. Transparency preview with checkerboard background.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Payment Section
if not st.session_state.signature_paid:
    st.subheader("💳 Unlock Full Access — $3.99 One‑Time")
    st.markdown("Remove the watermark permanently. Pay once, use forever.")
    
    col_pay1, col_pay2 = st.columns(2)
    with col_pay1:
        st.markdown('<div class="price-tag">$3.99 <small>USD</small></div>', unsafe_allow_html=True)
        if STRIPE_AVAILABLE and STRIPE_PRICE_ID_SIGNATURE:
            if st.button("💳 Pay with Stripe", key="stripe_btn", use_container_width=True):
                try:
                    session = stripe.checkout.Session.create(
                        payment_method_types=["card"],
                        line_items=[{"price": STRIPE_PRICE_ID_SIGNATURE, "quantity": 1}],
                        mode="payment",
                        success_url=APP_URL + "?signature_success=true",
                        cancel_url=APP_URL,
                    )
                    st.markdown(f'<meta http-equiv="refresh" content="0; url={session.url}">', unsafe_allow_html=True)
                    st.success("Redirecting to secure Stripe checkout...")
                except Exception as e:
                    st.error(f"Stripe error: {e}")
        else:
            st.info("Stripe not configured. Use PayPal or contact support.")
    with col_pay2:
        st.markdown(f"""
        <a href="{PAYPAL_LINK}" target="_blank">
            <button style="width:100%; padding:0.75rem; border-radius:40px; background:#0070ba; color:white; border:none; font-weight:600;">
                🅿️ Pay with PayPal
            </button>
        </a>
        """, unsafe_allow_html=True)
        st.caption("After payment, refresh this page to unlock.")
    
    # Unlock Code Section
    st.divider()
    st.caption("🔓 Have an unlock code?")
    col_code1, col_code2 = st.columns([3, 1])
    with col_code1:
        unlock_input = st.text_input("Enter code", type="password", key="unlock_input", label_visibility="collapsed", placeholder="Enter your secret code")
    with col_code2:
        if st.button("Redeem", key="redeem_btn", use_container_width=True):
            if unlock_input and unlock_input == UNLOCK_CODE_SECRET:
                st.session_state.signature_paid = True
                st.success("✅ Code accepted! Full access unlocked.")
                st.rerun()
            else:
                st.error("❌ Invalid code.")
else:
    st.success("🎉 You have full access! All downloads are watermark‑free.")
    if st.button("🔓 Sign Out / Reset Access"):
        st.session_state.signature_paid = False
        st.rerun()

st.divider()

# Tabs
tab1, tab2, tab3 = st.tabs(["📸 Capture & Clean", "✍️ Generate from Name", "🎨 Practice Mode"])

# ----- Tab 1: Upload & Clean (Optimized) -----
with tab1:
    st.subheader("Upload a photo of your signature")
    st.markdown("""
    <div class="tip-box">
        <strong>📝 Tips for best results:</strong><br>
        • Sign on plain <strong>white paper</strong> with a dark pen.<br>
        • Use good lighting — avoid shadows.<br>
        • Hold your phone steady and get close.
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Choose an image (JPG/PNG)", type=["jpg", "jpeg", "png"], key="upload")
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="Original", width=300)
        
        # Auto-resize for performance
        image = smart_resize_for_processing(image, max_pixels=1200)
        
        col_set1, col_set2 = st.columns(2)
        with col_set1:
            threshold = st.slider("White threshold (lower = more aggressive removal)", 180, 255, 240, 5)
        with col_set2:
            size_preset = st.selectbox("Output size", ["Original", "Small", "Medium", "Large", "Custom"])
        
        custom_width = None
        if size_preset == "Custom":
            custom_width = st.number_input("Custom width (pixels)", min_value=100, max_value=1200, value=400, step=50)
            size_key = "Custom"
        else:
            size_key = size_preset.split(" ")[0]
        
        if st.button("Process Signature", key="process_upload", type="primary"):
            start_time = time.time()
            with st.spinner("Removing background..."):
                cleaned = remove_white_background_fast(image, threshold)
                resized = resize_image(cleaned, size_key, custom_width)
                resized = resized.filter(ImageFilter.SHARPEN)
                if not st.session_state.signature_paid:
                    resized = add_watermark(resized)
                elapsed = time.time() - start_time
                st.success(f"✅ Done in {elapsed:.2f} seconds")
                preview = preview_transparent_image(resized)
                st.image(preview, caption="Processed Signature (checkerboard shows transparency)", width=400)
                st.markdown(get_image_download_link(resized, "signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)

# ----- Tab 2: Generate from Name -----
with tab2:
    st.subheader("Generate a signature from your name")
    name = st.text_input("Enter your full name", "John Doe")
    col_font1, col_font2 = st.columns(2)
    with col_font1:
        font_choice = st.selectbox("Font Style", ["DancingScript", "GreatVibes", "Pacifico", "AlexBrush"])
    with col_font2:
        size = st.slider("Font Size", 40, 150, 80)
    color = st.color_picker("Ink Color", "#000000")
    
    if st.button("Generate Signature", key="generate"):
        sig_img = generate_signature_from_text(name, font_choice, size, color)
        sig_img = sig_img.filter(ImageFilter.SHARPEN)
        if not st.session_state.signature_paid:
            sig_img = add_watermark(sig_img)
        preview = preview_transparent_image(sig_img)
        st.image(preview, caption="Generated Signature", width=400)
        st.markdown(get_image_download_link(sig_img, "generated_signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)
        st.caption("Note: This is a stylized text rendering, not a secure digital signature.")

# ----- Tab 3: Practice Mode -----
with tab3:
    st.subheader("Practice your signature")
    if CANVAS_AVAILABLE:
        st.markdown("Draw directly below to practice. Your strokes are converted to a transparent PNG.")
        canvas_result = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=3,
            stroke_color="#000000",
            background_color="#ffffff",
            height=200,
            width=500,
            drawing_mode="freedraw",
            key="signature_canvas",
        )
        if canvas_result.image_data is not None:
            img = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            cleaned = remove_white_background_fast(img, threshold=240)
            cleaned = resize_image(cleaned, "Medium")
            cleaned = cleaned.filter(ImageFilter.SHARPEN)
            if not st.session_state.signature_paid:
                cleaned = add_watermark(cleaned)
            preview = preview_transparent_image(cleaned)
            st.image(preview, caption="Your Practice Signature", width=400)
            st.markdown(get_image_download_link(cleaned, "practice_signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)
    else:
        st.warning("Install `streamlit-drawable-canvas` to enable practice mode: `pip install streamlit-drawable-canvas`")

st.markdown("---")
st.caption("© 2026 Signature Studio | Need help? Contact support.")