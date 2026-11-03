import SwiftUI
import AppKit

// MARK: - Root

/// Window content: engine setup until the Python engine is ready, then the studio.
struct RootView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        ZStack {
            Theme.bg0
            if store.engineState.isReady {
                StudioLayout()
            } else {
                SetupView()
            }
        }
        .ignoresSafeArea(.container, edges: .top)
        .overlay(alignment: .bottom) {
            ToastView().padding(.bottom, store.engineState.isReady ? 86 : 24)
        }
        .overlay { BusyOverlay() }
        .alert("AI Music Studio", isPresented: Binding(get: { store.alertText != nil },
                                                      set: { if !$0 { store.alertText = nil } })) {
            Button("OK", role: .cancel) { store.alertText = nil }
        } message: {
            Text(store.alertText ?? "")
        }
        .sheet(item: $store.regenTarget) { t in RegenerateSheet(target: t).environmentObject(store) }
        .sheet(isPresented: $store.showRecorder) { RecordView(rec: store.recorder).environmentObject(store) }
        .background(WindowConfigurator())
        .preferredColorScheme(.dark)
        .task { await store.bootstrap() }
    }
}

extension AppMode {
    var shortTitle: String {
        switch self {
        case .generate: return T("Generate", "Генерация")
        case .stage: return T("Stage", "Сцена")
        case .mixer: return T("Mixer", "Микшер")
        case .master: return T("Master", "Мастер")
        case .release: return T("Release", "Релиз")
        }
    }
}

private struct HLine: View {
    var body: some View { Rectangle().fill(Theme.stroke).frame(height: 1) }
}

private struct VLine: View {
    var body: some View { Rectangle().fill(Theme.stroke).frame(width: 1) }
}

struct StudioLayout: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            TopBar()
            HLine()
            HStack(spacing: 0) {
                if store.showSidebar {
                    SidebarView().frame(width: 250)
                    VLine()
                }
                CenterView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Theme.bg0)
                if store.showInspector {
                    VLine()
                    InspectorView().frame(width: 320)
                }
            }
            HLine()
            TimelineBar()
        }
    }
}

private struct CenterView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        switch store.mode {
        case .generate: GenerateView()
        case .stage: StageView()
        case .mixer: MixerView()
        case .master: MasterView()
        case .release: ReleaseView(rs: store.releases)
        }
    }
}

// MARK: - Top bar

private struct TopBar: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        HStack(spacing: 6) {
            ZStack(alignment: .leading) {                      // room for the window buttons
                Color.clear.frame(width: 70, height: 1)
                if Screenshots.active { ScreenshotTrafficLights() }
            }
            .frame(width: 70)
            IconButton(icon: "sidebar.left", help: T("Library (⌥⌘L)", "Библиотека (⌥⌘L)"), active: store.showSidebar) {
                withAnimation(.easeOut(duration: 0.15)) { store.showSidebar.toggle() }
            }
            ModeSwitcher()
            Spacer(minLength: 6)
            TransportControls(player: store.player)
            LCDDisplay(player: store.player)
            Segmented(selection: Binding(get: { store.listenSource }, set: { store.setListenSource($0) }),
                      options: [(false, T("Studio", "Студия")), (true, T("Original", "Оригинал"))], height: 24)
                .frame(width: 128)
                .disabled(store.session == nil)
                .help(T("A/B: the studio preview or the original mix of the same region",
                        "A/B: превью студии или исходный микс того же фрагмента"))
            Chip(title: "LIVE", isOn: store.liveMonitor, color: Theme.red,
                 help: T("Re-render the preview automatically after every change",
                         "Автоматически пересчитывать превью после каждого изменения")) {
                store.liveMonitor.toggle()
            }
            TopOutMeter(player: store.player)
            Spacer(minLength: 6)
            IconButton(icon: "arrow.uturn.backward", help: T("Undo (⌘Z)", "Отменить (⌘Z)")) { store.undo() }
                .disabled(!store.canUndo)
                .opacity(store.canUndo ? 1 : 0.35)
            IconButton(icon: "arrow.uturn.forward", help: T("Redo (⇧⌘Z)", "Повторить (⇧⌘Z)")) { store.redo() }
                .disabled(!store.canRedo)
                .opacity(store.canRedo ? 1 : 0.35)
            IconButton(icon: "wand.and.rays", help: T("Regenerate part of the song (ACE-Step)", "Перегенерировать часть песни (ACE-Step)")) {
                store.regenerateSessionSong()
            }
            .disabled(store.sourceMixPath == nil)
            .opacity(store.sourceMixPath == nil ? 0.35 : 1)
            IconButton(icon: "mic.circle", help: T("Record vocals into the session (⇧⌘R)", "Записать вокал в сессию (⇧⌘R)"),
                       active: store.showRecorder) {
                store.showRecorder = true
            }
            .disabled(store.session == nil)
            .opacity(store.session == nil ? 0.35 : 1)
            RenderButton()
            EngineMenu()
            IconButton(icon: "sidebar.right", help: T("Inspector (⌥⌘I)", "Инспектор (⌥⌘I)"), active: store.showInspector) {
                withAnimation(.easeOut(duration: 0.15)) { store.showInspector.toggle() }
            }
        }
        .padding(.leading, 8)
        .padding(.trailing, 10)
        .frame(height: 52)
        .background(ZStack { Theme.bg1; WindowDragArea() })
    }
}

