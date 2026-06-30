from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, timezone
import uuid


class Channel(str, Enum):
    web = "web"
    mobile = "mobile"
    email = "email"
    whatsapp = "whatsapp"


class MessageRequest(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=5000)
    channel: Channel = Channel.web
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = Field(default=0, ge=0, le=10)


class MessageResponse(BaseModel):
    message_id: str
    status: str
    published_at: datetime | None = None
    duplicate: bool = False
