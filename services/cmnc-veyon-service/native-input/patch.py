from pathlib import Path
import sys
source = Path(sys.argv[1])
plugin = source / "plugins/webapi"
p = plugin / "WebApiController.h"
s = p.read_text().replace("Response getFramebuffer( const Request& request );", "Response getFramebuffer( const Request& request );\n\tResponse sendInput(const Request& request);\n\tResponse refreshFramebuffer(const Request& request);")
p.write_text(s)
p = plugin / "WebApiController.cpp"
s = p.read_text()
old = """\trunInWorkerThread([&] {
\t\tVeyonCore::featureManager().controlFeature(Feature::Uid{feature}, operation, arguments, {connection->controlInterface()});
\t});"""
new = """\t// Feature plugins (including Demo's keepalive QTimer) belong to the core
\t// thread, while WebAPI connections live in a separate worker thread.
\tconst auto control = connection->controlInterface();
\tconst auto applyFeature = [feature, operation, arguments, control] {
\t\tVeyonCore::featureManager().controlFeature(Feature::Uid{feature}, operation, arguments, {control});
\t};
\tauto* core = VeyonCore::instance();
\tif (QThread::currentThread() == core->thread())
\t\tapplyFeature();
\telse
\t\tQMetaObject::invokeMethod(core, applyFeature, Qt::BlockingQueuedConnection);"""
if s.count(old) != 1:
    raise RuntimeError("Unexpected Veyon source; feature thread-affinity fix was not applied")
s = s.replace(old, new)
p.write_text('#include <cmath>\n#include <QThread>\n#include "VncConnection.h"\n#include "VncEvents.h"\n#include <rfb/rfbclient.h>\n' + s + Path(__file__).with_name("input-controller.cpp").read_text() + Path(__file__).with_name("refresh-controller.cpp").read_text())
p = plugin / "WebApiHttpServer.cpp"
s = p.read_text().replace('success &= addRoute<Method::Get>( QStringLiteral("framebuffer"), &WebApiController::getFramebuffer );', 'success &= addRoute<Method::Get>( QStringLiteral("framebuffer"), &WebApiController::getFramebuffer );\n\tsuccess &= addRoute<Method::Post>( QStringLiteral("input"), &WebApiController::sendInput );\n\tsuccess &= addRoute<Method::Post>( QStringLiteral("framebuffer/refresh"), &WebApiController::refreshFramebuffer );')
p.write_text(s)
p = source / "CMakeLists.txt"
p.write_text(p.read_text() + '\nif(WITH_CORE_ONLY)\nadd_subdirectory(plugins/webapi)\nendif()\n')

p = plugin / "CMakeLists.txt"
p.write_text(p.read_text() + "\ntarget_link_libraries(webapi PRIVATE vncclient)\n")
