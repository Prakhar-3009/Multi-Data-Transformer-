"""Unit tests for normalizers — the pure-function logic layer.

These tests validate the core normalization contract:
- Valid input → canonical form + high confidence
- Invalid input → None + 0.0 confidence
- Edge cases handled honestly (year-only dates, fuzzy skill threshold)
- Never invents values, never crashes on garbage
"""

import pytest

from src.normalizers.phone import normalize_phone
from src.normalizers.date import normalize_date
from src.normalizers.email import normalize_email, normalize_email_list
from src.normalizers.skill import SkillNormalizer
from src.normalizers.country import normalize_country


# ===================================================================
# Phone normalization
# ===================================================================

class TestPhoneNormalization:
    """Tests for phone → E.164 normalization."""

    def test_indian_10_digit(self):
        """10-digit Indian number with default region IN → +91..."""
        result, conf = normalize_phone("9876543210")
        assert result == "+919876543210"
        assert conf == 1.0

    def test_with_country_code(self):
        """Number with explicit country code → E.164."""
        result, conf = normalize_phone("+91 9876543210")
        assert result == "+919876543210"
        assert conf == 1.0

    def test_us_number(self):
        """US number with region override."""
        # 555 numbers are fictitious — libphonenumber correctly rejects them.
        # Use a valid US area code instead.
        result, conf = normalize_phone("(212) 555-1234", "US")
        assert result is not None
        assert result.startswith("+1")
        assert conf == 1.0

    def test_with_spaces_and_dashes(self):
        """Number with punctuation → cleaned E.164."""
        result, conf = normalize_phone("+91 98765 43210")
        assert result == "+919876543210"
        assert conf == 1.0

    def test_invalid_phone(self):
        """Obviously invalid string → None."""
        result, conf = normalize_phone("invalid")
        assert result is None
        assert conf == 0.0

    def test_empty_string(self):
        """Empty string → None."""
        result, conf = normalize_phone("")
        assert result is None
        assert conf == 0.0

    def test_none_input(self):
        """None input → None."""
        result, conf = normalize_phone(None)
        assert result is None
        assert conf == 0.0

    def test_too_short(self):
        """Too-short number → None (not padded, not guessed)."""
        result, conf = normalize_phone("123")
        assert result is None
        assert conf == 0.0

    def test_letters_in_number(self):
        """Clearly non-phone text → None."""
        result, conf = normalize_phone("call me maybe")
        assert result is None
        assert conf == 0.0


# ===================================================================
# Date normalization
# ===================================================================

class TestDateNormalization:
    """Tests for date → YYYY-MM normalization."""

    def test_month_year_full(self):
        """'January 2024' → '2024-01'."""
        result, conf = normalize_date("January 2024")
        assert result == "2024-01"
        assert conf == 1.0

    def test_month_year_abbreviated(self):
        """'Jan 2024' → '2024-01'."""
        result, conf = normalize_date("Jan 2024")
        assert result == "2024-01"
        assert conf == 1.0

    def test_slash_format(self):
        """'01/2024' → '2024-01'."""
        result, conf = normalize_date("01/2024")
        assert result == "2024-01"
        assert conf == 1.0

    def test_iso_format(self):
        """'2024-01' → '2024-01'."""
        result, conf = normalize_date("2024-01")
        assert result == "2024-01"
        assert conf == 1.0

    def test_year_only_no_fake_month(self):
        """Year-only '2024' → '2024' (NOT '2024-01').
        
        This is the classic confident-wrong bug: defaulting to January
        when the data never gave us a month. We return year-only with
        lower confidence.
        """
        result, conf = normalize_date("2024")
        assert result == "2024"
        assert conf == 0.8  # Lower confidence: month is genuinely unknown

    def test_present_sentinel(self):
        """'Present' → None (it's a state, not a date)."""
        result, conf = normalize_date("Present")
        assert result is None
        assert conf == 0.0

    def test_current_sentinel(self):
        """'Current' → None."""
        result, conf = normalize_date("Current")
        assert result is None
        assert conf == 0.0

    def test_empty(self):
        """Empty string → None."""
        result, conf = normalize_date("")
        assert result is None
        assert conf == 0.0

    def test_garbage(self):
        """Garbage string → None."""
        result, conf = normalize_date("not a date at all xyz")
        assert result is None
        assert conf == 0.0


# ===================================================================
# Email normalization
# ===================================================================

