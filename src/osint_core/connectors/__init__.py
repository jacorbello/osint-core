"""Connector package — registers all feed connectors with the ConnectorRegistry."""

from osint_core.connectors.abusech import FeodoTrackerConnector, MalwareBazaarConnector
from osint_core.connectors.acled import AcledConnector
from osint_core.connectors.base import BaseConnector, RawItem, SourceConfig
from osint_core.connectors.cisa_kev import CisaKevConnector
from osint_core.connectors.gdelt import GdeltConnector
from osint_core.connectors.nvd import NvdConnector
from osint_core.connectors.nws import NwsConnector
from osint_core.connectors.osv import OsvConnector
from osint_core.connectors.otx import OtxConnector
from osint_core.connectors.registry import ConnectorRegistry
from osint_core.connectors.reliefweb import ReliefWebConnector
from osint_core.connectors.rss import RssConnector
from osint_core.connectors.shodan import ShodanConnector
from osint_core.connectors.telegram import TelegramConnector
from osint_core.connectors.threatfox import ThreatFoxConnector
from osint_core.connectors.urlhaus import UrlhausConnector

__all__ = [
    "BaseConnector",
    "CisaKevConnector",
    "ConnectorRegistry",
    "AcledConnector",
    "FeodoTrackerConnector",
    "GdeltConnector",
    "MalwareBazaarConnector",
    "NvdConnector",
    "NwsConnector",
    "OsvConnector",
    "OtxConnector",
    "RawItem",
    "ReliefWebConnector",
    "RssConnector",
    "ShodanConnector",
    "SourceConfig",
    "TelegramConnector",
    "ThreatFoxConnector",
    "UrlhausConnector",
    "registry",
]

registry = ConnectorRegistry()
registry.register("cisa_kev", CisaKevConnector)
registry.register("gdelt_api", GdeltConnector)
registry.register("nvd_json_feed", NvdConnector)
registry.register("osv_api", OsvConnector)
registry.register("urlhaus_api", UrlhausConnector)
registry.register("threatfox_api", ThreatFoxConnector)
registry.register("reliefweb_api", ReliefWebConnector)
registry.register("shodan_api", ShodanConnector)
registry.register("rss", RssConnector)
registry.register("otx_api", OtxConnector)
registry.register("nws_alerts", NwsConnector)
registry.register("abusech_malwarebazaar", MalwareBazaarConnector)
registry.register("abusech_feodotracker", FeodoTrackerConnector)
registry.register("acled_api", AcledConnector)
registry.register("telegram", TelegramConnector)
