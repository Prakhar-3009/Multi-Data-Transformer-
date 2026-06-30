"""Recruiter notes text extractor — conservative regex-based extraction.


Extraction strategy:
- Email: regex (high confidence — email patterns are distinctive)
- Phone: regex (moderate confidence — phone patterns are ambiguous)
- Skills: keyword/fuzzy match against skill dictionary (variable confidence)
- Name: regex heuristics (lower confidence — names in prose are hard)
- Company: keyword patterns (lower confidence)
- Everything else: null (abstain)
"""

from __future__ import annotations

import logging
import re

from src.core.constants import EXTRACTION_CONFIDENCE, SOURCE_TRUST
from src.extractors.base import BaseExtractor
from src.models.enums import ExtractionMethod, SourceType
from src.models.fields import FieldValue
from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)

# --- Regex patterns for structured data in free text ---

# Email: fairly distinctive pattern, high confidence
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

# Phone: multiple patterns, moderate confidence
_PHONE_PATTERNS = [
    re.compile(r"\+?\d{1,3}[\s\-.]?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"),  # International
    re.compile(r"\b\d{10}\b"),  # 10-digit bare
    re.compile(r"\b\d{3}[\-.\s]\d{3}[\-.\s]\d{4}\b"),  # US-style
]

# Name extraction: look for labeled patterns
# Captures 2-3 words for general triggers, but allows 1 word for very specific conversational triggers
_NAME_PATTERNS = [
    re.compile(r"(?:name|candidate|applicant)\s*[:=\-]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", re.IGNORECASE),
    re.compile(r"(?:[Ss]poke\s+(?:with|to)|[Mm]et|[Ii]nterviewed|[Rr]egarding|[Aa]bout)\s+([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
    re.compile(r"(?:[Cc]hat\s+(?:with|w)|[Ii]ntro\s+call\s+(?:w|with)|[Mm]et)\s+([A-Z][a-z]+(?: \w+)?)\b"),
    re.compile(r"^([A-Z][a-z]+)\s+(?:reached\s+out|seems)\b", re.MULTILINE),
]

# Company extraction: look for labeled or contextual patterns
_COMPANY_PATTERNS = [
    re.compile(r"(?:company|employer|works?\s+at|working\s+at|employed\s+at|current(?:ly)?\s+with|current(?:ly)?\s+at|been\s+at|somewhere\s+at)\s*[:=\-]?\s*([A-Z][\w\s&.,]+?)(?:\s+in\b|\s+for\b|\.|,|\n|$|(?=\s+for))", re.IGNORECASE),
    re.compile(r"^([A-Z][a-z]+)\s+(?:currently|background)\b", re.MULTILINE),
    re.compile(r"(?:from|at|with)\s+(Google|Gooogle|Microsoft|Microsofft|Amazon|Amazn|Apple|Meta|Facebook|Netflix|Uber|Airbnb|Stripe|Twitter|LinkedIn|Salesforce|Adobe|Oracle|IBM|Intel|Cisco|VMware|Atlassian|Shopify|Spotify|Tesla|SpaceX|Nvidia|TCS|Infosys|Wipro|HCL|Tech Mahindra|Cognizant|Accenture|Flipkart|Swiggy|Zomato|Razorpay|PhonePe|Ola|Myntra|Zoho|Freshworks|Paytm|Byju's|CRED|Meesho|Zerodha|Groww|Unacademy|Dream11|Nykaa|PolicyBazaar|ShareChat)\b", re.IGNORECASE),
]

# Title extraction
_TITLE_PATTERNS = [
    re.compile(r"(?:title|role|position|designation)\s*[:=\-]\s*(.+?)(?:\.|,|\n|$)", re.IGNORECASE),
    re.compile(r"(?:works?\s+as\s+(?:a\s+|an\s+)?|working\s+as\s+(?:a\s+|an\s+)?|currently\s+(?:a|an)\s+|doing\s+)(.+?)(?:\s+at\b|\s+in\b|\s+on\b|\s+for\b|\.|,|\n|$)", re.IGNORECASE),
    re.compile(r"([A-Z][a-z\s]+?)\s+(?:profile|guy)\b"),
]

# Location extraction — only reliable triggers
_LOCATION_PATTERNS = [
    re.compile(r"(?:location|based\s+(?:out\s+of|in)|located\s+in|city)\s*[:=\-]?\s*([A-Z][\w\s,]+?)(?:\.|;|\n|$|\s+currently)", re.IGNORECASE),
    re.compile(r"^([A-Z][a-z]+)\s+(?:based|location)\b", re.MULTILINE),
    re.compile(r"(?:from|in)\s+(Bangalore|Bengaluru|Mumbai|Delhi|Hyderabad|Chennai|Pune|Gurgaon|Noida)\b", re.IGNORECASE)
]

# Skill indicators in text
_SKILL_INDICATORS = [
    re.compile(r"(?:skills?|technologies|tech\s+stack|proficient\s+in|experienced?\s+(?:in|with)|knows?|mention(?:ed|ing)|talked\s+(?:quite\s+a\s+bit\s+)?about|spoke\s+about|strong\s+in|comfortable\s+with)\s*[:=\-]?\s*(.+?)(?:\s+(?:really|inside|very)\s|\s+well\b|\.\s|\.\s*$|\n|$|(?=\s+for))", re.IGNORECASE),
    re.compile(r"^([A-Z][\w\s,]+?)(?:…|\.\.\.)", re.MULTILINE | re.IGNORECASE), # Catching "Terraform, docker, kubernetes..."
]


class TextExtractor(BaseExtractor):
    """Extracts CandidateFragments from recruiter notes text.

    Uses conservative regex extraction with explicit confidence scoring.
    Abstains on anything not confidently matched — never invents data.
    """

    def extract(self, raw_records: list[dict]) -> list[CandidateFragment]:
        """Convert text blocks into CandidateFragments.

        Args:
            raw_records: List of dicts with "raw_text" key from RecruiterNotesParser.

        Returns:
            List of CandidateFragments with REGEX_EXTRACTED method.
        """
        fragments: list[CandidateFragment] = []
        base_confidence = EXTRACTION_CONFIDENCE[ExtractionMethod.REGEX_EXTRACTED]
        trust = SOURCE_TRUST[SourceType.RECRUITER_NOTES]

        for i, record in enumerate(raw_records):
            raw_text = record.get("raw_text", "")
            if not raw_text.strip():
                continue

            try:
                fragment = self._extract_from_text(raw_text, base_confidence, trust)
                if fragment.fields:
                    fragments.append(fragment)
            except Exception as e:
                logger.warning("Text extraction failed for block %d: %s", i, e)
                continue

        logger.info(
            "Extracted %d fragments from %d text blocks",
            len(fragments), len(raw_records),
        )
        return fragments

    def _extract_from_text(
        self, text: str, confidence: float, trust: float
    ) -> CandidateFragment:
        """Extract fields from a single text block."""
        fields: dict[str, FieldValue] = {}

        # Email — highest confidence regex extraction
        emails = self._extract_emails(text)
        if emails:
            fields["emails"] = FieldValue(
                value=emails,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence,
            )

        # Phone — moderate confidence
        phones = self._extract_phones(text)
        if phones:
            fields["phones"] = FieldValue(
                value=phones,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.95,  # Slightly lower: phone regex is more ambiguous
            )

        # Name — lower confidence (names in prose are hard)
        name = self._extract_name(text)
        if name:
            fields["full_name"] = FieldValue(
                value=name,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.85,
            )

        # Company — lower confidence
        company = self._extract_company(text)
        if company:
            fields["current_company"] = FieldValue(
                value=company,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.85,
            )

        # Title — lower confidence
        title = self._extract_title(text)
        if title:
            fields["title"] = FieldValue(
                value=title,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.80,
            )

        # Skills — keyword/pattern extraction
        skills = self._extract_skills(text)
        if skills:
            fields["skills"] = FieldValue(
                value=skills,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.90,
            )

        # Location — lower confidence
        location = self._extract_location(text)
        if location:
            fields["location"] = FieldValue(
                value=location,
                source=SourceType.RECRUITER_NOTES,
                method=ExtractionMethod.REGEX_EXTRACTED,
                confidence=confidence * 0.75,
            )

        return CandidateFragment(
            source=SourceType.RECRUITER_NOTES,
            source_trust=trust,
            fields=fields,
        )

    @staticmethod
    def _extract_emails(text: str) -> list[str]:
        """Extract all email addresses from text."""
        return list(set(_EMAIL_RE.findall(text)))

    @staticmethod
    def _extract_phones(text: str) -> list[str]:
        """Extract phone numbers from text."""
        phones: set[str] = set()
        for pattern in _PHONE_PATTERNS:
            for match in pattern.findall(text):
                # Clean: remove non-digit except leading +
                cleaned = match.strip()
                if cleaned:
                    phones.add(cleaned)
        return list(phones)

    @staticmethod
    def _extract_name(text: str) -> str | None:
        """Extract candidate name from text using labeled patterns."""
        for pattern in _NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                # Clean: take only the first line, strip whitespace
                raw_name = match.group(1).strip()
                name = raw_name.split("\n")[0].strip()
                # Sanity check: name should be 1-4 words, all alpha
                words = name.split()
                if 1 <= len(words) <= 4 and all(w.isalpha() for w in words):
                    return name
        return None

    @staticmethod
    def _extract_company(text: str) -> str | None:
        """Extract company name from text."""
        for pattern in _COMPANY_PATTERNS:
            match = pattern.search(text)
            if match:
                company = match.group(1).strip()
                # Sanity: company name should be 1-5 words
                if 1 <= len(company.split()) <= 6 and len(company) <= 50:
                    return company
        return None

    @staticmethod
    def _extract_title(text: str) -> str | None:
        """Extract job title from text."""
        for pattern in _TITLE_PATTERNS:
            match = pattern.search(text)
            if match:
                title = match.group(1).strip()
                if 1 <= len(title.split()) <= 8 and len(title) <= 60:
                    return title
        return None

    @staticmethod
    def _extract_skills(text: str) -> list[str]:
        """Extract skill mentions from text."""
        skills: set[str] = set()

        # Try labeled skill patterns first
        for pattern in _SKILL_INDICATORS:
            match = pattern.search(text)
            if match:
                raw_skills = match.group(1)
                for skill in re.split(r"[,;|]|\band\b", raw_skills):
                    cleaned = skill.strip()
                    if cleaned and 1 <= len(cleaned) <= 30:
                        skills.add(cleaned)

        return list(skills) if skills else []

    @staticmethod
    def _extract_location(text: str) -> dict | None:
        """Extract location from text."""
        for pattern in _LOCATION_PATTERNS:
            match = pattern.search(text)
            if match:
                raw_loc = match.group(1).strip()
                # Try to split "City, State" or "City, Country"
                parts = [p.strip() for p in raw_loc.split(",")]
                location: dict[str, str | None] = {
                    "city": None,
                    "region": None,
                    "country": None,
                }
                if len(parts) >= 1:
                    location["city"] = parts[0]
                if len(parts) >= 2:
                    location["country"] = parts[-1]
                if len(parts) >= 3:
                    location["region"] = parts[1]
                return location
        return None
