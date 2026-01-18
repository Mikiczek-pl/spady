import io
import base64
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image

# =========================
# USTAWIENIA (STAŁE)
# =========================
STRIP_MM = 2.0
STRETCH_MM = 5.0
BLEED_MM = STRETCH_MM - STRIP_MM  # 3 mm
DPI = 300

LOGO_PATH = "assets/logo CR.png"  # <- Twoje logo


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
    w, h = img.size
    strip_px = mm_to_px(strip_mm, dpi)
    stretch_px = mm_to_px(stretch_mm, dpi)

    if strip_px <= 0 or stretch_px <= 0:
        raise ValueError("Błędne parametry po przeliczeniu na px.")

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
# UI
# =========================
st.set_page_config(page_title="Dodaj spady do PDF", layout="wide")

st.markdown("""
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}

.block-container{
    max-width: 1200px;
    padding-top: 26px;
    padding-bottom: 40px;
}

.center {text-align:center;}
.small-note{opacity:.75; font-size:13px;}

/* Uploader centrowany */
div[data-testid="stFileUploader"]{
    display:flex;
    justify-content:center;
}
div[data-testid="stFileUploader"] section{
    width: 640px;
    max-width: 100%;
}

/* Pasek "wybrany plik" */
.filebar{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    background:#f5f7fa;
    border:1px solid #e6e8ee;
    border-radius:12px;
    padding:10px 14px;
    margin: 6px auto 12px auto;
    max-width: 880px;
}
.filename{
    font-weight:600;
}
</style>
""", unsafe_allow_html=True)

# --- Logo + nagłówek ---
try:
    b64 = load_image_as_base64(LOGO_PATH)
    st.markdown(
        f'<div class="center"><img src="data:image/png;base64,{b64}" style="max-width:520px; width:100%; height:auto;"></div>',
        unsafe_allow_html=True
    )
except Exception:
    st.markdown('<div class="center" style="font-size:42px; font-weight:900;">Centrum Reklamy</div>', unsafe_allow_html=True)

st.markdown('<div class="center" style="margin-top:8px; font-size:18px; font-weight:700;">Dodaj spady do pliku PDF</div>', unsafe_allow_html=True)
st.markdown(f'<div class="center small-note">Spad {BLEED_MM:.0f} mm przez rozciąganie krawędzi • stałe DPI {DPI}</div>', unsafe_allow_html=True)
st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

# --- Upload (a potem "zwinięcie") ---
# Używamy session_state, żeby po wgraniu pokazać pasek z nazwą + opcję zmiany pliku
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
    st.session_state.pdf_name = None

if st.session_state.pdf_bytes is None:
    # bez etykiety (pusta), żeby nie było napisu
    uploaded = st.file_uploader("", type=["pdf"], label_visibility="collapsed")
    if not uploaded:
        st.stop()
    st.session_state.pdf_bytes = uploaded.read()
    st.session_state.pdf_name = uploaded.name
else:
    # zwinięty widok: nazwa + przycisk zmiany
    st.markdown(
        f"""
        <div class="filebar">
            <div class="filename">📄 {st.session_state.pdf_name}</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    cbtn1, cbtn2 = st.columns([1, 3])
    with cbtn1:
        if st.button("Zmień plik", use_container_width=True):
            st.session_state.pdf_bytes = None
            st.session_state.pdf_name = None
            st.rerun()
    with cbtn2:
        st.caption("Jeśli chcesz wgrać inny PDF, kliknij „Zmień plik”.")

pdf_bytes = st.session_state.pdf_bytes
page_count = get_page_count(pdf_bytes)

if page_count < 1:
    st.error("PDF nie ma stron.")
    st.stop()

pages_to_process = [0] if page_count == 1 else [0, 1]

if page_count == 1:
    st.success("Wczytano PDF: 1 strona — dodaję spady dla strony 1.")
else:
    st.success("Wczytano PDF: min. 2 strony — przetwarzam stronę 1 i 2 (przód/tył).")

st.markdown("---")

# =========================
# PRZETWARZANIE
# =========================
originals = []
processed = []

with st.spinner("Przetwarzam…"):
    try:
        for idx in pages_to_process:
            orig = render_pdf_page_to_image(pdf_bytes, page_index=idx, dpi=DPI)
            out = apply_bleed_stretch(orig, dpi=DPI, strip_mm=STRIP_MM, stretch_mm=STRETCH_MM)
            originals.append(orig)
            processed.append(out)
    except Exception as e:
        st.error(f"Błąd przetwarzania: {e}")
        st.stop()

# =========================
# PODGLĄD: DUŻY, CZYTELNY, MAŁO PUSTKI
# =========================
st.markdown("## Podgląd")
st.caption("Każda strona: po lewej oryginał, po prawej po dodaniu spadów.")

# Dwie strony obok siebie. Każda strona ma 2 kolumny (oryginał/spady) w środku.
page_cols = st.columns(len(pages_to_process), gap="large")

for col, page_idx, orig_img, proc_img in zip(page_cols, pages_to_process, originals, processed):
    with col:
        st.markdown(f"### Strona {page_idx+1}")
        a, b = st.columns(2, gap="small")
        with a:
            st.markdown("**Oryginał**")
            st.image(orig_img, use_container_width=True)
        with b:
            st.markdown("**Po spadach**")
            st.image(proc_img, use_container_width=True)

# =========================
# POBRANIE
# =========================
out_pdf = images_to_pdf_bytes(processed, dpi=DPI)

st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
st.download_button(
    "Pobierz PDF ze spadami",
    data=out_pdf,
    file_name=st.session_state.pdf_name.replace(".pdf", "") + f"_spady_{BLEED_MM:.0f}mm.pdf",
    mime="application/pdf",
    use_container_width=True
)

st.caption("Uwaga: PDF jest rasteryzowany (tekst staje się obrazem).")
