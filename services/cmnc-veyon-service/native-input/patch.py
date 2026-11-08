from pathlib import Path
import sys
source = Path(sys.argv[1])
plugin = source / "plugins/webapi"
p = plugin / "WebApiController.h"
s = p.read_text().replace("Response getFramebuffer( const Request& request );", "Response getFramebuffer( const Request& request );\n\tResponse sendInput(const Request& request);")
p.write_text(s)
p = plugin / "WebApiController.cpp"
p.write_text('#include <cmath>\n#include "VncConnection.h"\n' + p.read_text() + Path(__file__).with_name("input-controller.cpp").read_text())
p = plugin / "WebApiHttpServer.cpp"
s = p.read_text().replace('success &= addRoute<Method::Get>( QStringLiteral("framebuffer"), &WebApiController::getFramebuffer );', 'success &= addRoute<Method::Get>( QStringLiteral("framebuffer"), &WebApiController::getFramebuffer );\n\tsuccess &= addRoute<Method::Post>( QStringLiteral("input"), &WebApiController::sendInput );')
p.write_text(s)
p = source / "CMakeLists.txt"
p.write_text(p.read_text() + '\nif(WITH_CORE_ONLY)\nadd_subdirectory(plugins/webapi)\nendif()\n')
