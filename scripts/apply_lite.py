"""Apply an auditable, repeatable patch to the pinned source, never the original app."""

import difflib
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / ".local/upstream"
BASE = WORKSPACE / ".local/pristine"
changes = {}


def read(name):
    current = SOURCE / name
    backup = BASE / name
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(current.read_bytes())
    return backup.read_text(encoding="utf-8-sig")


def save(name, text):
    (SOURCE / name).write_text(text, encoding="utf-8", newline="\n")
    changes[name] = text


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Expected unique patch anchor: {old[:90]!r}")
    return text.replace(old, new, 1)


def block(text, marker, body):
    start = text.index(marker)
    opening = text.index("{", start)
    depth = 1
    i = opening + 1
    state = "code"
    while depth:
        char = text[i]
        pair = text[i:i+2]
        if state == "line":
            if char == "\n": state = "code"
        elif state == "comment":
            if pair == "*/": state = "code"; i += 1
        elif state in ('"', "'"):
            if char == "\\": i += 1
            elif char == state: state = "code"
        elif pair == "//": state = "line"; i += 1
        elif pair == "/*": state = "comment"; i += 1
        elif char in ('"', "'"): state = char
        elif char == "{": depth += 1
        elif char == "}": depth -= 1
        i += 1
    return text[:opening+1] + "\n" + body + "\n" + text[i-1:]