private struct ModeSwitcher: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        HStack(spacing: 2) {
            ForEach(AppMode.allCases) { m in
                let on = store.mode == m
                Button { store.mode = m } label: {
                    HStack(spacing: 5) {
                        Image(systemName: m.icon).font(.system(size: 11, weight: .semibold))
                            .foregroundColor(on ? Theme.accent : Theme.text3)
                        Text(m.shortTitle).font(.system(size: 12, weight: on ? .semibold : .regular))
                            .foregroundColor(on ? Theme.text : Theme.text2)
                            .lineLimit(1)
                            .fixedSize()
                    }
                    .padding(.horizontal, 10)
                    .frame(height: 28)
                    .background(RoundedRectangle(cornerRadius: 6).fill(on ? Theme.bg3 : Color.clear))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("\(m.title) (⌘\(String(m.shortcut.character)))")
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.stroke, lineWidth: 1))
    }
}

private struct TransportControls: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer

    var body: some View {
        HStack(spacing: 6) {
            IconButton(icon: "stop.fill", help: T("Stop", "Стоп"), size: 12) { store.stopPlayback() }
            Button { store.togglePlay() } label: {
                ZStack {
                    Circle().fill(player.isPlaying ? Theme.accent : Theme.bg3)
                    Circle().stroke(player.isPlaying ? Theme.accent : Theme.strokeStrong, lineWidth: 1)
                    if store.previewing && !player.isPlaying {
                        ProgressView().controlSize(.small).scaleEffect(0.7)
                    } else {
                        Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(player.isPlaying ? Theme.bg0 : Theme.text)
                            .offset(x: player.isPlaying ? 0 : 1)
                    }
                }
                .frame(width: 32, height: 32)
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .help(T("Play / pause (Space)", "Воспроизведение / пауза (пробел)"))
            IconButton(icon: "repeat", help: T("Loop the preview region", "Зациклить фрагмент превью"), active: player.loop, size: 12) {
                player.loop.toggle()
            }
        }
    }
}

private struct LCDDisplay: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer
    private static let lengths: [Double] = [10, 20, 30, 60]

    var body: some View {
        HStack(spacing: 10) {
            Text(Fmt.time(player.position))
                .font(.system(size: 16, weight: .medium, design: .monospaced))
                .foregroundColor(Theme.accent)
                .frame(width: 74, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(store.nowPlayingTitle.isEmpty ? T("Nothing loaded", "Ничего не загружено") : store.nowPlayingTitle)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(Theme.text2)
                    .lineLimit(1)
                Menu {
                    ForEach(LCDDisplay.lengths, id: \.self) { n in
                        Button(T("Preview \(Int(n)) s", "Превью \(Int(n)) с")) {
                            store.previewLength = n
                            store.setLoopStart(store.loopStart)
                        }
                    }
                } label: {
                    Text(T("LOOP \(Fmt.clock(store.loopStart)) · \(Int(store.previewLength)) s",
                           "ЦИКЛ \(Fmt.clock(store.loopStart)) · \(Int(store.previewLength)) с"))
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        .foregroundColor(Theme.text3)
                }
                .menuStyle(.button)
                .buttonStyle(.borderless)
                .menuIndicator(.hidden)
                .fixedSize()
                .help(T("Preview length", "Длина превью"))
            }
            .frame(width: 104, alignment: .leading)
        }
        .padding(.horizontal, 10)
        .frame(height: 36)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
    }
}

