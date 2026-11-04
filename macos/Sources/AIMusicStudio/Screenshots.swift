import SwiftUI
import AppKit

/// `AIMusicStudio --screenshots <dir>`: builds a real session with the engine (demo song "Night Drive"),
/// then renders the actual RootView offscreen at 1440×900 @2x for the README.
@MainActor
enum Screenshots {
    /// While capturing, the top bar draws the window buttons itself (an offscreen borderless window has none).
    static var active = false

    static func run(outDir: String) {
        NSApplication.shared.setActivationPolicy(.accessory)
        Task { @MainActor in
            let code = await capture(outDir: outDir)
            exit(code)
        }
    }

    private static let lyrics = """
    [Intro]

    [Verse]
    Neon rivers on the glass
    City lights are fading fast
    Hold the wheel and hold my hand
    Midnight runs to no-man's land

    [Chorus]
    Night drive, we're alive
    Chasing echoes down the line
    Night drive, satellite
    Shining only for tonight

    [Outro]
    """

    static func capture(outDir: String) async -> Int32 {
        active = true
        let out = URL(fileURLWithPath: (outDir as NSString).expandingTildeInPath, isDirectory: true)
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        // a readable project folder for the sidebar footer; it only ever holds this demo
        let root = URL(fileURLWithPath: "/tmp/AI Music Studio Demo", isDirectory: true)
        try? FileManager.default.removeItem(at: root)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        L10n.isRussian = false
        let store = StudioStore(projectRoot: root)
        L10n.isRussian = false
        store.langCode = "en"
        store.liveMonitor = false

        await store.startEngine()
        guard store.engineState.isReady else {
            print("engine did not start: \(store.engineState)")
            return 1
        }
        store.selectEngine("demo")
        store.form.title = "Night Drive"
        store.form.style = "synthwave, retro, dreamy pads, 80s drums, male vocals"
        store.form.lyrics = lyrics
        store.form.duration = 40
        store.form.autoBpm = false
        store.form.bpm = 96
        store.form.key = "A minor"
        store.form.randomSeed = false
        store.form.seed = 11
        await store.generate()
        guard let track = store.genResults.first else {
            print("generation failed: \(store.genMessage)")
            return 1
        }
        await store.refreshEngineStatuses()

        store.mode = .generate
        await shot(store, "app-generate.png", out)

        await store.openTrack(track)
        await store.loadWaveform()
        await store.sessionOp("set_scene", ["scene": .s("live_room"), "keep_layout": true])
        await store.refreshDescribe()
        store.previewLength = 20
        store.setLoopStart(8)
        await store.renderPreview(autoplay: false)
        store.meterSnapshotTime = 14
        await store.saveSession()
        await store.refreshLibrary()
        let vocals = store.session?.channels.first { $0.str("instrument").contains("vocal") || $0.str("name").lowercased().contains("vocal") }
        store.selectedChannel = vocals?.str("id") ?? store.channelIDs.first

        store.mode = .stage
        await shot(store, "app-stage.png", out)
        store.mode = .mixer
        await shot(store, "app-mixer.png", out)
        await store.renderFinal()
        store.mode = .master
        await shot(store, "app-master.png", out)

        // v1.2: release page, regenerate sheet, AI models settings
        let rs = store.releases
        rs.coverOpts.backend = "builtin"
        rs.sr.backend = "builtin"
        rs.detectOpts.aigm = false
        await rs.create(path: track.str("path"), title: "Night Drive", lyrics: lyrics)
        rs.refOpts.reference = track.str("path")
        rs.pkg.format = "wav"
        rs.pkg.sampleRate = 44100
        rs.pkg.bitDepth = 24
        for (k, v) in [("album", "Night Drive"), ("release_date", "2026-12-01"), ("composer", "Andrei"),
                       ("label", "Neon Records"), ("copyright", "2026 Andrei")] {
            rs.metaStr(k).wrappedValue = v
        }
        for step in [ReleaseStep.superres, .refmaster, .cover, .detect, .package] { await rs.run(step) }
        await rs.refreshDoctor()
        store.mode = .release
        await shot(store, "app-release.png", out)
        await shotView(RegenerateSheet(target: RegenTarget(path: track.str("path"), title: "Night Drive", lyrics: lyrics))
                           .environmentObject(store), "app-regenerate.png", NSSize(width: 820, height: 560), out)
        await shotView(ReleaseShowcase(rs: rs).environmentObject(store), "app-release-steps.png", NSSize(width: 900, height: 640), out)
        await shotView(PackageShowcase(rs: rs).environmentObject(store), "app-release-package.png", NSSize(width: 900, height: 620), out)
        await shotView(AIModelsSettings().environmentObject(store), "app-ai-models.png", NSSize(width: 760, height: 600), out)
        await shotView(PublishingSettings().environmentObject(store), "app-publishing.png", NSSize(width: 760, height: 600), out)

        L10n.isRussian = true
        store.langCode = "ru"
        await store.reloadLocalized()
        store.mode = .stage
        await shot(store, "app-stage-ru.png", out)
        store.mode = .mixer
        await shot(store, "app-mixer-ru.png", out)
        await shotView(PackageShowcase(rs: rs).environmentObject(store), "app-release-package-ru.png", NSSize(width: 900, height: 620), out)

        store.engine.stop()
        try? FileManager.default.removeItem(at: root)
        active = false
        print("screenshots written to \(out.path)")
        return 0
    }

