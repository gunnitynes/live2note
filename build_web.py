#!/usr/bin/env python3
"""Build web/index.html: page.html + converter core + tables, one self-contained file."""
import json
from pathlib import Path
import devices as D

H = Path(__file__).resolve().parent
tables = {"kinds": D.KINDS, "instruments": sorted(D.INSTRUMENTS), "effects": sorted(D.EFFECTS),
          "hints": D.UNSUPPORTED_HINTS, "enums": D.ENUMS,
          "verified": {f"{k}.{p}": sorted(v) for (k, p), v in D.VERIFIED.items()},
          "schema": json.loads((H / "note_schema.json").read_text())}
(H / "web_tables.json").write_text(json.dumps(tables, separators=(",", ":")))
page = (H / "web/page.html").read_text()
page = page.replace("<script>/*TABLES*/</script>",
                    "<script>Live2NoteTables=" + json.dumps(tables, separators=(",", ":")) + "</script>")
page = page.replace("<script>/*CORE*/</script>",
                    "<script>" + (H / "web/core.js").read_text() + "\nLive2Note.setTables(Live2NoteTables);</script>")
out = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"></head><body>\n' + page + "\n</body></html>\n")
(H / "web/index.html").write_text(out)
(H / "docs").mkdir(exist_ok=True)
(H / "docs/index.html").write_text(out)          # what GitHub Pages serves
(H / "docs/.nojekyll").write_text("")
print("web/index.html", len(out), "bytes")