class TestEmailNormalization:
    """Tests for email normalization."""

    def test_valid_email(self):
        """Standard email → lowercased."""
        result, conf = normalize_email("John@Example.COM")
        assert result == "john@example.com"
        assert conf == 1.0

    def test_trimming(self):
        """Whitespace trimmed."""
        result, conf = normalize_email("  user@domain.org  ")
        assert result == "user@domain.org"
        assert conf == 1.0

    def test_invalid_no_domain(self):
        """'john@' → None."""
        result, conf = normalize_email("john@")
        assert result is None
        assert conf == 0.0

    def test_invalid_no_at(self):
        """No @ symbol → None."""
        result, conf = normalize_email("johndomain.com")
        assert result is None
        assert conf == 0.0

    def test_invalid_no_tld(self):
        """No TLD → None."""
        result, conf = normalize_email("john@domain")
        assert result is None
        assert conf == 0.0

    def test_empty(self):
        """Empty → None."""
        result, conf = normalize_email("")
        assert result is None
        assert conf == 0.0

    def test_list_dedup(self):
        """Email list deduplication (case-insensitive) and sorting."""
        result = normalize_email_list([
            "John@Example.com",
            "john@example.com",
            "alice@test.org",
            "invalid@",
            "john@example.com",
        ])
        assert result == ["alice@test.org", "john@example.com"]


# ===================================================================
# Skill normalization
# ===================================================================

class TestSkillNormalization:
    """Tests for skill canonicalization."""

    def setup_method(self):
        """Create a shared normalizer instance."""
        self.normalizer = SkillNormalizer()

    def test_exact_alias_ml(self):
        """'ML' → 'Machine Learning' via alias."""
        result, conf = self.normalizer.normalize("ML")
        assert result == "Machine Learning"
        assert conf == 1.0

    def test_exact_alias_hyphenated(self):
        """'machine-learning' → 'Machine Learning'."""
        result, conf = self.normalizer.normalize("machine-learning")
        assert result == "Machine Learning"
        assert conf == 1.0

    def test_exact_alias_js(self):
        """'js' → 'JavaScript'."""
        result, conf = self.normalizer.normalize("js")
        assert result == "JavaScript"
        assert conf == 1.0

    def test_exact_alias_case_insensitive(self):
        """'PYTHON' → 'Python' (case-insensitive alias)."""
        result, conf = self.normalizer.normalize("PYTHON")
        assert result == "Python"
        assert conf == 1.0

    def test_java_not_javascript(self):
        """'Java' must NOT map to 'JavaScript'.
        
        This is the key safety test. At WRatio, 'Java' vs 'JavaScript'
        scores ~88-91, which is below our threshold of 95. The normalizer
        must either resolve 'Java' via exact alias or abstain.
        """
        result, conf = self.normalizer.normalize("Java")
        # "java" is in aliases → should map to "Java" exactly
        assert result == "Java"
        assert conf == 1.0

    def test_unknown_skill_below_threshold(self):
        """Unknown skill → passes through as-is with lower confidence."""
        result, conf = self.normalizer.normalize("xyzzy_nonexistent_skill")
        assert result == "xyzzy_nonexistent_skill"
        assert conf == 0.5

    def test_empty(self):
        """Empty → None."""
        result, conf = self.normalizer.normalize("")
        assert result is None
        assert conf == 0.0

    def test_fuzzy_match_typo(self):
        """Typo 'Pythonn' — may fuzzy-match to 'Python' or pass through.

        WRatio('Pythonn', 'Python') is ~92-96 depending on the version.
        If above threshold (95) → maps to 'Python' with high confidence.
        If below threshold → passes through as-is with 0.5 confidence.
        Both outcomes are acceptable (safe).
        """
        result, conf = self.normalizer.normalize("Pythonn")
        assert result is not None  # Never dropped
        if result == "Python":
            assert conf >= 0.95
        else:
            assert result == "Pythonn"
            assert conf == 0.5


# ===================================================================
# Country normalization
# ===================================================================

class TestCountryNormalization:
    """Tests for country → ISO 3166-1 alpha-2."""

    def test_alpha2(self):
        """Already alpha-2 → pass through."""
        result, conf = normalize_country("US")
        assert result == "US"
        assert conf == 1.0

    def test_alpha3(self):
        """Alpha-3 'USA' → 'US'."""
        result, conf = normalize_country("USA")
        assert result == "US"
        assert conf == 1.0

    def test_full_name(self):
        """Full name 'India' → 'IN'."""
        result, conf = normalize_country("India")
        assert result == "IN"
        assert conf == 0.95

    def test_common_alias(self):
        """Common alias 'UK' → 'GB'."""
        result, conf = normalize_country("UK")
        assert result == "GB"
        assert conf == 0.95

    def test_unknown(self):
        """Unknown country → None."""
        result, conf = normalize_country("Freedonia")
        assert result is None
        assert conf == 0.0

    def test_empty(self):
        """Empty → None."""
        result, conf = normalize_country("")
        assert result is None
        assert conf == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
