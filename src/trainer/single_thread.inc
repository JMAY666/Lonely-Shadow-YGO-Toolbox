    if(!TrainingActive()) {
        mainGame->env->addMessageBox(L"训练", L"请从 Start-Trainer.ps1 打开的工具箱选择构筑并开始训练。");
        return;
    }
    is_closing = false;
    is_continuing = true;
    std::ifstream input(TrainingPath("deck.ydk"), std::ios::binary);
    std::stringstream text;
    text << input.rdbuf();
    std::istringstream deckStream(text.str());
    Deck deck;
    if(!input || DeckManager::LoadDeckFromStream(deck, deckStream) || deck.main.empty()) {
        TrainingFinish(0, "deck_load_failed");
        mainGame->device->closeDevice();
        return;
    }
    std::random_device rd;
    uint32_t seeds[SEED_COUNT];
    for(auto& seed : seeds) seed = rd();
    if(TrainingTestControlled())
        std::fill(std::begin(seeds), std::end(seeds), 42u); // Reproducible internal acceptance only.
    std::seed_seq shuffleSeed(seeds, seeds + SEED_COUNT);
    std::mt19937 shuffle(shuffleSeed);
    std::shuffle(deck.main.begin(), deck.main.end(), shuffle);
    std::vector<uint32_t> drawOrder;
    std::vector<uint32_t> opponentOrder, opponentExtra;
    uint32_t handCount = 5, opponentHand = 5, responses = 1, firstPlayer = 0;
    int32_t playerLP = 8000, opponentLP = 8000;
    bool configuredOpponent = false;
    std::ifstream openingConfig(TrainingPath("opening.cfg"));
    if(openingConfig) {
        uint32_t version, ai, seed, count, code;
        if(!(openingConfig >> version >> ai >> seed >> count) || (version != 1 && version != 2) || ai > 1 || count != deck.main.size()) {
            TrainingFinish(0, "opening_invalid"); mainGame->device->closeDevice(); return;
        }
        std::multiset<uint32_t> expected, actual;
        for(auto c : deck.main) expected.insert(c->code);
        for(uint32_t i = 0; i < count && openingConfig >> code; ++i) { drawOrder.push_back(code); actual.insert(code); }
        if(expected != actual) { TrainingFinish(0, "opening_invalid"); mainGame->device->closeDevice(); return; }
        if(version == 2) {
            uint32_t opponentCount, extraCount;
            bool valid = bool(openingConfig >> handCount >> responses >> firstPlayer >> playerLP >> opponentLP >> opponentHand >> opponentCount);
            valid = valid && handCount > 0 && handCount <= count && responses <= 1 && firstPlayer <= 1
                && playerLP > 0 && opponentLP > 0 && opponentCount <= 60 && opponentHand <= opponentCount
                && (!ai || (opponentCount >= 40 && opponentHand > 0));
            if(valid) {
                for(uint32_t i = 0; i < opponentCount && openingConfig >> code; ++i) opponentOrder.push_back(code);
                valid = bool(openingConfig >> extraCount) && extraCount <= 15 && opponentOrder.size() == opponentCount;
                if(valid) for(uint32_t i = 0; i < extraCount && openingConfig >> code; ++i) opponentExtra.push_back(code);
                valid = valid && opponentExtra.size() == extraCount;
            }
            if(valid && ai) {
                std::ifstream opponentInput(TrainingPath("opponent.ydk"));
                std::stringstream opponentText;
                opponentText << opponentInput.rdbuf();
                std::istringstream opponentStream(opponentText.str());
                Deck opponentDeck;
                valid = bool(opponentInput) && !DeckManager::LoadDeckFromStream(opponentDeck, opponentStream);
                std::multiset<uint32_t> mainCodes, extraCodes;
                for(auto c : opponentDeck.main) mainCodes.insert(c->code);
                for(auto c : opponentDeck.extra) extraCodes.insert(c->code);
                valid = valid && mainCodes == std::multiset<uint32_t>(opponentOrder.begin(), opponentOrder.end())
                    && extraCodes == std::multiset<uint32_t>(opponentExtra.begin(), opponentExtra.end());
            }
            if(!valid) { TrainingFinish(0, "opening_invalid"); mainGame->device->closeDevice(); return; }
            configuredOpponent = true;
        }
        std::fill(std::begin(seeds), std::end(seeds), seed); // Random per expansion, reused only for its retries.
    }
    set_script_reader(DataManager::ScriptReaderEx);
    set_card_reader(DataManager::CardReader);
    set_message_handler(SingleMode::MessageHandler);
    const bool opponentAI = TrainingOpponentAI();
    // Capture the actual shuffled/configured opening once, including normal random runs.
    const auto factory = [&]() -> intptr_t {
        const auto created = create_duel_v2(seeds);
        set_player_info(created, 0, playerLP, handCount, 1);
        set_player_info(created, 1, opponentLP, opponentAI ? opponentHand : 0, opponentAI ? 1 : 0);
        auto field = reinterpret_cast<duel*>(created)->game_field;
        field->core.first_player = firstPlayer;
        field->core.simple_ai_responses = responses != 0;
        if(drawOrder.empty()) {
            for(auto c : deck.main) new_card(created, c->code, 0, 0, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
        } else {
            for(auto it = drawOrder.rbegin(); it != drawOrder.rend(); ++it)
                new_card(created, *it, 0, 0, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
        }
        for(auto c : deck.extra) new_card(created, c->code, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE);
        if(opponentAI && configuredOpponent) {
            for(auto it = opponentOrder.rbegin(); it != opponentOrder.rend(); ++it)
                new_card(created, *it, 1, 1, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
            for(auto code : opponentExtra) new_card(created, code, 1, 1, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE);
        } else if(opponentAI) {
            // basic-ash-v1: 3 Ash Blossom + 37 normal monsters; Ash + 4 normals in the initial hand.
            for(int i = 0; i < 2; ++i) new_card(created, 14558127, 1, 1, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
            for(int i = 0; i < 37; ++i) new_card(created, 1184620, 1, 1, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
            new_card(created, 14558127, 1, 1, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
        }
        return created;
    };
    pduel = factory();
    TrainingHistoryInit(factory, [&](const std::vector<unsigned char>& prompt) {
        {
            std::lock_guard<std::mutex> lock(mainGame->gMutex);
            mainGame->dField.HideMenu();
            for(auto window : {mainGame->wQuery, mainGame->wOptions, mainGame->wPosSelect, mainGame->wCardSelect, mainGame->wCardDisplay,
                    mainGame->wANNumber, mainGame->wANCard, mainGame->wANAttribute, mainGame->wANRace})
                window->setVisible(false);
            mainGame->btnCancelOrFinish->setVisible(false);
            mainGame->dField.selectable_cards.clear();
            mainGame->dField.selected_cards.clear();
            mainGame->dField.selectsum_cards.clear();
            mainGame->dField.selectsum_all.clear();
            mainGame->dField.selectable_field = mainGame->dField.selected_field = 0;
            mainGame->ClearCardInfo();
            mainGame->dInfo.turn = reinterpret_cast<duel*>(pduel)->game_field->infos.turn_id;
        }
        std::vector<unsigned char> reload(SIZE_QUERY_BUFFER);
        auto size = TrainingQueryFieldInfo(pduel, reload.data());
        DuelClient::ClientAnalyze(reload.data(), size);
        {
            std::lock_guard<std::mutex> lock(mainGame->gMutex);
            SinglePlayReload();
            TrainingRestorePresentation();
            mainGame->dField.RefreshAllCards();
        }
        auto phase = reinterpret_cast<duel*>(pduel)->game_field->infos.phase;
        unsigned char phaseMessage[]{MSG_NEW_PHASE, static_cast<unsigned char>(phase), static_cast<unsigned char>(phase >> 8)};
        mainGame->dInfo.curMsg = MSG_NEW_PHASE;
        DuelClient::ClientAnalyze(phaseMessage, sizeof phaseMessage);
        mainGame->dInfo.curMsg = prompt[0];
        if(TrainingPromptPlayer(prompt.data(), prompt.size()) != 1)
            DuelClient::ClientAnalyze(const_cast<unsigned char*>(prompt.data()), prompt.size());
    });
    mainGame->gMutex.lock();
    mainGame->dInfo.Clear();
    mainGame->dInfo.lp[0] = mainGame->dInfo.start_lp = playerLP;
    mainGame->dInfo.lp[1] = opponentLP;
    myswprintf(mainGame->dInfo.strLP[0], L"%d", playerLP);
    myswprintf(mainGame->dInfo.strLP[1], L"%d", opponentLP);
    BufferIO::CopyWideString(L"展开场地", mainGame->dInfo.hostname);
    BufferIO::CopyWideString(opponentAI ? L"对手 AI" : L"", mainGame->dInfo.clientname);
    mainGame->dInfo.player_type = 0;
    mainGame->dInfo.isFirst = true;
    mainGame->dInfo.isStarted = true;
    mainGame->dInfo.isSingleMode = true;
    mainGame->dField.Clear();
    mainGame->ClearCardInfo();
    mainGame->wCardImg->setVisible(true);
    mainGame->wInfos->setVisible(true);
    mainGame->wPhase->setVisible(true);
    mainGame->btnLeaveGame->setText(L"展开结束");
    mainGame->btnLeaveGame->setVisible(!TrainingEmbedded());
    mainGame->device->setEventReceiver(&mainGame->dField);
    mainGame->gMutex.unlock();
    std::vector<unsigned char> buffer(SIZE_MESSAGE_BUFFER);
    int len = 0;
    std::vector<unsigned char> resumed;
    if(TrainingResumeBranch(pduel, resumed)) {
        if(!TrainingStopping()) TrainingWait(pduel, resumed.data(), resumed.size());
    } else {
        TrainingCapture(pduel, "loaded");
        len = TrainingQueryFieldInfo(pduel, buffer.data());
        TrainingCapture(pduel, "batch", buffer.data(), len);
        SinglePlayAnalyze(buffer.data(), len);
        // Surface both seats' legal prompts before the adapter delegates to the
        // same pinned simple-AI policies. This keeps response windows restorable.
        TrainingStartDuel(pduel, MASTER_RULE_2020 << 16);
    }
    while(is_continuing && !TrainingStopping()) {
        const auto result = TrainingProcess(pduel, buffer);
        len = result & PROCESSOR_BUFFER_LEN;
        if(len) {
            if(size_t(len) > buffer.size()) buffer.resize(len);
            // Persist the entire actual engine batch BEFORE UI animations or choice dialogs.
            TrainingCapture(pduel, "batch", buffer.data(), len);
            is_continuing = SinglePlayAnalyze(buffer.data(), len);
        }
        if(result & PROCESSOR_END) break;
    }
    TrainingFinish(pduel, "engine_ended");
    end_duel(pduel);
    pduel = 0;
    if(!is_closing) {
        mainGame->gMutex.lock();
        mainGame->dInfo.isStarted = false;
        mainGame->dInfo.isInDuel = false;
        mainGame->dInfo.isFinished = true;
        mainGame->dInfo.isSingleMode = false;
        mainGame->gMutex.unlock();
        mainGame->device->closeDevice();
    }
