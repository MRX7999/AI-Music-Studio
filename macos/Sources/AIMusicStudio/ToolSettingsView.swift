import SwiftUI
import AppKit

// MARK: - Tool overrides (UserDefaults, pushed to the engine as config.set {"tools": …})

struct ToolOverride: Codable, Equatable {
    var path = ""
    var template = ""
    var enabled = true
}

/// Per-tool path/template/enabled overrides and the backend chosen per feature ("auto" = MLX first).
struct ToolSettings: Codable, Equatable {
    var tools: [String: ToolOverride] = [:]
    var backends: [String: String] = [:]

    static let key = "toolSettings"

    static func load() -> ToolSettings {
        guard let d = UserDefaults.standard.data(forKey: key),
              let t = try? JSONDecoder().decode(ToolSettings.self, from: d) else { return ToolSettings() }
        return t
    }

    func save() {
        if let d = try? JSONEncoder().encode(self) { UserDefaults.standard.set(d, forKey: Self.key) }
    }

    /// Engine format: {"tools": {id: {"path", "template", "enabled"}}, "backends": {feature: id}}.
    var payload: JSONValue {
        var t: [String: JSONValue] = [:]
        for (id, o) in tools {
            var x: [String: JSONValue] = ["enabled": .b(o.enabled)]
            let p = o.path.trimmingCharacters(in: .whitespaces)
            let tpl = o.template.trimmingCharacters(in: .whitespaces)
            if !p.isEmpty { x["path"] = .s((p as NSString).expandingTildeInPath) }
            if !tpl.isEmpty { x["template"] = .s(tpl) }
            t[id] = .object(x)
        }
        var b: [String: JSONValue] = [:]
        for (f, v) in backends { b[f] = .s(v) }
        return ["tools": .object(t), "backends": .object(b)]
    }
}

enum FeatureNames {
    static let order = ["superres", "lyrics", "stems", "cover", "detect", "voice", "refmaster", "video"]

    static func title(_ f: String) -> String {
        switch f {
        case "superres": return T("Bandwidth restore (super-resolution)", "Восстановление спектра (super-resolution)")
        case "lyrics": return T("Lyrics timing (LRC / SRT)", "Тайминг текста (LRC / SRT)")
        case "stems": return T("Stem separation", "Разделение на стемы")
        case "cover": return T("Cover art", "Обложка")
        case "detect": return T("AI-generation check", "Проверка на ИИ-генерацию")
        case "voice": return T("Voice conversion (RVC)", "Смена голоса (RVC)")
        case "refmaster": return T("Reference mastering", "Мастеринг по референсу")
        case "video": return T("MP3 / video encoding", "Кодирование MP3 / видео")
        default: return f
        }
    }

    static func builtin(_ f: String) -> String? {
        switch f {
        case "superres": return T("Built-in harmonic extension (fast, no model)", "Встроенное гармоническое расширение (быстро, без модели)")
        case "lyrics": return nil
        case "stems": return T("Built-in spectral split", "Встроенное спектральное деление")
        case "cover": return T("Built-in generative art (no model)", "Встроенная генеративная графика (без модели)")
        case "detect": return T("Built-in fakeprint detector (MIT)", "Встроенный детектор fakeprint (MIT)")
        case "refmaster": return T("Built-in reference EQ + loudness match", "Встроенный EQ и громкость по референсу")
        default: return nil
        }
    }
}

// MARK: - AI Models tab

struct AIModelsSettings: View {
    @EnvironmentObject var store: StudioStore
    @State private var settings = ToolSettings.load()
    @State private var loading = false
    @State private var expanded: Set<String> = []

    private var doctor: JSONValue { store.releases.doctor }