/// Compact stereo output meter (post monitor volume).
private struct TopOutMeter: View {
    @ObservedObject var player: AudioPlayer

    var body: some View {
        let l = player.isPlaying ? player.outPeak.0 : -90
        let r = player.isPlaying ? player.outPeak.1 : -90
        VStack(alignment: .leading, spacing: 3) {
            bar(l, hold: player.isPlaying ? player.outHold.0 : -90)
            bar(r, hold: player.isPlaying ? player.outHold.1 : -90)
            Text(max(l, r) <= -89 ? "OUT  −∞" : "OUT " + Fmt.dbShort(max(l, r)))
                .font(.system(size: 8, weight: .semibold, design: .monospaced))
                .foregroundColor(max(l, r) > -0.1 ? Theme.red : Theme.text3)
        }
        .frame(width: 72)
        .help(T("Output level, dBFS", "Уровень выхода, dBFS"))
    }

    private func frac(_ db: Double) -> CGFloat { CGFloat(min(max((db + 60) / 60, 0), 1)) }

    private func bar(_ db: Double, hold: Double) -> some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 1.5).fill(Theme.bg0)
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(LinearGradient(colors: [Theme.green, Theme.green, Theme.yellow, Theme.red],
                                         startPoint: .leading, endPoint: .trailing))
                    .mask(alignment: .leading) { Rectangle().frame(width: g.size.width * frac(db)) }
                if hold > -60 {
                    Rectangle().fill(Theme.meterColor(hold)).frame(width: 1.5)
                        .offset(x: g.size.width * frac(hold) - 1)
                }
            }
        }
        .frame(height: 4)
    }
}

private struct RenderButton: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        if let p = store.renderProgress {
            HStack(spacing: 6) {
                VStack(alignment: .leading, spacing: 2) {
                    ProgressStrip(value: p > 0 ? p : nil)
                    Text(store.renderMessage).font(.system(size: 8)).foregroundColor(Theme.text3).lineLimit(1)
                }
                .frame(width: 92)
                IconButton(icon: "xmark.circle.fill", help: T("Cancel render", "Отменить рендер"), size: 12) { store.cancelRender() }
            }
        } else {
            Button { Task { await store.renderFinal() } } label: {
                Label(T("Render", "Рендер"), systemImage: "square.and.arrow.down").lineLimit(1)
            }
            .buttonStyle(StudioButtonStyle(prominent: true, compact: true))
            .fixedSize()
            .disabled(store.session == nil)
            .help(T("Render the full mix with the current settings (⌘R)", "Свести весь трек с текущими настройками (⌘R)"))
        }
    }
}

private struct EngineMenu: View {
    @EnvironmentObject var store: StudioStore
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        Menu {
            Text(store.engineState.label)
            Text("Python \(store.pythonVersion) · " + T("engine", "движок") + " \(store.engineVersion)")
            Divider()
            Button(T("Restart Engine", "Перезапустить движок")) { Task { await store.restartEngine() } }
            Button(T("Settings…", "Настройки…")) { openSettings() }
            Button(T("Show Project Folder", "Показать папку проекта")) { store.reveal(store.projectRoot.path) }
        } label: {
            Image(systemName: "cpu")
                .font(.system(size: 12))
                .foregroundColor(store.engineState.isReady ? Theme.green : Theme.red)
                .frame(width: 26, height: 26)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.borderless)
        .menuIndicator(.hidden)
        .fixedSize()
        .help(store.engineState.label)
    }
}

// MARK: - Timeline

