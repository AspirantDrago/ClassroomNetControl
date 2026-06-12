from enum import StrEnum


class WanPolicyState(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class PolicySyncStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"


class DeviceOnlineState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
