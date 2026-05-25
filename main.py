from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess, os, uuid, shutil, traceback, zipfile, sys
from pathlib import Path

app = FastAPI(title="FileConvert API")

API_KEY = os.environ.get("API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_key(key: str = Security(api_key_header)):
    # Dacă API_KEY nu e setat pe server, acceptăm orice (mod debug)
    if not API_KEY:
        return key
    if key != API_KEY:
        raise HTTPException(403, "Acces refuzat")
    return key

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = Path("/tmp/fileconvert")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.get("/")
def root():
    libs = {}
    try:
        import pdf2docx; libs["pdf2docx"] = "ok"
    except Exception as e: libs["pdf2docx"] = str(e)
    try:
        import pdf2image; libs["pdf2image"] = "ok"
    except Exception as e: libs["pdf2image"] = str(e)
    try:
        from pypdf import PdfReader; libs["pypdf"] = "ok"
    except Exception as e: libs["pypdf"] = str(e)
    try:
        from docx import Document; libs["python-docx"] = "ok"
    except Exception as e: libs["python-docx"] = str(e)
    lo = subprocess.run(["which", "libreoffice"], capture_output=True, text=True)
    libs["libreoffice"] = "ok" if lo.returncode == 0 else "missing"
    lo2 = subprocess.run(["libreoffice", "--version"], capture_output=True, text=True)
    libs["libreoffice_version"] = lo2.stdout.strip()
    return {"status": "online", "version": "1.0.0", "libraries": libs}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/convert")
async def convert_file(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    _key: str = Security(verify_key)
):
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()
    error_detail = ""

    try:
        input_ext = Path(file.filename).suffix.lower().lstrip(".")
        input_path = job_dir / f"input.{input_ext}"
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        target_format = target_format.lower().strip(".")
        error_detail = f"starting: {input_ext} -> {target_format}, size={len(content)}"

        output_path = None

        # PDF -> DOCX
        if input_ext == "pdf" and target_format == "docx":
            error_detail += " | trying pdf2docx"
            try:
                from pdf2docx import Converter
                output_path = job_dir / "output.docx"
                cv = Converter(str(input_path))
                cv.convert(str(output_path))
                cv.close()
                error_detail += " | pdf2docx ok"
            except Exception as e:
                error_detail += f" | pdf2docx failed: {e}"
                output_path = None

        # PDF -> JPG/PNG
        elif input_ext == "pdf" and target_format in ("jpg", "jpeg", "png"):
            error_detail += " | trying pdf2image"
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(str(input_path), dpi=150)
                output_path = job_dir / f"output.{target_format}"
                pil_fmt = "JPEG" if target_format in ("jpg","jpeg") else "PNG"
                images[0].save(str(output_path), pil_fmt)
                error_detail += " | pdf2image ok"
            except Exception as e:
                error_detail += f" | pdf2image failed: {e}"
                raise HTTPException(500, error_detail)

        # Toate celelalte -> LibreOffice
        if output_path is None:
            error_detail += " | trying libreoffice"
            fmt_map = {
                "pdf":  "pdf:writer_pdf_Export",
                "docx": "docx:MS Word 2007 XML",
                "xlsx": "xlsx:Calc MS Excel 2007 XML",
                "pptx": "pptx:Impress MS PowerPoint 2007 XML",
                "odt":  "odt:writer8",
                "txt":  "txt:Text",
                "html": "html:HTML (StarWriter)",
                "csv":  "csv:Text - txt - csv (StarCalc)",
            }
            lo_fmt = fmt_map.get(target_format, target_format)
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", lo_fmt,
                 "--outdir", str(job_dir), str(input_path)],
                capture_output=True, text=True, timeout=120
            )
            error_detail += f" | LO rc={result.returncode} stdout={result.stdout[:200]} stderr={result.stderr[:200]}"

            if result.returncode != 0:
                raise HTTPException(500, error_detail)

            # Găsește output - orice fișier care nu e input
            for f in sorted(job_dir.iterdir()):
                if f.name != input_path.name:
                    output_path = f
                    break

        if not output_path or not output_path.exists():
            raise HTTPException(500, f"Output negăsit. {error_detail}")

        original_name = Path(file.filename).stem
        return FileResponse(
            path=str(output_path),
            filename=f"{original_name}.{target_format}",
            media_type="application/octet-stream",
            background=_cleanup(job_dir)
        )

    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        tb = traceback.format_exc()
        raise HTTPException(500, f"{error_detail} | EXCEPTION: {str(e)} | {tb[-500:]}")


