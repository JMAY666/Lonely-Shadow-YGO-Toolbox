// Reconstruct a second, independent Lua/core instance before changing the live duel.
// Record every core call made by the adapter, including queries that can evaluate Lua.
#include "training_support.h"
#include "game.h"
#include "../ocgcore/ocgapi.h"
#include "../ocgcore/duel.h"
#include "../ocgcore/field.h"
#include "../ocgcore/card.h"
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
#include <map>
#include <set>
#include <iomanip>

namespace ygo {
struct CoreCall {
    enum Kind { Process, Response, Integer, Start, FieldInfo, FieldCards, Card, Auto, Scene, LearningSnapshot } kind;
    uint64_t serial = 0;
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
    std::string maskedState;
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
static uint64_t nextCall = 0;
static int pendingPlayer = -1;
static bool pendingAnswered = false;
static bool opponentManual = false;
static uint64_t promptVersion = 0;
static std::string lastControlToken;
static std::vector<unsigned char> pendingPrompt;

#include "training_learning.inc"

static std::string encode(const std::vector<unsigned char>& bytes) {
    std::ostringstream out;
    for(auto b : bytes) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(b);
    return bytes.empty() ? "-" : out.str();
}
static std::vector<unsigned char> decode(const std::string& text) {
    if(text == "-") return {};
    if(text.size() % 2 || text.size() > 16 * 1024 * 1024 || text.find_first_not_of("0123456789abcdef") != std::string::npos)
        throw std::runtime_error("invalid_replay");
    std::vector<unsigned char> bytes;
    for(size_t i = 0; i < text.size(); i += 2) bytes.push_back(static_cast<unsigned char>(std::stoul(text.substr(i, 2), nullptr, 16)));
    return bytes;
}
static void persist(CoreCall& call) {
    call.serial = ++nextCall;
    std::ofstream out(TrainingPath("core-calls.txt"), std::ios::app | std::ios::binary);
    out << call.serial << ' ' << int(call.kind) << ' ' << call.result << ' ' << unsigned(call.player) << ' ' << unsigned(call.location)
        << ' ' << unsigned(call.sequence) << ' ' << call.flags << ' ' << call.cache << ' ' << encode(call.bytes) << '\n';
    out.close();
    if(!out) throw std::runtime_error("write_failed");
}
bool TrainingBranchActive() { return GetFileAttributesA(TrainingPath("branch.cfg").c_str()) != INVALID_FILE_ATTRIBUTES; }
bool TrainingOpponentManual() { return opponentManual; }
int TrainingPromptPlayer(const unsigned char* prompt, size_t len) {
    if(len < 2) return -1;
    const int msg = prompt[0];
    if((msg >= MSG_SELECT_BATTLECMD && msg <= MSG_SELECT_UNSELECT_CARD) || (msg >= MSG_ANNOUNCE_RACE && msg <= MSG_ANNOUNCE_NUMBER)) {
        const size_t offset = msg == MSG_SELECT_SUM ? 2 : 1;
        return len > offset && prompt[offset] <= 1 ? prompt[offset] : -1;
    }
    return -1;
}

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
    out << "{\"revision\":" << revision << ",\"cursor\":" << cursor << ",\"at_node\":" << (atNode ? "true" : "false") << ",\"available_nodes\":[";
    for(size_t i = 0; i < checkpoints.size(); ++i) { if(i) out << ','; out << checkpoints[i].id; }
    out << "]}";
    // A missed read-only status update must not terminate a playable duel. A stale
    // revision is rejected by the core before a subsequent restore can start.
    try { atomicFile("timeline-state.json", out.str()); } catch(const std::exception&) {}
}
static void operation(const std::string& token, const char* state, const char* error = "") {
    atomicFile("rewind-operation.json", "{\"token\":\"" + token + "\",\"status\":\"" + state + "\",\"error\":\"" + error + "\"}");
}
static LONG WINAPI trainingCrashDiagnostic(EXCEPTION_POINTERS* info) {
    std::ofstream out(TrainingPath("native-crash.txt"));
    const auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    out << std::hex << "code " << info->ExceptionRecord->ExceptionCode << " offset "
        << reinterpret_cast<uintptr_t>(info->ExceptionRecord->ExceptionAddress) - base << '\n';
    out << "rax " << info->ContextRecord->Rax << " rbx " << info->ContextRecord->Rbx << " rcx " << info->ContextRecord->Rcx
        << " rdx " << info->ContextRecord->Rdx << " rsi " << info->ContextRecord->Rsi << " rdi " << info->ContextRecord->Rdi << '\n';
    void* frames[48]{};
    const auto count = CaptureStackBackTrace(0, 48, frames, nullptr);
    for(USHORT i = 0; i < count; ++i) out << reinterpret_cast<uintptr_t>(frames[i]) - base << '\n';
    return EXCEPTION_EXECUTE_HANDLER;
}
void TrainingHistoryInit(std::function<intptr_t()> factory, std::function<void(const std::vector<unsigned char>&)> show) {
    makeDuel = factory; showDuel = show;
    if(TrainingTestControlled()) SetUnhandledExceptionFilter(trainingCrashDiagnostic);
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
    case CoreCall::LearningSnapshot: {
        if(!learningEnabled()) throw std::runtime_error("learning_query_disabled");
        const auto value = learningSnapshot(engine);
        if(!storage || value.size() > 2 * 1024 * 1024) throw std::runtime_error("learning_query_size");
        if(storage->size() < value.size()) storage->resize(value.size());
        std::memcpy(storage->data(), value.data(), value.size());
        return static_cast<int>(value.size());
    }
    case CoreCall::Scene: {
        if(call.bytes.size() % 4 || call.bytes.size() > 240) throw std::runtime_error("invalid_scene");
        std::multiset<uint32_t> wanted;
        for(size_t i = 0; i < call.bytes.size(); i += 4) { uint32_t code; std::memcpy(&code, call.bytes.data() + i, 4); wanted.insert(code); }
        auto f = reinterpret_cast<duel*>(engine)->game_field;
        const auto pendingHandShuffle = f->core.shuffle_hand_check[1];
        const auto hand = f->player[1].list_hand;
        for(auto c : hand) {
            auto found = wanted.find(c->data.code);
            if(found != wanted.end()) wanted.erase(found);
            else f->remove_card(c);
        }
        for(auto code : wanted) new_card(engine, code, 1, 1, LOCATION_HAND, 0, POS_FACEDOWN_DEFENSE);
        // These cards define the hypothetical hand at the restored boundary;
        // they were not added by an in-duel effect. Preserve any already-pending
        // shuffle, without introducing a synthetic hand-movement/shuffle event.
        f->core.shuffle_hand_check[1] = pendingHandShuffle;
        return 0;
    }
    case CoreCall::Auto: {
        auto f = reinterpret_cast<duel*>(engine)->game_field;
        if(f->core.units.empty()) return 0;
        auto it = f->core.units.begin();
        const auto options = f->core.duel_options;
        f->core.duel_options |= DUEL_SIMPLE_AI;
        bool handled = true;
        switch(it->type) {
        case PROCESSOR_SELECT_IDLECMD:
            if(!f->core.summonable_cards.empty()) {
                size_t choice = 0;
                for(size_t i = 0; i < f->core.summonable_cards.size(); ++i)
                    if(f->core.summonable_cards[i]->data.code == 1184620) { choice = i; break; }
                f->returns.ivalue[0] = static_cast<int32_t>(choice << 16);
            } else if(f->core.to_ep) f->returns.ivalue[0] = 7;
            else handled = false;
            break;
        case PROCESSOR_SELECT_BATTLECMD: if(f->core.to_ep) f->returns.ivalue[0] = 3; else handled = false; break;
        case PROCESSOR_SELECT_EFFECTYN: f->select_effect_yes_no(0, it->arg1, it->arg2, reinterpret_cast<card*>(it->ptarget)); break;
        case PROCESSOR_SELECT_YESNO: f->select_yes_no(0, it->arg1, it->arg2); break;
        case PROCESSOR_SELECT_OPTION: f->select_option(0, it->arg1); break;
        case PROCESSOR_SELECT_CARD: f->select_card(0, it->arg1 & 0xff, (it->arg1 >> 16) & 0xff, it->arg2 & 0xff, (it->arg2 >> 16) & 0xff); break;
        case PROCESSOR_SELECT_UNSELECT_CARD: f->select_unselect_card(0, it->arg1 & 0xff, (it->arg1 >> 16) & 0xff, it->arg2 & 0xff, (it->arg2 >> 16) & 0xff, it->arg3 & 0xff); break;
        case PROCESSOR_SELECT_CHAIN: f->select_chain(0, it->arg1, it->arg2 & 0xffff); break;
        case PROCESSOR_SELECT_DISFIELD:
        case PROCESSOR_SELECT_PLACE: f->select_place(0, it->arg1, it->arg2, it->arg3); break;
        case PROCESSOR_SELECT_POSITION: f->select_position(0, it->arg1 & 0xffff, it->arg2, (it->arg1 >> 16) & 0xffff); break;
        case PROCESSOR_SORT_CARD: f->sort_card(0, it->arg1); break;
        default: handled = false;
        }
        f->core.duel_options = options;
        if(!handled) return 0;
        std::memcpy(buffer, f->returns.bvalue, 64);
        set_responseb(engine, buffer);
        return 64;
    }
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
        persist(call);
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
void TrainingCheckpoint(intptr_t engine, const unsigned char* prompt, size_t len) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(restoring) return;
    Checkpoint node{++nextNode, calls.size(), {prompt, prompt + len}, TrainingState(engine)};
    node.maskedState = TrainingState(engine, true);
    {
        std::lock_guard<std::mutex> viewLock(mainGame->gMutex);
        node.deckReversed = mainGame->dField.deck_reversed;
        node.cantCheckGrave = mainGame->dField.cant_check_grave;
        node.disabledField = mainGame->dField.disabled_field;
    }
    std::ostringstream restore;
    restore << "1 " << node.id << ' ' << node.calls << ' ' << node.deckReversed << ' ' << node.cantCheckGrave << ' ' << node.disabledField << '\n'
        << node.state << '\n' << node.maskedState << '\n' << encode(node.prompt) << '\n';
    for(const auto& call : calls) restore << call.serial << ' ';
    restore << '\n';
    atomicFile(("restore-" + std::to_string(node.id) + ".txt").c_str(), restore.str());
    cursor = node.id; atNode = true;
    TrainingWrite("\"kind\":\"checkpoint\",\"node\":" + std::to_string(node.id) + ",\"revision\":" + std::to_string(revision)
        + ",\"restorable\":true,\"prompt\":" + std::to_string(prompt[0]) + ",\"player\":" + std::to_string(TrainingPromptPlayer(prompt, len))
        + ",\"raw\":\"" + encode(node.prompt) + "\",\"effects\":" + TrainingDecisionEffects(engine) + ",\"state\":" + node.state);
    checkpoints.push_back(std::move(node));
    status();
}
#include "training_modular.inc"

void TrainingPublishOpponent(intptr_t engine, const unsigned char* prompt, size_t len) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    mainGame->singleSignal.Reset();
    pendingPrompt.assign(prompt, prompt + len);
    pendingPlayer = TrainingPromptPlayer(prompt, len);
    pendingAnswered = false;
    ++promptVersion;
    modularPublish(engine);
    if(!TrainingBranchActive()) return;
    atomicFile("opponent-state.json", "{\"version\":" + std::to_string(promptVersion) + ",\"manual\":" + (opponentManual ? "true" : "false")
        + ",\"player\":" + std::to_string(pendingPlayer) + ",\"answered\":false,\"raw\":\"" + encode(pendingPrompt)
        + "\",\"token\":\"" + lastControlToken + "\",\"state\":" + TrainingState(engine) + '}');
}
bool TrainingRetry(intptr_t engine) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    const auto previous = pendingPrompt;
    if(previous.empty()) return false;
    if(pendingPlayer == 1 && TrainingBranchActive()) opponentManual = true;
    TrainingPublishOpponent(engine, previous.data(), previous.size());
    return pendingPlayer == 1 && TrainingBranchActive();
}
bool TrainingAutoResponse(intptr_t engine, int prompt) {
    unsigned char response[64]{};
    if(record(engine, {CoreCall::Auto}, response) != 64) return false;
    ++revision; atNode = false; pendingAnswered = true;
    TrainingWrite("\"kind\":\"route_input\",\"revision\":" + std::to_string(revision));
    TrainingWrite("\"kind\":\"response\",\"actor\":\"" + std::string(TrainingOpponentAI() || TrainingBranchActive() ? "opponent_ai" : "wall_pass")
        + "\",\"prompt\":" + std::to_string(prompt) + ",\"raw\":\"" + encode({response, response + 64}) + "\"");
    status();
    return true;
}
bool TrainingOpponentTick(intptr_t engine, const std::vector<unsigned char>& ignored) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(restoring) return false;
    if(!TrainingBranchActive()) return false;
    if(TrainingBranchActive()) {
        std::ifstream input(TrainingPath("opponent.request"));
        std::string command, token, response;
        uint64_t expected;
        if(input >> command >> expected >> token >> response) {
            input.close(); DeleteFileA(TrainingPath("opponent.request").c_str());
            if(token.size() != 32 || token.find_first_not_of("0123456789abcdef") != std::string::npos) return false;
            if(token != lastControlToken && (command != "answer" || (expected == promptVersion && pendingPlayer == 1 && opponentManual && !pendingAnswered))) {
                lastControlToken = token;
                if(command == "take" || command == "release") {
                    opponentManual = command == "take";
                    TrainingWrite("\"kind\":\"opponent_control\",\"manual\":" + std::string(opponentManual ? "true" : "false"));
                    const auto copy = pendingPrompt;
                    TrainingPublishOpponent(engine, copy.data(), copy.size());
                } else if(command == "answer") {
                    try {
                        auto bytes = decode(response);
                        if(bytes.empty() || bytes.size() > 64) return false;
                        const auto count = bytes.size(); bytes.resize(64);
                        TrainingResponse(bytes.data(), count, "opponent_manual", pendingPrompt[0]);
                        set_responseb(engine, bytes.data()); pendingAnswered = true;
                    } catch(const std::exception&) { return false; }
                }
            }
        }
    }
    if(pendingPlayer != 1) return false;
    if(!pendingAnswered && pendingPrompt.size() >= 12 && pendingPrompt[0] == MSG_SELECT_CHAIN && pendingPrompt[2] == 0) {
        // No legal candidate exists: there is no AI decision or player choice to
        // race. Do not strand a manually controlled duel on an empty window.
        int32_t answer = -1;
        TrainingResponse(reinterpret_cast<unsigned char*>(&answer), sizeof answer, "wall_pass", MSG_SELECT_CHAIN);
        set_responsei(engine, answer); pendingAnswered = true;
    }
    if(!pendingAnswered && !opponentManual) {
        if(!TrainingAutoResponse(engine, pendingPrompt[0])) {
            // The pinned basic AI has no strategy for this prompt. Keep the legal
            // choice pending; a branch can be taken over without guessing a response.
            if(!TrainingBranchActive()) return false;
            opponentManual = true;
            const auto copy = pendingPrompt;
            TrainingPublishOpponent(engine, copy.data(), copy.size());
        }
    }
    if(pendingAnswered && TrainingBranchActive())
        atomicFile("opponent-state.json", "{\"version\":" + std::to_string(promptVersion) + ",\"manual\":" + (opponentManual ? "true" : "false")
            + ",\"player\":1,\"answered\":true,\"token\":\"" + lastControlToken + "\",\"raw\":\"-\"}");
    return pendingAnswered;
}

