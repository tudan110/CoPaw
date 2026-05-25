import io
import sys
import zipfile
from pathlib import Path

import pytest


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


def test_legacy_doc_piece_table_extracts_word_text_not_binary_payload():
    text = "知识库DOC解析\n避免二进制乱码"
    text_bytes = text.encode("utf-16le")
    text_offset = 0x200
    word_document = bytearray(text_offset + len(text_bytes))
    word_document[text_offset:text_offset + len(text_bytes)] = text_bytes

    cp_end = len(text)
    pcdt = (
        (0).to_bytes(4, "little")
        + cp_end.to_bytes(4, "little")
        + b"\x00\x00"
        + text_offset.to_bytes(4, "little")
        + b"\x00\x00"
    )
    clx = b"\x02" + len(pcdt).to_bytes(4, "little") + pcdt

    extracted = ingestion._extract_doc_text_from_streams(bytes(word_document), clx)

    assert "知识库DOC解析" in extracted
    assert "避免二进制乱码" in extracted
    assert "PK" not in extracted


def test_legacy_doc_ole_reader_accepts_unpadded_final_sector():
    reader = ingestion._OleCompoundFile.__new__(ingestion._OleCompoundFile)
    reader.data = b"\x00" * 512 + b"partial"
    reader.sector_size = 512

    sector = reader._sector(0)

    assert sector.startswith(b"partial")
    assert len(sector) == 512


def test_real_wps_doc_upload_extracts_readable_chinese_text_when_available():
    sample = Path("/home/admin/users/vince/resource/test_files/testV1.0.doc")
    if not sample.exists():
        pytest.skip("local WPS .doc regression sample is not available")

    extracted = ingestion.extract(sample.name, sample.read_bytes())

    assert extracted.source_format == "markdown"
    assert "一体化运维平台运维知识平台需求" in extracted.content
    assert "运维知识平台改为调用智观AI平台页面" in extracted.content
    assert "\xd0\xcf\x11\xe0" not in extracted.content


def test_doc_upload_is_classified_as_doc_source_type():
    source_type = knowledge_base._detect_source_type(
        "历史故障复盘.doc",
        "application/msword",
    )

    assert source_type == "doc"
