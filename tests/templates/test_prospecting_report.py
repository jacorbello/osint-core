"""Tests for the prospecting report PDF template."""

import importlib.resources

from jinja2 import Environment, FileSystemLoader


def _template_dir() -> str:
    """Resolve the absolute path to the templates directory."""
    pkg = importlib.resources.files("osint_core") / "templates"
    return str(pkg)


def _render(context: dict) -> str:
    """Render the prospecting report template with the given context."""
    env = Environment(
        loader=FileSystemLoader(_template_dir()),
        autoescape=True,
    )
    template = env.get_template("prospecting_report.html")
    return template.render(**context)


def _sample_lead(*, lead_type: str = "incident", title: str = "Test Lead") -> dict:
    return {
        "lead_type": lead_type,
        "title": title,
        "summary": "A test lead summary.",
        "constitutional_basis": ["1A-free-speech", "14A-due-process"],
        "jurisdiction": "CA",
        "institution": "UC Berkeley",
        "severity": "high",
        "confidence": 0.85,
        "sections": {
            "executive_summary": "Executive summary content.",
            "constitutional_analysis": "Constitutional analysis content.",
            "parties": "Parties involved.",
            "evidence": "Evidence summary.",
            "jurisdiction_analysis": "Jurisdiction analysis.",
            "time_sensitivity": "Time-sensitive matter.",
            "recommendation": "Recommend further investigation.",
            "affected_population": "Students and faculty.",
            "policy_text": "The policy states...",
            "precedents": "Tinker v. Des Moines established...",
        },
        "source_citations": [
            "https://example.com/article-1",
            "https://example.com/article-2",
        ],
        "legal_citations": [
            {
                "case_name": "Tinker v. Des Moines",
                "citation": "393 U.S. 503",
                "courtlistener_url": "https://courtlistener.com/opinion/12345/",
                "verified": True,
            },
        ],
    }


def _sample_context(**overrides: object) -> dict:
    ctx = {
        "report_date": "March 27, 2026 — 3:00 PM CST",
        "report_period": "March 20–27, 2026",
        "summary": {
            "total_leads": 3,
            "incidents": 2,
            "policies": 1,
            "high_priority_count": 1,
            "by_jurisdiction": {"CA": 2, "TX": 1},
        },
        "leads": [
            _sample_lead(lead_type="incident", title="Professor Fired"),
            _sample_lead(lead_type="policy", title="New Speech Code"),
        ],
        "all_source_citations": [
            "https://example.com/article-1",
            "https://example.com/article-2",
        ],
        "all_legal_citations": [
            {
                "case_name": "Tinker v. Des Moines",
                "citation": "393 U.S. 503",
                "courtlistener_url": "https://courtlistener.com/opinion/12345/",
                "verified": True,
            },
            {
                "case_name": "Unknown Case",
                "citation": "999 U.S. 1",
                "courtlistener_url": "",
                "verified": False,
            },
        ],
    }
    ctx.update(overrides)
    return ctx


class TestProspectingReportTemplate:
    def test_renders_without_error(self):
        html = _render(_sample_context())
        assert "The Center For American Liberty" in html
        assert "libertycenter.org" in html

    def test_cover_page_content(self):
        html = _render(_sample_context())
        assert "March 27, 2026" in html
        assert "March 20–27, 2026" in html
        assert "Constitutional Rights" in html

    def test_executive_summary_stats(self):
        html = _render(_sample_context())
        assert ">3<" in html  # total_leads
        assert ">2<" in html  # incidents
        assert ">1<" in html  # policies

    def test_jurisdiction_table(self):
        html = _render(_sample_context())
        assert "CA" in html
        assert "TX" in html

    def test_incident_lead_sections(self):
        html = _render(_sample_context())
        assert "Professor Fired" in html
        assert "Executive Summary" in html
        assert "Constitutional Analysis" in html
        assert "Parties Involved" in html
        assert "Evidence Summary" in html

    def test_policy_lead_sections(self):
        html = _render(_sample_context())
        assert "New Speech Code" in html
        assert "Affected Population" in html
        assert "Policy Text" in html
        assert "Legal Precedents" in html

    def test_constitutional_tags(self):
        html = _render(_sample_context())
        assert "1A-free-speech" in html
        assert "14A-due-process" in html

    def test_severity_badges(self):
        html = _render(_sample_context())
        assert "severity-high" in html

    def test_citations_appendix(self):
        html = _render(_sample_context())
        assert "Citations Appendix" in html
        assert "Tinker v. Des Moines" in html
        assert "Verified" in html

    def test_zero_leads(self):
        ctx = _sample_context(
            leads=[],
            all_source_citations=None,
            all_legal_citations=None,
        )
        ctx["summary"]["total_leads"] = 0
        html = _render(ctx)
        assert "No reportable leads" in html
        # Should not contain any lead sections
        assert "lead-section" not in html

    def test_single_lead(self):
        ctx = _sample_context(leads=[_sample_lead()])
        ctx["summary"]["total_leads"] = 1
        html = _render(ctx)
        assert "Test Lead" in html

    def test_lead_without_sections(self):
        lead = _sample_lead()
        lead["sections"] = {}
        ctx = _sample_context(leads=[lead])
        html = _render(ctx)
        assert "Test Lead" in html

    def test_lead_without_citations(self):
        lead = _sample_lead()
        lead["source_citations"] = []
        lead["legal_citations"] = []
        ctx = _sample_context(leads=[lead])
        html = _render(ctx)
        assert "Test Lead" in html
