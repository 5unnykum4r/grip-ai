"""Tests for rule-based behavioral pattern extraction."""

from __future__ import annotations

from grip.memory.pattern_extractor import PatternExtractor


class TestPreferenceExtraction:
    def test_extracts_i_prefer(self):
        ex = PatternExtractor()
        results = ex.extract("I prefer dark mode for all editors", "", [])
        assert any(p.category == "user_preference" for p in results)
        assert any("dark mode" in p.content for p in results)

    def test_extracts_my_favorite(self):
        ex = PatternExtractor()
        results = ex.extract("my favorite language is Python", "", [])
        assert any(p.category == "user_preference" for p in results)

    def test_extracts_dont_use(self):
        ex = PatternExtractor()
        results = ex.extract("don't use tabs, always spaces", "", [])
        assert any(p.category == "user_preference" for p in results)

    def test_extracts_please_always(self):
        ex = PatternExtractor()
        results = ex.extract("please always include type hints", "", [])
        assert any(p.category == "user_preference" for p in results)


class TestDecisionExtraction:
    def test_extracts_lets_use(self):
        ex = PatternExtractor()
        results = ex.extract("let's use PostgreSQL for the database", "", [])
        assert any(p.category == "project_decision" for p in results)
        assert any("PostgreSQL" in p.content for p in results)

    def test_extracts_we_decided(self):
        ex = PatternExtractor()
        results = ex.extract("we decided to go with FastAPI instead of Flask", "", [])
        assert any(p.category == "project_decision" for p in results)

    def test_extracts_going_with(self):
        ex = PatternExtractor()
        results = ex.extract("going with Redis for caching layer", "", [])
        assert any(p.category == "project_decision" for p in results)


class TestErrorPatternExtraction:
    def test_extracts_error_from_response(self):
        ex = PatternExtractor()
        response = "Error: ModuleNotFoundError — yfinance is not installed"
        results = ex.extract("", response, [])
        assert any(p.category == "error_pattern" for p in results)
        assert any("ModuleNotFoundError" in p.content for p in results)

    def test_skips_short_errors(self):
        ex = PatternExtractor()
        results = ex.extract("", "Error: X", [])
        assert not any(p.category == "error_pattern" for p in results)


class TestToolFrequencyTracking:
    def test_tracks_frequent_tool(self):
        ex = PatternExtractor()
        for _ in range(4):
            ex.extract("", "", ["web_search"])
        # 5th time should trigger system_behavior extraction
        results = ex.extract("", "", ["web_search"])
        assert any(p.category == "system_behavior" and "web_search" in p.content for p in results)

    def test_does_not_record_infrequent_tool(self):
        ex = PatternExtractor()
        results = ex.extract("", "", ["rare_tool"])
        assert not any(p.category == "system_behavior" for p in results)

    def test_records_tool_only_once(self):
        ex = PatternExtractor()
        for _ in range(10):
            ex.extract("", "", ["exec"])
        results = ex.extract("", "", ["exec"])
        # Should not re-record because it was already recorded
        assert not any(p.category == "system_behavior" for p in results)


class TestExtractionLimits:
    def test_max_3_extractions_per_call(self):
        ex = PatternExtractor()
        msg = (
            "I prefer dark mode. let's use PostgreSQL. "
            "I like Python. we decided on Docker. going with Kubernetes"
        )
        results = ex.extract(msg, "Error: something went wrong with the build", [])
        assert len(results) <= 3

    def test_empty_inputs_return_empty(self):
        ex = PatternExtractor()
        results = ex.extract("", "", [])
        assert results == []

    def test_no_match_returns_empty(self):
        ex = PatternExtractor()
        results = ex.extract("hello world", "hi there", [])
        assert results == []

    def test_deduplicates_within_call(self):
        ex = PatternExtractor()
        results = ex.extract("I prefer dark mode. I prefer dark mode again", "", [])
        preference_contents = [p.content for p in results if p.category == "user_preference"]
        assert len(preference_contents) <= 1


class TestExtractedPatternFields:
    def test_source_is_user_message_for_preferences(self):
        ex = PatternExtractor()
        results = ex.extract("I prefer concise answers", "", [])
        assert all(p.source == "user_message" for p in results if p.category == "user_preference")

    def test_source_is_agent_response_for_errors(self):
        ex = PatternExtractor()
        results = ex.extract("", "Error: connection timed out after 30 seconds", [])
        assert all(p.source == "agent_response" for p in results if p.category == "error_pattern")

    def test_content_is_truncated(self):
        ex = PatternExtractor()
        long_pref = "I prefer " + "x" * 200
        results = ex.extract(long_pref, "", [])
        for p in results:
            assert len(p.content) <= 120
