import io
import sys
import zipfile
from pathlib import Path


KNOWLEDGE_BASE_SKILL_ROOT = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "knowledge"
    / "skills"
    / "knowledge-base"
)
if str(KNOWLEDGE_BASE_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_BASE_SKILL_ROOT))


from core import ingestion  # noqa: E402
from qwenpaw.extensions.integrations import knowledge_base  # noqa: E402


def _minimal_pptx(slides: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        for index, paragraphs in enumerate(slides, start=1):
            body = "".join(
                f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>" for text in paragraphs
            )
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>""",
            )
    return buffer.getvalue()


def test_pptx_upload_extracts_slide_text_not_zip_payload():
    payload = _minimal_pptx(
        [
            ["AI CODING Research Plan", "Architecture and delivery flow"],
            ["Evaluation", "IDE assistant and agent workflow"],
        ]
    )

    extracted = ingestion.extract("AI CODING研发方案调研.pptx", payload)

    assert extracted.source_format == "markdown"
    assert "AI CODING Research Plan" in extracted.content
    assert "IDE assistant and agent workflow" in extracted.content
    assert "PK" not in extracted.content
    assert "[Content_Types].xml" not in extracted.content


def test_pptx_upload_is_classified_as_pptx_source_type():
    source_type = knowledge_base._detect_source_type(
        "AI CODING研发方案调研.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    assert source_type == "pptx"
