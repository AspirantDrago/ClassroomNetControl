
// CMNC extension to Veyon WebAPI 4.11.4. GPL-2.0-or-later, like Veyon.
namespace {
class CmncFullFramebufferUpdateEvent final : public VncEvent
{
public:
    void fire(rfbClient* client) override
    {
        SendFramebufferUpdateRequest(client, 0, 0, client->width, client->height, FALSE);
    }
};
}

WebApiController::Response WebApiController::refreshFramebuffer(const Request& request)
{
    Response checked{};
    if ((checked = checkConnection(request)).error != Error::NoError) return checked;
    const auto connection = lookupConnection(request);
    if (!connection) return Error::InvalidConnection;
    auto control = connection->controlInterface();
    auto vnc = control->vncConnection();
    if (!vnc || !vnc->isConnected()) return Error::InvalidConnection;
    // The VNC socket is owned by the connection thread. Queue the request there.
    vnc->enqueueEvent(new CmncFullFramebufferUpdateEvent);
    return {};
}
