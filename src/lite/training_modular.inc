// Included in training_history.cpp: all engine work stays on the duel thread.
// A probe reconstructs a disposable core. It never replaces the live engine.
static bool modularDecisionWaiting(intptr_t engine) {
    const auto f = reinterpret_cast<duel*>(engine)->game_field;
    if(f->core.units.empty() || f->core.units.front().step == 0) return false;
    switch(f->core.units.front().type) {
    case PROCESSOR_SELECT_IDLECMD: case PROCESSOR_SELECT_BATTLECMD:
    case PROCESSOR_SELECT_EFFECTYN: case PROCESSOR_SELECT_YESNO: case PROCESSOR_SELECT_OPTION:
    case PROCESSOR_SELECT_CARD: case PROCESSOR_SELECT_UNSELECT_CARD: case PROCESSOR_SELECT_CHAIN:
    case PROCESSOR_SELECT_PLACE: case PROCESSOR_SELECT_DISFIELD: case PROCESSOR_SELECT_POSITION:
    case PROCESSOR_SELECT_TRIBUTE_P: case PROCESSOR_SELECT_COUNTER: case PROCESSOR_SELECT_SUM:
    case PROCESSOR_SORT_CARD: case PROCESSOR_ANNOUNCE_RACE: case PROCESSOR_ANNOUNCE_ATTRIB:
    case PROCESSOR_ANNOUNCE_CARD: case PROCESSOR_ANNOUNCE_NUMBER: case PROCESSOR_ROCK_PAPER_SCISSORS:
        return true;
    default: return false;
    }
}
struct ModularProbeCache {
    intptr_t engine = 0;
    uint64_t version = 0;
    unsigned scenario = 0;
    std::vector<std::string> path, batches;
    std::vector<unsigned char> boundary;
    bool ended = false;
};
static ModularProbeCache modularCache;
void TrainingModularClose() {
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    if(modularCache.engine) end_duel(modularCache.engine);
    modularCache = {};
}
static std::string modularState(intptr_t engine) {
    auto result = TrainingState(engine);
    result.pop_back();
    const auto f = reinterpret_cast<duel*>(engine)->game_field;
    std::ostringstream out;
    out << result << ",\"normal_summons_used\":[" << f->core.summon_count[0] << ',' << f->core.summon_count[1]
        << "],\"effect_usage\":[";
    bool first = true;
    for(int p = 0; p < 3; ++p) {
        std::map<uint32_t, int32_t> ordered(f->core.effect_count_code[p].begin(), f->core.effect_count_code[p].end());
        for(const auto& item : ordered) {
            if(!first) out << ',';
            first = false;
            out << "{\"player\":" << p << ",\"key\":" << item.first << ",\"used\":" << item.second << '}';
        }
    }
    out << "],\"restrictions\":\"engine_replay\"}";
    return out.str();
}
static void modularPublish(intptr_t engine) {
    atomicFile("modular-state.json", "{\"version\":" + std::to_string(promptVersion)
        + ",\"revision\":" + std::to_string(revision) + ",\"node\":" + std::to_string(cursor)
        + ",\"player\":" + std::to_string(pendingPlayer) + ",\"answered\":" + (pendingAnswered ? "true" : "false")
        + ",\"raw\":\"" + encode(pendingPrompt) + "\",\"effects\":" + TrainingDecisionEffects(engine) + ",\"state\":" + modularState(engine) + '}');
}
static bool modularTick(intptr_t engine) {
    std::ifstream request(TrainingPath("modular.request"));
    if(!request) return false;
    std::string command, token, encoded;
    uint64_t expected;
    unsigned scenario, count;
    if(!(request >> command >> expected >> token >> scenario >> count)) return false;
    if(token.size() != 32 || token.find_first_not_of("0123456789abcdef") != std::string::npos) return false;
    std::vector<std::string> path;
    for(unsigned i = 0; i < count && i <= 256 && request >> encoded; ++i) path.push_back(encoded);
    request.close(); DeleteFileA(TrainingPath("modular.request").c_str());
    if(TrainingTestControlled()) {
        std::ostringstream trace;
        trace << command << ' ' << expected << ' ' << scenario << '\n';
        for(const auto& step : path) trace << step << '\n';
        atomicFile("modular-probe.txt", trace.str());
    }
    std::lock_guard<std::recursive_mutex> lock(historyMutex);
    intptr_t candidate = 0;
    bool submitted = false;
    try {
        if(count > 256 || path.size() != count || scenario > 2) throw std::runtime_error("invalid_request");
        if(expected != promptVersion || pendingAnswered || restoring) throw std::runtime_error("stale_state");
        if(command == "answer") {
            if(count != 1 || scenario || pendingPlayer != 0) throw std::runtime_error("invalid_request");
            // The server commits a one-use lease containing source/preference versions.
            // Removing it cancels a queued action before it enters the core.
            std::ifstream lease(TrainingPath("modular-lease.txt"));
            std::string authorized; lease >> authorized; lease.close();
            if(authorized != token) throw std::runtime_error("stale_lease");
            auto bytes = decode(path[0]);
            if(bytes.empty() || bytes.size() > 64) throw std::runtime_error("invalid_response");
            const auto size = bytes.size(); bytes.resize(64);
            DeleteFileA(TrainingPath("modular-lease.txt").c_str());
            TrainingResponse(bytes.data(), size, "modular_ai", pendingPrompt[0]);
            set_responseb(engine, bytes.data()); pendingAnswered = true; submitted = true;
            {
                std::lock_guard<std::mutex> viewLock(mainGame->gMutex);
                mainGame->dField.HideMenu();
                for(auto window : {mainGame->wQuery, mainGame->wOptions, mainGame->wPosSelect, mainGame->wCardSelect,
                        mainGame->wANNumber, mainGame->wANCard, mainGame->wANAttribute, mainGame->wANRace})
                    window->setVisible(false);
                mainGame->btnCancelOrFinish->setVisible(false);
            }
            modularPublish(engine);
            atomicFile("modular-result.json", "{\"token\":\"" + token + "\",\"status\":\"submitted\"}");
            return true;
        }
        if(command != "probe") throw std::runtime_error("invalid_request");
        restoring = true; replayError = false;
        std::vector<unsigned char> buffer(SIZE_QUERY_BUFFER + SIZE_MESSAGE_BUFFER);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
        const bool cached = modularCache.engine && modularCache.version == expected && modularCache.scenario == scenario
            && path.size() >= modularCache.path.size() && std::equal(modularCache.path.begin(), modularCache.path.end(), path.begin());
        const size_t completed = cached ? modularCache.path.size() : 0;
        std::vector<std::string> batches = cached ? modularCache.batches : std::vector<std::string>{};
        std::vector<unsigned char> boundaryBytes = cached ? modularCache.boundary : pendingPrompt;
        bool ended = cached && modularCache.ended;
        if(cached) { candidate = modularCache.engine; modularCache.engine = 0; }
        else {
        if(modularCache.engine) { end_duel(modularCache.engine); modularCache.engine = 0; }
        candidate = makeDuel();
        if(!candidate) throw std::runtime_error("create_failed");
        const auto replay = [&] (const CoreCall& source) {
            if(TrainingStopping() || std::chrono::steady_clock::now() > deadline) throw std::runtime_error("search_limit");
            auto call = source;
            if(buffer.size() < call.bytes.size()) buffer.resize(call.bytes.size());
            const auto result = execute(candidate, call, buffer.data(), &buffer);
            if(result != call.result || replayError) throw std::runtime_error("replay_mismatch");
            if(call.kind != CoreCall::Response && call.kind != CoreCall::Integer && call.kind != CoreCall::Scene
                && !std::equal(call.bytes.begin(), call.bytes.end(), buffer.begin())) throw std::runtime_error("replay_mismatch");
        };
        size_t length = calls.size();
        if(resumeFromNode) {
            const auto node = std::find_if(checkpoints.begin(), checkpoints.end(), [](const Checkpoint& n){return n.id == cursor;});
            if(node == checkpoints.end()) throw std::runtime_error("node_unavailable");
            length = node->calls;
        }
        for(size_t i = 0; i < length; ++i) replay(calls[i]);
        if(resumeFromNode) for(const auto& call : resumeCalls) replay(call);
        if(TrainingComparableState(TrainingState(candidate)) != TrainingComparableState(TrainingState(engine))) {
            if(TrainingTestControlled()) atomicFile("modular-state-mismatch.json", "{\"live\":" + TrainingState(engine) + ",\"probe\":" + TrainingState(candidate) + '}');
            throw std::runtime_error("state_mismatch");
        }
        if(scenario) {
            // Explicit hypothetical scenario, only in this disposable engine:
            // opponent has one Ash Blossom and no other hidden hand resources.
            const auto f = reinterpret_cast<duel*>(candidate)->game_field;
            f->core.simple_ai_responses = true;
            const auto hand = f->player[1].list_hand;
            for(auto c : hand) f->remove_card(c);
            new_card(candidate, scenario == 1 ? 14558127 : 55144522, 1, 1, LOCATION_HAND, 0, POS_FACEDOWN_DEFENSE);
            if(scenario == 2) {
                const auto deck = f->player[1].list_main;
                for(auto c : deck) f->remove_card(c);
                for(int i = 0; i < 3; ++i) new_card(candidate, 1184620, 1, 1, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
            }
        }
        }
        auto& probeCore = reinterpret_cast<duel*>(candidate)->game_field->core;
        probeCore.modular_probe = true;
        if(!cached) probeCore.modular_private_cards.clear();
        for(size_t step = completed; step < path.size(); ++step) {
            probeCore.modular_private_cards.clear();
            const auto& guarded = path[step];
            if(ended) throw std::runtime_error("past_end");
            const auto separator = guarded.find(':');
            if(separator == std::string::npos) throw std::runtime_error("missing_prompt_guard");
            const auto guard = decode(guarded.substr(0, separator));
            const auto answer = guarded.substr(separator + 1);
            if(guard.empty() || boundaryBytes.size() < guard.size() || !std::equal(guard.rbegin(), guard.rend(), boundaryBytes.rbegin()))
                throw std::runtime_error("prompt_changed");
            if(!modularDecisionWaiting(candidate)) throw std::runtime_error("not_a_decision");
            if(answer == "ai") {
                CoreCall call{CoreCall::Auto};
                if(execute(candidate, call, buffer.data(), &buffer) != 64) throw std::runtime_error("ai_unavailable");
            } else {
                auto bytes = decode(answer);
                if(bytes.empty() || bytes.size() > 64) throw std::runtime_error("invalid_response");
                bytes.resize(64); set_responseb(candidate, bytes.data());
            }
            batches.clear();
            bool waiting = false;
            for(unsigned ticks = 0; ticks < 10000; ++ticks) {
                if(TrainingStopping() || std::chrono::steady_clock::now() > deadline) throw std::runtime_error("search_limit");
                CoreCall call{CoreCall::Process};
                const auto result = execute(candidate, call, buffer.data(), &buffer);
                const auto n = result & PROCESSOR_BUFFER_LEN;
                if(replayError) throw std::runtime_error("script_error");
                if(n) {
                    boundaryBytes.assign(buffer.begin(), buffer.begin() + n);
                    batches.push_back(encode(boundaryBytes));
                }
                if(n && buffer[0] == MSG_RETRY) throw std::runtime_error("illegal_response");
                ended = (result & PROCESSOR_END) != 0;
                // PROCESSOR_WAIT is also used for reveal/animation barriers. It
                // is not a legal decision window and must not consume a response.
                waiting = (result & PROCESSOR_WAITING) != 0 && modularDecisionWaiting(candidate);
                if(ended || waiting) break;
            }
            if(!ended && !waiting) throw std::runtime_error("search_limit");
        }
        std::ostringstream out;
        out << "{\"token\":\"" << token << "\",\"status\":\"ok\",\"version\":" << expected
            << ",\"ended\":" << (ended ? "true" : "false") << ",\"effects\":" << TrainingDecisionEffects(candidate)
            << ",\"state\":" << modularState(candidate) << ",\"batches\":[";
        for(size_t i = 0; i < batches.size(); ++i) { if(i) out << ','; out << '"' << batches[i] << '"'; }
        out << "],\"private_cards\":[";
        bool firstPrivate = true;
        for(const auto id : probeCore.modular_private_cards) { if(!firstPrivate) out << ','; firstPrivate = false; out << id; }
        out << "]}";
        modularCache = {candidate, expected, scenario, path, batches, boundaryBytes, ended};
        candidate = 0; restoring = false;
        atomicFile("modular-result.json", out.str());
    } catch(const std::exception& error) {
        if(candidate) end_duel(candidate);
        restoring = false;
        try { atomicFile("modular-result.json", "{\"token\":\"" + token + "\",\"status\":\"error\",\"error\":\"" + error.what() + "\"}"); } catch(...) {}
    }
    return submitted;
}
