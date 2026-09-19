// Test-only dynamic observation. Its engine calls are recorded and replayed.
static bool learningEnabled() {
    return TrainingLearningControlled();
}
static std::string learningGuard(intptr_t engine) {
    const auto f = reinterpret_cast<duel*>(engine)->game_field;
    std::ostringstream out;
    out << TrainingComparableState(TrainingState(engine)) << ':' << f->core.summon_count[0]
        << ':' << f->core.summon_count[1] << ':' << f->core.extra_summon[0] << ':' << f->core.extra_summon[1];
    for(int player = 0; player < 3; ++player) {
        std::map<uint32_t, int32_t> counts(f->core.effect_count_code[player].begin(), f->core.effect_count_code[player].end());
        for(const auto& entry : counts) out << ':' << player << ',' << entry.first << ',' << entry.second;
    }
    return out.str();
}
static std::string learningSnapshot(intptr_t engine) {
    const auto d = reinterpret_cast<duel*>(engine);
    const auto before = learningGuard(engine);
    std::vector<card*> cards(d->cards.begin(), d->cards.end());
    std::sort(cards.begin(), cards.end(), [](card* a, card* b){ return a->cardid < b->cardid; });
    std::ostringstream out;
    out << "{\"schema\":2,\"available\":true,\"source\":\"recorded_core_query\",\"cards\":[";
    bool first = true;
    for(const auto c : cards) {
        if(!c->data.code || (!c->current.location && !c->overlay_target)) continue;
        if(!first) out << ',';
        first = false;
        out << "{\"instance_id\":" << c->cardid << ",\"type\":" << c->get_type()
            << ",\"attribute\":" << c->get_attribute() << ",\"race\":" << c->get_race()
            << ",\"level\":" << c->get_level() << ",\"rank\":" << c->get_rank()
            << ",\"link\":" << c->get_link() << ",\"link_marker\":" << c->get_link_marker()
            << ",\"attack\":" << c->get_attack() << ",\"defense\":" << c->get_defense()
            << ",\"base_attack\":" << c->get_base_attack() << ",\"base_defense\":" << c->get_base_defense() << '}';
    }
    out << "]}";
    if(before != learningGuard(engine)) throw std::runtime_error("learning_query_changed_state");
    return out.str();
}
