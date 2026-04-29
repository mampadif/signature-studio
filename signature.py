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

# Compact Design System
C = {
    "primary": "#6366F1",
    "dark": "#0F172A",
    "light": "#F8FAFC",
    "surface": "#FFFFFF",
    "border": "#E2E8F0",
    "muted": "#64748B",
    "success": "#10B981",
    "warning": "#F59E0B",
}

st.set_page_config(page_title=CONFIG.app_name, page_icon="🖊️", layout="wide")

if "paid" not in st.session_state: st.session_state.paid = False
if "ai_calls_used" not in st.session_state: st.session_state.ai_calls_used = 0
if "final_img" not in st.session_state: st.session_state.final_img = None

# =========================================================
# 3. COMPACT CSS (Minimal scrolling, max density)
# =========================================================
st.markdown(f"""
<style>
    .stApp {{ background: {C["light"]}; }}
    
    /* Compact Header */
    .compact-header {{
        background: linear-gradient(135deg, {C["dark"]} 0%, {C["primary"]} 100%);
        border-radius: 16px;
        padding: 1.25rem 2rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 1rem;
    }}
    .compact-header h1 {{
        color: white;
        font-size: 1.75rem;
        font-weight: 800;
        margin: 0;
    }}
    .compact-header p {{
        color: rgba(255,255,255,0.85);
        margin: 0;
        font-size: 0.85rem;
    }}
    
    /* Electronic Pen Logo */
    .logo-icon {{
        font-size: 2.5rem;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2));
    }}
    
    /* Compact Cards */
    .compact-card {{
        background: {C["surface"]};
        border: 1px solid {C["border"]};
        border-radius: 12px;
        padding: 1rem;
    }}
    
    /* Preview Area */
    .preview-area {{
        background: {C["surface"]};
        background-image: 
            linear-gradient(45deg, #f1f5f9 25%, transparent 25%),
            linear-gradient(-45deg, #f1f5f9 25%, transparent 25%),
            linear-gradient(45deg, transparent 75%, #f1f5f9 75%),
            linear-gradient(-45deg, transparent 75%, #f1f5f9 75%);
        background-size: 16px 16px;
        background-position: 0 0, 0 8px, 8px -8px, -8px 0px;
        border-radius: 12px;
        border: 2px solid {C["border"]};
        padding: 1.5rem;
        text-align: center;
        min-height: 250px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    
    /* Payment Strip (horizontal, compact) */
    .payment-strip {{
        background: linear-gradient(90deg, #FFF7ED, #FFFBEB);
        border: 1px solid #FED7AA;
        border-radius: 12px;
        padding: 1rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
    }}
    
    /* Buttons */
    .btn {{
        padding: 0.6rem 1.25rem;
        border-radius: 10px;
        font-weight: 700;
        font-size: 0.9rem;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        transition: all 0.2s;
        cursor: pointer;
        border: none;
    }}
    .btn-primary {{ background: {C["primary"]}; color: white; }}
    .btn-primary:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(99,102,241,0.3); }}
    .btn-outline {{ background: white; color: {C["dark"]}; border: 2px solid {C["border"]}; }}
    .btn-outline:hover {{ border-color: {C["primary"]}; }}
    .btn-paypal {{ background: linear-gradient(90deg, #0070BA, #003087); color: white; }}
    .btn-success {{ background: {C["success"]}; color: white; }}
    
    /* Status Badge */
    .badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }}
    .badge-warning {{ background: #FEF3C7; color: #92400E; }}
    .badge-success {{ background: #D1FAE5; color: #065F46; }}
    
    /* Quota Bar */
    .quota-bar {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.8rem;
        color: {C["muted"]};
    }}
    
    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #0F172A, #1E293B);
        border-right: none;
    }}
    [data-testid="stSidebar"] * {{ color: #E2E8F0 !important; }}
    
    /* Compact Uploader */
    [data-testid="stFileUploader"] section {{ padding: 1rem !important; }}
    
    /* Remove excess padding */
    .block-container {{ padding-top: 1rem; padding-bottom: 1rem; }}
    .element-container {{ margin-bottom: 0.5rem; }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 4. EXTRACTION ENGINE
# =========================================================
def validate_quality(img: Image.Image) -> Tuple[bool, str]:
    arr = np.array(img.convert("RGB"))
    h, w, _ = arr.shape
    if w < 250 or h < 250: return False, "Photo resolution too low."
    gray = (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]).astype(np.uint8)
    ink_ratio = float((gray < 185).sum()) / (w * h)
    if ink_ratio < 0.0002: return False, "No clear signature detected."
    return True, "OK"

def process_pipeline(original_img, a_thresh, softness):
    img = ImageOps.exif_transpose(original_img)
    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            client = genai.Client(api_key=CONFIG.api_key)
            response = client.models.generate_content(
                model=CONFIG.ai_model,
                contents=["Extract ONLY the signature ink. High contrast black ink on pure white background.", img]
            )
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') or hasattr(part, 'as_image'):
                    img = part.as_image()
                    st.session_state.ai_calls_used += 1
                    break
        except: pass
    img = img.convert("RGBA")
    arr = np.array(img)
    brightness = arr[:, :, :3].mean(axis=2)
    soft_start = a_thresh - softness
    alpha = np.where(brightness >= a_thresh, 0, np.where(brightness <= soft_start, 255, ((a_thresh - brightness) / (a_thresh - soft_start) * 255)))
    arr[:, :, 3] = alpha.astype(np.uint8)
    arr[alpha > 0, 0:3] = np.minimum(arr[alpha > 0, 0:3], 25)
    final = Image.fromarray(arr)
    bbox = final.getchannel("A").getbbox()
    if bbox: final = final.crop(bbox)
    return final

# =========================================================
# 5. SIDEBAR (Compact Dark)
# =========================================================
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    a_thresh = st.slider("Threshold", 200, 255, 248)
    softness = st.slider("Smoothing", 5, 45, 18)
    st.divider()
    quota = st.session_state.ai_calls_used
    st.markdown(f'<div class="quota-bar">🖊️ AI calls: <b>{quota}/{CONFIG.max_calls}</b></div>', unsafe_allow_html=True)
    if st.button("🔄 Reset", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# =========================================================
# 6. COMPACT HEADER (Logo Restored)
# =========================================================
st.markdown(f"""
<div class="compact-header">
    <div class="logo-icon">🖊️</div>
    <div>
        <h1>{CONFIG.app_name}</h1>
        <p>AI-powered signature extraction for professionals</p>
    </div>
</div>
""", unsafe_allow_html=True)

# =========================================================
# 7. MAIN LAYOUT (2 Columns, Compact)
# =========================================================
col1, col2 = st.columns([1, 1], gap="medium")

with col1:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)
    st.markdown("#### 📤 Upload Signature Photo")
    file = st.file_uploader("", type=['png','jpg','jpeg','webp'], label_visibility="collapsed")
    
    if file:
        original = Image.open(file)
        if st.button("✨ Process Signature", type="primary", use_container_width=True):
            is_valid, msg = validate_quality(original)
            if not is_valid:
                st.error(msg)
            else:
                with st.spinner("Extracting..."):
                    st.session_state.final_img = process_pipeline(original, a_thresh, softness)
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)
    st.markdown("#### 🎯 Preview")
    
    if st.session_state.final_img:
        display_img = st.session_state.final_img.copy()
        if not st.session_state.paid:
            d = ImageDraw.Draw(display_img)
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(12, display_img.width // 20))
            except:
                font = ImageFont.load_default()
            txt = "PREVIEW"
            d.text((8, 8), txt, fill=(180,180,180,150), font=font)
        
        st.markdown('<div class="preview-area">', unsafe_allow_html=True)
        st.image(display_img, use_container_width=False)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Status badge
        badge = "badge-warning" if not st.session_state.paid else "badge-success"
        text = "🔒 Watermarked" if not st.session_state.paid else "✅ Unlocked"
        st.markdown(f'<br><span class="badge {badge}">{text}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="preview-area"><p style="color:#94A3B8;">Upload a photo and click Process</p></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# =========================================================
# 8. PAYMENT & DOWNLOAD (Compact Strip)
# =========================================================
if st.session_state.final_img:
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.session_state.paid:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)
        st.markdown('<b style="color:#065F46;">✅ Payment Confirmed</b>', unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        with c1:
            buf = io.BytesIO()
            st.session_state.final_img.save(buf, format="PNG", optimize=True)
            st.download_button("⬇ PNG", buf.getvalue(), "signature.png", "image/png", use_container_width=True)
        with c2:
            if DOCX_AVAILABLE:
                doc = Document()
                img_s = io.BytesIO()
                st.session_state.final_img.save(img_s, format="PNG")
                doc.add_picture(img_s, width=Inches(2.5))
                doc_buf = io.BytesIO()
                doc.save(doc_buf)
                st.download_button("⬇ DOCX", doc_buf.getvalue(), "signature.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)
        st.markdown(f"<b>🔓 Unlock clean download — {CONFIG.price}</b>", unsafe_allow_html=True)
        
        bc1, bc2, bc3 = st.columns([1,1,1.5], gap="small")
        with bc1:
            if st.button("💳 Card", use_container_width=True, key="card_btn"):
                if STRIPE_AVAILABLE and CONFIG.stripe_sk and CONFIG.stripe_price_id:
                    stripe.api_key = CONFIG.stripe_sk
                    sess = stripe.checkout.Session.create(
                        mode="payment",
                        line_items=[{"price": CONFIG.stripe_price_id, "quantity": 1}],
                        success_url=f"{CONFIG.app_url}?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
                        cancel_url=CONFIG.app_url
                    )
                    st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{sess.url}\'" />', unsafe_allow_html=True)
        with bc2:
            if CONFIG.paypal_url:
                st.link_button("🔵 PayPal", CONFIG.paypal_url, use_container_width=True)
        with bc3:
            with st.popover("🔑 Code"):
                code = st.text_input("Access code", type="password")
                if st.button("Unlock", use_container_width=True):
                    if code.strip() == CONFIG.unlock_code.strip():
                        st.session_state.paid = True
                        st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

# =========================================================
# 9. FOOTER
# =========================================================
st.markdown(f'<div style="text-align:center;color:{C["muted"]};font-size:0.75rem;padding:1rem 0;border-top:1px solid {C["border"]};margin-top:1rem;">© 2026 Technoworks Pty Ltd · {CONFIG.app_name}</div>', unsafe_allow_html=True)