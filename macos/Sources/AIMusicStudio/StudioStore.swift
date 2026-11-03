import SwiftUI
import AppKit
import UniformTypeIdentifiers

enum AppMode: String, CaseIterable, Identifiable {
    case generate, stage, mixer, master, release
    var id: String { rawValue }
    var title: String {
        switch self {
        case .generate: return T("Generate", "Генерация")
        case .stage: return T("Stage", "Сцена")
        case .mixer: return T("Mixer", "Микшер")
        case .master: return T("Master & Export", "Мастер и экспорт")
        case .release: return T("Release & Publish", "Релиз и публикация")
        }
    }
    var icon: String {
        switch self {
        case .generate: return "wand.and.stars"
        case .stage: return "person.3"
        case .mixer: return "slider.vertical.3"
        case .master: return "waveform"
        case .release: return "paperplane"
        }
    }
    var shortcut: KeyEquivalent {
        switch self {
        case .generate: return "1"
        case .stage: return "2"
        case .mixer: return "3"
        case .master: return "4"
        case .release: return "5"
        }
    }
}

enum EngineState: Equatable {
    case idle, detecting, starting, ready
    case needsSetup(String)
    case failed(String)

    var isReady: Bool { self == .ready }
    var label: String {
        switch self {
        case .idle: return T("Engine idle", "Движок не запущен")
        case .detecting: return T("Looking for Python…", "Поиск Python…")
        case .starting: return T("Starting engine…", "Запуск движка…")
        case .ready: return T("Engine ready", "Движок готов")
        case .needsSetup: return T("Engine setup needed", "Нужна настройка движка")
        case .failed: return T("Engine error", "Ошибка движка")
        }
    }
}

struct GenerateForm: Equatable {
    var engine = "demo"
    var model = ""
    var title = ""
    var style = ""
    var lyrics = ""
    var instrumental = false
    var duration: Double = 60
    var autoBpm = true
    var bpm: Double = 110
    var key = ""
    var timeSignature = "4"
    var language = "en"
    var randomSeed = true
    var seed: Double = 42
    var variations: Double = 1
    var extra: [String: JSONValue] = [:]
}

struct Toast: Identifiable, Equatable {
    let id = UUID()
    let text: String
    var isError = false
}

@MainActor
final class StudioStore: ObservableObject {
    /// The store of the running app (menu commands, the key monitor and the app delegate use it).
    static weak var shared: StudioStore?

    // MARK: engine
    @Published var engineState: EngineState = .idle
    @Published var info: JSONValue = .null
    @Published var pythonPath = ""
    @Published var pythonVersion = ""
    @Published var engineVersion = ""
    @Published var engineDir: URL?
    @Published var pythonCandidates: [PythonCandidate] = []
    @Published var setupLog: [String] = []
    @Published var settingUp = false
    let engine = EngineClient()
    let player = AudioPlayer()
    lazy var releases = ReleaseStore(studio: self)
    lazy var recorder = Recorder(studio: self)
    /// Song or mix opened in the "Regenerate part" sheet.
    @Published var regenTarget: RegenTarget?
    @Published var showRecorder = false

    // MARK: preferences
    @Published var languageSetting: String {
        didSet {
            UserDefaults.standard.set(languageSetting, forKey: "language")
            applyLanguage()
        }
    }
    @Published var langCode: String = L10n.code
    @Published var projectRoot: URL {
        didSet { UserDefaults.standard.set(projectRoot.path, forKey: "projectRoot") }
    }
    @Published var previewLength: Double {
        didSet { UserDefaults.standard.set(previewLength, forKey: "previewLength") }
    }
    @Published var liveMonitor: Bool {
        didSet { UserDefaults.standard.set(liveMonitor, forKey: "liveMonitor") }
    }
    @Published var autosave: Bool {
        didSet { UserDefaults.standard.set(autosave, forKey: "autosave") }
    }
    @Published var stemMethod: String {
        didSet { UserDefaults.standard.set(stemMethod, forKey: "stemMethod") }
    }

    // MARK: UI
    @Published var mode: AppMode = .generate
    @Published var selectedChannel: String?
    @Published var toast: Toast?
    @Published var alertText: String?
    @Published var busyText: String?
    @Published var busyProgress: Double?
    @Published var showSidebar = true
    @Published var showInspector = true

    // MARK: library
    @Published var library: JSONValue = .null
    @Published var librarySearch = ""

    // MARK: session
    @Published var session: JSONValue?
    @Published var sessionPath: String?
    @Published var describe: JSONValue = .null
    @Published var dirty = false
    @Published private(set) var canUndo = false
    @Published private(set) var canRedo = false
    private var undoStack: [JSONValue] = []
    private var redoStack: [JSONValue] = []
    private var lastUndoPush = Date.distantPast
    /// Continuous gestures (a knob or fader drag, a stage drag, typing) share one undo step per group;
    /// discrete edits (toggles, pickers, scene changes) always start a new step.
    private var lastUndoGroup: String?
    @Published var pendingRoom: (Double, Double, Double)?

    // MARK: transport / preview
    @Published var loopStart: Double = 0
    @Published var songDuration: Double = 0
    @Published var waveform: JSONValue = .null
    @Published var previewing = false
    @Published var previewStale = true
    @Published var previewReport: JSONValue = .null
    @Published var previewStart: Double = 0
    @Published var listenSource = false              // A/B: original mix instead of the studio preview
    @Published var nowPlayingTitle = ""
    /// Fixed playhead for meters while stopped (used by --screenshots to show real levels).
    @Published var meterSnapshotTime: Double?
    private var lastPreviewPath: String?
    private var previewSerial = 0

