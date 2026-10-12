"""/api/public/app/… tells the phone app about its newest build and serves it."""
import json

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def releases(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "APP_RELEASES_DIR", tmp_path)
    return tmp_path


def publish(folder, package="com.icreateflow.companion", code=3, apk_name=None):
    apk = apk_name or f"{package}-{code}.apk"
    (folder / apk).write_bytes(b"PK-not-really-an-apk")
    (folder / f"{package}.json").write_text(json.dumps({
        "version_code": code, "version_name": f"0.{code}.0", "apk": apk,
        "sha256": "ab" * 32, "notes": "Find profiles",
    }))


def test_it_describes_the_newest_build(releases):
    publish(releases)
    res = TestClient(main.app).get("/api/public/app/com.icreateflow.companion")
    assert res.status_code == 200
    body = res.json()
    assert body["version_code"] == 3
    assert body["version_name"] == "0.3.0"
    assert body["size"] == len(b"PK-not-really-an-apk")
    assert body["url"] == "/api/public/app/com.icreateflow.companion/apk"


def test_it_serves_the_file_it_describes(releases):
    publish(releases)
    res = TestClient(main.app).get("/api/public/app/com.icreateflow.companion/apk")
    assert res.status_code == 200
    assert res.content == b"PK-not-really-an-apk"
    assert res.headers["content-type"] == "application/vnd.android.package-archive"


def test_nothing_published_is_a_404_the_app_reads_as_up_to_date(releases):
    assert TestClient(main.app).get("/api/public/app/com.icreateflow.companion").status_code == 404


def test_a_manifest_without_its_file_is_not_offered(releases):
    """The publish script uploads the file first; if it's missing, say nothing."""
    publish(releases)
    (releases / "com.icreateflow.companion-3.apk").unlink()
    assert TestClient(main.app).get("/api/public/app/com.icreateflow.companion").status_code == 404


@pytest.mark.parametrize("package", ["..", "..%2F..%2Fetc", "com", "Com.Bad", "com.x;rm"])
def test_it_only_answers_for_package_names(releases, package):
    assert TestClient(main.app).get(f"/api/public/app/{package}").status_code == 404


def test_the_manifest_cannot_point_outside_the_folder(releases, tmp_path_factory):
    """`apk` is reduced to a bare file name, so `../` can't reach other files."""
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.apk"
    outside.write_bytes(b"secret")
    publish(releases, apk_name=f"../{outside.parent.name}/secret.apk")
    assert TestClient(main.app).get("/api/public/app/com.icreateflow.companion/apk").status_code == 404
