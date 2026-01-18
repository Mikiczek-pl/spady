import io
import fitz  # PyMuPDF
import streamlit as st
from PIL import Image

# --- Stała zasada spadów ---
STRIP_MM = 2.0       # wycinany pasek od krawędzi
STRETCH_MM = 5.0     # rozciągnięcie paska
BLEED_MM = STRETCH_MM - STRIP_MM  # 3 mm

def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm * dpi / 25.4))

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

    # zabezpieczenie przy bardzo małych stronach / DPI
    if strip_px * 2 >= h or strip_px * 2 >= w:
        raise ValueError(
            "Pasek 2mm jest za duży względem obrazu po rasteryzacji. "
            "Zwiększ DPI albo sprawdź, czy PDF ma prawidłowy rozmiar strony."
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

def get_page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = doc.page_count
    doc.close()
    return n

# ---------------- UI ----------------
st.set_page_config(page_title="Auto-spady (PDF) — 2 strony", layout="wide")
st.title("Auto-spady do PDF (2 strony) — spad 3 mm przez rozciąganie krawędzi")

uploaded = st.file_uploader("Wgraj PDF (1–2 strony: przód/tył). Dowolny rozmiar strony.", type=["pdf"])
dpi = st.slider("DPI podglądu / przetwarzania", 150, 600, 300, step=50)

st.caption(f"Zasada stała: pasek {STRIP_MM} mm → {STRETCH_MM} mm, czyli spad {BLEED_MM:.1f} mm z każdej strony.")

if not uploaded:
    st.info("Wgraj PDF, a pokażę podgląd (przód/tył) i wygeneruję PDF ze spadami.")
    st.stop()

pdf_bytes = uploaded.read()
page_count = get_page_count(pdf_bytes)

if page_count < 1:
    st.error("PDF nie ma stron.")
    st.stop()

if page_count == 1:
    st.warning("PDF ma 1 stronę. Zrobię spady tylko dla strony 1 (przód).")
    pages_to_process = [0]
else:
    st.success("PDF ma co najmniej 2 strony — przetworzę stronę 1 i 2 (przód/tył).")
    pages_to_process = [0, 1]

originals = []
processed = []

try:
    for idx in pages_to_process:
        orig = render_pdf_page_to_image(pdf_bytes, page_index=idx, dpi=dpi)
        out = apply_bleed_stretch(orig, dpi=dpi, strip_mm=STRIP_MM, stretch_mm=STRETCH_MM)
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
            st.image(orig_img, use_column_width=True)
        with c2:
            st.markdown("**Po dodaniu spadów**")
            st.image(proc_img, use_column_width=True)

        st.info(f"Efekt: +{BLEED_MM:.1f} mm na każdą krawędź (góra/dół/lewo/prawo).")

out_pdf = images_to_pdf_bytes(processed, dpi=dpi)

st.download_button(
    "Pobierz PDF ze spadami (1–2 strony)",
    data=out_pdf,
    file_name=uploaded.name.replace(".pdf", "") + f"_spady_{int(BLEED_MM)}mm.pdf",
    mime="application/pdf"
)