def main():
    t = read("gframe/gframe.cpp")
    t = replace(t, '#include "game.h"', '#include "game.h"\n#include "lite_support.h"')
    a = t.index("static int mymain(")
    z = t.index("\n#ifdef _WIN32\n\nint WINAPI", a)
    t = t[:a] + '''static int mymain(int wargc, const wchar_t* const[]) {
    if (!ygo::InitializeLitePaths())
        return EXIT_FAILURE;
    if (wargc != 1) {
        ygo::LiteTrace("blocked command line: Lite accepts no external mode or file arguments");
        return 2;
    }
    WORD version = MAKEWORD(2, 2);
    WSADATA data;
    if (WSAStartup(version, &data))
        return EXIT_FAILURE;
    evthread_use_windows_threads();
    ygo::Game game;
    ygo::mainGame = &game;
    if (!game.Initialize()) {
        ygo::LiteTrace("startup failed");
        WSACleanup();
        return EXIT_FAILURE;
    }
    ygo::LiteTrace("startup ok: YGOPro Lite 1.036.2; audio=excluded playback=excluded network=loopback-only");
    game.MainLoop();
    ygo::LiteTrace("shutdown clean");
    WSACleanup();
    return EXIT_SUCCESS;
}
''' + t[z:]
    save("gframe/gframe.cpp", t)

    t = read("gframe/game.cpp")
    t = replace(t, '\tLoadConfig("load-once.conf");', '''\tLoadConfig("load-once.conf");
    gameConf.enable_sound = false;
    gameConf.enable_music = false;
    gameConf.enable_bot_mode = true;
    gameConf.bot_room_public = false;
    gameConf.auto_save_replay = 0;
    gameConf.use_d3d = 0; // This portable build uses OpenGL, without the legacy DirectX SDK.
''')
    for line in t.splitlines():
        if line.lstrip().startswith(('btnLanMode =', 'btnReplayMode =')):
            t = t.replace(line + '\n', '')
    t = t.replace('L"YGOPro"', 'L"YGOPro Lite"').replace('L"YGOPro FPS: %d"', 'L"YGOPro Lite FPS: %d"')
    t = t.replace('L"YGOPro Version:%X.0%X.%X"', 'L"YGOPro Lite %X.0%X.%X"')
    t = replace(t, 'wMainMenu = env->addWindow(irr::core::rect<irr::s32>(370, 200, 650, 415)', 'wMainMenu = env->addWindow(irr::core::rect<irr::s32>(370, 200, 650, 345)')
    t = replace(t, 'wMainMenu->setRelativePosition(ResizeWin(370, 200, 650, 415))', 'wMainMenu->setRelativePosition(ResizeWin(370, 200, 650, 345))')
    t = replace(t, '(10, 135, 270, 165), wMainMenu, BUTTON_DECK_EDIT', '(10, 30, 270, 60), wMainMenu, BUTTON_DECK_EDIT')
    t = replace(t, '(10, 170, 270, 200), wMainMenu, BUTTON_MODE_EXIT', '(10, 100, 270, 130), wMainMenu, BUTTON_MODE_EXIT')
    t = t.replace('BUTTON_SINGLE_MODE, dataManager.GetSysString(1201)', 'BUTTON_SINGLE_MODE, L"单人训练"')
    t = replace(t, 'false, dataManager.GetSysString(1250));', 'false, L"本地训练：选择你的卡组");')
    t = replace(t, '\tSwapYesNoButtons(gameConf.swap_yes_no_button);', '''    chkAutoSaveReplay->setChecked(false);
    chkAutoSaveReplay->setVisible(false);
    btnHostPrepOB->setVisible(false);
    stHostPrepOB->setVisible(false);
    btnHostPrepDuelist->setVisible(false);
    wChat->setVisible(false);
\tSwapYesNoButtons(gameConf.swap_yes_no_button);''')
    t = block(t, 'void Game::RefreshReplay()', '    // No replay browser in this build.')
    t = replace(t, '#include "game.h"', '#include "game.h"\n#include "training_support.h"')
    t = replace(t, '\twhile(device->run()) {', '\twhile(device->run()) {\n        TrainingPoll();')
    t = replace(t, '\t\tdriver->endScene();', '\t\tTrainingCaptureFrame();\n\t\tdriver->endScene();')
    t = replace(t, '\tdevice->setResizable(true);', '\tif(!TrainingEmbedded()) device->setResizable(true);')
    t = replace(t, '\tif(gameConf.window_maximized)\n\t\tdevice->maximizeWindow();', '\tif(!TrainingEmbedded() && gameConf.window_maximized)\n\t\tdevice->maximizeWindow();')
    t = replace(t, '\tif(dInfo.isSingleMode)\n\t\tSingleMode::StopPlay(true);', '''    if(TrainingActive()) {
        // The renderer has stopped ticking. Release animation/choice waits before joining.
        frameSignal.SetNoWait(true);
        frameSignal.Set(); // SetNoWait alone does not wake an already waiting animation thread.
        actionSignal.SetNoWait(true);
        singleSignal.SetNoWait(true);
        SingleMode::StopPlay(true);
        SingleMode::WaitForExit(); // Journal + final state must finish before device teardown.
    } else if(dInfo.isSingleMode) {
        SingleMode::StopPlay(true);
    }''')
    save("gframe/game.cpp", t)

    t = read("gframe/drawing.cpp")
    t = replace(t, '#include "game.h"', '#include "game.h"\n#include "training_support.h"')
    t = replace(t, 'void Game::WaitFrameSignal(int frame) {', 'void Game::WaitFrameSignal(int frame) {\n    if(TrainingEmbedded() && (TrainingOpening() || dInfo.curMsg == MSG_NEW_TURN || dInfo.curMsg == MSG_NEW_PHASE)) return; // Presentation only; core events are still processed and recorded.')
    t = replace(t, '\tdriver->drawVertexPrimitiveList(matManager.vField, 4, matManager.iRectangle, 2);', '''    if(TrainingEmbedded() && !TrainingOpponentAI()) {
        irr::video::S3DVertex ownField[4];
        std::copy(std::begin(matManager.vField), std::end(matManager.vField), ownField);
        ownField[0].Pos.Y = ownField[1].Pos.Y = -0.8f;
        ownField[0].TCoords.Y = ownField[1].TCoords.Y = 0.4f;
        driver->drawVertexPrimitiveList(ownField, 4, matManager.iRectangle, 2);
    } else driver->drawVertexPrimitiveList(matManager.vField, 4, matManager.iRectangle, 2);''')
    # Keep own LP and card interactions; remove the empty opponent's status presentation.
    begin = t.index('\t\tif(dInfo.lp[1] > maxLP) {')
    end = t.index('\n\t}\n\tauto tLPFrameRect', begin)
    t = t[:begin] + '\t\tif(!TrainingEmbedded() || TrainingOpponentAI()) {\n' + t[begin:end] + '\n\t\t}' + t[end:]
    for line in t.splitlines():
        if ('draw2DImage(imageManager.tLPFrame, Resize(691' in line or
            'DrawShadowText(numFont, dInfo.strLP[1]' in line):
            t = t.replace(line, '\tif(!TrainingEmbedded() || TrainingOpponentAI()) ' + line.lstrip())
    t = replace(t, '\t\tdriver->draw2DRectangle(0xa0000000, Resize(689, 8, 992, 51));', '\t\tif(!TrainingEmbedded() || TrainingOpponentAI()) driver->draw2DRectangle(0xa0000000, Resize(689, 8, 992, 51));')
    t = replace(t, '\t\tdriver->draw2DRectangleOutline(Resize(689, 8, 992, 51), 0xffff8080);', '\t\tif(!TrainingEmbedded() || TrainingOpponentAI()) driver->draw2DRectangleOutline(Resize(689, 8, 992, 51), 0xffff8080);')
    save("gframe/drawing.cpp", t)

    # Create an actual native child from the start, so no standalone window flashes or steals focus.
    t = read("irrlicht/source/Irrlicht/CIrrDeviceWin32.cpp")
    t = replace(t, '\t// IME enable/disable: only re-check when messages that can change GUI focus state arrive.', '''    if(GetParent(hWnd) && GetEnvironmentVariableA("YGO_EMBED_PARENT", nullptr, 0)) {
        // A real click gives this child keyboard focus without activating another application.
        if(message == WM_LBUTTONDOWN || message == WM_RBUTTONDOWN) SetFocus(hWnd);
        if(message == WM_SYSKEYDOWN && wParam == VK_F4) {
            PostMessageW(GetAncestor(hWnd, GA_ROOT), WM_CLOSE, 0, 0);
            return 0;
        }
    }
\t// IME enable/disable: only re-check when messages that can change GUI focus state arrive.''')
    t = replace(t, '\t\tDWORD style = getWindowStyle(CreationParams.Fullscreen, CreationParams.WindowResizable > 0 ? true : false);', '''        HWND embeddedParent = nullptr;
        wchar_t parentValue[64]{}, parentPidValue[32]{};
        int embeddedX = 0, embeddedY = 0, embeddedW = 1024, embeddedH = 640;
        if(GetEnvironmentVariableW(L"YGO_EMBED_PARENT", parentValue, 64)) {
            embeddedParent = reinterpret_cast<HWND>(_wcstoui64(parentValue, nullptr, 10));
            GetEnvironmentVariableW(L"YGO_EMBED_PARENT_PID", parentPidValue, 32);
            DWORD actualPid = 0;
            GetWindowThreadProcessId(embeddedParent, &actualPid);
            if(!IsWindow(embeddedParent) || actualPid != wcstoul(parentPidValue, nullptr, 10)) {
                Close = true;
                return;
            }
            using GetContext = HANDLE(WINAPI*)(HWND);
            using SetContext = HANDLE(WINAPI*)(HANDLE);
            auto user32 = GetModuleHandleW(L"user32.dll");
            auto getContext = reinterpret_cast<GetContext>(GetProcAddress(user32, "GetWindowDpiAwarenessContext"));
            auto setContext = reinterpret_cast<SetContext>(GetProcAddress(user32, "SetThreadDpiAwarenessContext"));
            if(getContext && setContext) setContext(getContext(embeddedParent));
            char layout[128]{};
            GetEnvironmentVariableA("YGO_EMBED_RECT", layout, sizeof layout);
            if(sscanf(layout, "%d,%d,%d,%d", &embeddedX, &embeddedY, &embeddedW, &embeddedH) != 4 || embeddedW < 200 || embeddedH < 200) {
                Close = true;
                return;
            }
            CreationParams.Fullscreen = false;
            clientSize.right = embeddedW;
            clientSize.bottom = embeddedH;
        }
        DWORD style = embeddedParent ? (WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN) : getWindowStyle(CreationParams.Fullscreen, CreationParams.WindowResizable > 0 ? true : false);''')
    t = replace(t, '\t\t// create window\n', '''        if(embeddedParent) { windowLeft = embeddedX; windowTop = embeddedY; }
        // create window
''')
    t = replace(t, 'realWidth, realHeight, NULL, NULL, hInstance, NULL);', 'realWidth, realHeight, embeddedParent, NULL, hInstance, NULL);')
    t = replace(t, '\t\tShowWindow(HWnd, SW_SHOWNORMAL);', '\t\tShowWindow(HWnd, embeddedParent ? SW_SHOWNOACTIVATE : SW_SHOWNORMAL);')
    t = replace(t, '\t// set this as active window\n\tif (!ExternalWindow)', '\t// Embedded training never changes the foreground application.\n\tif (!ExternalWindow && !GetParent(HWnd))')
    save("irrlicht/source/Irrlicht/CIrrDeviceWin32.cpp", t)

    t = read("gframe/menu_handler.cpp")
    t = block(t, 'case BUTTON_SINGLE_MODE:', '''
                mainGame->env->addMessageBox(L"训练工具箱", L"请使用 Start-Trainer.ps1 选择构筑并开始训练；本入口不启动机器人。");
                break;''')
    for event in ['BUTTON_LAN_MODE','BUTTON_JOIN_HOST','BUTTON_LAN_REFRESH','BUTTON_CREATE_HOST',
                  'BUTTON_HOST_CONFIRM','BUTTON_HOST_CANCEL','BUTTON_HP_OBSERVER','BUTTON_HP_KICK',
                  'BUTTON_REPLAY_MODE','BUTTON_LOAD_REPLAY','BUTTON_DELETE_REPLAY','BUTTON_RENAME_REPLAY',
                  'BUTTON_CANCEL_REPLAY','BUTTON_EXPORT_DECK']:
        t = block(t, 'case '+event+':', '                break; // Feature excluded from Lite.')
    a = t.index('\t\t\t\tbool bot_server_public =')
    z = t.index('\n\t\t\t\tif(!NetServer::StartServer',a)
    t = t[:a] + '\t\t\t\tconstexpr bool bot_server_public = false;' + t[z:]
    save("gframe/menu_handler.cpp", t)

    t = read("gframe/netserver.cpp")
    t = replace(t, '#include "netserver.h"', '#include "netserver.h"\n#include "game.h"\n#include "lite_support.h"')
    signature = 'bool NetServer::StartServer(unsigned short port, unsigned int ip, unsigned short* out_actual_port, bool enable_broadcast) {'
    t = replace(t, signature, signature + '''
    if (!mainGame->bot_mode || ip != 0x7f000001 || enable_broadcast) {
        LiteTrace("blocked non-local server request");
        return false;
    }''')
    t = replace(t, '\tserver_port = ntohs(bound_addr.sin_port);', '\tserver_port = ntohs(bound_addr.sin_port);\n    LiteTrace("local training listener 127.0.0.1:%u", server_port);')
    t = block(t, 'bool NetServer::StartBroadcast()', '    return false; // No LAN discovery or public rooms.')
    t = block(t, 'void NetServer::BroadcastEvent(', '    // Broadcast handling is excluded.')
    marker='void NetServer::ServerAccept(evconnlistener* listener, EventSocket fd, sockaddr* address, int socklen, void* ctx) {'
    t = replace(t, marker, marker + '''
    if (socklen < sizeof(sockaddr_in) || address->sa_family != AF_INET ||
        ntohl(reinterpret_cast<sockaddr_in*>(address)->sin_addr.s_addr) != 0x7f000001 || users.size() >= 2) {
        evutil_closesocket(fd);
        return;
    }''')
    save("gframe/netserver.cpp", t)

    t = read("gframe/duelclient.cpp")
    t = replace(t, '#include "duelclient.h"', '#include "duelclient.h"\n#include "lite_support.h"\n#include "training_support.h"')
    t = t.replace('mainGame->btnLeaveGame->setText(dataManager.GetSysString(1351))', 'mainGame->btnLeaveGame->setText(TrainingActive() ? L"展开结束" : dataManager.GetSysString(1351))')
    signature='bool DuelClient::StartClient(unsigned int ip, unsigned short port, bool create_game) {'
    t=replace(t,signature,signature+'''
    if (!mainGame->bot_mode || ip != 0x7f000001 || !create_game) {
        LiteTrace("blocked non-local client connection");
        return false;
    }''')
    t=block(t, 'void DuelClient::BeginRefreshHost()', '    // LAN discovery has been removed.')
    t=block(t, 'int DuelClient::RefreshThread(', '    return 0;')
    t=block(t, 'void DuelClient::BroadcastReply(', '    // No discovery replies are accepted.')
    t=block(t, 'unsigned int DuelClient::ResolveHostName(', '    return 0; // External host resolution is removed.')
    t=block(t, 'case STOC_REPLAY:', '        break; // No replay dialog or file writes after training.')
    t=replace(t, 'bool DuelClient::ClientAnalyze(unsigned char* msg, size_t len) {', 'bool DuelClient::ClientAnalyze(unsigned char* msg, size_t len) {\n    LiteTracePacket(msg, len);')
    t=replace(t, 'void DuelClient::SendUpdateDeck(const Deck& deck) {', '''void DuelClient::SendUpdateDeck(const Deck& deck) {
    LiteTrace("training deck main=%zu extra=%zu side=%zu", deck.main.size(), deck.extra.size(), deck.side.size());
    for (const auto* card : deck.main) LiteTrace("training main id=%u", card->code);
    for (const auto* card : deck.extra) LiteTrace("training extra id=%u", card->code);''')
    # Shared preparation controls must stay hidden even when protocol handlers refresh them.
    t=t.replace('btnHostPrepOB->setVisible(true)', 'btnHostPrepOB->setVisible(false)')
    t=t.replace('stHostPrepOB->setVisible(true)', 'stHostPrepOB->setVisible(false)')
    t=t.replace('btnHostPrepDuelist->setVisible(true)', 'btnHostPrepDuelist->setVisible(false)')
    t=t.replace('wChat->setVisible(true)', 'wChat->setVisible(false)')
    save("gframe/duelclient.cpp",t)

    t=read("gframe/replay.cpp")
    t=block(t,'void Replay::BeginRecord()', '    Reset();\n    is_recording = true; // Internal buffer only; never open a replay file.')
    t=block(t,'void Replay::WriteHeader(', '    pheader = header;')
    t=block(t,'void Replay::WriteData(', '''    if (!is_recording || length > MAX_REPLAY_SIZE - replay_size) return;
    std::memcpy(replay_data + replay_size, data, length);
    replay_size += length;''')
    t=block(t,'void Replay::Flush()', '    // Replay recording is memory-only.')
    t=replace(t,'\tstd::fclose(fp);\n\tpheader.base.datasize = replay_size;', '\tpheader.base.datasize = replay_size;')
    for name in ['SaveReplay','OpenReplay','DeleteReplay','RenameReplay']:
        t=block(t,'bool Replay::'+name+'(', '    return false; // Replay file operations are excluded from Lite.')
    save("gframe/replay.cpp",t)

    t=read("gframe/single_mode.cpp")
    t=replace(t, '#include "single_mode.h"', '#include "single_mode.h"\n#include "training_support.h"\n#include "deck_manager.h"\n#include <fstream>\n#include <algorithm>\n#include <set>')
    t=replace(t, 'bool SingleMode::StartPlay() {', '''static std::thread trainingThread;
void SingleMode::WaitForExit() {
    if(trainingThread.joinable()) trainingThread.join();
}
bool SingleMode::StartPlay() {''')
    t=replace(t, '\tstd::thread(SinglePlayThread).detach();', '\tWaitForExit();\n\ttrainingThread = std::thread(SinglePlayThread);')
    t=block(t, 'void SingleMode::SinglePlayThread()', (WORKSPACE/'src/trainer/single_thread.inc').read_text(encoding='utf-8'))
    t=replace(t, 'void SingleMode::StopPlay(bool is_exiting) {', 'void SingleMode::StopPlay(bool is_exiting) {\n    TrainingStop(is_exiting);')
    t=replace(t, '\tlast_replay_response_size = last_replay.WriteResponse(resp, len);', '\tTrainingResponse(resp, len);\n    last_replay_response_size = last_replay.WriteResponse(resp, len);')
    t=t.replace('DuelClient::ClientAnalyze(offset, pbuf - offset)', 'TrainingAnalyze(pduel, offset, pbuf - offset)')
    t=replace(t, '\tmainGame->AddDebugMsg(msgbuf);', '\tTrainingWrite("\\\"kind\\\":\\\"script_error\\\",\\\"message_type\\\":" + std::to_string(type));\n    mainGame->AddDebugMsg(msgbuf);')
    save("gframe/single_mode.cpp",t)

    t=read("gframe/single_mode.h")
    t=replace(t, '\tstatic bool StartPlay();', '\tstatic bool StartPlay();\n\tstatic void WaitForExit();')
    save("gframe/single_mode.h",t)

    t=read("gframe/premake5.lua")
    t=replace(t,'    files { "*.cpp", "*.h" }','    files { "*.cpp", "*.h" }\n    removefiles { "replay_mode.cpp" }')
    save("gframe/premake5.lua",t)

    for p in (WORKSPACE/'src/lite').iterdir():
        name='gframe/'+p.name
        content=p.read_text(encoding='utf-8')
        (SOURCE/name).write_text(content,encoding='utf-8',newline='\n')
        changes[name]=content
    patch=[]
    for name,new in sorted(changes.items()):
        old=(BASE/name).read_text(encoding='utf-8-sig') if (BASE/name).exists() else ''
        patch.extend(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name))
    out=WORKSPACE/'patches/ygopro-lite.patch'
    out.parent.mkdir(exist_ok=True)
    out.write_text(''.join(patch),encoding='utf-8',newline='\n')
    print(f'Applied {len(changes)} source changes; playback implementation excluded from build')


if __name__ == '__main__':
    main()
