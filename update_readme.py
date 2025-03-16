from pathlib import Path


docs_index = Path("docs/index.md")

readme = Path("README.md")

readme_text = docs_index.read_text().split("<!-- BEGIN CONTENT -->\n\n")[1]

readme.write_text(readme_text)
