from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


DEFAULT_ROUTER_ID = 1


class BaseEvent(BaseModel):
    # Уникальный идентификатор события.
    # Нужен для логов, трассировки и защиты от повторной обработки.
    event_id: UUID = Field(default_factory=uuid4)

    # Тип события. Обычно совпадает с routing key в RabbitMQ.
    event_type: str

    # Время создания события в UTC.
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WanPolicyChangedEvent(BaseEvent):
    # Событие: для устройства изменилось желаемое состояние доступа в WAN.
    event_type: str = "classroom.device.wan_policy_changed"

    # Пока в системе один MikroTik, всегда будет 1.
    # Оставлено на случай будущего расширения на несколько роутеров.
    router_id: int = DEFAULT_ROUTER_ID

    # Аудитория, в которой находится устройство.
    classroom_id: int

    # Устройство, для которого изменили WAN-политику.
    device_id: int

    # Версия политики. Увеличивается при каждом изменении WAN-состояния.
    # Нужна, чтобы sync-service понимал, какую версию он применяет.
    policy_generation: int

    # Желаемое состояние:
    # true - интернет разрешён;
    # false - интернет запрещён.
    wan_allowed: bool

    # Пользователь, который изменил состояние.
    # Может быть None, если изменение сделал системный процесс.
    changed_by_user_id: int | None = None


class DhcpLeaseObserved(BaseModel):
    # MAC-адрес устройства из DHCP lease.
    mac: str

    # Активный IP-адрес, если MikroTik его видит.
    active_ip: str | None = None

    # Hostname устройства, если клиент его передал.
    hostname: str | None = None

    # DHCP lease динамический или статический.
    dynamic: bool | None = None

    # Активен ли lease в момент опроса.
    active: bool = True

    # Сырой объект из MikroTik REST API.
    # Нужен для диагностики и полей, которые пока не нормализованы.
    raw: dict[str, Any] = Field(default_factory=dict)


class DhcpLeasesObservedEvent(BaseEvent):
    # Событие: poller получил снимок DHCP leases с MikroTik.
    event_type: str = "mikrotik.dhcp_leases.observed"

    # Пока в системе один MikroTik, всегда будет 1.
    router_id: int = DEFAULT_ROUTER_ID

    # Список DHCP leases, полученных во время одного опроса.
    leases: list[DhcpLeaseObserved]


class PolicySyncCompletedEvent(BaseEvent):
    # Событие: policy-sync-service успешно применил WAN-политику на MikroTik.
    event_type: str = "policy.sync.completed"

    # Пока в системе один MikroTik, всегда будет 1.
    router_id: int = DEFAULT_ROUTER_ID

    # Версия политики, которая была применена.
    policy_generation: int

    # Сколько записей добавлено в address-list.
    added: int = 0

    # Сколько управляемых записей удалено из address-list.
    removed: int = 0

    # Сколько активных соединений было сброшено после блокировки.
    connections_killed: int = 0

    # Некритичные ошибки или предупреждения, если они были.
    errors: list[str] = Field(default_factory=list)


class PolicySyncFailedEvent(BaseEvent):
    # Событие: policy-sync-service не смог применить WAN-политику.
    event_type: str = "policy.sync.failed"

    # Пока в системе один MikroTik, всегда будет 1.
    router_id: int = DEFAULT_ROUTER_ID

    # Версия политики, которую пытались применить.
    policy_generation: int

    # Текст ошибки: timeout, ошибка авторизации, недоступен MikroTik и т.п.
    error: str