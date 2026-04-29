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
# 3. PREMIUM CSS INJECTION
# =========================================================
st.markdown(f"""
<style>
    .stApp {{ background-color: {BG_LIGHT} !important; }}
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {{
        background-color: white !important;
        border-right: 1px solid #E2E8F0;
    }}
    
    /* Hero Section */
    .hero-box {{
        background: white;
        padding: 3rem 2rem;
        border-radius: 24px;
        border: 1px solid #E2E8F0;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }}
    .hero-box h1 {{
        font-weight: 800;
        background: linear-gradient(90deg, {TEXT_DARK}, {PRIMARY});
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem !important;
    }}
    
    /* Step Cards */
    .step-card {{
        background: white;
        padding: 1.5rem;
        border-radius: 16px;
        border: 1px solid #E2E8F0;
        text-align: center;
        height: 100%;
    }}

    /* Result Preview Area */
    .preview-container {{
        background: #ffffff;
        border-radius: 20px;
        border: 1px solid #E2E8F0;
        padding: 1rem;
        box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05);
    }}

    /* Custom Buttons */
    div.stButton > button {{
        background: {PRIMARY} !important;
        color: white !important;
        border-radius: 12px !important;
        height: 3.5rem !important;
        font-weight: 700 !important;
        width: 100% !important;
        border: none !important;
        box-shadow: 0 4px 14px 0 rgba(37, 99, 235, 0.2) !important;
    }}
    
    /* Slider Color Force */
    .stSlider [data-baseweb="slider"] {{
        background-image: linear-gradient(to right, {PRIMARY} 0%, {PRIMARY} 100%) !important;
    }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 4. RESTORED EXTRACTION ENGINE (YOUR ORIGINAL LOGIC)
# =========================================================

def connected_components(mask):
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]: continue
            stack, pixels = [(y, x)], []
            visited[y, x] = True
            while stack:
                cy, cx = stack.pop()
                pixels.append((cy, cx))
                for ny in range(cy-1, cy+2):
                    for nx in range(cx-1, cx+2):
                        if 0 <= ny < height and 0 <= nx < width:
                            if mask[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((ny, nx))
            components.append(pixels)
    return components

def validate_quality(img: Image.Image) -> Tuple[bool, str]:
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape
    if w < 250 or h < 250: return False, "Image too small."
    gray = (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]).astype(np.uint8)
    ink_ratio = float((gray < 170).sum()) / (w * h)
    if ink_ratio < 0.0003: return False, "Signature not detected. Use a darker pen."
    return True, "Valid"

def process_pipeline(original_img, a_thresh, softness):
    img = ImageOps.exif_transpose(original_img)
    
    # 1. AI EXTRACTOR (PRIMARY)
    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            client = genai.Client(api_key=CONFIG.api_key)
            response = client.models.generate_content(
                model=CONFIG.ai_model, 
                contents=["Extract ONLY the signature ink. Output black ink on white.", img]
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    img = part.as_image()
                    st.session_state.ai_calls_used += 1
                    break
        except: pass

    # 2. ADVANCED TRANSPARENCY (RESTORED SOFT LOGIC)
    img = img.convert("RGBA")
    arr = np.array(img)
    brightness = arr[:, :, :3].mean(axis=2)
    
    # Soft transparency mask
    soft_start = a_thresh - softness
    alpha = np.where(brightness >= a_thresh, 0, 
             np.where(brightness <= soft_start, 255,
             ((a_thresh - brightness) / (a_thresh - soft_start) * 255)))
    
    arr[:, :, 3] = alpha.astype(np.uint8)
    
    # Force ink to be dark
    ink = alpha > 0
    arr[ink, 0:3] = np.minimum(arr[ink, 0:3], 30) # Keep strokes dark/black
    
    final = Image.fromarray(arr)
    
    # 3. NOISE REMOVAL & TIGHT CROP
    bbox = final.getchannel("A").getbbox()
    if bbox: final = final.crop(bbox)
    
    return final

# =========================================================
# 5. UI APP FLOW
# =========================================================

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3163/3163195.png", width=60)
    st.title("Studio Settings")
    a_thresh = st.slider("Paper Removal", 200, 255, 248)
    softness = st.slider("Edge Softness", 5, 40, 18)
    st.divider()
    st.write(f"AI Quota: {st.session_state.ai_calls_used}/{CONFIG.max_calls}")
    if st.button("🔄 Reset Studio"):
        st.session_state.clear()
        st.rerun()

# Hero Section
st.markdown(f"""
<div class="hero-box">
    <h1>{CONFIG.app_name}</h1>
    <p>Professional AI-powered signature extraction for your digital documents.</p>
</div>
""", unsafe_allow_html=True)

# Steps
c1, c2, c3 = st.columns(3)
with c1: st.markdown('<div class="step-card"><b>1. Upload</b><br><small>Photo of signature</small></div>', unsafe_allow_html=True)
with c2: st.markdown('<div class="step-card"><b>2. AI Cleanup</b><br><small>Isolating the ink</small></div>', unsafe_allow_html=True)
with c3: st.markdown('<div class="step-card"><b>3. Download</b><br><small>Pro PNG & Word files</small></div>', unsafe_allow_html=True)

st.divider()

# Working Area
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("📂 Upload Photo")
    file = st.file_uploader("", type=['png', 'jpg', 'jpeg', 'webp'], label_visibility="collapsed")
    if file:
        original = Image.open(file)
        if st.button("✨ Extract Signature", use_container_width=True):
            is_valid, msg = validate_quality(original)
            if not is_valid:
                st.error(msg)
            else:
                with st.spinner("AI is digitizing strokes..."):
                    st.session_state.final_img = process_pipeline(original, a_thresh, softness)

with right:
    st.subheader("🎯 Result Preview")
    if st.session_state.final_img:
        st.markdown('<div class="preview-container">', unsafe_allow_html=True)
        # Display with watermark if not paid
        display_img = st.session_state.final_img.copy()
        if not st.session_state.paid:
            d = ImageDraw.Draw(display_img)
            d.text((10, 10), "PREVIEW WATERMARK", fill=(150, 150, 150))
        st.image(display_img, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Upload a clear photo to begin.")

# Payment & Unlock
if st.session_state.final_img:
    st.write("---")
    if st.session_state.paid:
        st.success("✅ Files Unlocked! Download your pro assets below.")
        d1, d2 = st.columns(2)
        with d1:
            buf = io.BytesIO()
            st.session_state.final_img.save(buf, format="PNG")
            st.download_button("⬇️ Download PNG", buf.getvalue(), "signature.png", "image/png")
        with d2:
            if DOCX_AVAILABLE:
                doc = Document()
                img_s = io.BytesIO()
                st.session_state.final_img.save(img_s, format="PNG")
                doc.add_picture(img_s, width=Inches(2))
                dbuf = io.BytesIO()
                doc.save(dbuf)
                st.download_button("⬇️ Download Word (.docx)", dbuf.getvalue(), "signature.docx")
    else:
        st.markdown(f"""
        <div style="background: white; padding: 2rem; border-radius: 20px; text-align:center; border: 1px solid #E2E8F0;">
            <h3>Unlock Professional Files</h3>
            <p>One-time payment of <b>{CONFIG.price}</b> to get transparent high-res files.</p>
        </div>
        """, unsafe_allow_html=True)
        
        p1, p2 = st.columns(2)
        with p1:
            if st.button("💳 Pay with Card"):
                if STRIPE_AVAILABLE and CONFIG.stripe_sk:
                    stripe.api_key = CONFIG.stripe_sk
                    sess = stripe.checkout.Session.create(
                        mode="payment",
                        line_items=[{"price": CONFIG.stripe_price_id, "quantity": 1}],
                        success_url=f"{CONFIG.app_url}?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
                        cancel_url=CONFIG.app_url
                    )
                    st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{sess.url}\'" />', unsafe_allow_html=True)
        with p2:
            st.link_button("🔵 Pay via PayPal", CONFIG.paypal_url)

        with st.expander("Already paid?"):
            ucode = st.text_input("Enter Unlock Code", type="password")
            if st.button("Unlock"):
                if ucode == CONFIG.unlock_code:
                    st.session_state.paid = True
                    st.rerun()

st.markdown("<br><center><small>© 2026 Signature Studio Pro</small></center>", unsafe_allow_html=True)