    /// A single view (sheet or settings page) rendered on its own.
    private static func shotView<V: View>(_ view: V, _ name: String, _ size: NSSize, _ dir: URL) async {
        let win = NSWindow(contentRect: NSRect(origin: NSPoint(x: -20000, y: -20000), size: size),
                           styleMask: [.borderless], backing: .buffered, defer: false)
        win.appearance = NSAppearance(named: .darkAqua)
        win.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height).background(Theme.bg1))
        host.frame = NSRect(origin: .zero, size: size)
        win.contentView = host
        win.orderFrontRegardless()
        try? await Task.sleep(nanoseconds: 2_000_000_000)
        host.layoutSubtreeIfNeeded()
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return }
        rep.size = size
        host.cacheDisplay(in: host.bounds, to: rep)
        if let data = rep.representation(using: .png, properties: [:]) {
            try? data.write(to: dir.appendingPathComponent(name))
            print("wrote \(name) (\(data.count / 1024) KB)")
        }
        win.orderOut(nil)
        win.contentView = nil
    }

    private static func shot(_ store: StudioStore, _ name: String, _ dir: URL) async {
        store.toast = nil
        let size = NSSize(width: 1440, height: 900)
        let win = NSWindow(contentRect: NSRect(origin: NSPoint(x: -20000, y: -20000), size: size),
                           styleMask: [.borderless], backing: .buffered, defer: false)
        win.appearance = NSAppearance(named: .darkAqua)
        win.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: RootView().environmentObject(store).frame(width: size.width, height: size.height))
        host.frame = NSRect(origin: .zero, size: size)
        win.contentView = host
        win.orderFrontRegardless()
        try? await Task.sleep(nanoseconds: 1_400_000_000)
        if store.toast != nil {               // a late notification would cover the content
            store.toast = nil
            try? await Task.sleep(nanoseconds: 600_000_000)
        }
        host.layoutSubtreeIfNeeded()
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return }
        rep.size = size
        host.cacheDisplay(in: host.bounds, to: rep)
        if let data = rep.representation(using: .png, properties: [:]) {
            try? data.write(to: dir.appendingPathComponent(name))
            print("wrote \(name) (\(data.count / 1024) KB)")
        }
        win.orderOut(nil)
        win.contentView = nil
    }
}

/// The three window buttons, drawn only in README screenshots (the live window has the real ones here).
struct ScreenshotTrafficLights: View {
    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(Color(hex: "#FF5F57")).frame(width: 12, height: 12)
            Circle().fill(Color(hex: "#FEBC2E")).frame(width: 12, height: 12)
            Circle().fill(Color(hex: "#28C840")).frame(width: 12, height: 12)
        }
        .padding(.leading, 10)
    }
}
