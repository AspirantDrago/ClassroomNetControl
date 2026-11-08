from pathlib import Path
import sys

p = Path(sys.argv[1]) / "src/httpserver/qhttpserver.cpp"
s = p.read_text()
old = """    response.then(this, [this, &request, socket](QHttpServerResponse &&response) {
        sendResponse(std::move(response), request, socket);
    });"""
new = """    // QHttpServerRequest is owned by the socket in Qt 6.4. A delayed
    // response must not access either object after a client disconnects.
    const QPointer<QTcpSocket> guardedSocket(socket);
    response.then(this, [this, &request, guardedSocket](QHttpServerResponse &&response) {
        if (!guardedSocket || guardedSocket->state() != QAbstractSocket::ConnectedState)
            return;
        sendResponse(std::move(response), request, guardedSocket.data());
    });"""
if s.count(old) != 1:
    raise RuntimeError("Unexpected Qt HTTP Server source; disconnect fix was not applied")
include = "#include <QtNetwork/qtcpsocket.h>"
if s.count(include) != 1:
    raise RuntimeError("Qt TCP socket include not found")
s = s.replace(include, "#include <QtCore/qpointer.h>\n" + include).replace(old, new)
p.write_text(s)
