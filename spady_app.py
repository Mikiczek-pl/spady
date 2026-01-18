import io
import base64
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image

# =========================
# USTAWIENIA (STAŁE)
# =========================
STRIP_MM = 2.0       # wycinany pasek od krawędzi
STRETCH_MM = 5.0     # rozciągnięcie paska
BLEED_MM = STRETCH_MM - STRIP_MM  # 3 mm
DPI = 300            # STAŁE DPI

LOGO_PATH = "assets/logo CR.png"  # <- wrzuć logo do repo w tej ścieżce


# =========================
# POMOCNICZE
# =========================
def load_image_as_base64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8")

def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm * dpi / 25.4))

def get_page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = doc.page_count
    doc.close()
    return n

def render_pdf_page_to_image(pdf_bytes: bytes, page_index: int, dpi: int) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page_index < 0 or page_index >= doc.page_count:
        doc.close()
        raise ValueError(f"PDF ma {doc.page_count} stron, a prosisz o stronę {page_index+1}.")
    page = doc.load_page(page_index)

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img

def apply_bleed_stretch(img: Image.Image, dpi: int, strip_mm: float, stretch_mm: float) -> Image.Image:
    """
    Metoda "rozciągania krawędzi":
    1) Pion: góra (2mm->5mm), środek bez zmian, dół (2mm->5mm)
    2) Poziom: lewo (2mm->5mm), środek bez zmian, prawo (2mm->5mm)
    """
    w, h = img.size
    strip_px = mm_to_px(strip_mm, dpi)
    stretch_px = mm_to_px(stretch_mm, dpi)

    if strip_px <= 0 or stretch_px <= 0:
        raise ValueError("Błędne parametry po przeliczeniu na px (spróbuj zwiększyć DPI).")

    if strip_px * 2 >= h or strip_px * 2 >= w:
        raise ValueError(
            "Pasek 2mm jest za duży względem obrazu po rasteryzacji. "
            "Sprawdź, czy PDF ma prawidłowy rozmiar strony."
        )

    # --- PION ---
    top = img.crop((0, 0, w, strip_px)).resize((w, stretch_px), resample=Image.BICUBIC)
    mid = img.crop((0, strip_px, w, h - strip_px))
    bot = img.crop((0, h - strip_px, w, h)).resize((w, stretch_px), resample=Image.BICUBIC)

    v_h = top.size[1] + mid.size[1] + bot.size[1]
    v_img = Image.new("RGB", (w, v_h))
    y = 0
    v_img.paste(top, (0, y)); y += top.size[1]
    v_img.paste(mid, (0, y)); y += mid.size[1]
    v_img.paste(bot, (0, y))

    # --- POZIOM ---
    w2, h2 = v_img.size
    left = v_img.crop((0, 0, strip_px, h2)).resize((stretch_px, h2), resample=Image.BICUBIC)
    mid2 = v_img.crop((strip_px, 0, w2 - strip_px, h2))
    right = v_img.crop((w2 - strip_px, 0, w2, h2)).resize((stretch_px, h2), resample=Image.BICUBIC)

    out_w = left.size[0] + mid2.size[0] + right.size[0]
    out = Image.new("RGB", (out_w, h2))
    x = 0
    out.paste(left, (x, 0)); x += left.size[0]
    out.paste(mid2, (x, 0)); x += mid2.size[0]
    out.paste(right, (x, 0))

    return out

def images_to_pdf_bytes(images: list[Image.Image], dpi: int) -> bytes:
    """
    Składa obrazy do wielostronicowego PDF.
    Rozmiar strony dopasowany 1:1 do obrazu (w pt).
    """
    pdf = fitz.open()

    for img in images:
        w_px, h_px = img.size
        w_pt = w_px * 72.0 / dpi
        h_pt = h_px * 72.0 / dpi

        page = pdf.new_page(width=w_pt, height=h_pt)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        rect = fitz.Rect(0, 0, w_pt, h_pt)
        page.insert_image(rect, stream=png_bytes)

    out = pdf.write()
    pdf.close()
    return out


# =========================
# UI (WYGLĄD JAK LANDING)
# =========================
st.set_page_config(page_title="Dodaj spady do PDF", layout="centered")