@app.post("/split")
async def split_pdf(
    file: UploadFile = File(...),
    pages_per_split: int = Form(1),
    _key: str = Security(verify_key)
):
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise HTTPException(500, "pypdf nu e instalat")
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()
    try:
        input_path = job_dir / "input.pdf"
        with open(input_path, "wb") as f:
            f.write(await file.read())
        reader = PdfReader(str(input_path))
        total = len(reader.pages)
        zip_path = job_dir / "split.zip"
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            for i in range(0, total, pages_per_split):
                writer = PdfWriter()
                for j in range(i, min(i + pages_per_split, total)):
                    writer.add_page(reader.pages[j])
                part_path = job_dir / f"part_{i//pages_per_split + 1}.pdf"
                with open(part_path, "wb") as f:
                    writer.write(f)
                zf.write(part_path, part_path.name)
        return FileResponse(str(zip_path), filename="split.zip", media_type="application/zip", background=_cleanup(job_dir))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


@app.post("/merge")
async def merge_pdfs(
    files: list[UploadFile] = File(...),
    _key: str = Security(verify_key)
):
    try:
        from pypdf import PdfWriter
    except ImportError:
        raise HTTPException(500, "pypdf nu e instalat")
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()
    try:
        writer = PdfWriter()
        for i, f in enumerate(files):
            path = job_dir / f"input_{i}.pdf"
            with open(path, "wb") as fp:
                fp.write(await f.read())
            writer.append(str(path))
        output_path = job_dir / "merged.pdf"
        with open(output_path, "wb") as fp:
            writer.write(fp)
        return FileResponse(str(output_path), filename="merged.pdf", media_type="application/pdf", background=_cleanup(job_dir))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


@app.post("/compress")
async def compress_pdf(
    file: UploadFile = File(...),
    quality: int = Form(85),
    _key: str = Security(verify_key)
):
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise HTTPException(500, "pypdf nu e instalat")
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()
    try:
        input_path = job_dir / "input.pdf"
        with open(input_path, "wb") as f:
            f.write(await file.read())
        reader = PdfReader(str(input_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in writer.pages:
            page.compress_content_streams()
        output_path = job_dir / "compressed.pdf"
        with open(output_path, "wb") as f:
            writer.write(f)
        return FileResponse(str(output_path), filename="compressed.pdf", media_type="application/pdf", background=_cleanup(job_dir))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


@app.post("/margins")
async def adjust_margins(
    file: UploadFile = File(...),
    top: float = Form(20), bottom: float = Form(20),
    left: float = Form(20), right: float = Form(20),
    _key: str = Security(verify_key)
):
    try:
        from docx import Document
        from docx.shared import Mm
    except ImportError:
        raise HTTPException(500, "python-docx nu e instalat")
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir()
    try:
        input_ext = Path(file.filename).suffix.lower()
        input_path = job_dir / f"input{input_ext}"
        with open(input_path, "wb") as f:
            f.write(await file.read())
        if input_ext != ".docx":
            raise HTTPException(400, "Doar DOCX suportat")
        doc = Document(str(input_path))
        for section in doc.sections:
            section.top_margin = Mm(top)
            section.bottom_margin = Mm(bottom)
            section.left_margin = Mm(left)
            section.right_margin = Mm(right)
        output_path = job_dir / "output.docx"
        doc.save(str(output_path))
        return FileResponse(str(output_path), filename=f"margins_{file.filename}", media_type="application/octet-stream", background=_cleanup(job_dir))
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


def _cleanup(job_dir):
    from starlette.background import BackgroundTask
    return BackgroundTask(shutil.rmtree, job_dir, True)