    // MARK: render
    @Published var renderProgress: Double?
    @Published var renderMessage = ""
    @Published var lastRender: JSONValue = .null
    @Published var exportStems = false

    // MARK: generation
    @Published var form = GenerateForm()
    @Published var generating = false
    @Published var genProgress: Double = 0
    @Published var genMessage = ""
    @Published var genResults: [JSONValue] = []
    @Published var engineStatus: [String: JSONValue] = [:]
    @Published var models: [JSONValue] = []
    @Published var schema: [JSONValue] = []
    @Published var price: String?

    // MARK: secrets (Keychain) and generator endpoints
    @Published var acestepURL: String {
        didSet { UserDefaults.standard.set(acestepURL, forKey: "acestepURL") }
    }

    private var previewTask: Task<Void, Never>?
    private var describeTask: Task<Void, Never>?
    private var saveTask: Task<Void, Never>?
    private var roomTask: Task<Void, Never>?
    private var toastTask: Task<Void, Never>?

    init(projectRoot: URL? = nil) {
        let d = UserDefaults.standard
        languageSetting = d.string(forKey: "language") ?? "system"
        if let r = projectRoot {
            self.projectRoot = r
        } else if let p = d.string(forKey: "projectRoot"), !p.isEmpty {
            self.projectRoot = URL(fileURLWithPath: p, isDirectory: true)
        } else {
            self.projectRoot = AppPaths.defaultProjectRoot()
        }
        previewLength = d.object(forKey: "previewLength") as? Double ?? 20
        liveMonitor = d.object(forKey: "liveMonitor") as? Bool ?? true
        autosave = d.object(forKey: "autosave") as? Bool ?? true
        stemMethod = d.string(forKey: "stemMethod") ?? "auto"
        acestepURL = d.string(forKey: "acestepURL") ?? (ProcessInfo.processInfo.environment["ACESTEP_API_URL"] ?? "")
        L10n.isRussian = L10n.resolve(languageSetting)
        langCode = L10n.code
        form.language = L10n.isRussian ? "ru" : "en"
        engine.onExit = { [weak self] code, tail in self?.engineExited(code: code, tail: tail) }
        StudioStore.shared = self
    }

    // MARK: - Engine lifecycle

    func bootstrap() async {
        guard engineState == .idle else { return }
        await startEngine()
    }

    func startEngine() async {
        engineState = .detecting
        let d = UserDefaults.standard
        let pyOverride = d.string(forKey: "pythonPath")
        let dir = EngineLocator.engineDir(override: d.string(forKey: "engineDir"))
        engineDir = dir
        guard let dir else {
            engineState = .failed(T("Engine files (studio/engine_server.py) were not found. Choose the engine folder in Settings → Engine.",
                                    "Файлы движка (studio/engine_server.py) не найдены. Укажите папку движка в Настройки → Движок."))
            return
        }
        let found = await Task.detached { EngineLocator.detect(engineDir: dir, override: pyOverride) }.value
        pythonCandidates = found.all
        guard let py = found.best else {
            if found.all.isEmpty {
                engineState = .needsSetup(T("Python 3.9 or newer was not found on this Mac.",
                                            "На этом Mac не найден Python 3.9 или новее."))
            } else {
                let miss = Set(found.all.flatMap { $0.missing }).sorted().joined(separator: ", ")
                engineState = .needsSetup(T("Python was found, but the engine packages are missing: \(miss).",
                                            "Python найден, но не хватает пакетов движка: \(miss)."))
            }
            return
        }
        pythonPath = py.path
        pythonVersion = py.version
        engineState = .starting
        do {
            let ready = try await engine.start(.init(python: py.path, engineDir: dir.path, language: L10n.code))
            engineVersion = ready.str("version")
            try await pushConfig()
            info = try await engine.call("info", ["lang": .s(L10n.code)])
            engineState = .ready
            try? FileManager.default.createDirectory(at: projectRoot, withIntermediateDirectories: true)
            await refreshLibrary()
            await refreshGenerator()
        } catch {
            engineState = .failed(error.localizedDescription)
        }
    }

    func restartEngine() async {
        engine.stop()
        engineState = .idle
        await startEngine()
    }

    private func engineExited(code: Int32, tail: String) {
        guard engineState == .ready else { return }
        engineState = .failed(T("The engine stopped unexpectedly (code \(code)).", "Движок неожиданно остановился (код \(code)).")
                              + (tail.isEmpty ? "" : "\n" + tail))
        previewing = false
        generating = false
        renderProgress = nil
        busyText = nil
    }

    func pushConfig() async throws {
        var p: [String: JSONValue] = ["lang": .s(L10n.code)]
        if !acestepURL.isEmpty { p["acestep_url"] = .s(acestepURL) }
        if let k = Keychain.get("acestep_key"), !k.isEmpty { p["acestep_key"] = .s(k) }
        if let k = Keychain.get("gptunnel_key"), !k.isEmpty { p["gptunnel_key"] = .s(k) }
        p["secrets"] = .object(Self.publishSecrets())
        p["tools"] = ToolSettings.load().payload
        _ = try await engine.call("config.set", p)
    }

