"""LLM-based extraction: cleaned transcript -> structured markdown article.

Uses an OpenAI-compatible chat completions endpoint (configurable via env).
If no API key is configured, falls back to a deterministic heuristic builder
so the pipeline still produces usable articles offline.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..config import settings
from .cleaner import extract_dtc_codes
from .prompts import SYSTEM_EXTRACTION, build_extraction_user_prompt

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {
    "electrical", "engine", "transmission", "brakes", "steering-suspension",
    "hvac", "fuel-system", "diagnostics", "methodology", "scan-tools",
    "labscope", "oem-info", "safety", "general",
}

VEHICLE_RE = re.compile(
    r"\b(?:(?:19|20)\d{2})\s+[A-Z][A-Za-z0-9\- ]*(?:Corolla|Camry|Civic|Accord|F-150|Silverado|"
    r"Ranger|Tacoma|Tundra|Mustang|Cruze|Malibu|Impala|Explorer|Escape|Focus|Fiesta|Altima|"
    r"Sentra|Rogue|Outback|Forester|Impreza|Legacy|Grand Cherokee|Cherokee|Wrangler|Ram\s*\d+|"
    r"Fusion|Edge|Equinox|Traverse|Terrain|Sierra|Colorado|Canyon|Sonata|Elantra|Santa Fe|"
    r"Optima|Sorento|Sportage|Telluride|Golf|Jetta|Passat|Beetle|Prius|RAV4|Highlander|4Runner|"
    r"Sequoia|Land Cruiser|CR-V|HR-V|Pilot|Odyssey|MDX|RDX|CX-5|CX-9|Mazda3|Mazda6|GLA|GLC|"
    r"C-Class|E-Class|3 Series|5 Series|X3|X5|A3|A4|A6|Q5|Q7|XC40|XC60|XC90|S60|S90|"
    r"Spark|Sonic|Bolt|Volt|Leaf|Model\s*[S3XY]|Cybertruck|Mach-E|Bronco|Ranger|Explorer)\b"
)

TOOL_KEYWORDS = [
    "DVOM", "multimeter", "labscope", "oscilloscope", "scan tool", "scanner",
    "bidirectional", "bi-directional", "test light", "power probe", "ammeter",
    "clamp meter", "megohmmeter", "insulation tester", "borescope", "pressure gauge",
    "vacuum gauge", "fuel pressure gauge", "compression tester", "leak detector",
    "smoke machine", "smoke tester", "DVOM", "back probe", "pinout", "wiring diagram",
    "thermal camera", "infrared thermometer", "pyrometer", "torque wrench",
]


@dataclass
class ArticleData:
    title: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    technique: Optional[str] = None
    when_to_use: str = ""
    method_steps: list[str] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    common_mistakes: list[str] = field(default_factory=list)
    dtc_codes: list[str] = field(default_factory=list)
    vehicle_refs: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    summary: str = ""
    source: str = "llm"  # 'llm' or 'heuristic'

    def to_markdown(self, *, source_channel: str = "", source_url: str = "",
                    video_title: str = "") -> str:
        """Render the structured article as a Markdown document."""
        lines: list[str] = []
        title = self.title or video_title or "Untitled Article"
        lines.append(f"# {title}")
        lines.append("")
        if self.summary:
            lines.append(f"> **Summary:** {self.summary}")
            lines.append("")
        if self.technique:
            lines.append(f"**Technique:** {self.technique}")
            lines.append("")
        if self.when_to_use:
            lines.append("## When to Use")
            lines.append("")
            lines.append(self.when_to_use)
            lines.append("")
        if self.method_steps:
            lines.append("## Method")
            lines.append("")
            for i, step in enumerate(self.method_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")
        if self.key_insights:
            lines.append("## Key Insights")
            lines.append("")
            for k in self.key_insights:
                lines.append(f"- {k}")
            lines.append("")
        if self.common_mistakes:
            lines.append("## Common Mistakes")
            lines.append("")
            for m in self.common_mistakes:
                lines.append(f"- {m}")
            lines.append("")
        if self.dtc_codes:
            lines.append("## DTC Codes")
            lines.append("")
            lines.append(", ".join(self.dtc_codes))
            lines.append("")
        if self.vehicle_refs:
            lines.append("## Vehicles Referenced")
            lines.append("")
            for v in self.vehicle_refs:
                lines.append(f"- {v}")
            lines.append("")
        if self.tools_used:
            lines.append("## Tools Used")
            lines.append("")
            for t in self.tools_used:
                lines.append(f"- {t}")
            lines.append("")
        if self.tags:
            lines.append("## Tags")
            lines.append("")
            lines.append(" ".join(f"`{t}`" for t in self.tags))
            lines.append("")
        if source_channel or source_url:
            lines.append("---")
            lines.append("")
            meta: list[str] = []
            if source_channel:
                meta.append(f"**Source channel:** {source_channel}")
            if source_url:
                url_str = f"https://youtube.com/watch?v={source_url}" if not source_url.startswith("http") else source_url
                meta.append(f"**Source video:** [{url_str}]({url_str})")
            lines.extend(meta)
            lines.append("")
        return "\n".join(lines)


class LLMExtractor:
    """Extract structured articles from cleaned transcripts via LLM."""

    def __init__(self, api_base: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        self.api_base = api_base or settings.llm_api_base
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs: dict = {"api_key": self.api_key or "not-set"}
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = OpenAI(**kwargs)
        return self._client

    def extract(self, cleaned_transcript: str, *, video_title: str = "",
                channel: str = "") -> ArticleData:
        """Run LLM extraction; fall back to heuristics on failure."""
        if not self.api_key:
            logger.info("No LLM_API_KEY configured; using heuristic extraction.")
            return self._heuristic_extract(cleaned_transcript, video_title=video_title)

        prompt = build_extraction_user_prompt(cleaned_transcript, video_title, channel)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_EXTRACTION},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                
            )
            content = resp.choices[0].message.content or ""
            # Strip markdown json fences if present
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            try:
                data = json.loads(content)
            except Exception as e:
                logger.error(f"Failed to parse JSON. Raw content:\n{content}")
                raise e
            article = self._parse_llm_json(data, video_title=video_title)
            article.source = "llm"
            return article
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM extraction failed (%s); using heuristics.", exc)
            return self._heuristic_extract(cleaned_transcript, video_title=video_title)

    # -- LLM JSON parsing ----------------------------------------------------

    def _parse_llm_json(self, data: dict, *, video_title: str = "") -> ArticleData:
        def _str(key: str) -> str:
            val = data.get(key)
            return str(val).strip() if val else ""

        def _list(key: str) -> list[str]:
            val = data.get(key) or []
            if isinstance(val, str):
                val = [v.strip() for v in re.split(r"[\n,;]", val) if v.strip()]
            elif isinstance(val, list):
                val = [str(v).strip() for v in val if str(v).strip()]
            else:
                val = []
            return val

        category = _str("category").lower()
        if category not in ALLOWED_CATEGORIES:
            category = "general"

        dtc = _list("dtc_codes")
        if not dtc:
            dtc = extract_dtc_codes(data.get("summary", "") + " " + " ".join(_list("method_steps")))

        return ArticleData(
            title=_str("title") or video_title or "Untitled Article",
            category=category,
            tags=_list("tags")[:6],
            technique=_str("technique") or None,
            when_to_use=_str("when_to_use"),
            method_steps=_list("method_steps"),
            key_insights=_list("key_insights"),
            common_mistakes=_list("common_mistakes"),
            dtc_codes=dtc,
            vehicle_refs=_list("vehicle_refs"),
            tools_used=_list("tools_used"),
            summary=_str("summary"),
        )

    # -- Heuristic fallback --------------------------------------------------

    def _heuristic_extract(self, text: str, *, video_title: str = "") -> ArticleData:
        """Deterministic extraction for offline/no-LLM operation."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 20]
        dtc = extract_dtc_codes(text)
        vehicles: list[str] = []
        seen_v: set[str] = set()
        for m in VEHICLE_RE.finditer(text):
            v = m.group(0).strip()
            if v not in seen_v:
                seen_v.add(v)
                vehicles.append(v)
        tools: list[str] = []
        seen_t: set[str] = set()
        for kw in TOOL_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE):
                key = kw.lower()
                if key not in seen_t:
                    seen_t.add(key)
                    tools.append(kw)

        category = "general"
        lower = text.lower()
        if any(w in lower for w in ("voltage", "short", "open circuit", "ohm", "ground", "current")):
            category = "electrical"
        elif any(w in lower for w in ("misfire", "cylinder", "compression", "ignition", "fuel injector")):
            category = "engine"
        elif "transmission" in lower or "shift" in lower:
            category = "transmission"
        elif any(w in lower for w in ("scan tool", "scanner", "dtc", "diagnostic")):
            category = "diagnostics"
        elif any(w in lower for w in ("labscope", "oscilloscope", "waveform")):
            category = "labscope"

        method_steps = sentences[:6] if sentences else []
        key_insights = sentences[6:12] if len(sentences) > 6 else []
        summary = " ".join(sentences[:2]) if sentences else text[:300]

        return ArticleData(
            title=video_title or "Untitled Article",
            category=category,
            tags=[category] if category != "general" else [],
            technique=None,
            when_to_use="",
            method_steps=method_steps,
            key_insights=key_insights,
            common_mistakes=[],
            dtc_codes=dtc,
            vehicle_refs=vehicles,
            tools_used=tools,
            summary=summary,
            source="heuristic",
        )


def slugify(title: str) -> str:
    """Create a URL-safe slug from a title."""
    slug = unicodedata.normalize("NFKD", title)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:100] or f"article-{int(datetime.now().timestamp())}"
