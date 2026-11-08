
// CMNC extension to Veyon WebAPI 4.11.4. GPL-2.0-or-later, like Veyon.
WebApiController::Response WebApiController::sendInput(const Request& request)
{
    Response checked{};
    if ((checked = checkConnection(request)).error != Error::NoError) return checked;
    const auto connection = lookupConnection(request);
    if (!connection) return Error::InvalidConnection;
    auto control = connection->controlInterface();
    if (!control->hasValidFramebuffer() || !control->vncConnection()) return Error::FramebufferNotAvailable;
    const auto events = request.data.value(QStringLiteral("events")).toList();
    if (events.size() > 64) return Error::InvalidData;
    // Validate the whole batch before applying any event.
    for (const auto& item : events) {
        const auto event = item.toMap();
        const auto kind = event.value(QStringLiteral("type")).toString();
        if (kind == QStringLiteral("pointer")) {
            bool xOk{}, yOk{}, maskOk{};
            const double x = event.value(QStringLiteral("x")).toDouble(&xOk);
            const double y = event.value(QStringLiteral("y")).toDouble(&yOk);
            const int mask = event.value(QStringLiteral("buttons")).toInt(&maskOk);
            if (!xOk || !yOk || !maskOk || !std::isfinite(x) || !std::isfinite(y) || x < 0 || x > 1 || y < 0 || y > 1 || mask < 0 || mask > 127) return Error::InvalidData;
        } else if (kind == QStringLiteral("key")) {
            bool ok{};
            const auto key = event.value(QStringLiteral("key")).toULongLong(&ok);
            if (!ok || key == 0 || key > 0x1fffffff || event.value(QStringLiteral("pressed")).userType() != QMetaType::Bool) return Error::InvalidData;
        } else return Error::InvalidData;
    }
    const auto size = control->framebuffer().size();
    if (size.width() < 1 || size.height() < 1) return Error::FramebufferNotAvailable;
    for (const auto& item : events) {
        const auto event = item.toMap();
        if (event.value(QStringLiteral("type")) == QStringLiteral("pointer")) {
            control->vncConnection()->mouseEvent(qRound(event.value(QStringLiteral("x")).toDouble() * (size.width()-1)), qRound(event.value(QStringLiteral("y")).toDouble() * (size.height()-1)), event.value(QStringLiteral("buttons")).toInt());
        } else {
            control->vncConnection()->keyEvent(event.value(QStringLiteral("key")).toUInt(), event.value(QStringLiteral("pressed")).toBool());
        }
    }
    return {};
}
