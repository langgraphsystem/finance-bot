"""Document orchestrator state definition."""

from typing import TypedDict


class DocumentState(TypedDict, total=False):
    """State for the document LangGraph orchestrator.

    Covers multi-step document workflows: extraction, processing,
    generation, and quality review with optional revision loop.
    """

    intent: str
    message_text: str
    user_id: str
    family_id: str
    language: str

    # Input files passed by the caller
    input_files: list[dict]  # [{bytes, filename, mime_type}]
    template_file: dict | None

    # Populated by extractor node
    extracted_text: str
    extracted_tables: list[dict]
    extracted_metadata: dict

    # Populated by processor node
    processed_content: str

    # Populated by generator node
    output_bytes: bytes | None
    output_filename: str | None
    output_format: str

    # Populated by reviewer node
    quality_ok: bool
    revision_feedback: str
    revision_count: int

    # Final output
    response_text: str
