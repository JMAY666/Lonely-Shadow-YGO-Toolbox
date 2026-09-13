// Local recorder for the pinned YGOPro core. No rule decisions are inferred from text.
#include "training_support.h"
#include "game.h"
#include "single_mode.h"
#include "duelclient.h"
#include "data_manager.h"
#include "../ocgcore/duel.h"
#include "../ocgcore/field.h"
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

namespace ygo {
static std::string session;
static std::mutex logMutex;
static uint64_t sequence = 0;
static std::atomic<bool> stopping{false}, closing{false}, finished{false};
static std::ofstream journal;
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
static std::string describeEffect(effect* e) {
    if(!e) return "null";
    const auto handler = e->get_handler();
    std::ostringstream out;
    out << "{\"effect_id\":" << e->id << ",\"effect_handle\":" << e->ref_handle << ",\"description\":" << e->description
        << ",\"handler_instance\":" << (handler ? std::to_string(handler->cardid) : "null")
        << ",\"handler_code\":" << (handler ? std::to_string(handler->data.code) : "null") << '}';
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
void TrainingCapture(intptr_t engine, const char* kind, const unsigned char* bytes, size_t len) {
    if(!TrainingActive() || !engine) return;
    const auto d = reinterpret_cast<duel*>(engine);
    const auto f = d->game_field;
    std::ostringstream out;
    out << "\"kind\":\"" << kind << "\",\"raw\":\"" << hex(bytes, len) << "\",\"state\":{\"turn\":" << f->infos.turn_id
        << ",\"turn_player\":" << unsigned(f->infos.turn_player) << ",\"phase\":" << f->infos.phase
        << ",\"lp\":[" << f->player[0].lp << ',' << f->player[1].lp << "],\"cards\":[";
    std::vector<card*> cards(d->cards.begin(), d->cards.end());
    std::sort(cards.begin(), cards.end(), [](card* a, card* b){ return a->cardid < b->cardid; });
    bool first = true;
    for(const auto c : cards) {
        if(!c->data.code || (!c->current.location && !c->overlay_target)) continue;
        if(!first) out << ',';
        first = false;
        out << "{\"instance_id\":" << c->cardid << ",\"code\":" << c->data.code << ",\"name\":" << quote(dataManager.GetName(c->data.code))
            << ",\"owner\":" << unsigned(c->owner) << ",\"controller\":" << unsigned(c->overlay_target ? c->overlay_target->current.controler : c->current.controler)
            << ",\"location\":" << unsigned(c->overlay_target ? LOCATION_OVERLAY : c->current.location)
            << ",\"sequence\":" << unsigned(c->current.sequence) << ",\"position\":" << unsigned(c->current.position)
            << ",\"overlay_target\":" << (c->overlay_target ? std::to_string(c->overlay_target->cardid) : "null")
            << ",\"reason\":" << c->current.reason
            << ",\"reason_effect\":" << describeEffect(c->current.reason_effect) << '}';
    }
    out << "],\"chain_depth\":" << f->core.current_chain.size() << ",\"chains\":[";
    bool firstChain = true;
    for(const auto& chain : f->core.current_chain) {
        if(!firstChain) out << ',';
        firstChain = false;
        out << "{\"link\":" << unsigned(chain.chain_count) << ",\"effect\":" << describeEffect(chain.triggering_effect) << '}';
    }
    out << "]}";
    TrainingWrite(out.str());
}
void TrainingResponse(const unsigned char* bytes, size_t len, const char* actor) {
    TrainingWrite("\"kind\":\"response\",\"actor\":\"" + std::string(actor) + "\",\"prompt\":" + std::to_string(mainGame->dInfo.curMsg) + ",\"raw\":\"" + hex(bytes, len) + "\"");
}
bool TrainingAnalyze(intptr_t engine, unsigned char* bytes, size_t len) {
    // Empty opponent only passes optional windows and ends its turn. No AI is loaded.
    if(TrainingActive() && len > 1 && bytes[1] == 1) {
        int32_t answer = 0;
        bool pass = false;
        if(bytes[0] == MSG_SELECT_IDLECMD && len >= 3 && bytes[len - 2]) { answer = 7; pass = true; }
        if(bytes[0] == MSG_SELECT_CHAIN && len > 4 && !bytes[4]) { answer = -1; pass = true; }
        if(bytes[0] == MSG_SELECT_EFFECTYN) { answer = 0; pass = true; }
        if(pass) {
            TrainingResponse(reinterpret_cast<unsigned char*>(&answer), sizeof answer, "wall_pass");
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
    // A journal is exclusive to one new native process; never append to an old session.
    if(GetFileAttributesA(TrainingPath("native.jsonl").c_str()) != INVALID_FILE_ATTRIBUTES) { session.clear(); mainGame->device->closeDevice(); return; }
    journal.open(TrainingPath("native.jsonl"), std::ios::binary);
    if(!journal) { session.clear(); mainGame->device->closeDevice(); return; }
    TrainingWrite("\"kind\":\"begin\",\"source\":\"ygopro-core/8ff3583\",\"ai\":false,\"rule\":5");
    mainGame->wMainMenu->setVisible(false);
    mainGame->exit_on_return = true;
    SingleMode::StartPlay();
}
void TrainingPoll() {
    TrainingBoot();
    if(!TrainingActive() || finished || stopping) return;
    if(GetFileAttributesA(TrainingPath("stop.request").c_str()) != INVALID_FILE_ATTRIBUTES && mainGame->dInfo.isSingleMode) {
        mainGame->singleSignal.SetNoWait(true);
        SingleMode::StopPlay(false);
    }
}
}
