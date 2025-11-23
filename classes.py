import logging
from dataclasses import dataclass

logger = logging.getLogger("main")




@dataclass
class UserData:
    is_availale: bool = None
    date: str = None
    time: str = None


@dataclass
class MetaData:
    call_id: str = None
    created_at: str  = None
    ended_at: str = None
    from_number : str = None
    to_number: str = None
    call_type: str = None
    duration_seconds: float = None
    disconnection_reason: str = None

