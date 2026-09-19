#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include "training_history.h"

namespace ygo {
std::string TrainingDecisionEffects(intptr_t engine);
bool TrainingActive();
bool TrainingEmbedded();
bool TrainingOpening();
bool TrainingTestControlled();
bool TrainingLearningControlled();
bool TrainingOpponentAI();
void TrainingCaptureFrame();
void TrainingBoot();
void TrainingPoll();
bool TrainingStopping();
void TrainingStop(bool closing);
void TrainingWrite(const std::string& body);
void TrainingCapture(intptr_t engine, const char* kind, const unsigned char* bytes = nullptr, size_t len = 0);
std::string TrainingState(intptr_t engine, bool omitOpponentHand = false);
std::string TrainingComparableState(std::string state);
void TrainingResponse(const unsigned char* bytes, size_t len, const char* actor = "user", int prompt = -1);
bool TrainingAnalyze(intptr_t engine, unsigned char* bytes, size_t len);
void TrainingFinish(intptr_t engine, const char* reason);
std::string TrainingPath(const char* name);
}