st.markdown("""
<style>
/* ukryj menu/stopkę streamlit */
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}

/* zwęż i wyśrodkuj content */
.block-container {
    max-width: 720px;
    padding-top: 44px;
    padding-bottom: 80px;
}

/* centrowanie */
.center {text-align: center;}

/* przycisk jak w kaflu */
.big-upload-wrap{
    margin-top: 18px;
    display: flex;
    justify-content: center;
}
.big-upload-btn{
    width: 520px;
    max-width: 100%;
    height: 120px;
    background: #e6e6e6;
    border-radius: 18px;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size: 22px;
    font-weight: 700;
    cursor: pointer;
    user-select: none;
}
.big-upload-btn:hover{
    background: #dddddd;
}

/* chowamy standardowy wygląd file_uploader (zostawiamy sam input) */
div[data-testid="stFileUploader"] > label {display:none;}
div[data-testid="stFileUploader"] section {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
}
div[data-testid="stFileUploader"] section div {
    padding: 0 !important;
}
div[data-testid="stFileUploader"] button {
    display:none !important; /* ukryj domyślny przycisk */
}
div[data-testid="stFileUploader"] small {display:none !important;}
</style>
""", unsafe_allow_html=True)

# --- Logo ---
logo_html = ""
try:
    b64 = load_image_as_base64(LOGO_PATH)
    logo_html = f'<div class="center"><img src="data:image/png;base64,{b64}" style="max-width:460px; width:100%; height:auto;"></div>'
except Exception:
    logo_html = '<div class="center" style="font-size:42px; font-weight:900;">Czekalski</div>'

st.markdown(logo_html, unsafe_allow_html=True)

st.markdown('<div class="center" style="margin-top:12px; font-size:18px; font-weight:700;">Dodaj spady do pliku pdf</div>', unsafe_allow_html=True)
st.markdown('<div class="center" style="margin-top:6px; font-size:13px; opacity:0.75;">Spad 3 mm przez rozciąganie krawędzi • DPI 300</div>', unsafe_allow_html=True)

# --- Ukryty uploader + klikany kafel (przycisk) ---
# Uwaga: Streamlit nie pozwala w 100% "kliknąć diva" aby otworzyć dialog pliku,
# więc robimy: kafel + faktyczny uploader pod nim (niewidoczny), ale kliknięcie w kafel
# instruuje użytkownika, żeby kliknął w kafel – a realnie klik będzie w obszar uploader-a.
# Dlatego wstawiamy uploader w dokładnie tym samym miejscu wizualnie.

st.markdown('<div class="big-upload-wrap">', unsafe_allow_html=True)
st.markdown('<div class="big-upload-btn">Dodaj plik</div>', unsafe_allow_html=True)

uploaded = st.file_uploader("PDF", type=["pdf"], label_visibility="collapsed")
st.markdown('</div>', unsafe_allow_html=True)

# jeśli nie ma pliku – kończymy na „landing”
if not uploaded:
    st.stop()

# =========================
# PRZETWARZANIE
# =========================
pdf_bytes = uploaded.read()
page_count = get_page_count(pdf_bytes)

if page_count < 1:
    st.error("PDF nie ma stron.")
    st.stop()

if page_count == 1:
    pages_to_process = [0]
    st.success("Wczytano PDF: 1 strona — dodaję spady dla strony 1.")
else:
    pages_to_process = [0, 1]
    st.success("Wczytano PDF: min. 2 strony — przetwarzam stronę 1 i 2 (przód/tył).")

st.markdown("---")
st.markdown(f"**Parametry:** spad **{BLEED_MM:.1f} mm** na każdą krawędź • stałe **DPI {DPI}**")

originals = []
processed = []

try:
    for idx in pages_to_process:
        orig = render_pdf_page_to_image(pdf_bytes, page_index=idx, dpi=DPI)
        out = apply_bleed_stretch(orig, dpi=DPI, strip_mm=STRIP_MM, stretch_mm=STRETCH_MM)
        originals.append(orig)
        processed.append(out)
except Exception as e:
    st.error(f"Błąd przetwarzania: {e}")
    st.stop()

tabs = st.tabs([f"Strona {i+1}" for i in pages_to_process])

for tab, i, orig_img, proc_img in zip(tabs, pages_to_process, originals, processed):
    with tab:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Oryginał**")
            st.image(orig_img, use_container_width=True)
        with c2:
            st.markdown("**Po dodaniu spadów**")
            st.image(proc_img, use_container_width=True)

out_pdf = images_to_pdf_bytes(processed, dpi=DPI)

st.download_button(
    "Pobierz PDF ze spadami",
    data=out_pdf,
    file_name=uploaded.name.replace(".pdf", "") + f"_spady_{BLEED_MM:.0f}mm.pdf",
    mime="application/pdf",
    use_container_width=True
)

st.caption("Uwaga: plik jest rasteryzowany (tekst staje się obrazem). Jeśli potrzebujesz wersji wektorowej — daj znać.")