    var body: some View {
        SettingsScroll {
            SectionCard(title: T("Local models", "Локальные модели"), icon: "cpu", collapsible: false) {
                Text(T("Every neural tool runs as a separate local program (uv tool / Homebrew) next to the engine. On Apple Silicon the MLX version is used first; if it is missing the PyTorch version or a built-in fallback takes over. Nothing is installed without your click.",
                       "Каждая нейросеть — отдельная локальная программа (uv tool / Homebrew) рядом с движком. На Apple Silicon сначала берётся MLX-версия; если её нет — PyTorch-версия или встроенный запасной вариант. Ничего не ставится без вашего клика."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 14) {
                    InfoLine(label: "Apple Silicon", value: doctor.flag("apple_silicon") ? T("yes", "да") : T("no", "нет"),
                             color: doctor.flag("apple_silicon") ? Theme.green : Theme.yellow)
                    InfoLine(label: "ffmpeg", value: doctor.flag("ffmpeg") ? T("found", "найден") : T("missing", "нет"),
                             color: doctor.flag("ffmpeg") ? Theme.green : Theme.yellow)
                }
                HStack(spacing: 8) {
                    Button(T("Check Again", "Проверить снова")) { Task { await refresh(probe: true) } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                        .disabled(loading)
                    if loading { ProgressView().controlSize(.small) }
                    Spacer()
                    Link(T("Install guide (requirements-mlx.md)", "Инструкция по установке (requirements-mlx.md)"),
                         destination: URL(string: "https://github.com/MRX7999/AI-Music-Studio/blob/main/requirements-mlx.md")!)
                        .font(.system(size: 11))
                }
            }
            ForEach(FeatureNames.order, id: \.self) { f in featureCard(f) }
        }
        .task { await refresh(probe: false) }
    }

    private func refresh(probe: Bool) async {
        loading = true
        defer { loading = false }
        if let d = try? await store.engine.call("tools.doctor", ["probe": .b(probe)]) { store.releases.doctor = d }
    }

    private func apply() {
        let s = settings
        Task { await store.pushToolSettings(s) }
    }

    @ViewBuilder
    private func featureCard(_ f: String) -> some View {
        let feat = doctor["features"]?[f]
        let ids = feat?.list("candidates").compactMap { $0.string } ?? []
        let resolved = feat?.str("backend") ?? "—"
        SectionCard(title: FeatureNames.title(f), icon: icon(f), collapsible: false) {
            HStack(spacing: 8) {
                PickerRow(label: T("Backend", "Бэкенд"),
                          selection: Binding(get: { settings.backends[f] ?? "auto" },
                                             set: { settings.backends[f] = $0; apply() }),
                          options: backendOptions(f, ids), labelWidth: 90)
                Text(T("in use: ", "сейчас: ") + resolvedTitle(f, resolved))
                    .font(.system(size: 10)).foregroundColor(resolved.hasPrefix("missing") ? Theme.yellow : Theme.text2)
                    .lineLimit(1)
                    .frame(width: 210, alignment: .trailing)
            }
            if feat?.flag("fallback") == true && !resolved.hasPrefix("missing") {
                let wanted = feat?.str("wanted") ?? ""
                let wl = doctor["tools"]?[wanted]?.str("label") ?? wanted
                Text(T("\(wl) is selected but not installed, so \(resolvedTitle(f, resolved)) is used instead.",
                       "Выбран \(wl), но он не установлен, поэтому используется \(resolvedTitle(f, resolved))."))
                    .font(.system(size: 10)).foregroundColor(Theme.yellow)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(ids, id: \.self) { id in toolRow(id) }
        }
    }

    private func icon(_ f: String) -> String {
        ["superres": "waveform.badge.plus", "lyrics": "text.quote", "stems": "square.stack.3d.down.right",
         "cover": "photo", "detect": "checkmark.shield", "voice": "person.wave.2", "refmaster": "dial.medium",
         "video": "film"][f] ?? "cpu"
    }

    private func backendOptions(_ f: String, _ ids: [String]) -> [(String, String)] {
        var out: [(String, String)] = [("auto", T("Auto (MLX first)", "Авто (сначала MLX)"))]
        for id in ids {
            let t = doctor["tools"]?[id]
            out.append((id, (t?.str("label") ?? id) + (t?.flag("installed") == true ? "" : T(" — not installed", " — не установлен"))))
        }
        if let b = FeatureNames.builtin(f) { out.append(("builtin", b)) }
        out.append(("off", T("Off", "Выключено")))
        return out
    }

    private func resolvedTitle(_ f: String, _ r: String) -> String {
        if r == "builtin" { return FeatureNames.builtin(f) ?? T("built-in", "встроенный") }
        if r == "off" { return T("off", "выключено") }
        if r.hasPrefix("missing:") { return T("not installed: ", "не установлен: ") + String(r.dropFirst(8)) }
        return doctor["tools"]?[r]?.str("label") ?? r
    }

    @ViewBuilder
    private func toolRow(_ id: String) -> some View {
        let t = doctor["tools"]?[id] ?? .null
        let ov = Binding(get: { settings.tools[id] ?? ToolOverride() }, set: { settings.tools[id] = $0 })
        let open = expanded.contains(id)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Circle().fill(t.flag("installed") ? Theme.green : (t.flag("supported", true) ? Theme.text3 : Theme.red))
                    .frame(width: 7, height: 7)
                VStack(alignment: .leading, spacing: 1) {
                    Text(t.str("label", id)).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.text)
                    Text(statusLine(t)).font(.system(size: 9)).foregroundColor(Theme.text3).lineLimit(1).truncationMode(.middle)
                    if let m = modelLine(t) {
                        Text(m.0).font(.system(size: 9)).foregroundColor(m.1 ? Theme.text3 : Theme.yellow).lineLimit(1)
                    }
                }
                Spacer()
                Toggle("", isOn: Binding(get: { ov.wrappedValue.enabled }, set: { ov.wrappedValue.enabled = $0; apply() }))
                    .toggleStyle(.switch).controlSize(.mini).labelsHidden()
                    .help(T("Allow this tool", "Разрешить этот инструмент"))
                IconButton(icon: open ? "chevron.up" : "chevron.down", help: T("Details", "Подробнее"), size: 10) {
                    if open { expanded.remove(id) } else { expanded.insert(id) }
                }
            }
            if open {
                VStack(alignment: .leading, spacing: 6) {
                    InfoLine(label: T("License", "Лицензия"), value: t.str("license", "—"))
                    if !t.flag("supported", true) {
                        Text(T("Needs Apple Silicon.", "Нужен Apple Silicon.")).font(.system(size: 10)).foregroundColor(Theme.red)
                    }
                    if !t.str("install").isEmpty {
                        HStack(spacing: 6) {
                            Text(t.str("install")).font(Theme.monoSmall).foregroundColor(Theme.accent2)
                                .textSelection(.enabled).lineLimit(2)
                            Spacer()
                            Button(T("Copy", "Копировать")) {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(t.str("install"), forType: .string)
                                store.show(T("Install command copied", "Команда установки скопирована"))
                            }
                            .buttonStyle(StudioButtonStyle(compact: true))
                            Button(T("Run in Terminal", "Запустить в Терминале")) { runInTerminal(t.str("install")) }
                                .buttonStyle(StudioButtonStyle(compact: true))
                                .help(T("Opens Terminal with this command; you see and confirm everything there.",
                                        "Открывает Терминал с этой командой; всё видно и подтверждается там."))
                        }
                    }
                    HStack(spacing: 6) {
                        TextRow(label: T("Executable", "Программа"), text: ov.path,
                                placeholder: t.str("path").isEmpty ? T("searched in PATH, ~/.local/bin, Homebrew, pyenv, venv and conda", "ищется в PATH, ~/.local/bin, Homebrew, pyenv, venv и conda") : t.str("path"),
                                labelWidth: 90)
                        Button(T("Choose…", "Выбрать…")) {
                            let p = NSOpenPanel()
                            p.canChooseDirectories = false
                            p.showsHiddenFiles = true
                            if p.runModal() == .OK, let u = p.url { settings.tools[id, default: ToolOverride()].path = u.path; apply() }
                        }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    }
                    TextRow(label: T("Arguments", "Аргументы"), text: ov.template, placeholder: t.str("default_template"), labelWidth: 90)
                    HStack(spacing: 8) {
                        Text(T("Placeholders: {input} {output} {model} … An empty value drops the flag before it.",
                               "Подстановки: {input} {output} {model} … Пустое значение убирает флаг перед ним."))
                            .font(.system(size: 9)).foregroundColor(Theme.text3)
                        Spacer()
                        Button(T("Reset", "Сбросить")) { settings.tools[id] = ToolOverride(); apply() }
                            .buttonStyle(StudioButtonStyle(compact: true))
                        Button(T("Apply", "Применить")) { apply() }
                            .buttonStyle(StudioButtonStyle(prominent: true, compact: true))
                        if let u = URL(string: t.str("url")), !t.str("url").isEmpty {
                            Link(T("Project page", "Страница проекта"), destination: u).font(.system(size: 10))
                        }
                    }
                }
                .padding(.leading, 15)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg1))
    }