private struct TimelineBar: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Caption(text: T("Timeline", "Таймлайн"))
                Text(store.session == nil ? "—" : Fmt.clock(store.songDuration))
                    .font(Theme.mono)
                    .foregroundColor(Theme.text2)
                Text(T("click to move the loop", "клик — перенести цикл"))
                    .font(.system(size: 9))
                    .foregroundColor(Theme.text3)
                    .lineLimit(1)
            }
            .frame(width: 120, alignment: .leading)
            WaveformTimeline(player: store.player)
                .frame(maxWidth: .infinity)
            PreviewStatus(player: store.player)
                .frame(width: 168, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(height: 68)
        .background(Theme.bg1)
    }
}

private struct PreviewStatus: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if store.session == nil {
                Text(T("Open a song to start mixing", "Откройте песню, чтобы сводить"))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
            } else if store.previewing {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small).scaleEffect(0.6).frame(width: 14, height: 14)
                    Text(T("Rendering preview…", "Считаю превью…")).font(.system(size: 10)).foregroundColor(Theme.text2)
                }
            } else if store.listenSource {
                Label(T("Original mix (A/B)", "Исходный микс (A/B)"), systemImage: "a.square")
                    .font(.system(size: 10)).foregroundColor(Theme.blue)
            } else if store.previewStale {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.triangle.2.circlepath").font(.system(size: 10)).foregroundColor(Theme.yellow)
                    Text(T("Preview outdated", "Превью устарело")).font(.system(size: 10)).foregroundColor(Theme.text2)
                    Button(T("Update", "Обновить")) { Task { await store.renderPreview(autoplay: player.isPlaying) } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                }
            } else {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 10)).foregroundColor(Theme.green)
                    Text(T("Preview up to date", "Превью актуально")).font(.system(size: 10)).foregroundColor(Theme.text2)
                }
            }
            if store.session != nil {
                Text("LUFS \(Fmt.lufs(store.previewLufs).replacingOccurrences(of: " LUFS", with: ""))  ·  TP "
                     + (store.previewTruePeak.map { Fmt.dbShort($0) } ?? "—"))
                    .font(Theme.monoSmall)
                    .foregroundColor(Theme.text3)
            }
        }
    }
}

/// Waveform of the source mix with the preview loop region and the playhead.
private struct WaveformTimeline: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer
    @State private var dragStart: Double?

    var body: some View {
        GeometryReader { g in
            let dur = max(store.songDuration, 0.001)
            let w = g.size.width, h = g.size.height
            let start = dragStart ?? store.loopStart
            let len = min(store.previewLength, dur)
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 6).fill(Theme.bg0)
                if store.session == nil || store.waveform.isNull {
                    Text(store.session == nil ? T("No session", "Нет сессии") : T("Reading waveform…", "Читаю волну…"))
                        .font(.system(size: 10))
                        .foregroundColor(Theme.text3)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    WaveformCanvas(waveform: store.waveform, regionStart: start / dur, regionEnd: (start + len) / dur)
                    // loop region frame
                    Rectangle()
                        .stroke(Theme.accent.opacity(0.9), lineWidth: 1)
                        .background(Theme.accent.opacity(0.08))
                        .frame(width: max(2, CGFloat(len / dur) * w), height: h)
                        .offset(x: CGFloat(start / dur) * w)
                        .allowsHitTesting(false)
                    TimeTicks(duration: dur)
                        .allowsHitTesting(false)
                    // playhead (song timeline)
                    if store.timelinePlayback, player.position > 0 || player.isPlaying {
                        Rectangle()
                            .fill(Theme.text)
                            .frame(width: 1.5, height: h)
                            .offset(x: CGFloat(min(max(player.position / dur, 0), 1)) * w)
                            .allowsHitTesting(false)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        guard store.session != nil else { return }
                        let t = Double(v.location.x / max(w, 1)) * dur - len / 2
                        dragStart = min(max(0, t), max(0, dur - len))
                    }
                    .onEnded { _ in
                        if let s = dragStart { store.setLoopStart(s) }
                        dragStart = nil
                    }
            )
        }
    }
}

private struct WaveformCanvas: View {
    let waveform: JSONValue
    let regionStart: Double
    let regionEnd: Double