bool TrainingResumeBranch(intptr_t& engine, std::vector<unsigned char>& prompt) {
    if(!TrainingBranchActive()) return false;
    restoring = true; replayError = false;
    intptr_t candidate = 0;
    try {
        std::ifstream config(TrainingPath("branch.cfg"));
        unsigned count; uint32_t code; uint64_t lastNode;
        if(!(config >> lastNode >> count) || count > 60) throw std::runtime_error("invalid_scene");
        CoreCall scene{CoreCall::Scene};
        for(unsigned i = 0; i < count; ++i) {
            if(!(config >> code)) throw std::runtime_error("invalid_scene");
            const auto p = reinterpret_cast<unsigned char*>(&code); scene.bytes.insert(scene.bytes.end(), p, p + 4);
        }
        std::ifstream metadata(TrainingPath("restore.txt"));
        int version; Checkpoint node{}; std::string encoded;
        if(!(metadata >> version >> node.id >> node.calls >> node.deckReversed >> node.cantCheckGrave >> node.disabledField)
                || version != 1 || !node.calls || node.calls > 1000000) throw std::runtime_error("invalid_replay");
        metadata.ignore(2, '\n'); std::getline(metadata, node.state); std::getline(metadata, node.maskedState);
        metadata >> encoded; node.prompt = decode(encoded);
        std::vector<uint64_t> selected(node.calls);
        for(auto& serial : selected) if(!(metadata >> serial)) throw std::runtime_error("invalid_replay");
        std::set<uint64_t> needed(selected.begin(), selected.end()); std::map<uint64_t, CoreCall> source;
        std::ifstream tape(TrainingPath("replay-calls.txt"));
        CoreCall call{}; int kind, player, location, sequence;
        while(tape >> call.serial >> kind >> call.result >> player >> location >> sequence >> call.flags >> call.cache >> encoded) {
            if(!needed.count(call.serial)) continue;
            if(kind < 0 || kind > CoreCall::LearningSnapshot) throw std::runtime_error("invalid_replay");
            call.kind = static_cast<CoreCall::Kind>(kind); call.player = player; call.location = location; call.sequence = sequence;
            call.bytes = decode(encoded);
            if(source.count(call.serial) || player < 0 || player > 1 || location < 0 || location > 255 || sequence < 0 || sequence > 255
                || (call.kind == CoreCall::Response && call.bytes.size() != 64) || (call.kind == CoreCall::Integer && call.bytes.size() != 4)
                || (call.kind == CoreCall::Process && size_t(call.result & PROCESSOR_BUFFER_LEN) != call.bytes.size())
                || ((call.kind == CoreCall::FieldInfo || call.kind == CoreCall::FieldCards || call.kind == CoreCall::Card || call.kind == CoreCall::Auto)
                    && (call.result < 0 || size_t(call.result) != call.bytes.size()))) throw std::runtime_error("invalid_replay");
            source[call.serial] = call;
        }
        std::vector<CoreCall> replay;
        for(auto serial : selected) { if(!source.count(serial)) throw std::runtime_error("invalid_replay"); replay.push_back(source[serial]); }
        candidate = makeDuel();
        if(!candidate) throw std::runtime_error("create_failed");
        std::vector<unsigned char> buffer(SIZE_QUERY_BUFFER + SIZE_MESSAGE_BUFFER);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
        // First reconstruct and validate the unmodified engine, including all queries,
        // RNG-consuming calls, responses, Lua restrictions and the pending chain.
        for(auto& item : replay) {
            if(TrainingStopping() || std::chrono::steady_clock::now() > deadline) throw std::runtime_error("replay_timeout");
            if(buffer.size() < item.bytes.size()) buffer.resize(item.bytes.size());
            const int result = execute(candidate, item, buffer.data(), &buffer);
            if(result != item.result || replayError) throw std::runtime_error("replay_mismatch");
            if(item.kind != CoreCall::Response && item.kind != CoreCall::Integer && item.kind != CoreCall::Scene && !item.bytes.empty()
                && !std::equal(item.bytes.begin(), item.bytes.end(), buffer.begin())) throw std::runtime_error("replay_mismatch");
        }
        if(TrainingComparableState(TrainingState(candidate)) != TrainingComparableState(node.state)) throw std::runtime_error("state_mismatch");
        end_duel(candidate); candidate = makeDuel();
        size_t boundary = replay.size();
        while(boundary && replay[boundary - 1].kind != CoreCall::Process) --boundary;
        if(!boundary) throw std::runtime_error("prompt_unavailable");
        --boundary;
        const auto original = replay[boundary].bytes;
        if(original.size() < node.prompt.size() || !std::equal(node.prompt.rbegin(), node.prompt.rend(), original.rbegin()))
            throw std::runtime_error("prompt_not_at_boundary");
        const size_t prefix = original.size() - node.prompt.size();
        calls.clear(); nextCall = 0;
        for(size_t i = 0; i < replay.size(); ++i) {
            if(TrainingStopping() || std::chrono::steady_clock::now() > deadline) throw std::runtime_error("replay_timeout");
            if(i == boundary) { execute(candidate, scene, nullptr); persist(scene); calls.push_back(scene); }
            auto item = replay[i];
            const int result = execute(candidate, item, buffer.data(), &buffer);
            const int length = item.kind == CoreCall::Process ? result & PROCESSOR_BUFFER_LEN : result;
            if(i == boundary) {
                if(length < int(prefix + 2) || !std::equal(original.begin(), original.begin() + prefix, buffer.begin()))
                    throw std::runtime_error("scene_changes_prior_events");
                prompt.assign(buffer.begin() + prefix, buffer.begin() + length);
                if(TrainingTestControlled()) atomicFile("branch-replay-diagnostic.json", "{\"expected\":\"" + encode(node.prompt) + "\",\"actual\":\"" + encode(prompt) + "\"}");
                // A single available effect may use EFFECTYN where the empty or
                // multi-candidate window used CHAIN. Both are the same core response boundary.
                const bool responseWindow = (node.prompt[0] == MSG_SELECT_CHAIN || node.prompt[0] == MSG_SELECT_EFFECTYN)
                    && (prompt[0] == MSG_SELECT_CHAIN || prompt[0] == MSG_SELECT_EFFECTYN);
                if((prompt[0] != node.prompt[0] && !responseWindow) || TrainingPromptPlayer(prompt.data(), prompt.size()) != TrainingPromptPlayer(node.prompt.data(), node.prompt.size()))
                    throw std::runtime_error("scene_changes_prompt");
            }
            if(i >= boundary && length > 0) item.bytes.assign(buffer.begin(), buffer.begin() + length);
            item.result = result; persist(item); calls.push_back(std::move(item));
        }
        if(replayError || TrainingComparableState(TrainingState(candidate, true)) != TrainingComparableState(node.maskedState)) throw std::runtime_error("scene_changes_prior_state");
        const auto previous = engine; engine = candidate; candidate = 0; end_duel(previous);
        nextNode = lastNode; opponentManual = true;
        rebuildingView = true; presentationNode = &node; resumeCalls.clear();
        showDuel(prompt);
        rebuildingView = false; presentationNode = nullptr;
        calls.insert(calls.end(), resumeCalls.begin(), resumeCalls.end()); resumeCalls.clear();
        restoring = false;
        TrainingWrite("\"kind\":\"branch_restored\",\"source_node\":" + std::to_string(node.id) + ",\"raw\":\"" + encode(prompt) + "\",\"state\":" + TrainingState(engine));
        TrainingCheckpoint(engine, prompt.data(), prompt.size());
        TrainingPublishOpponent(engine, prompt.data(), prompt.size());
        atomicFile("branch-operation.json", "{\"status\":\"ready\"}");
        std::ofstream ready(TrainingPath("ready.json")); ready << "{\"ready\":true}";
        return true;
    } catch(const std::exception& error) {
        if(candidate) end_duel(candidate);
        restoring = false; rebuildingView = false; presentationNode = nullptr;
        try { atomicFile("branch-operation.json", "{\"status\":\"error\",\"error\":\"" + std::string(error.what()) + "\"}"); } catch(...) {}
        TrainingStop(true);
        return true;
    }
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
    persist(call);
    calls.push_back(std::move(call));
    ++revision; atNode = false;
    TrainingWrite("\"kind\":\"route_input\",\"revision\":" + std::to_string(revision));
    status();
}
void TrainingSubmitResponse(intptr_t& engine, unsigned char* bytes, size_t len) {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(restoring || (pendingPlayer == 1 && TrainingBranchActive()) || pendingAnswered) return;
    pendingAnswered = true;
    TrainingResponse(bytes, len);
    set_responseb(engine, bytes);
    modularPublish(engine);
}
void TrainingWait(intptr_t& engine, const unsigned char* prompt, size_t len) {
    {
        std::lock_guard<std::recursive_mutex> lock(historyMutex);
        status();
    }
    while(!TrainingStopping()) {
        if(modularTick(engine)) return;
        if(TrainingOpponentTick(engine, {prompt, prompt + len})) return;
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
                if(TrainingComparableState(TrainingState(candidate)) != TrainingComparableState(node->state)) throw std::runtime_error("state_mismatch");
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
                TrainingPublishOpponent(engine, node->prompt.data(), node->prompt.size());
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