    /// Model files a tool downloads on top of itself: (text, ready).
    private func modelLine(_ t: JSONValue) -> (String, Bool)? {
        guard t.flag("installed"), let m = t["model"], !m.isNull else { return nil }
        if m.flag("complete") {
            return (T("model: ", "модель: ") + (m.str("name").isEmpty ? T("downloaded", "скачана") : m.str("name") + T(", downloaded", ", скачана")), true)
        }
        if m["total_bytes"] != nil {
            let have = String(format: "%.1f", m.num("bytes") / 1e9), all = String(format: "%.1f", m.num("total_bytes") / 1e9)
            return (T("model: \(have) of \(all) GB, the rest is downloaded on first use",
                      "модель: \(have) из \(all) ГБ, остальное скачается при первом запуске"), false)
        }
        return (T("model: ", "модель: ") + m.str("name") + T(", downloaded on first use", ", скачается при первом запуске"), false)
    }

    private func statusLine(_ t: JSONValue) -> String {
        if t.flag("installed") {
            let v = t.str("version")
            return (v.isEmpty ? "" : v + " · ") + t.str("path")
        }
        return T("not installed", "не установлен")
    }

    private func runInTerminal(_ cmd: String) {
        let escaped = cmd.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let src = "tell application \"Terminal\"\nactivate\ndo script \"\(escaped)\"\nend tell"
        var err: NSDictionary?
        NSAppleScript(source: src)?.executeAndReturnError(&err)
        if let err { store.show(T("Terminal: \(err)", "Терминал: \(err)"), error: true) }
    }
}

