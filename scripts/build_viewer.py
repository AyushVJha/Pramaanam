"""Build the side-by-side checking pages for the human-verified sample.

For each sampled judgment we show up to 3 pages (first, middle, last): the page image on the left,
the text our pipeline extracted on the right. The checker edits the right-hand box until it matches
the image, and ticks flags (table on page / footnotes on page / page unreadable). Edits are kept in
the browser and saved with the "Download" button as bench/data/ground_truth/human/<path>.json.

Open bench/data/ground_truth/viewer/index.html in a browser. No server, no internet needed.
Usage: uv run python scripts/build_viewer.py
"""

import html
import json

import pymupdf

from pramaan.config import DATA_DIR
from pramaan.data.pdf_text import extract_raw_pages

GT = DATA_DIR.parent / "bench" / "data" / "ground_truth"
VIEW = GT / "viewer"
DPI = 110


def pick_pages(n: int) -> list[int]:
    """First, middle and last page (1-indexed), without repeats."""
    return sorted({1, (n + 1) // 2, n})


PAGE_CSS = """
body{font:15px system-ui,sans-serif;margin:0;background:#f4f4f2;color:#222}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ccc;
  padding:8px 16px;z-index:2}
.page{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 16px;
  border-bottom:2px solid #bbb}
.page img{width:100%;border:1px solid #999;background:#fff}
textarea{width:100%;height:80vh;font:13px/1.4 ui-monospace,monospace}
label{margin-right:14px}
button{padding:6px 12px}
@media(max-width:800px){.page{grid-template-columns:1fr}}
"""

PAGE_JS = """
const KEY = "pramaan-gt-" + document.body.dataset.path;
const state = JSON.parse(localStorage.getItem(KEY) || "{}");
document.querySelectorAll("[data-p]").forEach(el => {
  const id = el.dataset.p + ":" + el.dataset.f;
  if (id in state) {
    if (el.type === "checkbox") el.checked = state[id]; else el.value = state[id];
  }
  el.addEventListener("input", () => {
    state[id] = el.type === "checkbox" ? el.checked : el.value;
    localStorage.setItem(KEY, JSON.stringify(state));
  });
});
function download() {
  const pages = [...document.querySelectorAll(".page")].map(div => {
    const p = div.dataset.page, get = f => div.querySelector(`[data-f="${f}"]`);
    return {page: +p, corrected_text: get("text").value, has_table: get("table").checked,
            has_footnotes: get("foot").checked, unreadable: get("bad").checked,
            checked: get("done").checked};
  });
  const blob = new Blob([JSON.stringify({path: document.body.dataset.path, pages}, null, 1)],
                        {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = document.body.dataset.path + ".json"; a.click();
}
"""


def case_page(path: str, pages: list[tuple[int, str, str]]) -> str:
    blocks = []
    for page_no, img, text in pages:
        p = f"{page_no}"
        blocks.append(f"""<section class="page" data-page="{p}">
<div><img src="{img}" alt="page {p}"></div>
<div>
<p><b>Page {p}.</b> Edit the box until it matches the image exactly.
<label><input type="checkbox" data-p="{p}" data-f="table"> table on page</label>
<label><input type="checkbox" data-p="{p}" data-f="foot"> footnotes on page</label>
<label><input type="checkbox" data-p="{p}" data-f="bad"> unreadable</label>
<label><input type="checkbox" data-p="{p}" data-f="done"> <b>I checked this page</b></label></p>
<textarea data-p="{p}" data-f="text">{html.escape(text)}</textarea>
</div></section>""")
    return (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(path)}</title>"
        f"<style>{PAGE_CSS}</style><body data-path=\"{html.escape(path)}\">"
        f"<header><a href=\"index.html\">&larr; all judgments</a> &nbsp; <b>{html.escape(path)}</b>"
        f" &nbsp; <button onclick=\"download()\">Download my corrections</button></header>"
        + "".join(blocks) + f"<script>{PAGE_JS}</script></body>"
    )


def main() -> None:
    cases = json.loads((GT / "sample.json").read_text())["cases"]
    (VIEW / "img").mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        path = c["path"]
        pdf = GT / "pdfs" / f"{path}_EN.pdf"
        if not pdf.exists():
            continue
        raw = {p.page_no: p.text for p in extract_raw_pages(pdf.read_bytes())}
        doc = pymupdf.open(pdf)
        pages = []
        for n in pick_pages(len(doc)):
            img = f"img/{path}_p{n}.png"
            doc[n - 1].get_pixmap(dpi=DPI).save(VIEW / img)
            pages.append((n, img, raw.get(n, "")))
        doc.close()
        (VIEW / f"{path}.html").write_text(case_page(path, pages), encoding="utf-8")
        rows.append((path, c["decade"], c["band"], [n for n, _, _ in pages]))
    items = "".join(
        f'<li><a href="{html.escape(p)}.html">{html.escape(p)}</a> &mdash; {d}s, {b}, '
        f"pages {', '.join(map(str, pg))}</li>"
        for p, d, b, pg in rows
    )
    (VIEW / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>Pramaan text check</title>"
        f"<style>{PAGE_CSS}li{{margin:6px 0}}</style><body><header><b>Judgments to check "
        f"({len(rows)})</b></header><ol style='padding:16px 40px'>{items}</ol></body>",
        encoding="utf-8",
    )
    print(f"built {len(rows)} judgment pages -> {VIEW / 'index.html'}")


if __name__ == "__main__":
    main()
