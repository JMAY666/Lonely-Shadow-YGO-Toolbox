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
    std::seed_seq shuffleSeed(seeds, seeds + SEED_COUNT);
    std::mt19937 shuffle(shuffleSeed);
    std::shuffle(deck.main.begin(), deck.main.end(), shuffle);
    set_script_reader(DataManager::ScriptReaderEx);
    set_card_reader(DataManager::CardReader);
    set_message_handler(SingleMode::MessageHandler);
    pduel = create_duel_v2(seeds);
    set_player_info(pduel, 0, 8000, 5, 1);
    set_player_info(pduel, 1, 8000, 0, 0);
    for(auto c : deck.main) new_card(pduel, c->code, 0, 0, LOCATION_DECK, 0, POS_FACEDOWN_DEFENSE);
    for(auto c : deck.extra) new_card(pduel, c->code, 0, 0, LOCATION_EXTRA, 0, POS_FACEDOWN_DEFENSE);
    TrainingCapture(pduel, "loaded");
    mainGame->gMutex.lock();
    mainGame->dInfo.Clear();
    mainGame->dInfo.lp[0] = mainGame->dInfo.lp[1] = mainGame->dInfo.start_lp = 8000;
    for(auto& lp : mainGame->dInfo.strLP) myswprintf(lp, L"8000");
    BufferIO::CopyWideString(L"手动训练", mainGame->dInfo.hostname);
    BufferIO::CopyWideString(L"空场占位（自动跳过）", mainGame->dInfo.clientname);
    mainGame->dInfo.player_type = 0;
    mainGame->dInfo.isFirst = true;
    mainGame->dInfo.isStarted = true;
    mainGame->dInfo.isSingleMode = true;
    mainGame->dField.Clear();
    mainGame->ClearCardInfo();
    mainGame->wCardImg->setVisible(true);
    mainGame->wInfos->setVisible(true);
    mainGame->wPhase->setVisible(true);
    mainGame->btnLeaveGame->setText(L"结束训练");
    mainGame->btnLeaveGame->setVisible(true);
    mainGame->device->setEventReceiver(&mainGame->dField);
    mainGame->gMutex.unlock();
    std::vector<unsigned char> buffer(SIZE_MESSAGE_BUFFER);
    auto len = query_field_info(pduel, buffer.data());
    TrainingCapture(pduel, "batch", buffer.data(), len);
    SinglePlayAnalyze(buffer.data(), len);
    start_duel(pduel, MASTER_RULE_2020 << 16); // No DUEL_SIMPLE_AI and no network connection.
    while(is_continuing && !TrainingStopping()) {
        const auto result = process(pduel);
        len = result & PROCESSOR_BUFFER_LEN;
        if(len) {
            if(size_t(len) > buffer.size()) buffer.resize(len);
            get_message(pduel, buffer.data());
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
