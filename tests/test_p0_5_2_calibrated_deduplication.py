"""
Unit tests for P0.5.2 Calibrated Perceptual Deduplication in AssetPipeline.
Verifies:
1. Rejection of identical images (SHA256 and dHash == 0).
2. Rejection of near-duplicate images (dHash hamming distance <= 6).
3. Acceptance of perceptually distinct images (dHash hamming distance > 6).
"""

import tempfile
import pathlib
import pytest
from PIL import Image, ImageDraw
from core.asset_pipeline import AssetPipeline


def test_deduplication_exact_identical_rejected():
    with tempfile.TemporaryDirectory() as td:
        ws = pathlib.Path(td)
        img_dir = ws / "assets" / "images"
        img_dir.mkdir(parents=True)

        # Base image
        im = Image.new("RGB", (120, 120), (200, 50, 50))
        d = ImageDraw.Draw(im)
        d.rectangle([20, 20, 80, 80], fill=(50, 200, 50))
        im.save(img_dir / "hero.png")
        im.save(img_dir / "hero_dup.png")

        (ws / "index.html").write_text(
            '<img src="assets/images/hero.png"><img src="assets/images/hero_dup.png">',
            encoding="utf-8"
        )

        is_valid, missing, found = AssetPipeline.verify_workspace_assets(ws)
        assert not is_valid
        assert any("Duplicate image asset" in m or "Perceptually identical" in m for m in missing)


def test_deduplication_near_duplicate_rejected():
    with tempfile.TemporaryDirectory() as td:
        ws = pathlib.Path(td)
        img_dir = ws / "assets" / "images"
        img_dir.mkdir(parents=True)

        # Base image
        im1 = Image.new("RGB", (120, 120), (100, 100, 200))
        d1 = ImageDraw.Draw(im1)
        d1.rectangle([10, 10, 90, 90], fill=(200, 100, 50))
        im1.save(img_dir / "feat1.png")

        # Near-duplicate: slight pixel variation so SHA differs, but dHash <= 6
        im2 = im1.copy()
        d2 = ImageDraw.Draw(im2)
        d2.point((1, 1), fill=(255, 255, 255))
        im2.save(img_dir / "feat2.png")

        (ws / "index.html").write_text(
            '<img src="assets/images/feat1.png"><img src="assets/images/feat2.png">',
            encoding="utf-8"
        )

        is_valid, missing, found = AssetPipeline.verify_workspace_assets(ws)
        assert not is_valid
        assert any("dHash distance" in m for m in missing)


def test_deduplication_distinct_images_accepted():
    with tempfile.TemporaryDirectory() as td:
        ws = pathlib.Path(td)
        img_dir = ws / "assets" / "images"
        img_dir.mkdir(parents=True)

        # Image A: green background with red box
        im1 = Image.new("RGB", (120, 120), (30, 150, 40))
        d1 = ImageDraw.Draw(im1)
        d1.rectangle([15, 15, 60, 60], fill=(220, 40, 40))
        im1.save(img_dir / "nature.png")

        # Image B: blue background with yellow diagonal stroke
        im2 = Image.new("RGB", (120, 120), (20, 40, 180))
        d2 = ImageDraw.Draw(im2)
        d2.line([(0, 0), (120, 120)], fill=(250, 220, 20), width=15)
        im2.save(img_dir / "tech.png")

        (ws / "index.html").write_text(
            '<img src="assets/images/nature.png"><img src="assets/images/tech.png">',
            encoding="utf-8"
        )

        is_valid, missing, found = AssetPipeline.verify_workspace_assets(ws)
        assert is_valid
        assert len(missing) == 0
        assert len(found) == 2
