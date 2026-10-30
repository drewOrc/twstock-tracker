from ..config import settings
from .base import HttpClient
from .mis import MISClient
from .tpex import TPEXClient
from .twse import TWSEClient

_http = HttpClient(timeout=settings.http_timeout, delay=settings.request_delay_seconds)
_mis_http = HttpClient(timeout=settings.http_timeout, delay=0.5, retries=2)

twse = TWSEClient(_http)
tpex = TPEXClient(_http)
mis = MISClient(_mis_http)

CLIENTS = {"TWSE": twse, "TPEX": tpex}

__all__ = ["twse", "tpex", "mis", "CLIENTS", "HttpClient"]
