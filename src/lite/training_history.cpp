// Reconstruct a second, independent Lua/core instance before changing the live duel.
// Record every core call made by the adapter, including queries that can evaluate Lua.
#include "training_support.h"
#include "game.h"
#include "../ocgcore/ocgapi.h"
#include "../ocgcore/duel.h"
#include "../ocgcore/field.h"
#include <windows.h>
#include <array>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <fstream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace ygo {
struct CoreCall {
    enum Kind { Process, Response, Integer, Start, FieldInfo, FieldCards, Card } kind;
    int result = 0;
    uint8_t player = 0, location = 0, sequence = 0;
    uint32_t flags = 0;
    int cache = 0;
    std::vector<unsigned char> bytes;
};
struct Checkpoint {
    uint64_t id;
    size_t calls;
    std::vector<unsigned char> prompt;
    std::string state;
    bool deckReversed = false, cantCheckGrave = false;
    uint32_t disabledField = 0;
};
static std::vector<CoreCall> calls;
static std::vector<CoreCall> resumeCalls;
static std::vector<Checkpoint> checkpoints;
static std::function<intptr_t()> makeDuel;
static std::function<void(const std::vector<unsigned char>&)> showDuel;
static std::recursive_mutex historyMutex;
static std::atomic<bool> restoring{false};
static bool replayError = false;
static uint64_t revision = 0, nextNode = 0, cursor = 0;
static bool atNode = false;
static bool resumeFromNode = false, rebuildingView = false;
static Checkpoint* presentationNode = nullptr;

