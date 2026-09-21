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
    std::string observations;
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
        << "],\"normal_summon_limit\":[" << f->get_summon_count_limit(0) << ',' << f->get_summon_count_limit(1)
        << "],\"extra_normal_summon_used\":[" << (f->core.extra_summon[0] ? "true" : "false") << ','
        << (f->core.extra_summon[1] ? "true" : "false") << "],\"effect_usage\":[";
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
    std::string learning;
    if(learningEnabled() && !pendingAnswered) {
        try {
            std::vector<unsigned char> buffer(65536);
            const auto began = std::chrono::steady_clock::now();
            const int length = record(engine, {CoreCall::LearningSnapshot}, buffer.data(), &buffer);
            const std::string value(buffer.begin(), buffer.begin() + length);
            const auto micros = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - began).count();
            learning = ",\"learning\":" + value + ",\"learning_query_us\":" + std::to_string(micros);
            TrainingWrite("\"kind\":\"learning_snapshot\",\"node\":" + std::to_string(cursor)
                + ",\"version\":" + std::to_string(promptVersion) + ",\"value\":" + value);
        } catch(const std::exception& error) {
            learning = ",\"learning\":{\"schema\":2,\"available\":false,\"error\":\"" + std::string(error.what()) + "\"}";
        }
    }
    atomicFile("modular-state.json", "{\"version\":" + std::to_string(promptVersion)
        + ",\"revision\":" + std::to_string(revision) + ",\"node\":" + std::to_string(cursor)
        + ",\"player\":" + std::to_string(pendingPlayer) + ",\"answered\":" + (pendingAnswered ? "true" : "false")
        + ",\"raw\":\"" + encode(pendingPrompt) + "\",\"effects\":" + TrainingDecisionEffects(engine) + ",\"state\":" + modularState(engine) + learning + '}');
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
    struct Observation { unsigned index, kind; std::vector<unsigned> codes; };
    std::vector<Observation> observations;
    std::ostringstream observationKey;
    if(command == "forecast") {
        unsigned n = 0;
        if(!(request >> n) || n > 64) return false;
        for(unsigned i = 0; i < n; ++i) {
            Observation o{}; unsigned size = 0;
            if(!(request >> o.index >> o.kind >> size) || size == 0 || size > 60 || o.kind > 1 || o.index > 256) return false;
            observationKey << o.index << ':' << o.kind << ':';
            for(unsigned j = 0, code; j < size; ++j) {
                if(!(request >> code) || !code) return false;
                o.codes.push_back(code); observationKey << code << ',';
            }
            observations.push_back(o);
        }
    }
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
        if(command != "probe" && (command != "forecast" || !GetEnvironmentVariableA("YGO_TRAIN_PLANNING", nullptr, 0)))
            throw std::runtime_error("invalid_request");
        restoring = true; replayError = false;
        const auto profileStart = std::chrono::steady_clock::now();
        const auto elapsedMicros = [](const auto& start) {
            return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
        };
        std::vector<unsigned char> buffer(SIZE_QUERY_BUFFER + SIZE_MESSAGE_BUFFER);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
        const bool cached = modularCache.engine && modularCache.version == expected && modularCache.scenario == scenario
            && modularCache.observations == observationKey.str()
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
        const auto prefixMicros = elapsedMicros(profileStart);
        const auto branchStart = std::chrono::steady_clock::now();
        auto& probeCore = reinterpret_cast<duel*>(candidate)->game_field->core;
        probeCore.modular_probe = true;
        if(!cached) probeCore.modular_private_cards.clear();
        for(size_t step = completed; step < path.size(); ++step) {
            probeCore.modular_private_cards.clear();
            for(const auto& observation : observations) if(observation.index == step) {
                const auto f = reinterpret_cast<duel*>(candidate)->game_field;
                if(observation.kind == 0) {
                    // User-reported random outcomes only reorder existing deck
                    // instances in this disposable forecast. Effects still resolve
                    // in the original core, including triggers and summon limits.
                    auto& deck = f->player[0].list_main;
                    auto remaining = deck; std::vector<card*> top;
                    for(const auto code : observation.codes) {
                        auto found = std::find_if(remaining.begin(), remaining.end(), [code](card* c){return c->data.code == code;});
                        if(found == remaining.end()) throw std::runtime_error("reported_card_unavailable");
                        top.push_back(*found); remaining.erase(found);
                    }
                    remaining.insert(remaining.end(), top.rbegin(), top.rend()); deck = remaining;
                    for(size_t i = 0; i < deck.size(); ++i) deck[i]->current.sequence = static_cast<uint8_t>(i);
                } else {
                    f->core.simple_ai_responses = true;
                    for(const auto code : observation.codes) new_card(candidate, code, 1, 1, LOCATION_HAND, 0, POS_FACEDOWN_DEFENSE);
                }
            }
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
        const auto branchMicros = elapsedMicros(branchStart);
        std::ostringstream out;
        out << "{\"token\":\"" << token << "\",\"status\":\"ok\",\"version\":" << expected
            << ",\"ended\":" << (ended ? "true" : "false") << ",\"effects\":" << TrainingDecisionEffects(candidate)
            << ",\"state\":" << modularState(candidate) << ",\"batches\":[";
        for(size_t i = 0; i < batches.size(); ++i) { if(i) out << ','; out << '"' << batches[i] << '"'; }
        out << "],\"private_cards\":[";
        bool firstPrivate = true;
        for(const auto id : probeCore.modular_private_cards) { if(!firstPrivate) out << ','; firstPrivate = false; out << id; }
        out << "]}";
        if(learningEnabled()) {
            auto text = out.str(); text.pop_back();
            out.str(""); out.clear();
            const auto snapshotStart = std::chrono::steady_clock::now();
            const auto snapshot = learningSnapshot(candidate);
            const auto snapshotMicros = elapsedMicros(snapshotStart);
            out << text << ",\"learning\":" << snapshot
                << ",\"boundary_raw\":\"" << encode(boundaryBytes) << "\""
                << ",\"learning_profile\":{\"prefix_rebuild_us\":" << prefixMicros
                << ",\"branch_execute_us\":" << branchMicros
                << ",\"snapshot_us\":" << snapshotMicros
                << ",\"native_prepare_us\":" << elapsedMicros(profileStart)
                << ",\"cached_prefix\":" << (cached ? "true" : "false")
                << ",\"fast_animation\":" << (TrainingLearningFast() ? "true" : "false") << "}}";
        }
        modularCache = {candidate, expected, scenario, path, batches, boundaryBytes, ended, observationKey.str()};
        candidate = 0; restoring = false;
        atomicFile("modular-result.json", out.str());
    } catch(const std::exception& error) {
        if(candidate) end_duel(candidate);
        restoring = false;
        try { atomicFile("modular-result.json", "{\"token\":\"" + token + "\",\"status\":\"error\",\"error\":\"" + error.what() + "\"}"); } catch(...) {}
    }
    return submitted;
}
