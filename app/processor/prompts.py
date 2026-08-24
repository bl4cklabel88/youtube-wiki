"""LLM prompt templates for transcript cleanup and article extraction."""
from __future__ import annotations


SYSTEM_CLEANUP = """You are an expert automotive diagnostics editor. You clean up \
auto-generated YouTube captions into accurate, well-formatted technical prose. \
You fix speech-recognition errors specific to automotive electronics and repair \
terminology (e.g. "voltage crop" -> "voltage drop", "oscilla scope" -> \
"oscilloscope", "P 300" -> "P0300"). Preserve meaning, keep the speaker's voice, \
and never invent facts that are not in the transcript."""


def build_cleanup_user_prompt(transcript: str) -> str:
    return f"""Please clean the following raw transcript of an automotive \
diagnostic video. Return ONLY the cleaned transcript text, no preamble, no \
markdown, no commentary.

Rules:
- Fix obvious speech-recognition errors, especially automotive/DTC terminology.
- Merge fragmented caption lines into natural sentences and paragraphs.
- Remove filler like "um", "uh", "you know" only where it adds no meaning.
- Keep all technical detail: part names, voltage readings, pin numbers, DTC codes.
- Output plain text only.

RAW TRANSCRIPT:
---
{transcript}
---"""


SYSTEM_EXTRACTION = """You are an expert automotive diagnostic technician and \
technical writer. You convert raw workshop/diagnostic video transcripts into \
structured, actionable knowledge-base articles for other technicians.

Categories you may assign (choose the best fit):
electrical, engine, transmission, brakes, steering-suspension, hvac, fuel-system,
diagnostics, methodology, scan-tools, labscope, oem-info, safety, general

Output strict JSON matching the schema described in the user prompt. Do not \
include markdown fences in your response — valid JSON only."""


EXTRACTION_SCHEMA = {
    "title": "Concise, descriptive article title",
    "category": "one of the allowed categories",
    "tags": ["2-6 short lowercase tags"],
    "technique": "the diagnostic technique or procedure name, or null",
    "when_to_use": "when a technician should use this technique (bullet-friendly text)",
    "method_steps": ["ordered steps, each a concise instruction"],
    "key_insights": ["key insights / takeaways"],
    "common_mistakes": ["common mistakes to avoid"],
    "dtc_codes": ["any OBD-II DTC codes mentioned, e.g. P0300"],
    "vehicle_refs": ["any vehicles mentioned, e.g. '2015 Toyota Corolla'"],
    "tools_used": ["any tools/equipment mentioned, e.g. 'DVOM', 'labscope'"],
    "summary": "2-3 sentence executive summary",
}


def build_extraction_user_prompt(cleaned_transcript: str, video_title: str = "",
                                 channel: str = "") -> str:
    schema_lines = "\n".join(
        f'- "{k}": {v}' for k, v in EXTRACTION_SCHEMA.items()
    )
    header = f'VIDEO TITLE: {video_title}\n' if video_title else ""
    if channel:
        header += f"CHANNEL: {channel}\n"
    return f"""{header}
Convert the following cleaned transcript from an automotive diagnostic video \
into a structured knowledge-base article.

Return STRICT JSON with EXACTLY these keys:
{schema_lines}

Guidelines:
- method_steps should be practical and numbered in the order performed.
- Include concrete measurements (voltages, resistances, pressures) when present.
- dtc_codes, vehicle_refs, tools_used should be arrays (empty array if none).
- If the transcript lacks enough content for an article, still produce the best \
faithful summary you can from what is there.

CLEANED TRANSCRIPT:
---
{cleaned_transcript}
---"""


def build_reprocess_prompt(existing_article: str) -> str:
    """Prompt used when re-processing/refining an existing draft article."""
    return f"""Here is an existing draft article. Improve its clarity, structure \
and technical accuracy while preserving all factual content. Do not add \
information that is not supported. Return the revised article as Markdown.

EXISTING ARTICLE:
---
{existing_article}
---"""