    /// Keychain account → engine variable. Values never leave the engine process.
    static let secretAccounts: [(account: String, env: String)] = [
        ("telegram_token", "TELEGRAM_BOT_TOKEN"), ("telegram_chat", "TELEGRAM_CHAT_ID"),
        ("youtube_client_id", "YOUTUBE_CLIENT_ID"), ("youtube_client_secret", "YOUTUBE_CLIENT_SECRET"),
        ("youtube_refresh", "YOUTUBE_REFRESH_TOKEN"), ("sightengine_user", "SIGHTENGINE_API_USER"),
        ("sightengine_secret", "SIGHTENGINE_API_SECRET"), ("acrcloud_token", "ACRCLOUD_TOKEN"),
        ("acrcloud_container", "ACRCLOUD_CONTAINER_ID"), ("acrcloud_region", "ACRCLOUD_REGION"),
    ]

    static func publishSecrets() -> [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        for (acc, env) in secretAccounts {
            if let v = Keychain.get(acc), !v.isEmpty { out[env] = .s(v) }
        }
        return out
    }

    /// Saves (or with an empty string removes) publishing/detector secrets and pushes them to the engine.
    func savePublishSecrets(_ values: [String: String]) async {
        var push: [String: JSONValue] = [:]
        for (acc, env) in Self.secretAccounts {
            guard let v = values[acc] else { continue }
            Keychain.set(acc, v)
            push[env] = .s(v)
        }
        guard engineState.isReady else { return }
        do {
            _ = try await engine.call("config.set", ["secrets": .object(push)])
            await releases.refreshDoctor()
            show(T("Settings saved", "Настройки сохранены"))
        } catch { fail(error) }
    }

    func pushToolSettings(_ t: ToolSettings) async {
        t.save()
        guard engineState.isReady else { return }
        do {
            _ = try await engine.call("config.set", ["tools": t.payload])
            await releases.refreshDoctor()
        } catch { fail(error) }
    }

    func saveSecrets(acestepKey: String?, gptunnelKey: String?) async {
        if let a = acestepKey { Keychain.set("acestep_key", a) }
        if let g = gptunnelKey { Keychain.set("gptunnel_key", g) }
        guard engineState.isReady else { return }
        do {
            var p: [String: JSONValue] = ["acestep_url": .s(acestepURL)]
            if let a = acestepKey { p["acestep_key"] = .s(a) }
            if let g = gptunnelKey { p["gptunnel_key"] = .s(g) }
            _ = try await engine.call("config.set", p)
            await refreshGenerator()
            show(T("Settings saved", "Настройки сохранены"))
        } catch { fail(error) }
    }

    private func applyLanguage() {
        L10n.isRussian = L10n.resolve(languageSetting)
        langCode = L10n.code
        Task { await reloadLocalized() }
    }

    /// Re-reads everything the engine localizes (scene, mic and engine names, status texts).
    /// Channels that still carry a default instrument name are renamed to the new language;
    /// names the user typed stay as they are.
    func reloadLocalized() async {
        guard engineState.isReady else { return }
        _ = try? await engine.call("config.set", ["lang": .s(L10n.code)])
        if let i = try? await engine.call("info", ["lang": .s(L10n.code)]) { info = i }
        if session != nil {
            let wasStale = previewStale
            await sessionOp("localize_names")
            previewStale = wasStale          // names do not change the sound
        }
        await refreshDescribe()
        await refreshGenerator()
    }

    // MARK: - Python environment setup

    var requirementsFile: URL? {
        guard let dir = engineDir else { return nil }
        for name in ["requirements-engine.txt", "../requirements-engine.txt"] {
            let u = dir.appendingPathComponent(name).standardizedFileURL
            if FileManager.default.fileExists(atPath: u.path) { return u }
        }
        return nil
    }

    /// Creates ~/Library/Application Support/AI Music Studio/venv and installs the pinned engine packages.
    func setupEnvironment() async {
        guard let req = requirementsFile else {
            alertText = T("requirements-engine.txt was not found next to the engine.", "Рядом с движком нет requirements-engine.txt.")
            return
        }
        let base = pythonCandidates.first { !$0.path.hasPrefix(AppPaths.managedVenv.path) }?.path
        guard let base else {
            alertText = T("Install Python 3.11 first (python.org or `brew install python@3.11`), then press Retry.",
                          "Сначала установите Python 3.11 (python.org или `brew install python@3.11`), затем нажмите «Повторить».")
            return
        }
        settingUp = true
        setupLog = ["$ \(base) -m venv \(AppPaths.managedVenv.path)"]
        let venv = AppPaths.managedVenv.path
        let py = AppPaths.managedPython.path
        let ok = await Task.detached { [self] () -> Bool in
            try? FileManager.default.createDirectory(at: AppPaths.appSupport, withIntermediateDirectories: true)
            guard EngineLocator.run(base, ["-m", "venv", venv], timeout: 180) != nil else { return false }
            let log: (String) -> Void = { line in Task { @MainActor [weak self] in self?.appendSetup(line) } }
            log("$ \(py) -m pip install -r \(req.path)")
            let out = EngineLocator.run(py, ["-m", "pip", "install", "--disable-pip-version-check", "-r", req.path],
                                        timeout: 1800, onLine: log)
            return out != nil
        }.value
        settingUp = false
        if ok {
            appendSetup(T("Done. Starting the engine…", "Готово. Запускаю движок…"))
            UserDefaults.standard.set(py, forKey: "pythonPath")
            await startEngine()
        } else {
            appendSetup(T("Setup failed — see the log above.", "Установка не удалась — смотрите журнал выше."))
        }
    }

    private func appendSetup(_ line: String) {
        setupLog.append(line)
        if setupLog.count > 400 { setupLog.removeFirst(setupLog.count - 400) }
    }

