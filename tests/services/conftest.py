"""Shared fixtures for services tests."""

import sys
from unittest.mock import MagicMock

# Provide a mock weasyprint module so that tests can run without native
# pango/cairo libraries installed.
if "weasyprint" not in sys.modules:
    mock_weasyprint = MagicMock()
    mock_html_instance = MagicMock()
    mock_html_instance.write_pdf.return_value = b"%PDF-1.4 mock"
    mock_weasyprint.HTML.return_value = mock_html_instance
    sys.modules["weasyprint"] = mock_weasyprint
