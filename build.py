# Builds the self-contained receipt tool HTML with the logo embedded.
# Writes BOTH the named file and index.html (index.html is what Render serves).
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
logo = (HERE / ".tmp" / "logo_b64.txt").read_text().strip()
html = (HERE / "_template.html").read_text().replace("{{LOGO}}", logo)

(HERE / "BMT_Receipt_Tool.html").write_text(html)
(HERE / "index.html").write_text(html)
print("Built BMT_Receipt_Tool.html + index.html")
