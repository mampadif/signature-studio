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
# Configuration (Set in .streamlit/secrets.toml or env vars)
# ---------------------------
STRIPE_SECRET_KEY = st.secrets.get("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", ""))
STRIPE_PRICE_ID_SIGNATURE = st.secrets.get("STRIPE_PRICE_ID_SIGNATURE", os.getenv("STRIPE_PRICE_ID_SIGNATURE", ""))
PAYPAL_LINK = st.secrets.get("PAYPAL_LINK", os.getenv("PAYPAL_LINK", "https://paypal.me/yourlink/2.99"))
APP_URL = st.secrets.get("APP_URL", os.getenv("APP_URL", "http://localhost:8501"))

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
        # If pixel is light (R,G,B all > threshold), make transparent
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
        # Attempt to use a standard font
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()
    
    # Position watermark at bottom-right
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
    href = f'<a href="data:image/png;base64,{b64}" download="{filename}">{text}</a>'
    return href

def generate_signature_from_text(
    text: str,
    font_style: str = "DancingScript",
    size: int = 60,
    color: tuple = (0, 0, 0)
) -> Image.Image:
    """Generate a signature image from text using a cursive font."""
    # Map style names to font file paths (place .ttf files in same folder or subfolder)
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
            # Fallback to Arial if available
            font = ImageFont.truetype("arial.ttf", size)
        except:
            # Ultimate fallback
            font = ImageFont.load_default()

    # Create temporary image to measure text bounds
    temp_img = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    draw = ImageDraw.Draw(temp_img)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Create actual image with padding
    img = Image.new("RGBA", (text_width + 40, text_height + 20), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.text((20, 10), text, fill=color, font=font)
    return img

# ---------------------------
# UI Layout
# ---------------------------
st.title("🖊️ Signature Studio")
st.markdown("Create a clean, transparent signature for your documents.")

# Payment Section
if not st.session_state.signature_paid:
    st.warning("🔒 **Free Preview**: A watermark is applied. Purchase full access for $2.99 (one‑time).")
    col1, col2 = st.columns(2)
    with col1:
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
                    # Redirect to Stripe Checkout
                    st.markdown(f'<meta http-equiv="refresh" content="0; url={session.url}">', unsafe_allow_html=True)
                    st.success("Redirecting to Stripe checkout...")
                except Exception as e:
                    st.error(f"Stripe error: {e}")
        else:
            st.info("Stripe not configured. Use PayPal or add Stripe keys to secrets.")
    with col2:
        if PAYPAL_LINK:
            st.markdown(
                f'<a href="{PAYPAL_LINK}" target="_blank">'
                f'<button style="width:100%; padding:0.5rem; border-radius:0.5rem; background:#0070ba; color:white; border:none;">'
                f'🅿️ Pay with PayPal</button></a>',
                unsafe_allow_html=True
            )
            st.caption("After payment, refresh the page to unlock.")
        else:
            st.info("PayPal link not configured.")
else:
    st.success("✅ Full access unlocked – no watermark!")

st.divider()

# Feature Tabs
tab1, tab2, tab3 = st.tabs(["📸 Capture & Clean", "✍️ Generate from Name", "🎨 Practice Mode"])

# ----- Tab 1: Upload & Clean -----
with tab1:
    st.subheader("Upload a photo of your signature")
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
        st.caption("Tip: Sign on plain white paper with good lighting for best results.")

# ----- Tab 2: Generate from Name -----
with tab2:
    st.subheader("Generate a signature from your name")
    name = st.text_input("Enter your full name", "John Doe")
    font_choice = st.selectbox("Font Style", ["DancingScript", "GreatVibes", "Pacifico", "AlexBrush"])
    size = st.slider("Size", 30, 120, 60)
    color = st.color_picker("Ink Color", "#000000")

    if st.button("Generate Signature", key="generate"):
        sig_img = generate_signature_from_text(name, font_choice, size, color)
        if not st.session_state.signature_paid:
            sig_img = add_watermark(sig_img)
        st.image(sig_img, caption="Generated Signature", width=300)
        st.markdown(get_image_download_link(sig_img, "generated_signature.png", "⬇️ Download PNG"), unsafe_allow_html=True)
        st.caption("Note: The generated signature is a stylized text rendering, not a secure digital signature.")

# ----- Tab 3: Practice Mode -----
with tab3:
    st.subheader("Practice your signature")
    if CANVAS_AVAILABLE:
        st.markdown("Draw your signature below. Use mouse or touch.")
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
st.caption("Need help? Contact support.")