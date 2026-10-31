"""
Pydantic Request & Response Schemas
"""

from typing import Optional
from pydantic import BaseModel


class PlayRequest(BaseModel):
    scenario: str
    speed_multiplier: float = 1.0
    loop: bool = False
    device_id: str = "blackbox-01"
    lead_in_normal: bool = True


class StepRequest(BaseModel):
    scenario: str
    device_id: str = "blackbox-01"
    lead_in_normal: bool = True


class FallbackSimulateRequest(BaseModel):
    internet_enabled: Optional[bool] = None
    gsm_enabled: Optional[bool] = None
    lorawan_enabled: Optional[bool] = None
    emergency_recipient: Optional[str] = None
    device_msisdn: Optional[str] = None


class ManualSmsRequest(BaseModel):
    recipient: Optional[str] = None
    body: Optional[str] = None
    device_id: Optional[str] = "blackbox-01"


class InboundSmsRequest(BaseModel):
    sender: Optional[str] = None
    body: Optional[str] = None
    from_: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[str] = None


class ManualLorawanRequest(BaseModel):
    msg_type: Optional[str] = "CRASH"
    device_id: Optional[str] = "blackbox-01"


class InboundLorawanRequest(BaseModel):
    data: Optional[str] = None
    hex: Optional[str] = None
    devEUI: Optional[str] = None
    rssi: Optional[float] = None
    snr: Optional[float] = None
    fPort: Optional[int] = 1