    // MARK: - Catalogs from the engine

    var scenes: [JSONValue] { info.list("scenes") }
    var mics: [JSONValue] { info.list("mics") }
    var instruments: [JSONValue] { info.list("instruments") }
    var patterns: [JSONValue] { info.list("patterns") }
    var preamps: [JSONValue] { info.list("preamps") }
    var tapes: [JSONValue] { info.list("tapes") }
    var ambienceKinds: [JSONValue] { info.list("ambience") }
    var techniques: [JSONValue] { info.list("techniques") }
    var stemMethods: [JSONValue] { info.list("stem_methods") }
    var engines: [JSONValue] { info.list("engines") }
    var formats: [String] { info.list("formats").compactMap { $0.string } }
    var languages: [String] { info.list("languages").compactMap { $0.string } }

    func scene(_ id: String) -> JSONValue? { scenes.first { $0.str("id") == id } }
    func mic(_ id: String) -> JSONValue? { mics.first { $0.str("id") == id } }
    func instrument(_ id: String) -> JSONValue? { instruments.first { $0.str("id") == id } }
    func name(in list: [JSONValue], _ id: String) -> String { list.first { $0.str("id") == id }?.str("name", id) ?? id }
    func defaultValue(_ kind: String, _ key: String) -> JSONValue? { info["defaults"]?[kind]?[key] }

    // MARK: - Library

    func refreshLibrary() async {
        guard engineState.isReady else { return }
        do {
            try? FileManager.default.createDirectory(at: projectRoot, withIntermediateDirectories: true)
            library = try await engine.call("library.scan", ["root": .s(projectRoot.path)])
        } catch { fail(error) }
    }

    var songs: [JSONValue] { filter(library.list("songs"), key: "title") }
    var sessions: [JSONValue] { filter(library.list("sessions"), key: "name") }
    var renders: [JSONValue] { filter(library.list("renders"), key: "name") }

