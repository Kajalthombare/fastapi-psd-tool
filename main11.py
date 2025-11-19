from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os, uuid, zipfile
from psd_tools import PSDImage
from PIL import Image

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------- PSD Export Functions ----------------

def export_layers_simple(layers, output_folder, parent=""):
    for i, layer in enumerate(layers):
        name = f"{parent}_{i}_{layer.name}".strip("_")
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_')).rstrip()

        if layer.is_group():
            export_layers_simple(layer, output_folder, parent=name)
            group_img = layer.composite()
            if group_img and group_img.getbbox():
                group_img.save(os.path.join(output_folder, f"{safe_name}_group_simple.png"))
        else:
            if layer.is_visible():
                img = layer.composite()
                if img and img.getbbox():
                    img.save(os.path.join(output_folder, f"{safe_name}_simple.png"))

def export_layers_full_canvas(layers, output_folder, parent="", canvas_size=None):
    if canvas_size is None:
        if isinstance(layers, PSDImage):
            canvas_size = (layers.width, layers.height)
        elif hasattr(layers, "psd"):
            canvas_size = (layers.psd.width, layers.psd.height)
        else:
            raise ValueError("Cannot determine canvas size")

    for i, layer in enumerate(layers):
        name = f"{parent}_{i}_{layer.name}".strip("_")
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_')).rstrip()

        if layer.is_group():
            export_layers_full_canvas(layer, output_folder, parent=name, canvas_size=canvas_size)
            group_img = layer.composite()
            if group_img and group_img.getbbox():
                full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                full_img.paste(group_img, layer.offset)
                full_img.save(os.path.join(output_folder, f"{safe_name}_group_full.png"))
        else:
            if layer.is_visible():
                img = layer.composite()
                if img and img.getbbox():
                    full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                    full_img.paste(img, layer.offset)
                    full_img.save(os.path.join(output_folder, f"{safe_name}_full.png"))

# ---------------- Core Processing Functions ----------------

def process_psd_file(psd_path, output_zip_name="output_layers.zip"):
    output_base = "output_single"
    if os.path.exists(output_base):
        shutil.rmtree(output_base)
    os.makedirs(output_base, exist_ok=True)

    psd_name = os.path.splitext(os.path.basename(psd_path))[0]
    output_folder = os.path.join(output_base, psd_name)
    os.makedirs(output_folder, exist_ok=True)

    psd = PSDImage.open(psd_path)
    export_layers_simple(psd, output_folder)
    export_layers_full_canvas(psd, output_folder)

    shutil.make_archive(output_zip_name.replace(".zip", ""), 'zip', output_base)
    return output_zip_name

def process_psds_from_zip_one_folder(zip_path, output_zip_name="swiggy_layers.zip"):
    temp_extract = "temp_psds"
    output_base = "output_layers"

    for path in [temp_extract, output_base, output_zip_name]:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_extract)

    os.makedirs(output_base, exist_ok=True)

    for root, _, files in os.walk(temp_extract):
        for file in files:
            if file.lower().endswith(".psd"):
                psd_path = os.path.join(root, file)
                psd_name = os.path.splitext(file)[0]
                output_folder = os.path.join(output_base, psd_name)
                os.makedirs(output_folder, exist_ok=True)

                psd = PSDImage.open(psd_path)
                export_layers_simple(psd, output_folder)
                export_layers_full_canvas(psd, output_folder)

    shutil.make_archive(output_zip_name.replace(".zip", ""), 'zip', output_base)
    return output_zip_name

# ---------------- Routes ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    file_ext = file.filename.split(".")[-1].lower()
    input_path = f"uploads/{file.filename}"
    output_zip = f"outputs/{os.path.splitext(file.filename)[0]}_layers.zip"

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if file_ext == "zip":
        result = process_psds_from_zip_one_folder(input_path, output_zip)
    elif file_ext == "psd":
        result = process_psd_file(input_path, output_zip)
    else:
        return {"error": "Unsupported file type. Please upload PSD or ZIP."}

    return FileResponse(result, filename=os.path.basename(result))
