#include "lite_support.h"
#include "config.h"
#include "network.h"
#include <cstdarg>
#include <cstdio>
#include <mutex>
#include <string>
#include <windows.h>

namespace ygo {
bool InitializeLitePaths() {
    wchar_t path[32768]{};
    const auto length = GetModuleFileNameW(nullptr, path, 32768);
    if (!length || length >= 32768)
        return false;
    std::wstring root(path);
    const auto slash = root.find_last_of(L"\\/");
    if (slash == std::wstring::npos)
        return false;
    root.resize(slash);
    if (!SetCurrentDirectoryW(root.c_str()))
        return false;
    for (const auto* sub : {L"_profile", L"_profile\\AppData", L"_profile\\AppData\\Roaming",
                            L"_profile\\AppData\\Local", L"_profile\\Temp", L"_profile\\logs"}) {
        if (!CreateDirectoryW((root + L"\\" + sub).c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS)
            return false;
    }
    SetEnvironmentVariableW(L"USERPROFILE", (root + L"\\_profile").c_str());
    SetEnvironmentVariableW(L"APPDATA", (root + L"\\_profile\\AppData\\Roaming").c_str());
    SetEnvironmentVariableW(L"LOCALAPPDATA", (root + L"\\_profile\\AppData\\Local").c_str());
    SetEnvironmentVariableW(L"TEMP", (root + L"\\_profile\\Temp").c_str());
    SetEnvironmentVariableW(L"TMP", (root + L"\\_profile\\Temp").c_str());
    FILE* stream{};
    freopen_s(&stream, "_profile/logs/stdout.log", "a", stdout);
    freopen_s(&stream, "_profile/logs/stderr.log", "a", stderr);
    return true;
}

void LiteTrace(const char* format, ...) {
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    FILE* output = std::fopen("_profile/logs/training.log", "a");
    if (!output)
        return;
    va_list args;
    va_start(args, format);
    std::vfprintf(output, format, args);
    va_end(args);
    std::fputc('\n', output);
    std::fclose(output);
}

void LiteTracePacket(const unsigned char* message, size_t length) {
    if (!length)
        return;
    switch (message[0]) {
    case MSG_START: case MSG_WIN: case MSG_DRAW: case MSG_SUMMONING:
    case MSG_SUMMONED: case MSG_CHAINING: case MSG_CHAIN_SOLVED:
    case MSG_NEW_TURN: case MSG_NEW_PHASE: {
        static const char digits[] = "0123456789abcdef";
        std::string bytes;
        for (size_t i = 1; i < length && i < 81; ++i) {
            bytes += digits[message[i] >> 4];
            bytes += digits[message[i] & 15];
        }
        LiteTrace("event message=%u bytes=%s", static_cast<unsigned>(message[0]), bytes.c_str());
        break;
    }
    default: break;
    }
}
}