    private func filter(_ items: [JSONValue], key: String) -> [JSONValue] {
        let q = librarySearch.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return items }
        return items.filter { $0.str(key).lowercased().contains(q) }
    }

    func chooseProjectRoot() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.canCreateDirectories = true
        p.prompt = T("Use Folder", "Выбрать папку")
        p.directoryURL = projectRoot
        if p.runModal() == .OK, let u = p.url {
            projectRoot = u
            Task { await refreshLibrary() }
        }
    }

    func reveal(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    // MARK: - Listening to files

    func listen(_ path: String, title: String) {
        do {
            try player.load(URL(fileURLWithPath: path), timelineStart: 0, keepPosition: false, autoplay: true)
            nowPlayingTitle = title
            lastPreviewPath = nil
        } catch { fail(error) }
    }

    // MARK: - Generation

    func refreshGenerator() async {
        guard engineState.isReady else { return }
        let id = form.engine
        if let st = try? await engine.call("engine.status", ["engine": .s(id)]) { engineStatus[id] = st }
        do {
            let r = try await engine.call("engine.models", ["engine": .s(id), "model": .s(form.model)])
            models = r.list("models")
            let m = r.str("model")
            if form.model.isEmpty || !models.contains(where: { $0.str("id") == form.model }) { form.model = m }
            schema = r.list("schema")
            var extra: [String: JSONValue] = [:]
            for f in schema { extra[f.str("key")] = form.extra[f.str("key")] ?? f["default"] ?? .null }
            form.extra = extra
        } catch {
            models = []
            schema = []
        }
        price = nil
    }

    func selectEngine(_ id: String) {
        guard form.engine != id else { return }
        form.engine = id
        form.model = ""
        form.extra = [:]
        Task { await refreshGenerator() }
    }

    func selectModel(_ id: String) {
        form.model = id
        Task {
            if let r = try? await engine.call("engine.schema", ["engine": .s(form.engine), "model": .s(id)]) {
                schema = r.list("schema")
                var extra: [String: JSONValue] = [:]
                for f in schema { extra[f.str("key")] = f["default"] ?? .null }
                form.extra = extra
            }
        }
    }

    private var generationRequest: JSONValue {
        var r: [String: JSONValue] = [
            "title": .s(form.title.isEmpty ? T("Untitled", "Без названия") : form.title),
            "style": .s(form.style), "lyrics": .s(form.lyrics), "instrumental": .b(form.instrumental),
            "duration": .n(form.duration.rounded()), "key": .s(form.key), "time_signature": .s(form.timeSignature),
            "language": .s(form.language), "variations": .n(Int(form.variations)), "model": .s(form.model),
            "extra": .object(form.extra.filter { !$0.value.isNull }),
        ]
        r["bpm"] = form.autoBpm ? .null : .n(Int(form.bpm))
        r["seed"] = form.randomSeed ? .null : .n(Int(form.seed))
        return .object(r)
    }

    func estimatePrice() async {
        do {
            let r = try await engine.call("engine.price", ["engine": .s(form.engine), "request": generationRequest])
            price = r["price"]?.string ?? T("No price for this engine", "Для этого движка цены нет")
        } catch { price = error.localizedDescription }
    }

    func generate() async {
        guard engineState.isReady, !generating else { return }
        generating = true
        genProgress = 0
        genMessage = T("Starting…", "Запуск…")
        do {
            let r = try await engine.call("generate", ["engine": .s(form.engine), "root": .s(projectRoot.path),
                                                       "request": generationRequest, "_group": "generate"]) { [weak self] f, m in
                self?.genProgress = f
                if !m.isEmpty { self?.genMessage = m }
            }
            genResults = r.list("tracks")
            genMessage = T("Done: \(genResults.count) track(s)", "Готово: треков — \(genResults.count)")
            genProgress = 1
            await refreshLibrary()
            show(genMessage)
        } catch let e as EngineError where e.isCancelled {
            genMessage = T("Cancelled", "Отменено")
        } catch {
            genMessage = error.localizedDescription
            fail(error)
        }
        generating = false
    }

    func cancelGeneration() {
        Task { _ = try? await engine.call("cancel", ["group": "generate"]) }
    }

    // MARK: - Sessions

    func openTrack(_ track: JSONValue, fresh: Bool = false) async {
        let side = track.str("sidecar")
        let path = !side.isEmpty && FileManager.default.fileExists(atPath: side) ? side : track.str("path")
        await openAudio(path, title: track.str("title"), fresh: fresh)
    }

    func openAudio(_ path: String, title: String, fresh: Bool = false, method: String? = nil) async {
        guard engineState.isReady else { return }
        busyText = T("Preparing session for “\(title)”…", "Готовлю сессию «\(title)»…")
        busyProgress = 0
        defer { busyText = nil; busyProgress = nil }
        do {
            let r = try await engine.call("session.open_track", [
                "path": .s(path), "root": .s(projectRoot.path), "method": .s(method ?? stemMethod), "fresh": .b(fresh),
            ]) { [weak self] f, m in
                self?.busyProgress = f
                if !m.isEmpty { self?.busyText = m }
            }
            guard let s = r["session"] else { return }
            setSession(s, path: r["path"]?.string)
            if mode == .generate { mode = .stage }
            await refreshLibrary()
        } catch { fail(error) }
    }

    func openSession(_ path: String) async {
        guard engineState.isReady else { return }
        do {
            let r = try await engine.call("session.load", ["path": .s(path)])
            guard let s = r["session"] else { return }
            setSession(s, path: r["path"]?.string ?? path)
            if mode == .generate { mode = .stage }
        } catch { fail(error) }
    }

    func importAudio(method: String) {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.allowsMultipleSelection = false
        p.prompt = T("Import", "Импорт")
        guard p.runModal() == .OK, let u = p.url else { return }
        Task { await openAudio(u.path, title: u.deletingPathExtension().lastPathComponent, fresh: false, method: method) }
    }

    func newSessionFromStems() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.allowsMultipleSelection = true
        p.message = T("Choose the stems (one file per instrument)", "Выберите стемы (по файлу на инструмент)")
        p.prompt = T("Create Session", "Создать сессию")
        guard p.runModal() == .OK, !p.urls.isEmpty else { return }
        let name = p.urls[0].deletingLastPathComponent().lastPathComponent
        Task {
            do {
                let r = try await engine.call("session.new", ["name": .s(name), "scene": "studio_a",
                                                              "sources": .array(p.urls.map { .s($0.path) })])
                guard var s = r["session"] else { return }
                s.updateObject("meta") { $0["title"] = .s(name) }
                setSession(s, path: nil)
                await saveSession()
                mode = .stage
                await refreshLibrary()
            } catch { fail(error) }
        }
    }

    func setSession(_ s: JSONValue, path: String?) {
        session = s
        sessionPath = path
        undoStack = []
        redoStack = []
        updateUndoFlags()
        dirty = false
        selectedChannel = nil
        loopStart = 0
        previewStale = true
        previewReport = .null
        lastPreviewPath = nil
        listenSource = false
        player.unload()
        nowPlayingTitle = sessionTitle
        Task {
            await refreshDescribe()
            await loadWaveform()
        }
    }

    func closeSession() {
        Task {
            if dirty { await saveSession() }
            session = nil
            sessionPath = nil
            describe = .null
            waveform = .null
            previewReport = .null
            player.unload()
        }
    }

    var sessionTitle: String {
        guard let s = session else { return "" }
        let t = s["meta"]?.str("title") ?? ""
        return t.isEmpty ? s.str("name", T("Session", "Сессия")) : t
    }

    var sourceMixPath: String? {
        guard let s = session else { return nil }
        if let src = s["meta"]?["source"]?.string, FileManager.default.fileExists(atPath: src) { return src }
        return s.channels.first.map { $0.str("source") }
    }

    func loadWaveform() async {
        guard let path = sourceMixPath else { waveform = .null; songDuration = 0; return }
        do {
            waveform = try await engine.call("analyze", ["path": .s(path), "points": 1600])
            songDuration = waveform.num("duration")
        } catch {
            waveform = .null
        }
    }

    func saveSession() async {
        guard let s = session, engineState.isReady else { return }
        let path: String
        if let sp = sessionPath {
            path = sp
        } else {
            let safe = sessionTitle.map { $0.isLetter || $0.isNumber || " -_()".contains($0) ? $0 : "_" }
            path = projectRoot.appendingPathComponent("sessions").appendingPathComponent(String(safe))
                .appendingPathComponent("session.studio.json").path
        }
        do {
            let r = try await engine.call("session.save", ["session": s, "path": .s(path)])
            sessionPath = r.str("path", path)
            if session == s { dirty = false }
        } catch { fail(error) }
    }

    // MARK: - Editing (undo-aware)

    func mutate(_ group: String? = nil, _ f: (inout JSONValue) -> Void) {
        guard var s = session else { return }
        let before = s
        f(&s)
        guard s != before else { return }
        pushUndo(before, group: group)
        session = s
        sessionDidChange()
    }

    private func pushUndo(_ before: JSONValue, group: String?) {
        let now = Date()
        let continues = group != nil && group == lastUndoGroup && now.timeIntervalSince(lastUndoPush) < 0.7
        if !continues {
            undoStack.append(before)
            if undoStack.count > 200 { undoStack.removeFirst() }
            redoStack.removeAll()
            updateUndoFlags()
        }
        lastUndoPush = now
        lastUndoGroup = group
    }

    private func updateUndoFlags() {
        canUndo = !undoStack.isEmpty
        canRedo = !redoStack.isEmpty
    }

    func undo() {
        guard let prev = undoStack.popLast(), let cur = session else { return }
        redoStack.append(cur)
        session = prev
        lastUndoPush = .distantPast
        lastUndoGroup = nil
        updateUndoFlags()
        sessionDidChange()
    }

    func redo() {
        guard let next = redoStack.popLast(), let cur = session else { return }
        undoStack.append(cur)
        session = next
        lastUndoPush = .distantPast
        lastUndoGroup = nil
        updateUndoFlags()
        sessionDidChange()
    }

    func replaceSession(_ ns: JSONValue) {
        guard let cur = session, ns != cur else { return }
        pushUndo(cur, group: nil)
        session = ns
        sessionDidChange()
    }

    private func sessionDidChange() {
        dirty = true
        previewStale = true
        scheduleDescribe()
        if autosave { scheduleSave() }
        if liveMonitor && player.isPlaying && !listenSource { schedulePreview(after: 0.22) }
    }

    func sessionOp(_ op: String, _ args: [String: JSONValue] = [:]) async {
        guard let s = session, engineState.isReady else { return }
        do {
            let r = try await engine.call("session.op", ["session": s, "op": .s(op), "args": .object(args)])
            if let ns = r["session"] { replaceSession(ns) }
        } catch { fail(error) }
    }

    func setScene(_ id: String) { Task { await sessionOp("set_scene", ["scene": .s(id), "keep_layout": true]) } }
    func resetLayout() { Task { await sessionOp("reset_layout") } }
    func applyInstrument(_ ch: String, _ inst: String) {
        Task { await sessionOp("apply_instrument", ["channel": .s(ch), "instrument": .s(inst)]) }
    }
    func duplicateChannel(_ ch: String) { Task { await sessionOp("duplicate_channel", ["channel": .s(ch)]) } }
    func removeChannel(_ ch: String) {
        if selectedChannel == ch { selectedChannel = nil }
        Task { await sessionOp("remove_channel", ["channel": .s(ch)]) }
    }

    func addChannels() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.allowsMultipleSelection = true
        p.prompt = T("Add", "Добавить")
        guard p.runModal() == .OK else { return }
        Task {
            for u in p.urls { await sessionOp("add_channel", ["source": .s(u.path)]) }
        }
    }

    // room size: debounced engine op (positions scale with the room)
    var roomSize: (Double, Double, Double) {
        if let p = pendingRoom { return p }
        let r = describe["room"]
        return (r?.num("width", 9) ?? 9, r?.num("depth", 7) ?? 7, r?.num("height", 3.6) ?? 3.6)
    }

    func setRoomSize(width: Double? = nil, depth: Double? = nil, height: Double? = nil) {
        var cur = roomSize
        if let width { cur.0 = width }
        if let depth { cur.1 = depth }
        if let height { cur.2 = height }
        pendingRoom = cur
        roomTask?.cancel()
        roomTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard !Task.isCancelled, let self, let p = self.pendingRoom else { return }
            await self.sessionOp("set_room_size", ["width": .n(p.0), "depth": .n(p.1), "height": .n(p.2)])
            await self.refreshDescribe()
            if self.pendingRoom.map({ $0 == p }) ?? false { self.pendingRoom = nil }
        }
    }

    func resetRoomSize() {
        pendingRoom = nil
        Task { await sessionOp("set_room_size", ["width": nil, "depth": nil, "height": nil]) }
    }

    private func scheduleDescribe() {
        describeTask?.cancel()
        describeTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 90_000_000)
            guard !Task.isCancelled else { return }
            await self?.refreshDescribe()
        }
    }

    func refreshDescribe() async {
        guard let s = session, engineState.isReady else { return }
        if let d = try? await engine.call("session.describe", ["session": s]) { describe = d }
    }

    private func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            await self?.saveSession()
        }
    }

    // MARK: - Bindings into the session JSON

    func chNum(_ id: String, _ key: String) -> Binding<Double> {
        Binding(get: { [weak self] in
            guard let self else { return 0 }
            return self.session?.channel(id)?[key]?.double ?? self.defaultValue("channel", key)?.double ?? 0
        }, set: { [weak self] v in
            self?.mutate("ch.\(id)") { $0.updateChannel(id) { $0[key] = .number(v) } }
        })
    }

    func chBool(_ id: String, _ key: String) -> Binding<Bool> {
        Binding(get: { [weak self] in
            guard let self else { return false }
            return self.session?.channel(id)?[key]?.bool ?? self.defaultValue("channel", key)?.bool ?? false
        }, set: { [weak self] v in
            self?.mutate { $0.updateChannel(id) { $0[key] = .bool(v) } }
        })
    }

    func chStr(_ id: String, _ key: String) -> Binding<String> {
        Binding(get: { [weak self] in
            guard let self else { return "" }
            return self.session?.channel(id)?[key]?.string ?? self.defaultValue("channel", key)?.string ?? ""
        }, set: { [weak self] v in
            self?.mutate { $0.updateChannel(id) { $0[key] = .string(v) } }
        })
    }

    /// Pan: null in the session means "follow the stage position".
    func chPanAuto(_ id: String) -> Binding<Bool> {
        Binding(get: { [weak self] in
            self?.session?.channel(id)?["pan"]?.isNull ?? true
        }, set: { [weak self] auto in
            guard let self else { return }
            let autoPan = self.describe["channels"]?[id]?.num("auto_pan") ?? 0
            self.mutate { $0.updateChannel(id) { $0["pan"] = auto ? .null : .number((autoPan * 100).rounded() / 100) } }
        })
    }

    func chPan(_ id: String) -> Binding<Double> {
        Binding(get: { [weak self] in
            guard let self else { return 0 }
            if let p = self.session?.channel(id)?["pan"]?.double { return p }
            return self.describe["channels"]?[id]?.num("auto_pan") ?? 0
        }, set: { [weak self] v in
            self?.mutate("ch.\(id)") { $0.updateChannel(id) { $0["pan"] = .number(v) } }
        })
    }

    func recNum(_ key: String) -> Binding<Double> {
        Binding(get: { [weak self] in
            guard let self else { return 0 }
            return self.session?["recording"]?[key]?.double ?? self.defaultValue("recording", key)?.double ?? 0
        }, set: { [weak self] v in
            self?.mutate("rec") { $0.updateObject("recording") { $0[key] = .number(v) } }
        })
    }

    func recBool(_ key: String) -> Binding<Bool> {
        Binding(get: { [weak self] in
            guard let self else { return false }
            return self.session?["recording"]?[key]?.bool ?? self.defaultValue("recording", key)?.bool ?? false
        }, set: { [weak self] v in
            self?.mutate { $0.updateObject("recording") { $0[key] = .bool(v) } }
        })
    }

    func recStr(_ key: String) -> Binding<String> {
        Binding(get: { [weak self] in
            guard let self else { return "" }
            return self.session?["recording"]?[key]?.string ?? self.defaultValue("recording", key)?.string ?? ""
        }, set: { [weak self] v in
            self?.mutate { $0.updateObject("recording") { $0[key] = .string(v) } }
        })
    }

    func sesNum(_ key: String) -> Binding<Double> {
        Binding(get: { [weak self] in
            guard let self else { return 0 }
            return self.session?[key]?.double ?? self.defaultValue("session", key)?.double ?? 0
        }, set: { [weak self] v in
            self?.mutate("ses") { $0[key] = .number(v) }
        })
    }

    func sesStr(_ key: String, fallback: String = "") -> Binding<String> {
        Binding(get: { [weak self] in
            self?.session?[key]?.string ?? fallback
        }, set: { [weak self] v in
            self?.mutate("ses.\(key)") { $0[key] = v.isEmpty ? .null : .string(v) }
        })
    }

    func metaStr(_ key: String) -> Binding<String> {
        Binding(get: { [weak self] in
            self?.session?["meta"]?[key]?.string ?? ""
        }, set: { [weak self] v in
            self?.mutate("meta.\(key)") { $0.updateObject("meta") { $0[key] = .string(v) } }
        })
    }

    /// Moves a musician (or the listener when id == nil) on the stage plan, in meters.
    func move(_ id: String?, x: Double, y: Double) {
        let (w, d, _) = roomSize
        let cx = min(max(x, 0.3), w - 0.3), cy = min(max(y, 0.3), d - 0.3)
        mutate("move.\(id ?? "listener")") { s in
            if let id {
                s.updateChannel(id) { $0["x"] = .number(cx); $0["y"] = .number(cy) }
            } else {
                s["listener_x"] = .number(cx)
                s["listener_y"] = .number(cy)
            }
        }
    }

    func resetListener() {
        mutate { $0["listener_x"] = .null; $0["listener_y"] = .null }
    }

    func toggleSolo(_ id: String) { mutate { s in s.updateChannel(id) { $0["solo"] = .bool(!($0["solo"]?.bool ?? false)) } } }
    func toggleMute(_ id: String) { mutate { s in s.updateChannel(id) { $0["mute"] = .bool(!($0["mute"]?.bool ?? false)) } } }

    // MARK: - Preview and transport

    func togglePlay() {
        if player.isPlaying {
            player.pause()
            return
        }
        guard session != nil else {
            if player.hasAudio { player.play() }
            return
        }
        if listenSource {
            loadSourceRegion(autoplay: true)
        } else if previewStale || lastPreviewPath == nil || player.loaded?.path != lastPreviewPath {
            Task { await renderPreview(autoplay: true) }
        } else {
            player.play()
        }
    }

    func stopPlayback() {
        player.stop()
    }

    func setListenSource(_ on: Bool) {
        listenSource = on
        guard session != nil else { return }
        if on {
            loadSourceRegion(autoplay: player.isPlaying)
        } else if let p = lastPreviewPath, !previewStale {
            try? player.load(URL(fileURLWithPath: p), timelineStart: previewStart, keepPosition: true)
        } else if player.isPlaying {
            Task { await renderPreview(autoplay: true) }
        }
    }

    private func loadSourceRegion(autoplay: Bool) {
        guard let src = sourceMixPath else { return }
        do {
            try player.load(URL(fileURLWithPath: src), timelineStart: loopStart, keepPosition: true, autoplay: autoplay,
                            region: (loopStart, previewLength))
        } catch { fail(error) }
    }

    func setLoopStart(_ t: Double) {
        let maxStart = max(0, songDuration - min(previewLength, songDuration))
        loopStart = min(max(0, t), maxStart)
        previewStale = true
        if player.isPlaying {
            if listenSource { loadSourceRegion(autoplay: true) } else { schedulePreview(after: 0.05) }
        }
    }

    func schedulePreview(after delay: Double) {
        previewTask?.cancel()
        previewTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            await self?.renderPreview(autoplay: false)
        }
    }

    func renderPreview(autoplay: Bool) async {
        guard let s = session, engineState.isReady else { return }
        previewSerial += 1
        let serial = previewSerial
        previewing = true
        let start = loopStart, len = previewLength
        do {
            let r = try await engine.call("render.preview", ["session": s, "start_s": .n(start), "duration_s": .n(len),
                                                             "_group": "preview"])
            guard serial == previewSerial else { return }
            previewReport = r["report"] ?? .null
            previewStart = start
            let path = r.str("path")
            lastPreviewPath = path
            previewStale = session != s
            if !listenSource {
                try player.load(URL(fileURLWithPath: path), timelineStart: start, keepPosition: true, autoplay: autoplay)
            }
            nowPlayingTitle = sessionTitle
        } catch let e as EngineError where e.isCancelled {
            // replaced by a newer preview
        } catch {
            if serial == previewSerial { fail(error) }
        }
        if serial == previewSerial { previewing = false }
    }

    /// Channel level at the playhead, from the meters in the preview report: (peak, rms, hold) dBFS.
    func meter(channel id: String?, at time: Double) -> (Double, Double, Double) {
        let m = previewReport["meters"]
        let hop = max(m?.num("hop_s", 0.05) ?? 0.05, 0.001)
        let src: JSONValue?
        if let id { src = m?["channels"]?[id] } else { src = m?["master"] }
        let live = player.isPlaying && !listenSource && player.loaded?.path == lastPreviewPath
        let t: Double
        if live { t = time } else if let snap = meterSnapshotTime { t = snap } else { return (-90, -90, -90) }
        guard let src else { return (-90, -90, -90) }
        let idx = Int((t - previewStart) / hop)
        let peaks = src["peak"]?.array ?? [], rms = src["rms"]?.array ?? []
        guard idx >= 0, idx < peaks.count, idx < rms.count else { return (-90, -90, -90) }
        var hold = -90.0
        for i in max(0, idx - 30)...idx { hold = max(hold, peaks[i].double ?? -90) }
        return (peaks[idx].double ?? -90, rms[idx].double ?? -90, hold)
    }

    // MARK: - Final render

    func renderFinal() async {
        guard let s = session, engineState.isReady, renderProgress == nil else { return }
        await saveSession()
        renderProgress = 0
        renderMessage = T("Rendering…", "Рендер…")
        do {
            var p: [String: JSONValue] = ["session": s, "root": .s(projectRoot.path), "export_stems": .b(exportStems),
                                          "_group": "final"]
            if let sp = sessionPath { p["session_path"] = .s(sp) }
            let r = try await engine.call("render.final", p) { [weak self] f, m in
                self?.renderProgress = f
                if !m.isEmpty { self?.renderMessage = m }
            }
            lastRender = r
            await refreshLibrary()
            show(T("Mix saved: ", "Микс сохранён: ") + URL(fileURLWithPath: r.str("path")).lastPathComponent)
        } catch let e as EngineError where e.isCancelled {
            show(T("Render cancelled", "Рендер отменён"))
        } catch { fail(error) }
        renderProgress = nil
    }

    func cancelRender() {
        Task { _ = try? await engine.call("cancel", ["group": "final"]) }
    }

    // MARK: - View helpers

    var channelIDs: [String] { session?.channels.map { $0.str("id") } ?? [] }

    var selectedChannelData: JSONValue? {
        guard let id = selectedChannel else { return nil }
        return session?.channel(id)
    }

    func color(of ch: JSONValue) -> Color { Color(hex: ch.str("color", "#cba6f7")) }

    /// Polar pattern coefficient (1 = omni … 0 = figure-8) of a microphone model.
    func patternA(mic id: String) -> Double? {
        guard let m = mic(id), id != "di" else { return nil }
        return patterns.first { $0.str("id") == m.str("pattern") }?.num("a", 0.5)
    }

    func patternName(mic id: String) -> String {
        guard let m = mic(id) else { return "" }
        return name(in: patterns, m.str("pattern"))
    }

    /// Master loudness of the last preview: integrated LUFS after normalization (or plain LUFS).
    var previewLufs: Double? {
        guard let m = previewReport["master"] else { return nil }
        return m["lufs_after"]?.double ?? m["lufs"]?.double
    }

    var previewTruePeak: Double? { previewReport["master"]?["true_peak_db"]?.double }

    /// True when the player holds audio on the song timeline (studio preview or an A/B region of the source).
    var timelinePlayback: Bool {
        guard session != nil, let p = player.loaded?.path else { return false }
        return p == lastPreviewPath || p == sourceMixPath
    }

    func setChannel(_ id: String, _ key: String, _ value: JSONValue) {
        mutate { $0.updateChannel(id) { $0[key] = value } }
    }

    func setRecording(_ key: String, _ value: JSONValue) {
        mutate { $0.updateObject("recording") { $0[key] = value } }
    }

    // MARK: - Messages

    func show(_ text: String, error: Bool = false) {
        toast = Toast(text: text, isError: error)
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_500_000_000)
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }

    func fail(_ error: Error) {
        if let e = error as? EngineError, e.isCancelled { return }
        show(error.localizedDescription, error: true)
    }
}

