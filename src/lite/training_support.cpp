// Local recorder for the pinned YGOPro core. No rule decisions are inferred from text.
#include "training_support.h"
#include "game.h"
#include "single_mode.h"
#include "duelclient.h"
#include "data_manager.h"
#include "client_card.h"
#include "../ocgcore/duel.h"
#include "../ocgcore/field.h"
#include "../ocgcore/interpreter.h"
#include "../ocgcore/card.h"
#include "../ocgcore/effect.h"
#include "../ocgcore/ocgapi.h"
#include <windows.h>
#include <atomic>
#include <chrono>
#include <fstream>
#include <mutex>
#include <sstream>
#include <algorithm>
#include <map>
#include <thread>

namespace ygo {
static std::string session;
static std::mutex logMutex;
static uint64_t sequence = 0;
static std::atomic<bool> stopping{false}, closing{false}, finished{false};
static std::ofstream journal;
static std::string captureToken;
static std::atomic<bool> opening{true};
bool TrainingOpening() { return TrainingEmbedded() && opening; }
bool TrainingOpponentAI() {
    if(!TrainingActive()) return false;
    static const bool enabled = [] {
        std::ifstream config(TrainingPath("opening.cfg"));
        int version = 0, ai = 0;
        return (config >> version >> ai) && (version == 1 || version == 2) && ai == 1;
    }();
    return enabled;
}
static std::string quote(const wchar_t* value);
static void TestButtons(irr::gui::IGUIElement* element, std::ostringstream& out, bool& first) {
    if(!element->isVisible()) return;
    if(element->getType() == irr::gui::EGUIET_BUTTON && element->isEnabled()) {
        const auto rect = element->getAbsoluteClippingRect();
        if(rect.getWidth() > 0 && rect.getHeight() > 0) {
            if(!first) out << ','; first = false;
            out << "{\"text\":" << quote(element->getText()) << ",\"x\":" << rect.getCenter().X << ",\"y\":" << rect.getCenter().Y << '}';
        }
    }
    for(auto child : element->getChildren()) TestButtons(child, out, first);
}
static std::string TestUIState() {
    std::lock_guard<std::mutex> lock(mainGame->gMutex);
    auto& field = mainGame->dField;
    auto oldController = field.hovered_controler, oldLocation = field.hovered_location;
    auto oldSequence = field.hovered_sequence;
    std::map<int, std::vector<int>> hits;
    // Use the engine's own hit test in its reference coordinate system.
    for(int y = 200; y < 624; y += 8) for(int x = 280; x < 1000; x += 8) {
        field.GetHoverField(x, y);
        if(field.hovered_controler != 0 || (field.hovered_location != 2 && field.hovered_location != 4 && field.hovered_location != 8 && field.hovered_location != 64)) continue;
        const int key = field.hovered_location * 100 + int(field.hovered_sequence);
        auto& hit = hits[key];
        if(hit.empty()) hit = {0, 0, 0};
        hit[0] += x; hit[1] += y; ++hit[2];
    }
    field.hovered_controler = oldController; field.hovered_location = oldLocation; field.hovered_sequence = oldSequence;
    std::ostringstream out;
    out << ",\"prompt\":" << unsigned(mainGame->dInfo.curMsg) << ",\"targets\":[";
    bool first = true;
    for(const auto& pair : hits) {
        if(!first) out << ','; first = false;
        const auto point = mainGame->Resize(pair.second[0] / pair.second[2], pair.second[1] / pair.second[2]);
        auto card = field.GetCard(0, pair.first / 100, pair.first % 100);
        out << "{\"location\":" << pair.first / 100 << ",\"sequence\":" << pair.first % 100 << ",\"code\":" << (card ? card->code : 0)
            << ",\"x\":" << point.X << ",\"y\":" << point.Y << '}';
    }
    out << "],\"buttons\":[";
    first = true; TestButtons(mainGame->env->getRootGUIElement(), out, first);
    out << "],\"activatable\":[";
    first = true;
    for(auto card : field.activatable_cards) { if(!first) out << ','; first = false; out << card->code; }
    out << "],\"summonable\":[";
    first = true;
    for(auto card : field.summonable_cards) { if(!first) out << ','; first = false; out << card->code; }
    out << "],\"choices\":[";
    first = true;
    if(mainGame->wCardSelect->isVisible()) {
        const auto start = mainGame->scrCardList->getPos() / 10;
        for(int i = 0; i < 5 && size_t(start + i) < field.selectable_cards.size(); ++i) {
            auto button = mainGame->btnCardSelect[i];
            if(!button->isVisible()) continue;
            if(!first) out << ','; first = false;
            const auto point = button->getAbsoluteClippingRect().getCenter();
            out << "{\"code\":" << field.selectable_cards[start + i]->code << ",\"selected\":" << (field.selectable_cards[start + i]->is_selected ? "true" : "false") << ",\"x\":" << point.X << ",\"y\":" << point.Y << '}';
        }
    }
    out << ']';
    return out.str();
}
bool TrainingEmbedded() { return GetEnvironmentVariableA("YGO_EMBED_PARENT", nullptr, 0) > 0; }
bool TrainingTestControlled() {
    char enabled[4]{};
    return GetEnvironmentVariableA("YGO_TRAIN_TEST_CONTROL", enabled, sizeof enabled) && enabled[0] == '1';
}
bool TrainingLearningControlled() {
    char enabled[8]{};
    return TrainingTestControlled() && GetEnvironmentVariableA("YGO_TRAIN_LEARNING", enabled, sizeof enabled)
        && enabled[0] == '1';
}
bool TrainingLearningFast() {
    char enabled[8]{};
    return TrainingLearningControlled() && GetEnvironmentVariableA("YGO_TRAIN_LEARNING_FAST", enabled, sizeof enabled)
        && enabled[0] == '1';
}
static void TrainingTestInput() {
    if(!TrainingTestControlled()) return;
    std::ifstream command(TrainingPath("test-command.txt"));
    std::string kind, token;
    int x = 0, y = 0;
    if(!(command >> kind >> token >> x >> y)) return;
    command.close();
    DeleteFileA(TrainingPath("test-command.txt").c_str());
    if(token.size() != 32 || token.find_first_not_of("0123456789abcdef") != std::string::npos) return;
    const auto size = mainGame->driver->getScreenSize();
    if(x < 0 || y < 0 || x >= int(size.Width) || y >= int(size.Height)) return;
    if(kind == "focus-lock") {
        std::atomic<bool> held{false}, done{false};
        std::thread blocker([&] {
            std::lock_guard<std::recursive_mutex> lock(TrainingInputMutex());
            held = true;
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(350);
            while(!done && std::chrono::steady_clock::now() < deadline)
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
        });
        while(!held) std::this_thread::yield();
        const auto began = std::chrono::steady_clock::now();
        bool consumed = false;
        {
            std::lock_guard<std::mutex> lock(mainGame->gMutex);
            irr::SEvent event{};
            event.EventType = irr::EET_GUI_EVENT;
            event.GUIEvent.Caller = mainGame->wQuery;
            for(const auto kind : {irr::gui::EGET_ELEMENT_FOCUSED, irr::gui::EGET_ELEMENT_FOCUS_LOST}) {
                event.GUIEvent.EventType = kind;
                consumed |= mainGame->dField.OnEvent(event);
            }
        }
        const auto micros = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - began).count();
        done = true; blocker.join();
        std::ofstream response(TrainingPath(("native-" + token + ".json").c_str()));
        response << "{\"focus_events\":2,\"history_mutex_contended\":true,\"consumed\":"
                 << (consumed ? "true" : "false") << ",\"elapsed_us\":" << micros << '}';
        return;
    }
    if(kind == "click") {
        // Deliver Irrlicht events to this engine only. No SendInput, cursor warp or global keys.
        irr::SEvent event{};
        event.EventType = irr::EET_MOUSE_INPUT_EVENT;
        event.MouseInput.X = x; event.MouseInput.Y = y;
        event.MouseInput.Event = irr::EMIE_MOUSE_MOVED;
        mainGame->device->postEventFromUser(event);
        event.MouseInput.Event = irr::EMIE_LMOUSE_PRESSED_DOWN;
        event.MouseInput.ButtonStates = irr::EMBSM_LEFT;
        mainGame->device->postEventFromUser(event);
        event.MouseInput.Event = irr::EMIE_LMOUSE_LEFT_UP;
        event.MouseInput.ButtonStates = 0;
        mainGame->device->postEventFromUser(event);
    } else if(kind != "capture") return;
    captureToken = token;
}
void TrainingCaptureFrame() {
    static bool frameReady = false;
    if(TrainingActive() && mainGame->dInfo.isStarted && !frameReady) {
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        std::ofstream ready(TrainingPath("frame-ready.json"));
        ready << "{\"time_ms\":" << ms << '}';
        frameReady = true;
    }
    if(captureToken.empty()) return;
    const std::string name = "native-" + captureToken;
    auto screenshot = mainGame->driver->createScreenShot();
    bool ok = screenshot && mainGame->driver->writeImageToFile(screenshot, TrainingPath((name + ".png").c_str()).c_str());
    if(screenshot) screenshot->drop();
    const auto size = mainGame->driver->getScreenSize();
    std::ofstream response(TrainingPath((name + ".json").c_str()));
    if(ok) response << "{\"width\":" << size.Width << ",\"height\":" << size.Height << TestUIState() << '}';
    else response << "{\"error\":\"Engine frame capture failed\"}";
    response.close();
    captureToken.clear();
}
static std::string hex(const unsigned char* bytes, size_t len) {
    static const char digits[] = "0123456789abcdef";
    std::string result;
    for(size_t i = 0; i < len; ++i) { result += digits[bytes[i] >> 4]; result += digits[bytes[i] & 15]; }
    return result;
}
static std::string quote(const wchar_t* value) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
    std::string utf8(size, 0), result = "\"";
    WideCharToMultiByte(CP_UTF8, 0, value, -1, &utf8[0], size, nullptr, nullptr);
    for(int i = 0; i + 1 < size; ++i) {
        const unsigned char c = utf8[i];
        if(c == '"' || c == '\\') { result += '\\'; result += c; }
        else if(c < 32) { char escape[7]; std::snprintf(escape, 7, "\\u%04x", c); result += escape; }
        else result += c;
    }
    return result + '"';
}
static int functionLine(effect* e, int reference) {
    if(!reference) return 0;
    auto L = e->pduel->lua->lua_state;
    const auto top = lua_gettop(L);
    lua_rawgeti(L, LUA_REGISTRYINDEX, reference);
    lua_Debug info{};
    const auto line = lua_isfunction(L, -1) && lua_getinfo(L, ">S", &info) ? info.linedefined : 0;
    lua_settop(L, top);
    return line;
}
static std::string describeEffect(effect* e) {
    if(!e) return "null";
    const auto handler = e->get_handler();
    std::ostringstream out;
    out << "{\"effect_id\":" << e->id << ",\"effect_handle\":" << e->ref_handle << ",\"description\":" << e->description
        << ",\"effect_type\":" << e->type << ",\"event_code\":" << e->code << ",\"range\":" << e->range << ",\"category\":" << e->category
        << ",\"owner_code\":" << (e->owner ? std::to_string(e->owner->data.code) : "null")
        << ",\"handler_instance\":" << (handler ? std::to_string(handler->cardid) : "null")
        << ",\"handler_code\":" << (handler ? std::to_string(handler->data.code) : "null")
        << ",\"count_code\":" << e->count_code << ",\"count_remaining\":" << unsigned(e->count_limit)
        << ",\"count_max\":" << unsigned(e->count_limit_max)
        << ",\"property_flags\":[\"" << e->flag[0] << "\",\"" << e->flag[1] << "\"]"
        << ",\"self_range\":" << e->s_range << ",\"opponent_range\":" << e->o_range
        << ",\"effect_value\":" << (e->is_flag(EFFECT_FLAG_FUNC_VALUE) ? "null" : std::to_string(e->value))
        << ",\"value_line\":" << (e->is_flag(EFFECT_FLAG_FUNC_VALUE) ? functionLine(e, e->value) : 0)
        << ",\"condition_line\":" << functionLine(e, e->condition) << ",\"cost_line\":" << functionLine(e, e->cost)
        << ",\"target_line\":" << functionLine(e, e->target) << ",\"operation_line\":" << functionLine(e, e->operation)
        << ",\"labels\":[";
    for(size_t i = 0; i < e->label.size(); ++i) { if(i) out << ','; out << e->label[i]; }
    out << "]}";
    return out.str();
}
std::string TrainingDecisionEffects(intptr_t engine) {
    const auto f = reinterpret_cast<duel*>(engine)->game_field;
    std::ostringstream out;
    out << "{\"context\":" << describeEffect(f->core.reason_effect) << ",\"choices\":[";
    bool first = true;
    for(const auto& chain : f->core.select_chains) {
        if(!first) out << ',';
        first = false;
        out << describeEffect(chain.triggering_effect);
    }
    out << "]}";
    return out.str();
}
bool TrainingActive() { return !session.empty(); }
std::string TrainingPath(const char* name) { return "_trainer/sessions/" + session + "/" + name; }
void TrainingWrite(const std::string& body) {
    if(!TrainingActive()) return;
    std::lock_guard<std::mutex> lock(logMutex);
    const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    journal << "{\"session\":\"" << session << "\",\"seq\":" << ++sequence << ",\"time_ms\":" << now << ',' << body << "}\n";
    journal.flush();
    if(!journal) { stopping = true; closing = true; }
}
std::string TrainingComparableState(std::string state) {
    // Lua registry references may differ after garbage collection in an
    // independently rebuilt VM. They identify evidence within one VM only.
    // Keep the effect's registration ID, handler, callbacks, values and flags.
    const std::string key = ",\"effect_handle\":";
    size_t at = 0;
    while((at = state.find(key, at)) != std::string::npos) {
        size_t end = at + key.size();
        if(end < state.size() && state[end] == '-') ++end;
        while(end < state.size() && state[end] >= '0' && state[end] <= '9') ++end;
        state.erase(at, end - at);
    }
    return state;
}
std::string TrainingState(intptr_t engine, bool omitOpponentHand) {
    const auto d = reinterpret_cast<duel*>(engine);
    const auto f = d->game_field;
    std::ostringstream out;
    out << "{\"turn\":" << f->infos.turn_id
        << ",\"turn_player\":" << unsigned(f->infos.turn_player) << ",\"phase\":" << f->infos.phase
        << ",\"lp\":[" << f->player[0].lp << ',' << f->player[1].lp << "],\"cards\":[";
    std::vector<card*> cards(d->cards.begin(), d->cards.end());
    std::sort(cards.begin(), cards.end(), [](card* a, card* b){ return a->cardid < b->cardid; });
    bool first = true;
    for(const auto c : cards) {
        if(!c->data.code || (!c->current.location && !c->overlay_target)) continue;
        if(omitOpponentHand && c->current.controler == 1 && c->current.location == LOCATION_HAND) continue;
        if(!first) out << ',';
        first = false;
        out << "{\"instance_id\":" << c->cardid << ",\"code\":" << c->data.code << ",\"name\":" << quote(dataManager.GetName(c->data.code))
            << ",\"owner\":" << unsigned(c->owner) << ",\"controller\":" << unsigned(c->overlay_target ? c->overlay_target->current.controler : c->current.controler)
            << ",\"location\":" << unsigned(c->overlay_target ? LOCATION_OVERLAY : c->current.location)
            << ",\"sequence\":" << unsigned(c->current.sequence) << ",\"position\":" << unsigned(c->current.position)
            << ",\"status_flags\":" << c->status << ",\"disabled\":" << ((c->status & STATUS_DISABLED) ? "true" : "false")
            << ",\"overlay_target\":" << (c->overlay_target ? std::to_string(c->overlay_target->cardid) : "null")
            << ",\"reason\":" << c->current.reason
            << ",\"reason_card_instance\":" << (c->current.reason_card ? std::to_string(c->current.reason_card->cardid) : "null")
            << ",\"summon_info\":" << c->summon_info << ",\"material_instance_ids\":[";
        std::vector<uint64_t> materials;
        for(const auto material : c->material_cards) materials.push_back(material->cardid);
        std::sort(materials.begin(), materials.end());
        for(size_t i = 0; i < materials.size(); ++i) { if(i) out << ','; out << materials[i]; }
        out << "],\"counters\":[";
        bool firstCounter = true;
        for(const auto& counter : c->counters) {
            if(!firstCounter) out << ',';
            firstCounter = false;
            out << "{\"type\":" << counter.first << ",\"count\":" << counter.second << '}';
        }
        out << "],\"reason_effect\":" << describeEffect(c->current.reason_effect) << '}';
    }
    out << "],\"chain_depth\":" << f->core.current_chain.size() << ",\"chains\":[";
    bool firstChain = true;
    for(const auto& chain : f->core.current_chain) {
        if(!firstChain) out << ',';
        firstChain = false;
        out << "{\"link\":" << unsigned(chain.chain_count) << ",\"effect\":" << describeEffect(chain.triggering_effect) << '}';
    }
    out << "]}";
    return out.str();
}
void TrainingCapture(intptr_t engine, const char* kind, const unsigned char* bytes, size_t len) {
    if(!TrainingActive() || !engine) return;
    TrainingWrite("\"kind\":\"" + std::string(kind) + "\",\"raw\":\"" + hex(bytes, len) + "\",\"state\":" + TrainingState(engine));
}
void TrainingResponse(const unsigned char* bytes, size_t len, const char* actor, int prompt) {
    TrainingHistoryResponse(bytes, len, std::string(actor) != "user" && std::string(actor) != "opponent_manual" && std::string(actor) != "opponent_auto");
    TrainingWrite("\"kind\":\"response\",\"actor\":\"" + std::string(actor) + "\",\"prompt\":" + std::to_string(prompt >= 0 ? prompt : mainGame->dInfo.curMsg) + ",\"raw\":\"" + hex(bytes, len) + "\"");
}
bool TrainingAnalyze(intptr_t engine, unsigned char* bytes, size_t len) {
    if(len && bytes[0] == MSG_RETRY && TrainingRetry(engine)) return false;
    const int inputPlayer = TrainingPromptPlayer(bytes, len);
    if(inputPlayer >= 0) {
        TrainingCheckpoint(engine, bytes, len);
        TrainingPublishOpponent(engine, bytes, len);
        if(inputPlayer == 1) {
            if(TrainingBranchActive()) return false;
            if(TrainingAutoResponse(engine, bytes[0])) return true;
            // Retain the native choice UI for prompts beyond the pinned basic AI.
        }
    }
    // Read-only readiness marker in every runtime, never an input/control endpoint.
    static bool ready = false;
    if(!ready && TrainingActive() && len > 1 && bytes[1] == 0 && bytes[0] >= MSG_SELECT_BATTLECMD && bytes[0] <= MSG_SELECT_UNSELECT_CARD) {
        std::ofstream marker(TrainingPath("ready.json"));
        marker << "{\"ready\":true}";
        ready = true;
    }
    if(TrainingOpening() && len && bytes[0] == MSG_SELECT_IDLECMD) {
        opening = false;
        std::lock_guard<std::mutex> lock(mainGame->gMutex);
        mainGame->dField.RefreshAllCards();
        mainGame->showcard = 0;
    }
    // The pinned core's simple AI handles legal chain/target choices. Supply its idle turn policy.
    if(TrainingActive() && TrainingOpponentAI() && len > 1 && bytes[1] == 1) {
        const auto f = reinterpret_cast<duel*>(engine)->game_field;
        int32_t answer = -1;
        if(bytes[0] == MSG_SELECT_IDLECMD) {
            if(!f->core.summonable_cards.empty()) {
                size_t choice = 0;
                for(size_t i = 0; i < f->core.summonable_cards.size(); ++i)
                    if(f->core.summonable_cards[i]->data.code == 1184620) { choice = i; break; }
                answer = static_cast<int32_t>(choice << 16);
            } else if(f->core.to_ep) answer = 7;
        } else if(bytes[0] == MSG_SELECT_BATTLECMD && f->core.to_ep) answer = 3;
        if(answer >= 0) {
            TrainingResponse(reinterpret_cast<unsigned char*>(&answer), sizeof answer, "opponent_ai", bytes[0]);
            set_responsei(engine, answer);
            return true;
        }
    }
    // Disabled AI preserves the existing empty, optional-window-passing opponent.
    if(TrainingActive() && !TrainingOpponentAI() && len > 1 && bytes[1] == 1) {
        int32_t answer = 0;
        bool pass = false;
        if(bytes[0] == MSG_SELECT_IDLECMD && len >= 3 && bytes[len - 2]) { answer = 7; pass = true; }
        if(bytes[0] == MSG_SELECT_CHAIN && len > 4 && !bytes[4]) { answer = -1; pass = true; }
        if(bytes[0] == MSG_SELECT_EFFECTYN) { answer = 0; pass = true; }
        if(pass) {
            TrainingResponse(reinterpret_cast<unsigned char*>(&answer), sizeof answer, "wall_pass", bytes[0]);
            set_responsei(engine, answer);
            return true;
        }
    }
    if(TrainingActive() && bytes[0] == MSG_WIN) return true; // Finish with a report, without a win dialog.
    return DuelClient::ClientAnalyze(bytes, len);
}
bool TrainingStopping() { return stopping; }
void TrainingStop(bool isClosing) { if(TrainingActive()) { closing = isClosing; stopping = true; } }
void TrainingFinish(intptr_t engine, const char* reason) {
    TrainingCapture(engine, "final_state");
    TrainingWrite("\"kind\":\"end\",\"reason\":\"" + std::string(stopping ? (closing ? "client_closed" : "manual") : reason) + "\"");
    finished = true;
}
void TrainingBoot() {
    static bool booted = false;
    if(booted) return;
    booted = true;
    char id[64]{};
    if(!GetEnvironmentVariableA("YGO_TRAIN_SESSION", id, sizeof id)) return;
    std::string candidate(id);
    if(candidate.size() != 36 || candidate.find_first_not_of("0123456789abcdef-") != std::string::npos) return;
    session = candidate;
    if(TrainingEmbedded()) {
        auto hwnd = mainGame->driver->getExposedVideoData().OpenGLWin32.HWnd;
        std::ofstream windowInfo(TrainingPath("native-window.json"));
        windowInfo << "{\"hwnd\":\"" << reinterpret_cast<uintptr_t>(hwnd) << "\",\"pid\":" << GetCurrentProcessId() << '}';
    }
    // A journal is exclusive to one new native process; never append to an old session.
    if(GetFileAttributesA(TrainingPath("native.jsonl").c_str()) != INVALID_FILE_ATTRIBUTES) { session.clear(); mainGame->device->closeDevice(); return; }
    journal.open(TrainingPath("native.jsonl"), std::ios::binary);
    if(!journal) { session.clear(); mainGame->device->closeDevice(); return; }
    if(TrainingBranchActive()) {
        std::ifstream inherited(TrainingPath("inherit.jsonl"), std::ios::binary);
        std::string line;
        while(std::getline(inherited, line)) { journal << line << '\n'; ++sequence; }
        journal.flush();
    }
    TrainingWrite("\"kind\":\"begin\",\"source\":\"ygopro-core/8ff3583\",\"ai\":" + std::string(TrainingOpponentAI() ? "true" : "false") + ",\"rule\":5,\"test_control\":" + std::string(TrainingTestControlled() ? "true" : "false"));
    mainGame->wMainMenu->setVisible(false);
    if(TrainingEmbedded()) {
        mainGame->wInfos->setActiveTab(0);
        mainGame->wInfos->setTabHeight(0);
    }
    mainGame->exit_on_return = true;
    SingleMode::StartPlay();
}
void TrainingPoll() {
    TrainingBoot();
    if(TrainingActive()) TrainingTestInput();
    if(TrainingEmbedded()) {
        mainGame->btnChainIgnore->setVisible(false);
        mainGame->btnChainAlways->setVisible(false);
        mainGame->btnChainWhenAvail->setVisible(false);
        mainGame->btnShuffle->setVisible(false);
        mainGame->btnLeaveGame->setVisible(false);
    }
    if(!TrainingActive() || finished || stopping) return;
    if(GetFileAttributesA(TrainingPath("stop.request").c_str()) != INVALID_FILE_ATTRIBUTES && mainGame->dInfo.isSingleMode) {
        mainGame->singleSignal.SetNoWait(true);
        SingleMode::StopPlay(false);
    }
}
}
