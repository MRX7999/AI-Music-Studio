import SwiftUI
import AppKit

/// Options parsed from the command line in main.swift.
enum LaunchOptions {
    static var smokeSeconds: Double?
    static var smokeReport = "/tmp/ams-smoke.json"
    static var projectRoot: String?
}

/// Weak reference to the studio window (Space = play only when it is the key window).
@MainActor
enum StudioWindow {
    static weak var main: NSWindow?
}

struct AIMusicStudioApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var store = StudioStore(projectRoot: LaunchOptions.projectRoot.map { URL(fileURLWithPath: $0, isDirectory: true) })

    var body: some Scene {
        Window("AI Music Studio", id: "main") {
            RootView()
                .environmentObject(store)
                .id(store.langCode)
                .frame(minWidth: 1180, minHeight: 720)
                .background(MainWindowMarker())
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1440, height: 900)
        .commands { StudioCommands(store: store) }

        Settings {
            SettingsView().environmentObject(store)
        }
    }
}

/// Remembers the hosting window as the main studio window.
private struct MainWindowMarker: NSViewRepresentable {
    final class Marker: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let w = window { StudioWindow.main = w }
        }
    }
    func makeNSView(context: Context) -> NSView { Marker() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

struct StudioCommands: Commands {
    @ObservedObject var store: StudioStore

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button(T("Import Song…", "Импорт песни…")) { store.importAudio(method: store.stemMethod) }
                .keyboardShortcut("o")
                .disabled(!store.engineState.isReady)
            Button(T("New Session from Stems…", "Новая сессия из стемов…")) { store.newSessionFromStems() }
                .keyboardShortcut("n", modifiers: [.command, .shift])
                .disabled(!store.engineState.isReady)
            Divider()
            Button(T("Save Session", "Сохранить сессию")) { Task { await store.saveSession() } }
                .keyboardShortcut("s")
                .disabled(store.session == nil)
            Button(T("Choose Project Folder…", "Папка проекта…")) { store.chooseProjectRoot() }
        }
        CommandGroup(replacing: .undoRedo) {
            Button(T("Undo", "Отменить")) {
                if NSApp.keyWindow?.firstResponder is NSTextView {
                    NSApp.sendAction(Selector(("undo:")), to: nil, from: nil)
                } else {
                    store.undo()
                }
            }
            .keyboardShortcut("z")
            Button(T("Redo", "Повторить")) {
                if NSApp.keyWindow?.firstResponder is NSTextView {
                    NSApp.sendAction(Selector(("redo:")), to: nil, from: nil)
                } else {
                    store.redo()
                }
            }
            .keyboardShortcut("z", modifiers: [.command, .shift])
        }
        CommandMenu(T("Studio", "Студия")) {
            ForEach(AppMode.allCases) { m in
                Button(m.title) { store.mode = m }
                    .keyboardShortcut(m.shortcut)
            }
            Divider()
            Button(T("Play / Pause", "Воспроизведение / пауза")) { store.togglePlay() }
            Button(T("Stop", "Стоп")) { store.stopPlayback() }
                .keyboardShortcut(".")
            Button(T("Render Mix", "Свести микс")) { Task { await store.renderFinal() } }
                .keyboardShortcut("r")
                .disabled(store.session == nil || store.renderProgress != nil)
            Button(T("Generate", "Сгенерировать")) {
                store.mode = .generate
                Task { await store.generate() }
            }
            .keyboardShortcut(.return)
            .disabled(!store.engineState.isReady || store.generating)
            Divider()
            Button(store.showSidebar ? T("Hide Library", "Скрыть библиотеку") : T("Show Library", "Показать библиотеку")) {
                withAnimation(.easeOut(duration: 0.15)) { store.showSidebar.toggle() }
            }
            .keyboardShortcut("l", modifiers: [.command, .option])
            Button(store.showInspector ? T("Hide Inspector", "Скрыть инспектор") : T("Show Inspector", "Показать инспектор")) {
                withAnimation(.easeOut(duration: 0.15)) { store.showInspector.toggle() }
            }
            .keyboardShortcut("i", modifiers: [.command, .option])
            Divider()
            Button(T("Restart Engine", "Перезапустить движок")) { Task { await store.restartEngine() } }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var keyMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
        installSpaceMonitor()
        if let s = LaunchOptions.smokeSeconds {
            DispatchQueue.main.asyncAfter(deadline: .now() + s) {
                MainActor.assumeIsolated { SmokeReport.write(to: LaunchOptions.smokeReport) }
                NSApp.terminate(nil)
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        StudioStore.shared?.engine.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// Space toggles playback unless a text field or editor has focus.
    private func installSpaceMonitor() {
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let handled: Bool = MainActor.assumeIsolated {
                guard event.keyCode == 49,
                      event.modifierFlags.intersection([.command, .control, .option]).isEmpty,
                      let win = NSApp.keyWindow, win === StudioWindow.main else { return false }
                if win.firstResponder is NSText { return false }
                guard let store = StudioStore.shared, store.engineState.isReady else { return false }
                store.togglePlay()
                return true
            }
            return handled ? nil : event
        }
    }
}

/// `--smoke N`: after N seconds the app writes a JSON report about the running UI and quits.
@MainActor
enum SmokeReport {
    static func write(to path: String) {
        var r: [String: JSONValue] = [:]
        let store = StudioStore.shared
        r["engine_state"] = .s(store?.engineState.label ?? "no store")
        r["engine_ready"] = .b(store?.engineState.isReady ?? false)
        r["python"] = .s(store?.pythonPath ?? "")
        r["python_version"] = .s(store?.pythonVersion ?? "")
        r["engine_version"] = .s(store?.engineVersion ?? "")
        r["engine_dir"] = .s(store?.engineDir?.path ?? "")
        r["scenes"] = .n(store?.scenes.count ?? 0)
        r["mics"] = .n(store?.mics.count ?? 0)
        r["engines"] = .n(store?.engines.count ?? 0)
        r["songs"] = .n(store?.library.list("songs").count ?? 0)
        r["project_root"] = .s(store?.projectRoot.path ?? "")
        r["language"] = .s(L10n.code)
        r["bundle_path"] = .s(Bundle.main.bundlePath)
        r["windows"] = .n(NSApp.windows.filter { $0.isVisible }.count)
        if let w = StudioWindow.main {
            r["window_frame"] = .s(NSStringFromRect(w.frame))
            r["window_key"] = .b(w.isKeyWindow)
            if let close = w.standardWindowButton(.closeButton) {
                let inWindow = close.convert(close.bounds, to: nil)
                r["close_button_frame"] = .s(NSStringFromRect(inWindow))
            }
            // which view receives a click in the custom top bar (between the mode switcher and transport)
            if let frameView = w.contentView?.superview {
                let pt = NSPoint(x: w.frame.width / 2, y: w.frame.height - 26)
                let hit = frameView.hitTest(pt)
                r["topbar_hit_view"] = .s(hit.map { String(describing: type(of: $0)) } ?? "nil")
            }
        }
        if let data = try? JSONValue.object(r).data(pretty: true) {
            try? data.write(to: URL(fileURLWithPath: path))
        }
    }
}
