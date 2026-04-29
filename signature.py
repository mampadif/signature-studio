import base64
import io
import streamlit as st
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional, List
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, PngImagePlugin

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
# 2. CONFIGURATION & STATE
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

# Branding Colors
PRIMARY = "#2563EB"
BG_LIGHT = "#F8FAFC"
TEXT_DARK = "#0F172A"

st.set_page_config(page_title=CONFIG.app_name, page_icon="🖊️", layout="wide")

if "paid" not in st.session_state: st.session_state.paid = False
if "ai_calls_used" not in st.session_state: st.session_state.ai_calls_used = 0
if "final_img" not in st.session_state: st.session_state.final_img = None

# =========================================================
# 3. PREMIUM UI CSS
# =========================================================
st.markdown(f"""
<style>
    /* Global App Overrides */
    .stApp {{ background-color: {BG_LIGHT} !important; }}
    
    /* Hero Section - SaaS Landing Style */
    .hero-box {{
        background: white;
        padding: 3.5rem 2rem;
        border-radius: 32px;
        border: 1px solid #E2E8F0;
        text-align: center;
        margin-bottom: 2.5rem;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05);
    }}
    .hero-box h1 {{
        font-weight: 850 !important;
        background: linear-gradient(90deg, {TEXT_DARK}, {PRIMARY});
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3.5rem !important;
        margin-bottom: 0.5rem;
    }}
    
    /* Result Area with Checkerboard Background */
    .preview-container {{
        background: #ffffff;
        background-image: radial-gradient(#e5e7eb 1px, transparent 1px);
        background-size: 20px 20px;
        border-radius: 24px;
        border: 2px solid #E2E8F0;
        padding: 2rem;
        text-align: center;
    }}

    /* Sidebar Styling */
    [data-testid="stSidebar"] {{
        background-color: white !important;
        border-right: 1px solid #E2E8F0;
    }}

    /* Primary Action Buttons */
    div.stButton > button {{
        background: {PRIMARY} !important;
        color: white !important;
        border-radius: 14px !important;
        height: 3.8rem !important;
        font-weight: 700 !important;
        font-size: 1.1rem !important;
        border: none !important;
        box-shadow: 0 8px 20px -4px rgba(37, 99, 235, 0.4) !important;
        transition: all 0.2s ease;
    }}
    div.stButton > button:hover {{
        transform: translateY(-2px);
        box-shadow: 0 12px 24px -4px rgba(37, 99, 235, 0.5) !important;
    }}

    /* Slider Overrides */
    .stSlider [data-baseweb="slider"] {{
        background-image: linear-gradient(to right, {PRIMARY} 0%, {PRIMARY} 100%) !important;
    }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 4. RESTORED & CORRECTED EXTRACTION ENGINE
# =========================================================

def validate_quality(img: Image.Image) -> Tuple[bool, str]:
    """Ensures input meets technical standards for extraction."""
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape
    if w < 250 or h < 250: return False, "Photo resolution too low for pro extraction."
    gray = (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]).astype(np.uint8)
    ink_ratio = float((gray < 185).sum()) / (w * h)
    if ink_ratio < 0.0002: return False, "No clear signature detected. Try better lighting."
    return True, "Quality Validated"

def process_pipeline(original_img, a_thresh, softness):
    """The master pipeline combining AI unboxing and soft-edge logic."""
    # Start by fixing orientation from EXIF data
    img = ImageOps.exif_transpose(original_img)
    
    # 1. AI EXTRACTION (Targeting Pydantic attributes correctly)
    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            client = genai.Client(api_key=CONFIG.api_key)
            response = client.models.generate_content(
                model=CONFIG.ai_model, 
                contents=["Extract ONLY the signature ink. High contrast black ink on pure white background.", img]
            )
            # Iterate through parts to find the image data and convert to PIL
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') or hasattr(part, 'as_image'):
                    img = part.as_image() # Correct conversion from GenAI object to PIL
                    st.session_state.ai_calls_used += 1
                    break
        except Exception as e:
            st.sidebar.warning("AI processing unavailable; falling back to local engine.")

    # 2. PRO TRANSPARENCY (Restored 'Soft' Logic)
    img = img.convert("RGBA")
    arr = np.array(img)
    brightness = arr[:, :, :3].mean(axis=2)
    
    # Calculate alpha based on brightness and user-defined softness
    soft_start = a_thresh - softness
    alpha = np.where(brightness >= a_thresh, 0, 
             np.where(brightness <= soft_start, 255,
             ((a_thresh - brightness) / (a_thresh - soft_start) * 255)))
    
    arr[:, :, 3] = alpha.astype(np.uint8)
    
    # Force ink to professional deep black/blue
    ink = alpha > 0
    arr[ink, 0:3] = np.minimum(arr[ink, 0:3], 25) # Crushes gray noise to dark ink
    
    final = Image.fromarray(arr)
    
    # 3. TIGHT AUTOCROP
    bbox = final.getchannel("A").getbbox()
    if bbox:
        final = final.crop(bbox)
    
    return final

# =========================================================
# 5. WEBSITE WORKFLOW
# =========================================================

with st.sidebar:
    st.markdown(f"## 🛠️ Extraction Engine")
    a_thresh = st.slider("Transparency Threshold", 200, 255, 248)
    softness = st.slider("Edge Smoothing", 5, 45, 18)
    st.divider()
    st.info(f"AI Quota Used: {st.session_state.ai_calls_used}/{CONFIG.max_calls}")
    if st.button("🔄 Start New Project"):
        st.session_state.clear()
        st.rerun()

# Hero Header
st.markdown(f"""
<div class="hero-box">
    <h1>{CONFIG.app_name}</h1>
    <p style="font-size: 1.3rem; color: #64748B;">Turn handwritten signatures into professional digital assets for Word, PDF, and legal docs.</p>
</div>
""", unsafe_allow_html=True)

# Main Dashboard Layout
upload_col, preview_col = st.columns([1, 1], gap="large")

with upload_col:
    st.markdown("### 📂 1. Source Upload")
    file = st.file_uploader("", type=['png', 'jpg', 'jpeg', 'webp'], label_visibility="collapsed")
    if file:
        original = Image.open(file)
        if st.button("✨ Generate Pro Signature", use_container_width=True):
            is_valid, msg = validate_quality(original)
            if not is_valid:
                st.error(msg)
            else:
                with st.spinner("AI is analyzing stroke patterns..."):
                    st.session_state.final_img = process_pipeline(original, a_thresh, softness)

with preview_col:
    st.markdown("### 🎯 2. Live Preview")
    if st.session_state.final_img:
        st.markdown('<div class="preview-container">', unsafe_allow_html=True)
        # Apply Watermark for unpaid previews
        display_img = st.session_state.final_img.copy()
        if not st.session_state.paid:
            d = ImageDraw.Draw(display_img)
            # Simple text watermark; reference image_a7b00d.png shows this area
            d.text((15, 15), "PREVIEW • PROTECTED", fill=(180, 180, 180))
        
        st.image(display_img, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Your processed signature will appear here after extraction.")

# Monetization & Export Section
if st.session_state.final_img:
    st.write("---")
    if st.session_state.paid:
        st.success("✅ Payment Confirmed. Your professional files are ready.")
        dl1, dl2 = st.columns(2)
        with dl1:
            buf = io.BytesIO()
            st.session_state.final_img.save(buf, format="PNG")
            st.download_button("⬇️ Download Transparent PNG", buf.getvalue(), "signature_studio_pro.png", "image/png")
        with dl2:
            if DOCX_AVAILABLE:
                doc = Document()
                doc.add_paragraph("High-Resolution Signature Asset:")
                img_s = io.BytesIO()
                st.session_state.final_img.save(img_s, format="PNG")
                doc.add_picture(img_s, width=Inches(2.5))
                doc_buf = io.BytesIO()
                doc.save(doc_buf)
                st.download_button("⬇️ Download Word (.docx)", doc_buf.getvalue(), "signature_pro.docx")
    else:
        st.markdown(f"""
        <div style="background: white; padding: 2.5rem; border-radius: 32px; text-align:center; border: 2px solid #DBEAFE; box-shadow: 0 4px 12px rgba(0,0,0,0.03);">
            <h2 style="color: {TEXT_DARK};">Unlock High-Resolution Export</h2>
            <p style="color: #64748B;">Pay <b>{CONFIG.price}</b> once to remove the watermark and unlock transparent PNG and Word-ready files.</p>
        </div>
        """, unsafe_allow_html=True)
        
        p_col1, p_col2 = st.columns(2)
        with p_col1:
            if st.button("💳 Pay via Stripe"):
                if STRIPE_AVAILABLE and CONFIG.stripe_sk:
                    stripe.api_key = CONFIG.stripe_sk
                    sess = stripe.checkout.Session.create(
                        mode="payment",
                        line_items=[{"price": CONFIG.stripe_price_id, "quantity": 1}],
                        success_url=f"{CONFIG.app_url}?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
                        cancel_url=CONFIG.app_url
                    )
                    st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{sess.url}\'" />', unsafe_allow_html=True)
        with p_col2:
            st.link_button("🔵 Pay via PayPal", CONFIG.paypal_url)

        with st.expander("Unlock with access code"):
            code = st.text_input("Enter code", type="password")
            if st.button("Verify"):
                if code == CONFIG.unlock_code:
                    st.session_state.paid = True
                    st.rerun()

st.markdown("<br><center><p style='color:#94A3B8;'>© 2026 Signature Studio Pro • Professional Grade Extraction</p></center>", unsafe_allow_html=True)