    var body: some View {
        Canvas { ctx, size in
            let peaksL = waveform["peaks"]?[0]?.doubles ?? []
            let peaksR = waveform["peaks"]?[1]?.doubles ?? peaksL
            let rmsL = waveform["rms"]?[0]?.doubles ?? []
            let rmsR = waveform["rms"]?[1]?.doubles ?? rmsL
            let n = min(peaksL.count, peaksR.count)
            guard n > 1 else { return }
            let cols = max(1, Int(size.width / 2))
            let mid = size.height / 2
            var inside = Path(), outside = Path(), rmsIn = Path(), rmsOut = Path()
            for c in 0..<cols {
                let a = c * n / cols, b = max(a + 1, (c + 1) * n / cols)
                var pk = 0.0, rm = 0.0
                for i in a..<min(b, n) {
                    pk = max(pk, max(peaksL[i], peaksR[i]))
                    if i < rmsL.count && i < rmsR.count { rm = max(rm, (rmsL[i] + rmsR[i]) / 2) }
                }
                let x = CGFloat(c) * size.width / CGFloat(cols)
                let ph = max(0.5, CGFloat(min(pk, 1)) * (mid - 2))
                let rh = max(0.5, CGFloat(min(rm * 1.4, 1)) * (mid - 2))
                let frac = Double(c) / Double(cols)
                let inRegion = frac >= regionStart && frac <= regionEnd
                let pr = CGRect(x: x, y: mid - ph, width: 1.2, height: ph * 2)
                let rr = CGRect(x: x, y: mid - rh, width: 1.2, height: rh * 2)
                if inRegion { inside.addRect(pr); rmsIn.addRect(rr) } else { outside.addRect(pr); rmsOut.addRect(rr) }
            }
            ctx.fill(outside, with: .color(Theme.text3.opacity(0.45)))
            ctx.fill(rmsOut, with: .color(Theme.text2.opacity(0.45)))
            ctx.fill(inside, with: .color(Theme.accent.opacity(0.55)))
            ctx.fill(rmsIn, with: .color(Theme.accent))
        }
        .allowsHitTesting(false)
    }
}

private struct TimeTicks: View {
    let duration: Double

    var body: some View {
        Canvas { ctx, size in
            let step: Double = duration > 360 ? 60 : (duration > 120 ? 30 : (duration > 40 ? 10 : 5))
            var t = step
            while t < duration {
                let x = CGFloat(t / duration) * size.width
                ctx.fill(Path(CGRect(x: x, y: size.height - 5, width: 1, height: 5)), with: .color(Theme.text3.opacity(0.6)))
                ctx.draw(Text(Fmt.clock(t)).font(.system(size: 8, design: .monospaced)).foregroundColor(Theme.text3),
                         at: CGPoint(x: x + 2, y: 2), anchor: .topLeading)
                t += step
            }
        }
    }
}

// MARK: - Overlays

private struct ToastView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        ZStack {
            if let t = store.toast {
                HStack(spacing: 8) {
                    Image(systemName: t.isError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                        .foregroundColor(t.isError ? Theme.red : Theme.green)
                    Text(t.text)
                        .font(.system(size: 12))
                        .foregroundColor(Theme.text)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .frame(maxWidth: 560)
                .background(Capsule().fill(Theme.bg3))
                .overlay(Capsule().stroke(t.isError ? Theme.red.opacity(0.6) : Theme.strokeStrong, lineWidth: 1))
                .shadow(color: .black.opacity(0.4), radius: 12, y: 4)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .onTapGesture { store.toast = nil }
            }
        }
        .animation(.easeOut(duration: 0.2), value: store.toast)
    }
}

private struct BusyOverlay: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        if let text = store.busyText {
            ZStack {
                Color.black.opacity(0.35)
                    .contentShape(Rectangle())
                    .onTapGesture {}
                VStack(spacing: 10) {
                    if let p = store.busyProgress, p > 0 {
                        ProgressView(value: min(max(p, 0), 1)).frame(width: 240).tint(Theme.accent)
                    } else {
                        ProgressView().controlSize(.regular)
                    }
                    Text(text).font(.system(size: 12)).foregroundColor(Theme.text).multilineTextAlignment(.center)
                }
                .padding(20)
                .frame(minWidth: 300)
                .background(RoundedRectangle(cornerRadius: 12).fill(Theme.bg2))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.strokeStrong, lineWidth: 1))
            }
            .transition(.opacity)
        }
    }
}

