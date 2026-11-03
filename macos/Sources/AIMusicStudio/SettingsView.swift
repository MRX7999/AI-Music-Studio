import SwiftUI
import AppKit

/// App settings (⌘,): general preferences, generator endpoints and keys, Python engine, about.
struct SettingsView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        TabView {
            GeneralSettings()
                .tabItem { Label(T("General", "Основные"), systemImage: "gearshape") }
            GeneratorSettings()
                .tabItem { Label(T("Generators", "Генераторы"), systemImage: "wand.and.stars") }
            AIModelsSettings()
                .tabItem { Label(T("AI Models", "AI-модели"), systemImage: "brain") }
            PublishingSettings()
                .tabItem { Label(T("Publishing", "Публикация"), systemImage: "paperplane") }
            EngineSettings()
                .tabItem { Label(T("Engine", "Движок"), systemImage: "cpu") }
            AboutSettings()
                .tabItem { Label(T("About", "О программе"), systemImage: "info.circle") }
        }
        .frame(width: 760, height: 600)
        .preferredColorScheme(.dark)
        .id(store.langCode)
    }
}

/// Settings page scaffold: dark background, scrollable column of cards.
private struct SettingsPage<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) { content() }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Theme.bg0)
    }
}

// MARK: - General

private struct GeneralSettings: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SettingsPage {
            SectionCard(title: T("Interface", "Интерфейс"), icon: "globe", collapsible: false) {
                PickerRow(label: T("Language", "Язык"), selection: $store.languageSetting,
                          options: AppLanguage.allCases.map { ($0.rawValue, $0.title) }, labelWidth: 150)
                Text(T("English is the default. Engine texts (scenes, mics, statuses) switch together with the interface.",
                       "По умолчанию английский. Тексты движка (сцены, микрофоны, статусы) переключаются вместе с интерфейсом."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            SectionCard(title: T("Project folder", "Папка проекта"), icon: "folder", collapsible: false) {
                HStack {
                    Text(store.projectRoot.path)
                        .font(Theme.monoSmall)
                        .foregroundColor(Theme.text2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                    Spacer()
                    Button(T("Choose…", "Выбрать…")) { store.chooseProjectRoot() }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button(T("Show in Finder", "Показать в Finder")) {
                        try? FileManager.default.createDirectory(at: store.projectRoot, withIntermediateDirectories: true)
                        store.reveal(store.projectRoot.path)
                    }
                    .buttonStyle(StudioButtonStyle(compact: true))
                }
                Text(T("Generated songs, sessions and mixes are stored here: generated/, sessions/, renders/.",
                       "Здесь хранятся песни, сессии и миксы: generated/, sessions/, renders/."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
            }
            SectionCard(title: T("Monitoring", "Прослушивание"), icon: "headphones", collapsible: false) {
                HStack {
                    Text(T("Preview length", "Длина превью")).font(Theme.label).foregroundColor(Theme.text2)
                        .frame(width: 150, alignment: .leading)
                    Segmented(selection: Binding(get: { store.previewLength },
                                                 set: { store.previewLength = $0; store.setLoopStart(store.loopStart) }),
                              options: [(10.0, "10 s"), (20.0, "20 s"), (30.0, "30 s"), (60.0, "60 s")])
                        .frame(width: 240)
                    Spacer()
                }
                ToggleRow(label: T("Live preview: re-render after every change", "Живое превью: пересчёт после каждого изменения"),
                          isOn: $store.liveMonitor)
                ToggleRow(label: T("Save sessions automatically", "Сохранять сессии автоматически"), isOn: $store.autosave)
                ParamRow(label: T("Monitor volume", "Громкость мониторов"),
                         value: Binding(get: { store.player.volume }, set: { store.player.volume = $0 }),
                         range: 0...1, defaultValue: 1, format: Fmt.pct, labelWidth: 150)
            }
            SectionCard(title: T("Import", "Импорт"), icon: "square.and.arrow.down", collapsible: false) {
                PickerRow(label: T("Stem separation", "Разделение на стемы"), selection: $store.stemMethod,
                          options: stemOptions, labelWidth: 150)
                Text(T("Demucs gives real instrument stems when it is installed (pip install demucs). Without it the engine uses a fast spectral split.",
                       "Demucs даёт настоящие стемы инструментов, если установлен (pip install demucs). Без него движок делит спектрально и быстро."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var stemOptions: [(String, String)] {
        var out: [(String, String)] = store.stemMethods.map { m in
            (m.str("id"), m.str("name", m.str("id")) + (m.flag("available", true) ? "" : T(" (not installed)", " (не установлен)")))
        }
        if out.isEmpty { out = [("auto", "Auto")] }
        if !out.contains(where: { $0.0 == store.stemMethod }) { out.insert((store.stemMethod, store.stemMethod), at: 0) }
        return out
    }
}

// MARK: - Generators

private struct GeneratorSettings: View {
    @EnvironmentObject var store: StudioStore
    @State private var acestepKey = ""
    @State private var gptunnelKey = ""
    @State private var acestepSaved = false
    @State private var gptunnelSaved = false

    private var envGptunnel: Bool { !(ProcessInfo.processInfo.environment["GPTUNNEL_API_KEY"] ?? "").isEmpty }
    private var envAcestep: Bool { !(ProcessInfo.processInfo.environment["ACESTEP_API_KEY"] ?? "").isEmpty }

    var body: some View {
        SettingsPage {
            SectionCard(title: "ACE-Step 1.5", icon: "desktopcomputer", collapsible: false) {
                Text(T("Open-source song model that runs locally (Apple Silicon supported). Start its API server, then generate from the app.",
                       "Открытая модель песен, работает локально (Apple Silicon поддерживается). Запустите её API-сервер и генерируйте из приложения."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                TextRow(label: T("Server URL", "Адрес сервера"), text: $store.acestepURL,
                        placeholder: "http://127.0.0.1:8001", labelWidth: 150)
                KeyRow(label: T("API key (optional)", "API-ключ (необязательно)"), text: $acestepKey,
                       saved: acestepSaved, fromEnv: envAcestep, envName: "ACESTEP_API_KEY") {
                    Keychain.set("acestep_key", "")
                    acestepSaved = false
                    Task { await store.saveSecrets(acestepKey: "", gptunnelKey: nil) }
                }
                Text("cd ACE-Step-1.5 && uv run acestep-api")
                    .font(Theme.monoSmall).foregroundColor(Theme.accent2).textSelection(.enabled)
                Link(T("ACE-Step 1.5 on GitHub", "ACE-Step 1.5 на GitHub"), destination: URL(string: "https://github.com/ace-step/ACE-Step-1.5")!)
                    .font(.system(size: 11))
            }
            SectionCard(title: T("Suno via GPTunneL", "Suno через GPTunneL"), icon: "cloud", collapsible: false) {
                Text(T("Paid cloud generation. The key is stored in the macOS Keychain and passed to the engine process only.",
                       "Платная облачная генерация. Ключ хранится в связке ключей macOS и передаётся только процессу движка."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                KeyRow(label: T("API key", "API-ключ"), text: $gptunnelKey, saved: gptunnelSaved, fromEnv: envGptunnel,
                       envName: "GPTUNNEL_API_KEY") {
                    Keychain.set("gptunnel_key", "")
                    gptunnelSaved = false
                    Task { await store.saveSecrets(acestepKey: nil, gptunnelKey: "") }
                }
                Link(T("GPTunneL Creative Lab API", "GPTunneL Creative Lab API"),
                     destination: URL(string: "https://docs.gptunnel.ru/creative-lab/create-task/")!)
                    .font(.system(size: 11))
            }
            HStack {
                Spacer()
                Button(T("Save", "Сохранить")) { save() }
                    .buttonStyle(StudioButtonStyle(prominent: true))
                    .keyboardShortcut(.defaultAction)
            }
            SectionCard(title: T("Status", "Состояние"), icon: "dot.radiowaves.left.and.right", collapsible: false) {
                ForEach(store.engines.map { $0.str("id") }, id: \.self) { id in
                    let st = store.engineStatus[id]
                    HStack(spacing: 8) {
                        Circle().fill(st == nil ? Theme.text3 : (st?["ok"]?.bool == true ? Theme.green : Theme.red))
                            .frame(width: 7, height: 7)
                        Text(store.name(in: store.engines, id)).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.text)
                            .frame(width: 150, alignment: .leading)
                        Text(st?.str("status") ?? "—").font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                        Spacer()
                    }
                }
                Button(T("Check Again", "Проверить снова")) {
                    store.engineStatus = [:]
                    Task {
                        await store.refreshEngineStatuses()
                        await store.refreshGenerator()
                    }
                }
                .buttonStyle(StudioButtonStyle(compact: true))
            }
        }
        .onAppear {
            acestepSaved = !(Keychain.get("acestep_key") ?? "").isEmpty
            gptunnelSaved = !(Keychain.get("gptunnel_key") ?? "").isEmpty
        }
    }

    private func save() {
        let a = acestepKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let g = gptunnelKey.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            await store.saveSecrets(acestepKey: a.isEmpty ? nil : a, gptunnelKey: g.isEmpty ? nil : g)
            if !a.isEmpty { acestepSaved = true }
            if !g.isEmpty { gptunnelSaved = true }
            acestepKey = ""
            gptunnelKey = ""
            store.engineStatus = [:]
            await store.refreshEngineStatuses()
        }
    }
}

private struct KeyRow: View {
    let label: String
    @Binding var text: String
    let saved: Bool
    let fromEnv: Bool
    let envName: String
    let remove: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(label).font(Theme.label).foregroundColor(Theme.text2).frame(width: 150, alignment: .leading)
                SecureField(saved ? T("•••••• saved in Keychain", "•••••• сохранён в Keychain") : T("paste the key", "вставьте ключ"),
                            text: $text)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .padding(.horizontal, 8)
                    .frame(height: 24)
                    .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
                    .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
                if saved {
                    Button(T("Remove", "Удалить"), action: remove)
                        .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
                }
            }
            if fromEnv {
                Text(T("The \(envName) environment variable is set; a key saved here takes priority.",
                       "Задана переменная окружения \(envName); ключ, сохранённый здесь, имеет приоритет."))
                    .font(.system(size: 9)).foregroundColor(Theme.text3)
                    .padding(.leading, 158)
            }
        }
    }
}

// MARK: - Engine

private struct EngineSettings: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SettingsPage {
            SectionCard(title: T("Python engine", "Python-движок"), icon: "cpu", collapsible: false) {
                InfoLine(label: T("State", "Состояние"), value: store.engineState.label,
                         color: store.engineState.isReady ? Theme.green : Theme.yellow)
                InfoLine(label: "Python", value: store.pythonPath.isEmpty ? "—" : "\(store.pythonVersion) · \(store.pythonPath)")
                InfoLine(label: T("Engine version", "Версия движка"), value: store.engineVersion.isEmpty ? "—" : store.engineVersion)
                InfoLine(label: T("Engine folder", "Папка движка"), value: store.engineDir?.path ?? "—")
                InfoLine(label: "ffmpeg", value: dep("ffmpeg"), color: store.info["deps"]?["ffmpeg"]?.bool == true ? Theme.green : Theme.text3)
                InfoLine(label: "Demucs", value: dep("demucs"), color: store.info["deps"]?["demucs"]?.bool == true ? Theme.green : Theme.text3)
                HStack(spacing: 8) {
                    Button(T("Restart Engine", "Перезапустить")) { Task { await store.restartEngine() } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button(T("Choose Python…", "Выбрать Python…")) { choose(python: true) }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button(T("Choose Engine Folder…", "Папка движка…")) { choose(python: false) }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button(T("Automatic", "Автоматически")) {
                        UserDefaults.standard.removeObject(forKey: "pythonPath")
                        UserDefaults.standard.removeObject(forKey: "engineDir")
                        Task { await store.restartEngine() }
                    }
                    .buttonStyle(StudioButtonStyle(compact: true))
                    .help(T("Forget the chosen Python and folder and detect them again", "Забыть выбранные Python и папку и найти заново"))
                }
            }
            SectionCard(title: T("Managed environment", "Собственное окружение"), icon: "shippingbox", collapsible: false) {
                Text(T("The app can create its own Python environment in ~/Library/Application Support/AI Music Studio/venv and install the pinned engine packages (needs internet).",
                       "Приложение может создать своё окружение Python в ~/Library/Application Support/AI Music Studio/venv и поставить закреплённые версии пакетов движка (нужен интернет)."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button(T("Create / Update Environment", "Создать / обновить окружение")) { Task { await store.setupEnvironment() } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                        .disabled(store.settingUp)
                    if store.settingUp { ProgressView().controlSize(.small) }
                    Spacer()
                }
                if !store.setupLog.isEmpty {
                    ScrollView {
                        Text(store.setupLog.suffix(200).joined(separator: "\n"))
                            .font(Theme.monoSmall)
                            .foregroundColor(Theme.text2)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(6)
                    }
                    .frame(height: 110)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
                }
            }
        }
    }

    private func dep(_ key: String) -> String {
        guard let v = store.info["deps"]?[key]?.bool else { return "—" }
        return v ? T("installed", "установлен") : T("not found", "не найден")
    }

    private func choose(python: Bool) {
        let p = NSOpenPanel()
        p.canChooseFiles = python
        p.canChooseDirectories = !python
        p.showsHiddenFiles = python
        p.treatsFilePackagesAsDirectories = python
        p.prompt = T("Use", "Использовать")
        if p.runModal() == .OK, let u = p.url {
            UserDefaults.standard.set(u.path, forKey: python ? "pythonPath" : "engineDir")
            Task { await store.restartEngine() }
        }
    }
}

// MARK: - About

private struct AboutSettings: View {
    var body: some View {
        SettingsPage {
            HStack(spacing: 14) {
                Image(systemName: "waveform.circle.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(LinearGradient(colors: [Theme.accent, Theme.purple], startPoint: .topLeading, endPoint: .bottomTrailing))
                VStack(alignment: .leading, spacing: 4) {
                    Text("AI Music Studio").font(.system(size: 20, weight: .semibold)).foregroundColor(Theme.text)
                    Text(T("Version \(AppInfo.version)", "Версия \(AppInfo.version)")).font(Theme.mono).foregroundColor(Theme.text2)
                    Text(T("Generate songs, then record them in a virtual studio: room, microphones, preamps, mixer and mastering.",
                           "Генерация песен и запись в виртуальной студии: комната, микрофоны, предусилители, микшер и мастеринг."))
                        .font(.system(size: 11)).foregroundColor(Theme.text3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            SectionCard(title: T("Links", "Ссылки"), icon: "link", collapsible: false) {
                Link("github.com/MRX7999/AI-Music-Studio", destination: URL(string: "https://github.com/MRX7999/AI-Music-Studio")!)
                Link(T("Releases", "Релизы"), destination: URL(string: "https://github.com/MRX7999/AI-Music-Studio/releases")!)
                Link("ACE-Step 1.5", destination: URL(string: "https://github.com/ace-step/ACE-Step-1.5")!)
            }
            .font(.system(size: 11))
            Text(T("MIT License. The Python engine does all audio processing; this app is its native macOS interface.",
                   "Лицензия MIT. Всю обработку звука выполняет Python-движок; это приложение — его нативный интерфейс для macOS."))
                .font(.system(size: 10)).foregroundColor(Theme.text3)
        }
    }
}

enum AppInfo {
    static var version: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "1.2.0"
    }
}
