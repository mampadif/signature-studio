# signature.py
"""
🖊️ Signature Studio
- Upload a photo of your signature → remove white background → transparent PNG
- Generate a cursive signature from your name
- Practice drawing with a canvas
- Free preview with watermark; one‑time payment removes watermark.
"""

import streamlit as st
import io
import base64
import os
from PIL import Image, ImageDraw, ImageFont

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
    /* Import Google Fonts */
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
    
    .btn-stripe {
        background: #635BFF;
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 40px;
        font-weight: 600;
        width: 100%;
        transition: all 0.2s;
    }
    
    .btn-stripe:hover {
        background: #4f46e5;
        transform: scale(1.02);
    }
    
    .btn-paypal {
        background: #0070ba;
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 40px;
        font-weight: 600;
        width: 100%;
        transition: all 0.2s;
    }
    
    .btn-paypal:hover {
        background: #005ea6;
        transform: scale(1.02);
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
    
    /* Dark mode adjustments */
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

# Build PayPal.me link with amount
PAYPAL_LINK = f"https://paypal.me/{PAYPAL_EMAIL.split('@')[0]}/3.99" if PAYPAL_EMAIL else "https://paypal.me/mampadif/3.99"

if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# ---------------------------
# Session State
# ---------------------------
if "signature_paid" not in st.session_state:
    st.session_state.signature_paid = False

# Check for successful Stripe redirect
query_params = st.query_params
if "signature_success" in query_params:
    st.session_state.signature_paid = True
    st.query_params.clear()
    st.rerun()

# ---------------------------
# Helper Functions
# ---------------------------
def remove_white_background(image: Image.Image, threshold: int = 240) -> Image.Image:
    """Convert white/near-white pixels to transparent."""
    image = image.convert("RGBA")
    data = image.getdata()
    new_data = []
    for item in data:
        if item[0] > threshold and item[1] > threshold and item[2] > threshold:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    image.putdata(new_data)
    return image

def resize_for_document(image: Image.Image, max_width: int = 400, max_height: int = 150) -> Image.Image:
    """Resize image to fit typical signature placeholder (maintains aspect ratio)."""
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return image

def add_watermark(image: Image.Image, text: str = "PREVIEW") -> Image.Image:
    """Add a semi-transparent watermark to the image."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    width, height = img.size
    x = width - text_width - 10
    y = height - text_height - 10
    draw.text((x, y), text, fill=(200, 200, 200, 180), font=font)
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
    size: int = 60,
    color: tuple = (0, 0, 0)
) -> Image.Image:
    """Generate a signature image from text using a cursive font."""
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

    img = Image.new("RGBA", (text_width + 40, text_height + 20), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((20, 10), text, fill=color, font=font)
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

# Three feature columns for quick overview
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("""
    <div class="feature-card">
        <h3>📸 Capture & Clean</h3>
        <p>Upload a photo of your signature on white paper. We'll remove the background and give you a transparent PNG ready for documents.</p>
        <p style="font-size:0.9rem; color:#718096;">💡 <em>Practice on paper first, then snap a photo!</em></p>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown("""
    <div class="feature-card">
        <h3>✍️ Generate from Name</h3>
        <p>Type your name and choose from elegant cursive fonts. Get a stylized signature instantly.</p>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown("""
    <div class="feature-card">
        <h3>🎨 Practice Mode</h3>
        <p>Use the built‑in canvas to rehearse your signature with mouse or touch before committing.</p>
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
            st.info("Stripe not configured. Please use PayPal or contact support.")
    with col_pay2:
        st.markdown(f"""
        <a href="{PAYPAL_LINK}" target="_blank">
            <button class="btn-paypal" style="width:100%; padding:0.75rem; border-radius:40px; background:#0070ba; color:white; border:none; font-weight:600;">
                🅿️ Pay with PayPal
            </button>
        </a>
        """, unsafe_allow_html=True)
        st.caption("You'll be redirected to PayPal. After payment, refresh this page to unlock.")
    
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

# Feature Tabs
tab1, tab2, tab3 = st.tabs(["📸 Capture & Clean", "✍️ Generate from Name", "🎨 Practice Mode"])

with tab1:
    st.subheader("Upload a photo of your signature")
    st.markdown("""
    <div class="tip-box">
        <strong>📝 Tips for best results:</strong><br>
        • Sign on plain <strong>white paper</strong> with a dark pen.<br>
        • Use good lighting — avoid shadows.<br>
        • Hold your phone steady and get close.<br>
        • <em>Practice on paper until you're happy, then snap the final version!</em>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Choose an image (JPG/PNG)", type=["jpg", "jpeg", "png"], key="upload")
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="Original", width=300)

        with st.spinner("Removing background..."):
            cleaned = remove_white_background(image)
            cleaned = resize_for_document(cleaned)

        if not st.session_state.signature_paid:
            cleaned = add_watermark(cleaned)

        st.image(cleaned, caption="Cleaned Signature", width=300)
        st.markdown(get_image_download_link(cleaned, "signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)

with tab2:
    st.subheader("Generate a signature from your name")
    name = st.text_input("Enter your full name", "John Doe")
    col_font1, col_font2 = st.columns(2)
    with col_font1:
        font_choice = st.selectbox("Font Style", ["DancingScript", "GreatVibes", "Pacifico", "AlexBrush"])
    with col_font2:
        size = st.slider("Size", 30, 120, 60)
    color = st.color_picker("Ink Color", "#000000")

    if st.button("Generate Signature", key="generate"):
        sig_img = generate_signature_from_text(name, font_choice, size, color)
        if not st.session_state.signature_paid:
            sig_img = add_watermark(sig_img)
        st.image(sig_img, caption="Generated Signature", width=300)
        st.markdown(get_image_download_link(sig_img, "generated_signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)
        st.caption("Note: This is a stylized text rendering, not a secure digital signature.")

with tab3:
    st.subheader("Practice your signature")
    st.markdown("Draw directly below to practice. Your strokes are converted to a transparent PNG.")
    if CANVAS_AVAILABLE:
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
            cleaned = remove_white_background(img)
            cleaned = resize_for_document(cleaned)
            if not st.session_state.signature_paid:
                cleaned = add_watermark(cleaned)
            st.image(cleaned, caption="Your Practice Signature", width=300)
            st.markdown(get_image_download_link(cleaned, "practice_signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)
    else:
        st.warning("Install `streamlit-drawable-canvas` to enable practice mode: `pip install streamlit-drawable-canvas`")

st.markdown("---")
st.caption("© 2026 Signature Studio | Need help? Contact support.")