// MARK: - Engine setup

struct SetupView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        ZStack {
            WindowDragArea()
            VStack(spacing: 18) {
                VStack(spacing: 8) {
                    Image(systemName: "waveform.circle.fill")
                        .font(.system(size: 52))
                        .foregroundStyle(LinearGradient(colors: [Theme.accent, Theme.purple], startPoint: .topLeading, endPoint: .bottomTrailing))
                    Text("AI Music Studio").font(.system(size: 24, weight: .semibold)).foregroundColor(Theme.text)
                    Text(T("Generate songs, place the band in a virtual room and mix — on your Mac.",
                           "Генерируйте песни, расставляйте музыкантов в виртуальной комнате и сводите — на вашем Mac."))
                        .font(.system(size: 12))
                        .foregroundColor(Theme.text2)
                }
                switch store.engineState {
                case .needsSetup(let message):
                    SetupPanel(message: message, isError: false)
                case .failed(let message):
                    SetupPanel(message: message, isError: true)
                default:
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text(store.engineState.label).font(.system(size: 12)).foregroundColor(Theme.text2)
                    }
                    .padding(.top, 8)
                }
            }
            .frame(maxWidth: 720)
            .padding(40)
        }
    }
}

private struct SetupPanel: View {
    @EnvironmentObject var store: StudioStore
    let message: String
    let isError: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: isError ? "xmark.octagon.fill" : "wrench.and.screwdriver.fill")
                    .foregroundColor(isError ? Theme.red : Theme.yellow)
                Text(message)
                    .font(.system(size: 12))
                    .foregroundColor(Theme.text)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !store.pythonCandidates.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Caption(text: T("Python interpreters found", "Найденные интерпретаторы Python"))
                    ForEach(store.pythonCandidates) { c in
                        HStack(spacing: 8) {
                            Image(systemName: c.hasDeps ? "checkmark.circle.fill" : "exclamationmark.circle")
                                .foregroundColor(c.hasDeps ? Theme.green : Theme.yellow)
                                .font(.system(size: 10))
                            Text(c.path).font(Theme.monoSmall).foregroundColor(Theme.text2).lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Text("Python \(c.version)").font(Theme.monoSmall).foregroundColor(Theme.text3)
                            if !c.missing.isEmpty {
                                Text(T("missing: ", "нет: ") + c.missing.joined(separator: ", "))
                                    .font(Theme.monoSmall).foregroundColor(Theme.yellow)
                            }
                        }
                    }
                }
            }
            HStack(spacing: 8) {
                Button { Task { await store.startEngine() } } label: { Label(T("Retry", "Повторить"), systemImage: "arrow.clockwise") }
                    .buttonStyle(StudioButtonStyle())
                if case .needsSetup = store.engineState {
                    Button { Task { await store.setupEnvironment() } } label: {
                        Label(T("Set Up Automatically", "Настроить автоматически"), systemImage: "wand.and.stars")
                    }
                    .buttonStyle(StudioButtonStyle(prominent: true))
                    .disabled(store.settingUp)
                }
                Button(T("Choose Python…", "Выбрать Python…")) { choosePython() }
                    .buttonStyle(StudioButtonStyle())
                Button(T("Choose Engine Folder…", "Папка движка…")) { chooseEngineDir() }
                    .buttonStyle(StudioButtonStyle())
                Spacer()
                if store.settingUp { ProgressView().controlSize(.small) }
            }
            if !store.setupLog.isEmpty {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 1) {
                            ForEach(Array(store.setupLog.enumerated()), id: \.offset) { i, line in
                                Text(line).font(Theme.monoSmall).foregroundColor(Theme.text2).id(i)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .padding(8)
                        .textSelection(.enabled)
                    }
                    .frame(height: 150)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
                    .onChange(of: store.setupLog.count) { _, n in proxy.scrollTo(n - 1, anchor: .bottom) }
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Caption(text: T("Or set it up in Terminal", "Или вручную в Терминале"))
                Text(manualCommands)
                    .font(Theme.monoSmall)
                    .foregroundColor(Theme.accent2)
                    .textSelection(.enabled)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
                Text(T("The engine needs Python 3.9+ with numpy, scipy, soundfile and requests. ffmpeg (brew install ffmpeg) adds MP3/M4A export.",
                       "Движку нужен Python 3.9+ с numpy, scipy, soundfile и requests. ffmpeg (brew install ffmpeg) добавляет экспорт MP3/M4A."))
                    .font(.system(size: 10))
                    .foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 12).fill(Theme.bg1))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.stroke, lineWidth: 1))
    }

    private var manualCommands: String {
        let venv = AppPaths.managedVenv.path.replacingOccurrences(of: " ", with: "\\ ")
        let req = (store.requirementsFile?.path ?? "requirements-engine.txt").replacingOccurrences(of: " ", with: "\\ ")
        return "python3 -m venv \(venv)\n\(venv)/bin/python -m pip install -r \(req)"
    }

    private func choosePython() {
        let p = NSOpenPanel()
        p.canChooseFiles = true
        p.canChooseDirectories = false
        p.treatsFilePackagesAsDirectories = true
        p.showsHiddenFiles = true
        p.prompt = T("Use This Python", "Использовать")
        p.message = T("Choose a python3 executable (for example ~/.pyenv/versions/3.11.6/bin/python)",
                      "Выберите исполняемый файл python3 (например ~/.pyenv/versions/3.11.6/bin/python)")
        if p.runModal() == .OK, let u = p.url {
            UserDefaults.standard.set(u.path, forKey: "pythonPath")
            Task { await store.startEngine() }
        }
    }

    private func chooseEngineDir() {
        let p = NSOpenPanel()
        p.canChooseFiles = false
        p.canChooseDirectories = true
        p.prompt = T("Use Folder", "Выбрать")
        p.message = T("Choose the folder that contains studio/engine_server.py", "Выберите папку, в которой лежит studio/engine_server.py")
        if p.runModal() == .OK, let u = p.url {
            UserDefaults.standard.set(u.path, forKey: "engineDir")
            Task { await store.startEngine() }
        }
    }
}

