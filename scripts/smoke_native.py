"""Exercise a built eco folder without Python or Java from the host."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def smoke(app: Path) -> None:
    exe = app / ("eco.exe" if os.name == "nt" else "eco")
    java = app / "runtime" / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")
    jar = app / "runtime" / "epubcheck" / "epubcheck.jar"
    for path in (exe, java, jar, jar.parent / "lib", jar.parent / "LICENSE.txt"):
        if not path.exists():
            raise RuntimeError(f"Missing bundle component: {path}")
    internal = app / "_internal"
    for path in (
        internal / "latex2mathml" / "unimathsymbols.txt",
        internal / "docling_parse" / "pdf_resources",
        internal / "rapidocr" / "default_models.yaml",
        internal / "rapidocr" / "config.yaml",
        internal / "rapidocr" / "inference_engine" / "pytorch" / "networks" / "arch_config.yaml",
    ):
        if not path.exists():
            raise RuntimeError(f"Missing PDF component: {path}")
    if not list((internal / "torchvision").glob("_C*")):
        raise RuntimeError("Missing torchvision native operations")
    if not list(internal.glob("docling_slim-*.dist-info/entry_points.txt")):
        raise RuntimeError("Missing Docling plugin metadata")
    env = os.environ.copy()
    for name in ("ECO_JAVA", "ECO_EPUBCHECK_JAR", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    subprocess.run([str(exe), "--help"], env=env, check=True, capture_output=True, timeout=30)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source = work / "book.md"
        source.write_text("# One\n\nA small book.\n", encoding="utf-8")
        result = subprocess.run(
            [
                str(exe),
                "convert",
                str(source),
                "-o",
                str(work / "out"),
                "--data",
                str(work / "data"),
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        epub = work / "out" / "book.x4-pro.epub"  # the default device
        if result.returncode or not epub.is_file():
            raise RuntimeError(f"Bundled conversion failed: {result.stdout}\n{result.stderr}")
        checked = subprocess.run(
            [str(java), "-jar", str(jar), str(epub)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if checked.returncode or "No errors or warnings detected." not in checked.stdout:
            raise RuntimeError(f"Bundled EPUBCheck failed: {checked.stdout}\n{checked.stderr}")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        web_log = work / "web.log"
        with web_log.open("wb") as log:
            proc = subprocess.Popen(
                [
                    str(exe),
                    "web",
                    "--no-browser",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--data",
                    str(work / "web-data"),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                for _ in range(40):
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/health", timeout=1
                        ) as response:
                            if json.load(response)["ok"] is True:
                                break
                    except (OSError, ValueError):
                        time.sleep(0.5)
                else:
                    raise RuntimeError(
                        f"Bundled web server failed: {web_log.read_text(errors='replace')}"
                    )
                boundary = "eco-native-smoke"
                body = (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="files[]"; filename="web.md"\r\n'
                    "Content-Type: text/markdown\r\n\r\n"
                    "# Web\n\nA small book.\n"
                    f"\r\n--{boundary}--\r\n"
                ).encode()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/jobs",
                    data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    job_id = json.load(response)["id"]
                for _ in range(120):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/jobs/{job_id}", timeout=2
                    ) as response:
                        job = json.load(response)
                    if job["status"] in ("done", "failed"):
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("Bundled web conversion timed out")
                if job["status"] != "done":
                    raise RuntimeError(
                        f"Bundled web conversion failed: {job}\n"
                        f"Server log: {web_log.read_text(errors='replace')[-1500:]}"
                    )
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/jobs/{job_id}/files/0/download/epub", timeout=10
                ) as response:
                    if not response.read(4).startswith(b"PK"):
                        raise RuntimeError("Bundled web download is not an EPUB")
                print(f"Native smoke passed: {epub.name}, EPUBCheck, web conversion")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    smoke(args.app.resolve())
