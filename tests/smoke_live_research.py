# tests/smoke_live_research.py
"""
Live smoke qualification script testing real Serper, Tavily, Pixabay, and Image Download endpoints.
Run via: python tests/smoke_live_research.py
"""

import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.web_search_tools import WebSearchTool
from tools.image_asset_tools import ImageSearchTool, DownloadImageTool
from config.research_config import get_research_status

def run_live_smoke():
    print("=== HERMES LIVE RESEARCH & VISUAL ASSET SMOKE TEST ===")
    status = get_research_status()
    print(f"Provider Status: Serper={status['serper']['configured']}, Tavily={status['tavily']['configured']}, Pixabay={status['pixabay']['configured']}")

    # 1. Live Serper Web Search
    print("\n[1] Testing Live Web Search (Serper)...")
    search_tool = WebSearchTool()
    res = search_tool.execute(WebSearchTool.Input(query="ISRO LVM3 Chandrayaan 3 mission", num_results=3))
    assert res.success, f"Search failed: {res.error}"
    assert len(res.metadata.get("results", [])) > 0, "No results returned"
    print(f"-> SUCCESS: Sourced {len(res.metadata['results'])} results via {res.metadata['provider']}:")
    for r in res.metadata['results'][:2]:
        print(f"   * {r['title']} ({r['url'][:60]}...)")

    # 2. Live Pixabay Image Search
    print("\n[2] Testing Live Image Search (Pixabay)...")
    img_tool = ImageSearchTool()
    img_res = img_tool.execute(ImageSearchTool.Input(query="rocket launch", num_results=3, image_type="photo"))
    assert img_res.success, f"Image search failed: {img_res.error}"
    images = img_res.metadata.get("images", [])
    assert len(images) > 0, "No image candidates found"
    print(f"-> SUCCESS: Found {len(images)} images via {img_res.metadata['provider']}:")
    candidate = images[0]
    print(f"   * Image ID {candidate['id']}: {candidate['title']} ({candidate['width']}x{candidate['height']})")
    print(f"   * Author: {candidate['author']} | License: {candidate['license']}")

    # 3. Live Image Download into Temporary Workspace
    print("\n[3] Testing Live Download and Verification...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["HERMES_WORKSPACE_ROOT"] = tmp_dir
        dl_tool = DownloadImageTool()
        dl_res = dl_tool.execute(DownloadImageTool.Input(
            image_url=candidate["image_url"],
            filename="live_rocket.jpg",
            alt_text="ISRO Launch Simulation Asset",
            attribution={
                "author": candidate["author"],
                "license": candidate["license"],
                "source_platform": candidate["source_platform"],
                "preview_url": candidate.get("preview_url"),
            }
        ))
        assert dl_res.success, f"Download failed: {dl_res.error}"
        img_path = Path(tmp_dir) / "assets" / "images" / "live_rocket.jpg"
        manifest_path = Path(tmp_dir) / "assets" / "images" / "asset_manifest.json"
        credits_path = Path(tmp_dir) / "IMAGE_CREDITS.md"

        assert img_path.exists(), "Image file was not written to disk"
        assert manifest_path.exists(), "asset_manifest.json was not created"
        assert credits_path.exists(), "IMAGE_CREDITS.md was not created"
        print(f"-> SUCCESS: Downloaded {img_path.stat().st_size} bytes ({dl_res.metadata['width']}x{dl_res.metadata['height']})")
        print(f"-> Verified manifest and credits generated cleanly.")

    print("\n=== ALL LIVE SMOKE TESTS PASSED CLEANLY ===")

if __name__ == "__main__":
    run_live_smoke()