// MARK: - Window setup

/// Configures the hosting NSWindow once it exists: tabbing off, traffic lights centred in the 52 pt top bar.
struct WindowConfigurator: NSViewRepresentable {
    final class Probe: NSView {
        private var observers: [NSObjectProtocol] = []

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            observers.forEach { NotificationCenter.default.removeObserver($0) }
            observers = []
            guard let w = window else { return }
            w.tabbingMode = .disallowed
            w.isMovableByWindowBackground = false
            let names: [Notification.Name] = [NSWindow.didResizeNotification, NSWindow.didBecomeKeyNotification,
                                              NSWindow.didResignKeyNotification, NSWindow.didExitFullScreenNotification,
                                              NSWindow.didEndLiveResizeNotification]
            for n in names {
                observers.append(NotificationCenter.default.addObserver(forName: n, object: w, queue: .main) { [weak w] _ in
                    guard let w else { return }
                    MainActor.assumeIsolated { TrafficLights.layout(w) }
                })
            }
            DispatchQueue.main.async { [weak w] in
                guard let w else { return }
                MainActor.assumeIsolated { TrafficLights.layout(w) }
            }
        }

        deinit { observers.forEach { NotificationCenter.default.removeObserver($0) } }
    }

    func makeNSView(context: Context) -> NSView { Probe() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

@MainActor
enum TrafficLights {
    static let barHeight: CGFloat = 52
    static let leading: CGFloat = 18

    /// Moves the close/minimize/zoom buttons to the vertical centre of the custom top bar.
    static func layout(_ window: NSWindow) {
        guard !window.styleMask.contains(.fullScreen),
              let close = window.standardWindowButton(.closeButton),
              let mini = window.standardWindowButton(.miniaturizeButton),
              let zoom = window.standardWindowButton(.zoomButton),
              let container = close.superview?.superview else { return }
        let h = close.frame.height
        var r = container.frame
        r.size.height = barHeight
        r.origin.y = window.frame.height - barHeight
        container.frame = r
        let space = mini.frame.minX - close.frame.minX
        guard space > 0 else { return }
        for (i, b) in [close, mini, zoom].enumerated() {
            b.setFrameOrigin(NSPoint(x: leading + CGFloat(i) * space, y: (barHeight - h) / 2))
        }
    }
}
