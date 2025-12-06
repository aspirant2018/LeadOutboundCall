import logging
from dataclasses import dataclass

logger = logging.getLogger("main")




@dataclass
class UserData:
    room_name: str  = None
    transcripts: str = None
    conversation_items: list = None
    from_number : str = None
    to_number: str = None
    call_type: str = None
    disconnection_reason: str = None



@dataclass
class MetaData:
    session_id: str = None
    room_name: str  = None
    transcripts: str = None
    from_number : str = None
    to_number: str = None
    call_type: str = None
    disconnection_reason: str = None
