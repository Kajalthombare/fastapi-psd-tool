from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os, zipfile
from psd_tools import PSDImage
from PIL import Image

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# =====================================================
# 🔵 UTIL FUNCTIONS
# =====================================================

def clean_layer_name(name: str):
    """Remove unsafe chars & return clean filename."""
    safe = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    return safe or "unnamed_layer"


def handle_duplicate_name(output_folder, filename):
    """
    If filename exists, rename like:
    name.png → name (1).png → name (2).png
    """
    base, ext = os.path.splitext(filename)
    counter = 1
    new_name = filename

    while os.path.exists(os.path.join(output_folder, new_name)):
        new_name = f"{base} ({counter}){ext}"
        counter += 1

    return new_name


def compress_png(image: Image.Image, output_path: str):
    """Optimize PNG (lossless)."""
    image.save(output_path, format="PNG", optimize=True)


def save_webp(image: Image.Image, output_path: str, quality=80):
    """Save WebP version of asset."""
    webp_path = output_path.replace(".png", ".webp")
    image.save(webp_path, format="WEBP", quality=quality)


# =====================================================
# 🔵 EXPORT FUNCTIONS (UPDATED)
# =====================================================

def export_layers_simple(layers, output_folder):
    """Exports trimmed layer PNG + WebP."""
    for layer in layers:
        if layer.is_group():
            export_layers_simple(layer, output_folder)

        if not layer.is_visible():
            continue

        img = layer.composite()
        if img and img.getbbox():
            safe_name = clean_layer_name(layer.name)
            file_name = f"{safe_name}.png"

            # Handle duplicates
            file_name = handle_duplicate_name(output_folder, file_name)
            full_path = os.path.join(output_folder, file_name)

            # Save compressed PNG and WEBP
            compress_png(img, full_path)
            save_webp(img, full_path)


def export_layers_full_canvas(layers, output_folder, canvas_size=None):
    """Exports full-canvas version with WebP."""
    if canvas_size is None:
        if isinstance(layers, PSDImage):
            canvas_size = (layers.width, layers.height)
        else:
            canvas_size = (layers.psd.width, layers.psd.height)

    for layer in layers:
        if layer.is_group():
            export_layers_full_canvas(layer, output_folder, canvas_size)

        if not layer.is_visible():
            continue

        img = layer.composite()
        if img and img.getbbox():
            safe_name = clean_layer_name(layer.name)
            file_name = f"{safe_name}_full.png"

            # Handle duplicates
            file_name = handle_duplicate_name(output_folder, file_name)
            full_path = os.path.join(output_folder, file_name)

            full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            full_img.paste(img, layer.offset)

            # Save compressed PNG and WEBP
            compress_png(full_img, full_path)
            save_webp(full_img, full_path)


# =====================================================
# 🔵 PROCESSORS
# =====================================================

def process_psd_file(psd_path, output_zip_name="output_layers.zip"):
    temp_out = "output_single"
    if os.path.exists(temp_out):
        shutil.rmtree(temp_out)
    os.makedirs(temp_out)

    psd_name = os.path.splitext(os.path.basename(psd_path))[0]
    output_folder = os.path.join(temp_out, psd_name)
    os.makedirs(output_folder, exist_ok=True)

    psd = PSDImage.open(psd_path)

    export_layers_simple(psd, output_folder)
    export_layers_full_canvas(psd, output_folder)

    shutil.make_archive(output_zip_name.replace(".zip", ""), "zip", temp_out)
    return output_zip_name


def process_psds_from_zip(zip_path, output_zip_name="swiggy_layers.zip"):
    temp_extract = "temp_psds"
    output_base = "output_layers"

    for path in [temp_extract, output_base]:
        if os.path.exists(path):
            shutil.rmtree(path)

    if os.path.exists(output_zip_name):
        os.remove(output_zip_name)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_extract)

    os.makedirs(output_base)

    for root, _, files in os.walk(temp_extract):
        for file in files:
            if file.lower().endswith(".psd"):
                psd_path = os.path.join(root, file)
                psd_name = os.path.splitext(file)[0]
                out_folder = os.path.join(output_base, psd_name)
                os.makedirs(out_folder)

                psd = PSDImage.open(psd_path)
                export_layers_simple(psd, out_folder)
                export_layers_full_canvas(psd, out_folder)

    shutil.make_archive(output_zip_name.replace(".zip", ""), "zip", output_base)
    return output_zip_name


# =====================================================
# 🔵 ROUTES
# =====================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    file_ext = file.filename.lower().split(".")[-1]
    input_path = f"uploads/{file.filename}"
    output_zip = f"outputs/{os.path.splitext(file.filename)[0]}_layers.zip"

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if file_ext == "zip":
        result = process_psds_from_zip(input_path, output_zip)
    elif file_ext == "psd":
        result = process_psd_file(input_path, output_zip)
    else:
        return {"error": "Unsupported file type. Please upload PSD or ZIP."}

    return FileResponse(result, filename=os.path.basename(result))
