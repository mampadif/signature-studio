import base64
import io
import streamlit as st
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional
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

# Inline Theme Definition (Acts like config.toml)
THEME_PRIMARY = "#2563EB"  # Royal Blue
THEME_BG = "#F8FAFC"       # Soft Slate
THEME_TEXT = "#0F172A"     # Deep Navy

st.set_page_config(
    page_title=CONFIG.app_name, 
    page_icon="🖊️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State
for key, val in {"paid": False, "ai_calls_used": 0, "final_img": None, "method": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# =========================================================
# 3. THEME & CSS INJECTION (The "Inline config.toml")
# =========================================================
st.markdown(f"""
<style>
    /* 1. Global App Overrides */
    .stApp {{
        background-color: {THEME_BG} !important;
        color: {THEME_TEXT} !important;
    }}
    
    /* 2. Slider & Primary Highlight Overrides */
    .stSlider [data-baseweb="slider"] {{
        background-image: linear-gradient(to right, {THEME_PRIMARY} 0%, {THEME_PRIMARY} 100%) !important;
    }}
    
    /* 3. Hero Section Design */
    .hero-container {{
        text-align: center !important;
        padding: 4rem 2rem !important;
        background: white !important;
        border-radius: 32px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 10px 30px rgba(0,0,0,0.03) !important;
        margin-bottom: 2rem !important;
    }}
    .hero-container h1 {{
        font-size: 3.5rem !important;
        font-weight: 850 !important;
        background: linear-gradient(90deg, {THEME_TEXT}, {THEME_PRIMARY}) !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
    }}

    /* 4. Steps & Cards */
    .step-card {{
        background: white !important;
        padding: 2rem !important;
        border-radius: 24px !important;
        border: 1px solid #E2E8F0 !important;
        text-align: center !important;
    }}

    /* 5. Modern Buttons */
    div.stButton > button {{
        background-color: {THEME_PRIMARY} !important;
        color: white !important;
        border-radius: 14px !important;
        height: 3.5rem !important;
        font-weight: 700 !important;
        border: none !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2) !important;
    }}
    
    /* 6. Sidebar Background */
    [data-testid="stSidebar"] {{
        background-color: white !important;
        border-right: 1px solid #E2E8F0 !important;
    }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 4. PROCESSING LOGIC
# =========================================================

def extract_signature(img, a_thresh):
    img = ImageOps.exif_transpose(img)
    
    # AI Engine
    extracted = None
    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            client = genai.Client(api_key=CONFIG.api_key)
            prompt = "Isolate the handwritten signature ink. Output black ink on white background."
            response = client.models.generate_content(model=CONFIG.ai_model, contents=[prompt, img])
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    extracted = part.as_image().convert("RGBA")
                    st.session_state.ai_calls_used += 1
                    st.session_state.method = "AI Enhanced"
                    break
        except: pass

    if extracted is None:
        extracted = img.convert("RGBA")
        st.session_state.method = "Standard Extraction"

    # Remove White Background
    data = np.array(extracted)
    r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]
    white_mask = (r > a_thresh) & (g > a_thresh) & (b > a_thresh)
    data[white_mask, 3] = 0 
    data[~white_mask, :3] = 0 # Force Black
    
    final = Image.fromarray(data)
    bbox = final.getchannel("A").getbbox()
    return final.crop(bbox) if bbox else final

# =========================================================
# 5. WEBSITE UI
# =========================================================

with st.sidebar:
    st.markdown(f"### ⚙️ {CONFIG.app_name}")
    st.caption("Fine-tune your output here.")
    a_thresh = st.slider("Paper Removal Threshold", 200, 255, 248)
    st.divider()
    st.info(f"AI Quota: {st.session_state.ai_calls_used}/{CONFIG.max_calls}")
    if st.button("Reset Session"):
        st.session_state.clear()
        st.rerun()

# Hero Section
st.markdown(f"""
<div class="hero-container">
    <h1>{CONFIG.app_name}</h1>
    <p>Convert handwriting into high-res digital assets in seconds.</p>
</div>
""", unsafe_allow_html=True)

# Process Steps
col1, col2, col3 = st.columns(3)
with col1: st.markdown('<div class="step-card"><h3>1</h3><b>Upload Photo</b></div>', unsafe_allow_html=True)
with col2: st.markdown('<div class="step-card"><h3>2</h3><b>AI Processing</b></div>', unsafe_allow_html=True)
with col3: st.markdown('<div class="step-card"><h3>3</h3><b>Download PNG</b></div>', unsafe_allow_html=True)

st.write("---")

# Interface Split
left, right = st.columns([1, 1], gap="large")

with left:
    st.markdown("### 📂 Upload Image")
    file = st.file_uploader("", type=['png', 'jpg', 'jpeg', 'webp'], label_visibility="collapsed")
    if file:
        original = Image.open(file)
        if st.button("✨ Extract Signature", use_container_width=True):
            with st.spinner("Analyzing and cleaning..."):
                st.session_state.final_img = extract_signature(original, a_thresh)

with right:
    st.markdown("### 🎯 Preview")
    if st.session_state.final_img:
        preview = st.session_state.final_img.copy()
        if not st.session_state.paid:
            draw = ImageDraw.Draw(preview)
            draw.text((20, 20), "PREVIEW WATERMARK", fill=(200, 200, 200))
        st.image(preview, use_container_width=True, caption=f"Processing Engine: {st.session_state.method}")
    else:
        st.info("Awaiting upload...")

# Payment & Unlock Logic
if st.session_state.final_img:
    st.divider()
    if st.session_state.paid:
        st.success("Download Unlocked!")
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            buf = io.BytesIO()
            st.session_state.final_img.save(buf, format="PNG")
            st.download_button("⬇️ Get Transparent PNG", buf.getvalue(), "sig_pro.png", "image/png")
        with dcol2:
            if DOCX_AVAILABLE:
                doc = Document()
                img_s = io.BytesIO()
                st.session_state.final_img.save(img_s, format="PNG")
                doc.add_picture(img_s, width=Inches(2))
                dbuf = io.BytesIO()
                doc.save(dbuf)
                st.download_button("⬇️ Get Word File", dbuf.getvalue(), "sig_pro.docx")
    else:
        st.markdown(f"""
        <div style="background: white; padding: 2rem; border-radius: 24px; text-align:center; border: 1px solid #E2E8F0;">
            <h3>Unlock Pro Files for {CONFIG.price}</h3>
            <p>Removes watermark and provides high-res transparency.</p>
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
            st.link_button("🔵 Pay with PayPal", CONFIG.paypal_url)

        with st.expander("Already Paid?"):
            code = st.text_input("Enter Code", type="password")
            if st.button("Verify"):
                if code == CONFIG.unlock_code:
                    st.session_state.paid = True
                    st.rerun()

st.markdown("<br><center><small>© 2026 Signature Studio Pro</small></center>", unsafe_allow_html=True)