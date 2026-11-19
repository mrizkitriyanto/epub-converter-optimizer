import io
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from eco.options import Options
from eco.style import BUNDLED_FONTS
from eco.web.app import create_app
from eco.xtc.codec import encode_xth
from eco.xtc.container import write_container

LOCAL = "http://127.0.0.1:8000"


def client(tmp_path):
    app = create_app(tmp_path, token=None)
    return app, TestClient(app, base_url=LOCAL)


def job_with_output(app, fmt="xtch"):
    store = app.state.store
    info = store.create(
        [("book.md", io.BytesIO(b"# One\n\nFirst chapter text.\n"))],
        Options(formats=(fmt,)),
    )
    output = store.job_dir(info.id) / "output" / f"book.x4.{fmt}"
    output.write_bytes(b"converted")
    info.files[0].outputs = {fmt: str(output)}
    info.status = "done"
    store.save(info)
    return info, output


def test_rejects_a_renamed_text_file_as_a_font(tmp_path):
    app, c = client(tmp_path)
    job, _ = job_with_output(app)

    response = c.post(
        f"/api/jobs/{job.id}/fonts",
        files={"file": ("pretend.ttf", b"plain text", "font/ttf")},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Not a usable font file"}


def test_uploads_a_font_and_lists_its_family_and_weight(tmp_path):
    app, c = client(tmp_path)
    job, _ = job_with_output(app)
    font = BUNDLED_FONTS["Bitter"][400]

    response = c.post(
        f"/api/jobs/{job.id}/fonts",
        files={"file": (font.name, font.read_bytes(), "font/ttf")},
    )

    assert response.status_code == 200
    assert response.json() == {"family": "Bitter", "weights": [400]}
    listed = {item["family"]: item["weights"] for item in c.get(f"/api/fonts?job={job.id}").json()}
    assert 400 in listed["Bitter"]

    rebuilt = c.post(
        f"/api/jobs/{job.id}/rebuild",
        json={**job.options, "style": {**job.options["style"], "font": "Bitter"}},
    )
    assert rebuilt.status_code == 201
    copied = app.state.store.job_dir(rebuilt.json()["id"]) / "fonts" / font.name
    assert copied.read_bytes() == font.read_bytes()


def test_xtch_live_style_is_exactly_four_level_and_invalid_style_is_422(tmp_path):
    app, c = client(tmp_path)
    job, _ = job_with_output(app)
    base = f"/api/jobs/{job.id}/files/0/live.png?format=xtch&chapter=0"

    response = c.get(base + '&style={"font_size":40}')

    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        assert set(image.get_flattened_data()) <= {0, 85, 170, 255}
    black_white = c.get(
        f'/api/jobs/{job.id}/files/0/live.png?format=xtc&chapter=0&style={{"mode":"xtg"}}'
    )
    assert black_white.status_code == 200
    with Image.open(BytesIO(black_white.content)) as image:
        assert set(image.get_flattened_data()) <= {0, 255}
    refused = c.get(base + '&style={"font_size":500}')
    assert refused.status_code == 422
    assert "font_size" in refused.json()["error"]


def test_decoded_xtc_page_route_reads_the_produced_container(tmp_path):
    app, c = client(tmp_path)
    job, output = job_with_output(app)
    page = Image.new("L", (8, 8), 170)
    output.write_bytes(
        write_container(
            [encode_xth(page)],
            hq=True,
            width=8,
            height=8,
            title="Book",
            author="",
            language="en",
            chapters=[],
        )
    )

    response = c.get(f"/api/jobs/{job.id}/files/0/xtc/1.png")

    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as decoded:
        assert decoded.size == (8, 8) and set(decoded.get_flattened_data()) == {170}


def test_page_contains_all_page_style_controls(tmp_path):
    _, c = client(tmp_path)
    html = c.get("/").text

    for element_id in (
        "page-style",
        "font",
        "font-weight",
        "line-height",
        "dither-strength",
        "bar-position",
        "orientation",
        "copy-style",
    ):
        assert f'id="{element_id}"' in html
