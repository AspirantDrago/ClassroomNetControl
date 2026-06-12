# Событие публикует cmnc-classroom-service, когда для устройства
# изменили желаемое состояние доступа в WAN.
# Например: преподаватель нажал "Отключить интернет" или "Включить интернет".
# Основной получатель: cmnc-policy-sync-service.
CLASSROOM_DEVICE_WAN_POLICY_CHANGED = "classroom.device.wan_policy_changed"

# Событие публикует cmnc-classroom-service, когда изменилась конфигурация
# аудитории: сетка, закрепление устройства, row/column, состав устройств.
# Получатели могут использовать событие для обновления кэша или повторной синхронизации.
CLASSROOM_LAYOUT_CHANGED = "classroom.layout.changed"


# Событие публикует cmnc-mikrotik-poller-service после опроса DHCP leases
# на MikroTik. Содержит список устройств, которые MikroTik видит через DHCP:
# MAC, active IP, hostname, dynamic/static, active/inactive.
# Основной получатель: cmnc-inventory-service.
MIKROTIK_DHCP_LEASES_OBSERVED = "mikrotik.dhcp_leases.observed"

# Событие публикует cmnc-mikrotik-poller-service после опроса ARP-таблицы
# на MikroTik. Нужно для устройств со статическими IP или случаев,
# когда DHCP leases недостаточно для фактической картины сети.
# Основной получатель: cmnc-inventory-service.
MIKROTIK_ARP_OBSERVED = "mikrotik.arp.observed"


# Событие публикует cmnc-policy-sync-service, когда желаемая WAN-политика
# успешно применена на MikroTik: address-list/firewall приведены
# к нужному состоянию.
# Основной получатель: cmnc-classroom-service.
POLICY_SYNC_COMPLETED = "policy.sync.completed"

# Событие публикует cmnc-policy-sync-service, когда не удалось применить
# желаемую WAN-политику на MikroTik.
# Например: MikroTik недоступен, ошибка авторизации, timeout, ошибка REST API.
# Основной получатель: cmnc-classroom-service.
POLICY_SYNC_FAILED = "policy.sync.failed"
