#pragma once

#include <cstddef>

namespace ygo {
bool InitializeLitePaths();
void LiteTrace(const char* format, ...);
void LiteTracePacket(const unsigned char* message, size_t length);
}
