import base64
import io
import streamlit as st
import numpy as np
from dataclasses import dataclass
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

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

C = {
    "primary": "#6366F1",
    "dark": "#0F172A",
    "light": "#F8FAFC",
    "surface": "#FFFFFF",
    "border": "#E2E8F0",
    "muted": "#64748B",
    "success": "#10B981",
}

st.set_page_config(page_title=CONFIG.app_name, page_icon="🖊️", layout="wide")

if "paid" not in st.session_state: st.session_state.paid = False
if "ai_calls_used" not in st.session_state: st.session_state.ai_calls_used = 0
if "final_clean_rgba" not in st.session_state: st.session_state.final_clean_rgba = None
if "method_used" not in st.session_state: st.session_state.method_used = None

# =========================================================
# 3. COMPACT CSS
# =========================================================
st.markdown(f"""
<style>
    .stApp {{ background: {C["light"]}; }}
    .compact-header {{
        background: linear-gradient(135deg, {C["dark"]} 0%, {C["primary"]} 100%);
        border-radius: 16px; padding: 1.25rem 2rem; margin-bottom: 1rem;
        display: flex; align-items: center; gap: 1rem;
    }}
    .compact-header h1 {{ color: white; font-size: 1.75rem; font-weight: 800; margin: 0; }}
    .compact-header p {{ color: rgba(255,255,255,0.85); margin: 0; font-size: 0.85rem; }}
    .logo-icon {{ font-size: 2.5rem; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2)); }}
    .compact-card {{ background: {C["surface"]}; border: 1px solid {C["border"]}; border-radius: 12px; padding: 1rem; }}
    .preview-area {{
        background: {C["surface"]}; border-radius: 12px; border: 2px solid {C["border"]};
        padding: 1.5rem; text-align: center; min-height: 250px;
        display: flex; align-items: center; justify-content: center;
    }}
    .payment-strip {{
        background: linear-gradient(90deg, #FFF7ED, #FFFBEB); border: 1px solid #FED7AA;
        border-radius: 12px; padding: 1rem 1.5rem; display: flex;
        align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
    }}
    .badge {{ display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.2rem 0.65rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }}
    .badge-warning {{ background: #FEF3C7; color: #92400E; }}
    .badge-success {{ background: #D1FAE5; color: #065F46; }}
    .quota-bar {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; color: {C["muted"]}; }}
    [data-testid="stSidebar"] {{ background: linear-gradient(180deg, #0F172A, #1E293B); border-right: none; }}
    [data-testid="stSidebar"] * {{ color: #E2E8F0 !important; }}
    [data-testid="stFileUploader"] section {{ padding: 1rem !important; }}
    .block-container {{ padding-top: 1rem; padding-bottom: 1rem; }}
    .element-container {{ margin-bottom: 0.5rem; }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 4. PROVEN IMAGE HELPERS (from sample code)
# =========================================================

def fix_image_orientation(image: Image.Image) -> Image.Image:
    try: return ImageOps.exif_transpose(image)
    except: return image

def ensure_pil_image(obj) -> Image.Image:
    if isinstance(obj, Image.Image): return obj.convert("RGBA")
    if hasattr(obj, "convert"): return obj.convert("RGBA")
    raise TypeError(f"Unsupported image object: {type(obj)}")

def smart_resize_for_processing(image: Image.Image, max_pixels: int = 2400) -> Image.Image:
    w, h = image.size
    if max(w, h) <= max_pixels: return image.copy()
    ratio = max_pixels / max(w, h)
    return image.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)

def create_checkerboard_bg(size: tuple, square_size: int = 16) -> Image.Image:
    bg = Image.new("RGBA", size, (255,255,255,255))
    draw = ImageDraw.Draw(bg)
    light, dark = (242,244,247,255), (222,226,231,255)
    for y in range(0, size[1], square_size):
        for x in range(0, size[0], square_size):
            fill = light if ((x//square_size + y//square_size) % 2 == 0) else dark
            draw.rectangle([x, y, x+square_size, y+square_size], fill=fill)
    return bg

def preview_transparent_image(sig_img: Image.Image) -> Image.Image:
    sig_img = sig_img.convert("RGBA")
    bg = create_checkerboard_bg(sig_img.size)
    out = bg.copy()
    out.paste(sig_img, (0,0), sig_img)
    return out

# =========================================================
# 5. PROVEN TRANSPARENCY PIPELINE (from sample code)
# =========================================================

def white_to_transparent_soft(image: Image.Image, threshold: int = 248, softness: int = 18) -> Image.Image:
    image = ensure_pil_image(image)
    soft_start = max(0, threshold - softness)
    arr = np.array(image, dtype=np.uint8)
    brightness = arr[:,:,:3].mean(axis=2)
    alpha = np.where(brightness >= threshold, 0,
             np.where(brightness <= soft_start, 255,
             ((threshold - brightness) / max(1, threshold - soft_start) * 255))).astype(np.uint8)
    arr[:,:,3] = alpha
    ink = alpha > 0
    arr[ink, 0] = np.minimum(arr[ink, 0], 20)
    arr[ink, 1] = np.minimum(arr[ink, 1], 20)
    arr[ink, 2] = np.minimum(arr[ink, 2], 20)
    return Image.fromarray(arr, mode="RGBA")

def remove_small_noise(image: Image.Image, alpha_cutoff: int = 25) -> Image.Image:
    image = image.convert("RGBA")
    arr = np.array(image, dtype=np.uint8)
    alpha = arr[:,:,3]
    alpha[alpha < alpha_cutoff] = 0
    arr[:,:,3] = alpha
    ink = alpha > 0
    arr[ink, 0] = np.minimum(arr[ink, 0], 20)
    arr[ink, 1] = np.minimum(arr[ink, 1], 20)
    arr[ink, 2] = np.minimum(arr[ink, 2], 20)
    return Image.fromarray(arr, mode="RGBA")

def connected_components(mask):
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components = []
    for y in range(h):
        for x in range(w):
            if not mask[y,x] or visited[y,x]: continue
            stack = [(y,x)]; visited[y,x] = True; pixels = []
            while stack:
                cy, cx = stack.pop(); pixels.append((cy,cx))
                for ny in range(cy-1, cy+2):
                    for nx in range(cx-1, cx+2):
                        if 0 <= ny < h and 0 <= nx < w and mask[ny,nx] and not visited[ny,nx]:
                            visited[ny,nx] = True; stack.append((ny,nx))
            components.append(pixels)
    return components

def keep_signature_cluster_only(image: Image.Image, min_area: int = 20, margin: int = 45) -> Image.Image:
    image = image.convert("RGBA")
    arr = np.array(image, dtype=np.uint8)
    alpha = arr[:,:,3]; mask = alpha > 0
    components = [c for c in connected_components(mask) if len(c) >= min_area]
    if not components: return image
    main = max(components, key=len)
    main_ys = [p[0] for p in main]; main_xs = [p[1] for p in main]
    my1, my2 = min(main_ys), max(main_ys); mx1, mx2 = min(main_xs), max(main_xs)
    keep = np.zeros_like(mask, dtype=bool)
    for comp in components:
        ys = [p[0] for p in comp]; xs = [p[1] for p in comp]
        y1, y2 = min(ys), max(ys); x1, x2 = min(xs), max(xs)
        close = not (x2 < mx1 - margin or x1 > mx2 + margin or y2 < my1 - margin or y1 > my2 + margin)
        if close:
            for y, x in comp: keep[y,x] = True
    arr[~keep, 3] = 0
    return Image.fromarray(arr, mode="RGBA")

def tight_crop_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if not bbox: return image
    l, t, r, b = bbox
    return image.crop((max(0,l-padding), max(0,t-padding), min(image.width,r+padding), min(image.height,b+padding)))

def center_signature_canvas(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if not bbox: return image
    cropped = image.crop(bbox)
    canvas = Image.new("RGBA", cropped.size, (0,0,0,0))
    canvas.paste(cropped, (0,0), cropped)
    return canvas

def resize_signature_only(image: Image.Image, max_w: int = 700, max_h: int = 240) -> Image.Image:
    img = image.copy(); img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS); return img

def finalize_signature_only(image: Image.Image) -> Image.Image:
    image = ensure_pil_image(image)
    image = remove_small_noise(image, alpha_cutoff=25)
    image = keep_signature_cluster_only(image, min_area=20, margin=45)
    image = tight_crop_alpha(image, padding=10)
    image = center_signature_canvas(image)
    image = resize_signature_only(image, max_w=700, max_h=240)
    image = remove_small_noise(image, alpha_cutoff=18)
    image = keep_signature_cluster_only(image, min_area=12, margin=35)
    image = tight_crop_alpha(image, padding=8)
    image = center_signature_canvas(image)
    return image

# =========================================================
# 6. AI EXTRACTION (with safe fallback)
# =========================================================

def ask_ai_extract_signature_only(cropped_image: Image.Image, model_name: str) -> Image.Image:
    client = genai.Client(api_key=CONFIG.api_key)
    prompt = """Extract ONLY the handwritten signature ink. Remove all paper, shadows, backgrounds. Pure black ink on white background. Keep original shape and proportions."""
    response = client.models.generate_content(model=model_name, contents=[prompt, cropped_image])
    st.session_state.ai_calls_used += 1
    parts = getattr(response, "parts", None)
    if parts:
        for part in parts:
            if getattr(part, "inline_data", None) is not None:
                return ensure_pil_image(part.as_image())
    candidates = getattr(response, "candidates", None)
    if candidates:
        for c in candidates:
            content = getattr(c, "content", None)
            if content and getattr(content, "parts", None):
                for part in content.parts:
                    if getattr(part, "inline_data", None) is not None:
                        return ensure_pil_image(part.as_image())
    raise RuntimeError("AI did not return an image.")

def process_signature(image: Image.Image, a_thresh: int, softness: int) -> Tuple[Image.Image | None, str]:
    image = fix_image_orientation(image)
    image = smart_resize_for_processing(image, max_pixels=2400)
    
    if HAS_GENAI and CONFIG.api_key and st.session_state.ai_calls_used < CONFIG.max_calls:
        try:
            cleaned = ask_ai_extract_signature_only(image, CONFIG.ai_model)
            transparent = white_to_transparent_soft(cleaned, threshold=a_thresh, softness=softness)
            final = finalize_signature_only(transparent)
            return final, "Enhanced AI"
        except Exception:
            pass
    
    # Local fallback
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    gray = (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2])
    ink = gray < 170
    arr[:,:,3] = np.where(ink, 255, 0).astype(np.uint8)
    arr[ink, 0:3] = 0
    final = finalize_signature_only(Image.fromarray(arr, mode="RGBA"))
    return final, "Standard"

# =========================================================
# 7. SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    a_thresh = st.slider("Threshold", 200, 255, 248)
    softness = st.slider("Smoothing", 5, 45, 18)
    st.divider()
    quota = st.session_state.ai_calls_used
    st.markdown(f'<div class="quota-bar">🖊️ AI calls: <b>{quota}/{CONFIG.max_calls}</b></div>', unsafe_allow_html=True)
    if st.button("🔄 Reset", use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# =========================================================
# 8. HEADER
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
# 9. MAIN LAYOUT
# =========================================================
col1, col2 = st.columns([1, 1], gap="medium")

with col1:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)
    st.markdown("#### 📤 Upload Signature Photo")
    file = st.file_uploader("", type=['png','jpg','jpeg','webp'], label_visibility="collapsed")
    if file:
        original = Image.open(file)
        if st.button("✨ Process Signature", type="primary", use_container_width=True):
            with st.spinner("Extracting..."):
                final_img, method = process_signature(original, a_thresh, softness)
                st.session_state.final_clean_rgba = final_img
                st.session_state.method_used = method
            st.success(f"✅ Done! ({method})")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="compact-card">', unsafe_allow_html=True)
    st.markdown("#### 🎯 Preview")
    if st.session_state.final_clean_rgba:
        display_img = st.session_state.final_clean_rgba.copy()
        if not st.session_state.paid:
            d = ImageDraw.Draw(display_img)
            try: font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(12, display_img.width//20))
            except: font = ImageFont.load_default()
            d.text((8,8), "PREVIEW", fill=(180,180,180,150), font=font)
        st.markdown('<div class="preview-area">', unsafe_allow_html=True)
        st.image(preview_transparent_image(display_img), use_container_width=False)
        st.markdown('</div>', unsafe_allow_html=True)
        badge = "badge-warning" if not st.session_state.paid else "badge-success"
        text = "🔒 Watermarked" if not st.session_state.paid else "✅ Unlocked"
        st.markdown(f'<br><span class="badge {badge}">{text}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="preview-area"><p style="color:#94A3B8;">Upload a photo and click Process</p></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# =========================================================
# 10. PAYMENT & DOWNLOAD
# =========================================================
if st.session_state.final_clean_rgba:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.session_state.paid:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)
        st.markdown('<b style="color:#065F46;">✅ Payment Confirmed</b>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            buf = io.BytesIO()
            st.session_state.final_clean_rgba.save(buf, format="PNG", optimize=True)
            st.download_button("⬇ PNG", buf.getvalue(), "signature.png", "image/png", use_container_width=True, type="primary")
        with c2:
            if DOCX_AVAILABLE:
                doc = Document(); doc.add_heading("Signature Asset", level=1)
                img_s = io.BytesIO(); st.session_state.final_clean_rgba.save(img_s, format="PNG")
                doc.add_picture(img_s, width=Inches(2.5))
                doc_buf = io.BytesIO(); doc.save(doc_buf)
                st.download_button("⬇ DOCX", doc_buf.getvalue(), "signature.docx", use_container_width=True, type="secondary")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="payment-strip">', unsafe_allow_html=True)
        st.markdown(f"<b>🔓 Unlock — {CONFIG.price}</b>", unsafe_allow_html=True)
        bc1, bc2, bc3 = st.columns([1,1,1.5], gap="small")
        with bc1:
            if st.button("💳 Card", use_container_width=True):
                if STRIPE_AVAILABLE and CONFIG.stripe_sk and CONFIG.stripe_price_id:
                    stripe.api_key = CONFIG.stripe_sk
                    sess = stripe.checkout.Session.create(mode="payment", line_items=[{"price": CONFIG.stripe_price_id, "quantity": 1}], success_url=f"{CONFIG.app_url}?paid=1&session_id={{CHECKOUT_SESSION_ID}}", cancel_url=CONFIG.app_url)
                    st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{sess.url}\'" />', unsafe_allow_html=True)
        with bc2:
            if CONFIG.paypal_url: st.link_button("🔵 PayPal", CONFIG.paypal_url, use_container_width=True)
        with bc3:
            with st.popover("🔑 Code"):
                code = st.text_input("Access code", type="password")
                if st.button("Unlock", use_container_width=True) and code.strip() == CONFIG.unlock_code.strip():
                    st.session_state.paid = True; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div style="text-align:center;color:{C["muted"]};font-size:0.75rem;padding:1rem 0;border-top:1px solid {C["border"]};margin-top:1rem;">© 2026 Technoworks Pty Ltd · {CONFIG.app_name}</div>', unsafe_allow_html=True)