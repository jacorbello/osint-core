"""Connector package — registers all feed connectors with the ConnectorRegistry."""

from osint_core.connectors.base import BaseConnector, RawItem, SourceConfig
from osint_core.connectors.cisa_kev import CisaKevConnector
from osint_core.connectors.nvd import NvdConnector
from osint_core.connectors.osv import OsvConnector
from osint_core.connectors.registry import ConnectorRegistry
from osint_core.connectors.rss import RssConnector
from osint_core.connectors.threatfox import ThreatFoxConnector
from osint_core.connectors.urlhaus import UrlhausConnector

__all__ = [
    "BaseConnector",
    "CisaKevConnector",
    "ConnectorRegistry",
    "NvdConnector",
    "OsvConnector",
    "RawItem",
    "RssConnector",
    "SourceConfig",
    "ThreatFoxConnector",
    "UrlhausConnector",
    "registry",
]

registry = ConnectorRegistry()
registry.register("cisa_kev", CisaKevConnector)
registry.register("nvd", NvdConnector)
registry.register("osv", OsvConnector)
registry.register("urlhaus", UrlhausConnector)
registry.register("threatfox", ThreatFoxConnector)
registry.register("rss", RssConnector)
