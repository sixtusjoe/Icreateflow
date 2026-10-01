"""/api/files serves uploads, output and music — and nothing else."""
import pytest

import main


@pytest.mark.parametrize("path", [
    ".env", "main.py", "../backend/main.py", "uploads/../.env", "uploads/../../etc/passwd", "/etc/passwd",
])
def test_the_file_route_serves_nothing_outside_its_folders(path):
    """It used to hand out the server's own .env and source code."""
    assert main._servable(path) is None


def test_the_file_route_still_serves_uploads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "uploads" / "brand").mkdir(parents=True)
    (tmp_path / "uploads" / "brand" / "slide.jpg").write_bytes(b"x")
    (tmp_path / ".env").write_text("SECRET=1")
    assert main._servable("uploads/brand/slide.jpg") is not None
    assert main._servable("brand/slide.jpg") is not None
    assert main._servable(".env") is None
    assert main._servable("uploads/../.env") is None
