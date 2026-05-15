from __future__ import annotations

import base64
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path


def _deflate_raw_base64(text: str) -> str:
    data = text.encode("utf-8")
    compressor = zlib.compressobj(level=9, wbits=-15)  # raw DEFLATE
    comp = compressor.compress(data) + compressor.flush()
    return base64.b64encode(comp).decode("ascii")


def convert_drawio_file(path: Path) -> Path:
    raw = path.read_text(encoding="utf-8")
    root = ET.fromstring(raw)

    diagram = root.find("diagram")
    if diagram is None:
        raise ValueError(f"No <diagram> found in {path}")

    # If it already looks compressed (text payload and no mxGraphModel child), keep as-is.
    if (diagram.text or "").strip() and diagram.find("mxGraphModel") is None:
        return path

    mx = diagram.find("mxGraphModel")
    if mx is None:
        raise ValueError(f"No <mxGraphModel> under <diagram> in {path}")

    mx_xml = ET.tostring(mx, encoding="utf-8", method="xml").decode("utf-8")
    encoded = _deflate_raw_base64(mx_xml)

    new_root = ET.Element("mxfile", root.attrib)
    new_diag = ET.SubElement(
        new_root,
        "diagram",
        {
            "id": diagram.attrib.get("id", ""),
            "name": diagram.attrib.get("name", ""),
            "compressed": "true",
        },
    )
    new_diag.text = encoded

    out = ET.tostring(new_root, encoding="utf-8", method="xml").decode("utf-8")
    out_path = path.with_suffix(".compressed.drawio")
    out_path.write_text(out, encoding="utf-8")
    return out_path


def main() -> None:
    diagrams_dir = Path(__file__).resolve().parents[1] / "diagrams"
    targets = [diagrams_dir / "rag_flow.drawio", diagrams_dir / "mcp_flow.drawio"]

    for p in targets:
        if not p.exists():
            raise SystemExit(f"Missing file: {p}")

    for p in targets:
        out = convert_drawio_file(p)
        print(f"OK: {p.name} -> {out.name}")


if __name__ == "__main__":
    main()
