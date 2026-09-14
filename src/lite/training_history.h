#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>
#include <mutex>

namespace ygo {
void TrainingHistoryInit(std::function<intptr_t()> factory, std::function<void(const std::vector<unsigned char>&)> show);
bool TrainingRestoring();
std::recursive_mutex& TrainingInputMutex();
void TrainingRestorePresentation(); // Called under the renderer mutex after reloading cards.
bool TrainingHistoryScriptError();
void TrainingHistoryResponse(const unsigned char* bytes, size_t len, bool integer);
void TrainingSubmitResponse(intptr_t& engine, unsigned char* bytes, size_t len);
void TrainingWait(intptr_t& engine, const unsigned char* prompt, size_t len);
int TrainingProcess(intptr_t engine, std::vector<unsigned char>& buffer);
void TrainingStartDuel(intptr_t engine, int options);
int TrainingQueryFieldInfo(intptr_t engine, unsigned char* buffer);
int TrainingQueryFieldCard(intptr_t engine, uint8_t player, uint8_t location, uint32_t flags, unsigned char* buffer, int cache);
int TrainingQueryCard(intptr_t engine, uint8_t player, uint8_t location, uint8_t sequence, uint32_t flags, unsigned char* buffer, int cache);
}
