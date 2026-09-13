// Playback is excluded from the Lite build. These inert adapters satisfy shared UI references.
#include "replay_mode.h"
namespace ygo {
Replay ReplayMode::cur_replay;
bool ReplayMode::StartReplay(int) { return false; }
void ReplayMode::StopReplay(bool) {}
void ReplayMode::SwapField() {}
void ReplayMode::Pause(bool, bool) {}
void ReplayMode::Undo() {}
}
