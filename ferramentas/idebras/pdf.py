"""Extração de ZIP e conversão de imagens para PDF."""

from __future__ import annotations

import zipfile
from pathlib import Path

import img2pdf

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

A4_PORTRAIT = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
BORDER = (img2pdf.mm_to_pt(5), img2pdf.mm_to_pt(5), img2pdf.mm_to_pt(5), img2pdf.mm_to_pt(5))


def extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extrai o ZIP em dest_dir/images e retorna a pasta das imagens."""
    images_dir = dest_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(images_dir)

    return images_dir


def _collect_images(images_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in images_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(path)
    files.sort(key=lambda p: p.name.lower())
    return files


def images_to_pdf(images_dir: Path, pdf_path: Path) -> Path:
    """Gera PDF A4 com cada foto encaixada na página."""
    images = _collect_images(images_dir)
    if not images:
        raise FileNotFoundError(
            f"Nenhuma imagem encontrada em {images_dir}. "
            "Verifique se o ZIP contém fotos."
        )

    layout = img2pdf.get_layout_fun(
        pagesize=A4_PORTRAIT,
        border=BORDER,
        fit=img2pdf.FitMode.into,
        auto_orient=True,
    )

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(
            img2pdf.convert(
                [str(p) for p in images],
                layout_fun=layout,
                rotation=img2pdf.Rotation.ifvalid,
            )
        )

    return pdf_path


def zip_to_pdf(zip_path: Path, dest_dir: Path, pdf_name: str = "fotos.pdf") -> Path:
    """Extrai o ZIP e gera o PDF no diretório de destino."""
    images_dir = extract_zip(zip_path, dest_dir)
    return images_to_pdf(images_dir, dest_dir / pdf_name)
