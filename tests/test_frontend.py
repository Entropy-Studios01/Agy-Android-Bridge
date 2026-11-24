from fastapi.testclient import TestClient
from server import create_app

def test_static_index_and_manifest(tmp_path):
    app = create_app(default_cwd=str(tmp_path))
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.text
        assert "tab-btn-sessions" in html
        assert "tab-btn-terminal" in html
        assert "btn-resume" in html
        assert "transcript-modal" in html

        manifest_res = client.get("/manifest.json")
        assert manifest_res.status_code == 200
        manifest = manifest_res.json()
        assert "name" in manifest
        assert manifest.get("display") == "standalone"

        icon_res = client.get("/static/icon.svg")
        assert icon_res.status_code == 200