static void atomicFile(const char* name, const std::string& value) {
    const auto destination = TrainingPath(name), temporary = destination + ".tmp";
    std::ofstream file(temporary, std::ios::binary | std::ios::trunc);
    file << value;
    file.close();
    if(!file) throw std::runtime_error("write_failed");
    for(int attempt = 0; attempt < 100; ++attempt) {
        if(MoveFileExA(temporary.c_str(), destination.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return;
        const auto error = GetLastError();
        if(error != ERROR_SHARING_VIOLATION && error != ERROR_ACCESS_DENIED) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    throw std::runtime_error("write_failed");
}
static void status() {
    std::ostringstream out;
    out << "{\"revision\":" << revision << ",\"cursor\":" << cursor << ",\"at_node\":" << (atNode ? "true" : "false") << '}';
    // A missed read-only status update must not terminate a playable duel. A stale
    // revision is rejected by the core before a subsequent restore can start.
    try { atomicFile("timeline-state.json", out.str()); } catch(const std::exception&) {}
}
static void operation(const std::string& token, const char* state, const char* error = "") {
    atomicFile("rewind-operation.json", "{\"token\":\"" + token + "\",\"status\":\"" + state + "\",\"error\":\"" + error + "\"}");
}
void TrainingHistoryInit(std::function<intptr_t()> factory, std::function<void(const std::vector<unsigned char>&)> show) {
    makeDuel = factory; showDuel = show;
}
bool TrainingRestoring() { return restoring; }
std::recursive_mutex& TrainingInputMutex() { return historyMutex; }
void TrainingRestorePresentation() {
    if(!presentationNode) return;
    mainGame->dField.deck_reversed = presentationNode->deckReversed;
    mainGame->dField.cant_check_grave = presentationNode->cantCheckGrave;
    mainGame->dField.disabled_field = presentationNode->disabledField;
}
bool TrainingHistoryScriptError() {
    if(!restoring) return false;
    replayError = true;
    return true;
}
static int execute(intptr_t engine, CoreCall& call, unsigned char* buffer, std::vector<unsigned char>* storage = nullptr) {
    switch(call.kind) {
    case CoreCall::Process: {
        const auto result = process(engine);
        const auto length = result & PROCESSOR_BUFFER_LEN;
        if(storage) {
            if(storage->size() < size_t(length)) storage->resize(length);
            buffer = storage->data();
        }
        if(result & PROCESSOR_BUFFER_LEN) get_message(engine, buffer);
        return result;
    }
    case CoreCall::Response: set_responseb(engine, call.bytes.data()); return 0;
    case CoreCall::Integer: {
        int32_t value; std::memcpy(&value, call.bytes.data(), sizeof value);
        set_responsei(engine, value); return 0;
    }
    case CoreCall::Start: start_duel(engine, call.flags); return 0;
    case CoreCall::FieldInfo: return query_field_info(engine, buffer);
    case CoreCall::FieldCards: return query_field_card(engine, call.player, call.location, call.flags, buffer, call.cache);
    case CoreCall::Card: return query_card(engine, call.player, call.location, call.sequence, call.flags, buffer, call.cache);
    }
    return 0;
}
static int record(intptr_t engine, CoreCall call, unsigned char* buffer, std::vector<unsigned char>* storage = nullptr) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    const int result = execute(engine, call, buffer, storage);
    if(storage) buffer = storage->data();
    if(!restoring || rebuildingView) {
        call.result = result;
        const int len = call.kind == CoreCall::Process ? result & PROCESSOR_BUFFER_LEN : result;
        if(len > 0) call.bytes.assign(buffer, buffer + len);
        (rebuildingView ? resumeCalls : calls).push_back(std::move(call));
    }
    return result;
}
int TrainingProcess(intptr_t engine, std::vector<unsigned char>& buffer) { return record(engine, {CoreCall::Process}, buffer.data(), &buffer); }
void TrainingStartDuel(intptr_t engine, int options) {
    CoreCall call{CoreCall::Start}; call.flags = options; record(engine, call, nullptr);
}
int TrainingQueryFieldInfo(intptr_t engine, unsigned char* buffer) { return record(engine, {CoreCall::FieldInfo}, buffer); }
int TrainingQueryFieldCard(intptr_t engine, uint8_t player, uint8_t location, uint32_t flags, unsigned char* buffer, int cache) {
    CoreCall call{CoreCall::FieldCards}; call.player = player; call.location = location; call.flags = flags; call.cache = cache;
    return record(engine, call, buffer);
}
int TrainingQueryCard(intptr_t engine, uint8_t player, uint8_t location, uint8_t sequence, uint32_t flags, unsigned char* buffer, int cache) {
    CoreCall call{CoreCall::Card}; call.player = player; call.location = location; call.sequence = sequence; call.flags = flags; call.cache = cache;
    return record(engine, call, buffer);
}
void TrainingHistoryResponse(const unsigned char* bytes, size_t len, bool integer) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(restoring) return;
    if(resumeFromNode) {
        const auto node = std::find_if(checkpoints.begin(), checkpoints.end(), [](const Checkpoint& c){return c.id == cursor;});
        calls.resize(node->calls);
        checkpoints.erase(node + 1, checkpoints.end());
        calls.insert(calls.end(), resumeCalls.begin(), resumeCalls.end());
        resumeCalls.clear(); resumeFromNode = false;
        TrainingWrite("\"kind\":\"branch\",\"target\":" + std::to_string(cursor));
    }
    CoreCall call{integer ? CoreCall::Integer : CoreCall::Response};
    // set_responseb consumes the entire 64-byte buffer, even for a shorter UI answer.
    call.bytes.assign(bytes, bytes + (integer ? 4 : 64));
    calls.push_back(std::move(call));
    ++revision; atNode = false;
    TrainingWrite("\"kind\":\"route_input\",\"revision\":" + std::to_string(revision));
    status();
}
void TrainingSubmitResponse(intptr_t& engine, unsigned char* bytes, size_t len) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(restoring) return;
    TrainingResponse(bytes, len);
    set_responseb(engine, bytes);
}
void TrainingWait(intptr_t& engine, const unsigned char* prompt, size_t len) {
    mainGame->singleSignal.Reset();
    {
        std::lock_guard<std::recursive_mutex> lock(historyMutex);
        const auto f = reinterpret_cast<duel*>(engine)->game_field;
        const auto playerOffset = prompt[0] == MSG_SELECT_SUM ? 2u : 1u;
        const bool firstChoice = checkpoints.empty() && len > playerOffset && prompt[playerOffset] == 0
            && prompt[0] >= MSG_SELECT_BATTLECMD && prompt[0] <= MSG_SELECT_UNSELECT_CARD;
        if(firstChoice || (len > 1 && prompt[1] == 0 && (prompt[0] == MSG_SELECT_IDLECMD || prompt[0] == MSG_SELECT_BATTLECMD)
                && f->core.current_chain.empty())) {
            Checkpoint node{++nextNode, calls.size(), {prompt, prompt + len}, TrainingState(engine)};
            {
                std::lock_guard<std::mutex> viewLock(mainGame->gMutex);
                node.deckReversed = mainGame->dField.deck_reversed;
                node.cantCheckGrave = mainGame->dField.cant_check_grave;
                node.disabledField = mainGame->dField.disabled_field;
            }
            cursor = node.id; atNode = true;
            TrainingWrite("\"kind\":\"checkpoint\",\"node\":" + std::to_string(node.id) + ",\"revision\":" + std::to_string(revision)
                + ",\"state\":" + node.state);
            checkpoints.push_back(std::move(node));
        }
        status();
    }
    while(!TrainingStopping()) {
        // Only the duel thread reads rewind requests, at an engine input boundary.
        std::ifstream request(TrainingPath("rewind.request"));
        uint64_t target, expected;
        std::string token;
        if(request >> target >> expected >> token) {
            request.close(); DeleteFileA(TrainingPath("rewind.request").c_str());
            if(token.size() != 32 || token.find_first_not_of("0123456789abcdef") != std::string::npos) continue;
            std::lock_guard<std::recursive_mutex> lock(historyMutex);
            intptr_t candidate = 0;
            try {
                if(expected != revision) throw std::runtime_error("stale_route");
                auto node = std::find_if(checkpoints.begin(), checkpoints.end(), [target](const Checkpoint& c){return c.id == target;});
                if(node == checkpoints.end()) throw std::runtime_error("node_unavailable");
                restoring = true; replayError = false;
                operation(token, "running");
                candidate = makeDuel();
                if(!candidate) throw std::runtime_error("create_failed");
                std::vector<unsigned char> buffer(SIZE_QUERY_BUFFER + SIZE_MESSAGE_BUFFER);
                const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
                for(size_t i = 0; i < node->calls; ++i) {
                    if(TrainingStopping() || std::chrono::steady_clock::now() > deadline) throw std::runtime_error("replay_timeout");
                    auto& call = calls[i];
                    const int result = execute(candidate, call, buffer.data(), &buffer);
                    if(result != call.result || replayError) throw std::runtime_error("replay_mismatch");
                    if(call.kind != CoreCall::Response && call.kind != CoreCall::Integer && !call.bytes.empty()
                            && !std::equal(call.bytes.begin(), call.bytes.end(), buffer.begin())) throw std::runtime_error("replay_mismatch");
                }
                if(TrainingState(candidate) != node->state) throw std::runtime_error("state_mismatch");
                // Test-only failure injection exercises the real transaction after reconstruction.
                if(TrainingTestControlled() && GetFileAttributesA(TrainingPath("test-rewind-fail").c_str()) != INVALID_FILE_ATTRIBUTES)
                    throw std::runtime_error("test_validation_failed");
                // Flush the branch pointer before publishing the new field. The old engine is still intact.
                TrainingWrite("\"kind\":\"rewind\",\"target\":" + std::to_string(target) + ",\"token\":\"" + token
                    + "\",\"revision\":" + std::to_string(revision + 1) + ",\"state\":" + node->state);
                if(TrainingStopping()) throw std::runtime_error("write_failed");
                const auto old = engine; engine = candidate; candidate = 0;
                resumeCalls.clear(); rebuildingView = true; presentationNode = &*node;
                showDuel(node->prompt);
                rebuildingView = false; presentationNode = nullptr; resumeFromNode = true;
                end_duel(old);
                cursor = target; atNode = true; ++revision;
                mainGame->singleSignal.Reset();
                status();
                // A lost acknowledgement is not a failed restore. The service can
                // reconcile the committed token with the published cursor/revision.
                try { operation(token, "done"); } catch(const std::exception&) {}
            } catch(const std::exception& error) {
                if(candidate) end_duel(candidate);
                try { operation(token, "error", error.what()); } catch(const std::exception&) {}
            }
            restoring = false;
        }
        if(mainGame->singleSignal.Wait(30)) return;
    }
}
}