// MARK: - Publishing tab

struct PublishingSettings: View {
    @EnvironmentObject var store: StudioStore
    @State private var fields: [String: String] = [:]
    @State private var saved: Set<String> = []
    @State private var tgStatus = ""
    @State private var ytStatus = ""
    @State private var connecting = false
    @State private var authID = ""

    var body: some View {
        SettingsScroll {
            SectionCard(title: "Telegram", icon: "paperplane", collapsible: false) {
                note(T("Create a bot with @BotFather, add it to your channel as an admin, and enter the channel @username or numeric chat id. Audio up to 50 MB is sent as a track with the cover.",
                       "Создайте бота у @BotFather, добавьте его администратором в канал и укажите @username канала или числовой chat id. Аудио до 50 МБ уходит треком с обложкой."))
                secret(T("Bot token", "Токен бота"), "telegram_token", "TELEGRAM_BOT_TOKEN")
                secret(T("Chat / channel", "Чат / канал"), "telegram_chat", "TELEGRAM_CHAT_ID", plain: true)
                HStack(spacing: 8) {
                    Button(T("Test Connection", "Проверить связь")) { Task { await test("telegram") } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                        .disabled(!saved.contains("telegram_token"))
                    Text(tgStatus).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                    Spacer()
                }
            }
            SectionCard(title: "YouTube", icon: "play.rectangle", collapsible: false) {
                note(T("Create an OAuth client of type “Desktop app” in Google Cloud Console with the YouTube Data API v3 enabled. While the app is in Testing mode Google expires the sign-in after 7 days — reconnect then, or publish the app in the console.",
                       "Создайте OAuth-клиент типа «Desktop app» в Google Cloud Console и включите YouTube Data API v3. Пока приложение в режиме Testing, Google сбрасывает вход через 7 дней — тогда переподключитесь или опубликуйте приложение в консоли."))
                secret("Client ID", "youtube_client_id", "YOUTUBE_CLIENT_ID", plain: true)
                secret("Client secret", "youtube_client_secret", "YOUTUBE_CLIENT_SECRET")
                HStack(spacing: 8) {
                    Button(connecting ? T("Waiting for the browser…", "Жду браузер…")
                                      : (saved.contains("youtube_refresh") ? T("Reconnect Account", "Переподключить аккаунт")
                                                                            : T("Connect Account", "Подключить аккаунт"))) {
                        Task { await connectYouTube() }
                    }
                    .buttonStyle(StudioButtonStyle(prominent: !saved.contains("youtube_refresh"), compact: true))
                    .disabled(connecting || !saved.contains("youtube_client_id") || !saved.contains("youtube_client_secret"))
                    if connecting {
                        Button(T("Cancel", "Отмена")) { Task { _ = try? await store.engine.call("cancel", ["group": "ytauth"]) } }
                            .buttonStyle(StudioButtonStyle(compact: true))
                    }
                    if saved.contains("youtube_refresh") {
                        Button(T("Test", "Проверить")) { Task { await test("youtube") } }
                            .buttonStyle(StudioButtonStyle(compact: true))
                        Button(T("Disconnect", "Отключить")) {
                            Task {
                                await store.savePublishSecrets(["youtube_refresh": ""])
                                reload()
                                ytStatus = ""
                            }
                        }
                        .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
                    }
                    Text(ytStatus).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                    Spacer()
                }
                Link(T("YouTube Data API: quota and limits", "YouTube Data API: квоты и лимиты"),
                     destination: URL(string: "https://developers.google.com/youtube/data/determine_quota_cost")!)
                    .font(.system(size: 10))
            }
            SectionCard(title: T("AI-check services (optional)", "Сервисы проверки на ИИ (необязательно)"),
                        icon: "checkmark.shield", collapsible: false) {
                note(T("The built-in fakeprint detector works offline. Paid services add independent opinions: Sightengine (AI music detection, Pro plan) and ACRCloud (AI detection in File Scanning).",
                       "Встроенный детектор fakeprint работает офлайн. Платные сервисы дают независимое мнение: Sightengine (AI music detection, тариф Pro) и ACRCloud (AI-детекция в File Scanning)."))
                secret("Sightengine API user", "sightengine_user", "SIGHTENGINE_API_USER", plain: true)
                secret("Sightengine API secret", "sightengine_secret", "SIGHTENGINE_API_SECRET")
                secret("ACRCloud token", "acrcloud_token", "ACRCLOUD_TOKEN")
                secret("ACRCloud container", "acrcloud_container", "ACRCLOUD_CONTAINER_ID", plain: true)
                secret(T("ACRCloud region", "Регион ACRCloud"), "acrcloud_region", "ACRCLOUD_REGION", plain: true,
                       placeholder: "eu-west-1")
                HStack(spacing: 12) {
                    Link("Sightengine", destination: URL(string: "https://sightengine.com/docs/ai-generated-music-detection")!)
                    Link("ACRCloud", destination: URL(string: "https://docs.acrcloud.com/reference/console-api/file-scanning/metadata/ai-detection")!)
                }
                .font(.system(size: 10))
            }
            SectionCard(title: T("Distributors", "Дистрибьюторы"), icon: "shippingbox", collapsible: false) {
                note(T("Spotify, Apple Music and Yandex Music accept releases only through a distributor. The Release tab builds a ready folder (WAV 24-bit, 3000×3000 cover, LRC, metadata.json with the AI disclosure) to upload there.",
                       "Spotify, Apple Music и Яндекс Музыка принимают релизы только через дистрибьютора. Вкладка «Релиз» собирает готовую папку (WAV 24 бит, обложка 3000×3000, LRC, metadata.json с пометкой об ИИ) для загрузки туда."))
            }
            HStack {
                Text(T("Secrets are stored in the macOS Keychain and passed only to the local engine process.",
                       "Секреты хранятся в связке ключей macOS и передаются только локальному процессу движка."))
                    .font(.system(size: 9)).foregroundColor(Theme.text3)
                Spacer()
                Button(T("Save", "Сохранить")) { save() }
                    .buttonStyle(StudioButtonStyle(prominent: true))
                    .keyboardShortcut(.defaultAction)
            }
        }
        .onAppear { reload() }
    }

    private func note(_ s: String) -> some View {
        Text(s).font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder
    private func secret(_ label: String, _ account: String, _ env: String, plain: Bool = false, placeholder: String = "") -> some View {
        let b = Binding(get: { fields[account] ?? "" }, set: { fields[account] = $0 })
        HStack(spacing: 8) {
            Text(label).font(Theme.label).foregroundColor(Theme.text2).frame(width: 150, alignment: .leading)
            Group {
                if plain {
                    TextField(saved.contains(account) ? (Keychain.get(account) ?? "") : (placeholder.isEmpty ? env : placeholder), text: b)
                } else {
                    SecureField(saved.contains(account) ? T("•••••• saved in Keychain", "•••••• сохранён в Keychain") : env, text: b)
                }
            }
            .textFieldStyle(.plain)
            .font(.system(size: 12))
            .padding(.horizontal, 8)
            .frame(height: 24)
            .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
            if saved.contains(account) {
                Button(T("Remove", "Удалить")) {
                    Task {
                        await store.savePublishSecrets([account: ""])
                        reload()
                    }
                }
                .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
            }
        }
    }

    private func reload() {
        saved = Set(StudioStore.secretAccounts.map { $0.account }.filter { !(Keychain.get($0) ?? "").isEmpty })
    }

    private func save() {
        var values: [String: String] = [:]
        for (k, v) in fields {
            let t = v.trimmingCharacters(in: .whitespacesAndNewlines)
            if !t.isEmpty { values[k] = t }
        }
        guard !values.isEmpty else { return }
        Task {
            await store.savePublishSecrets(values)
            fields = [:]
            reload()
        }
    }

    private func test(_ service: String) async {
        let set: (String) -> Void = { s in if service == "telegram" { tgStatus = s } else { ytStatus = s } }
        set(T("Checking…", "Проверяю…"))
        do {
            let r = try await store.engine.call("publish.check", ["service": .s(service)])
            if service == "telegram" {
                set(T("OK: bot @\(r.str("bot")) → \(r.str("chat_title", r.str("chat")))",
                      "Готово: бот @\(r.str("bot")) → \(r.str("chat_title", r.str("chat")))"))
            } else {
                set(T("OK: channel \(r.str("title"))", "Готово: канал \(r.str("title"))"))
            }
        } catch { set(error.localizedDescription) }
    }

    private func connectYouTube() async {
        if !fields.isEmpty { save() }
        connecting = true
        defer { connecting = false }
        do {
            let s = try await store.engine.call("youtube.auth_start", [:])
            authID = s.str("auth_id")
            if let u = URL(string: s.str("url")) { NSWorkspace.shared.open(u) }
            ytStatus = T("Sign in in the browser and allow access…", "Войдите в браузере и разрешите доступ…")
            let r = try await store.engine.call("youtube.auth_wait", ["auth_id": .s(authID), "timeout": 600, "_group": "ytauth"])
            let tok = r.str("refresh_token")
            if !tok.isEmpty { Keychain.set("youtube_refresh", tok) }
            reload()
            let title = r["channel"]?.str("title") ?? ""
            ytStatus = title.isEmpty ? T("Connected", "Подключено") : T("Connected: \(title)", "Подключено: \(title)")
            await store.releases.refreshDoctor()
        } catch let e as EngineError where e.isCancelled {
            ytStatus = T("Cancelled", "Отменено")
        } catch {
            ytStatus = error.localizedDescription
        }
    }
}

/// Scrollable settings column (same look as the other settings pages).
struct SettingsScroll<Content: View>: View {
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
