import SwiftUI

extension StudioStore {
    /// Status of every generator (the selected one is refreshed by refreshGenerator()).
    func refreshEngineStatuses() async {
        guard engineState.isReady else { return }
        for e in engines {
            let id = e.str("id")
            if engineStatus[id] != nil { continue }
            if let st = try? await engine.call("engine.status", ["engine": .s(id)]) { engineStatus[id] = st }
        }
    }
}

/// Generate mode: engine choice, song text and style, musical parameters, engine-specific options.
struct GenerateView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 12) {
                    GenerateHeader()
                    EngineCards()
                    EngineHint()
                    HStack(alignment: .top, spacing: 12) {
                        SongCard().frame(maxWidth: .infinity)
                        VStack(spacing: 12) {
                            MusicCard()
                            EngineOptionsCard()
                        }
                        .frame(width: 300)
                    }
                }
                .padding(12)
            }
            Rectangle().fill(Theme.stroke).frame(height: 1)
            GenerateBar()
        }
        .task(id: store.engineState) { await store.refreshEngineStatuses() }
    }
}

private struct GenerateHeader: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(T("Generate a song", "Генерация песни"))
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(Theme.text)
            Text(T("Write the style and lyrics, pick an engine and press Generate. Then open the result in the studio to place the musicians and mix.",
                   "Опишите стиль и текст, выберите движок и нажмите «Сгенерировать». Затем откройте результат в студии, расставьте музыкантов и сведите."))
                .font(.system(size: 11))
                .foregroundColor(Theme.text2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Engines

private struct EngineCards: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        HStack(spacing: 8) {
            ForEach(store.engines.map { $0.str("id") }, id: \.self) { id in
                if let e = store.engines.first(where: { $0.str("id") == id }) {
                    EngineCard(engine: e, status: store.engineStatus[id], selected: store.form.engine == id) {
                        store.selectEngine(id)
                    }
                }
            }
        }
    }
}

private struct EngineCard: View {
    let engine: JSONValue
    let status: JSONValue?
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        let ok = status?["ok"]?.bool
        Button(action: action) {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Circle()
                        .fill(ok == nil ? Theme.text3 : (ok == true ? Theme.green : Theme.red))
                        .frame(width: 7, height: 7)
                    Text(EngineCard.title(engine))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Theme.text)
                        .lineLimit(1)
                        .help(engine.str("name"))
                    Spacer(minLength: 0)
                    Badge(text: engine.flag("local") ? T("LOCAL", "ЛОКАЛЬНО") : T("CLOUD", "ОБЛАКО"),
                          color: engine.flag("local") ? Theme.green : Theme.blue)
                }
                Text(engine.str("description"))
                    .font(.system(size: 10))
                    .foregroundColor(Theme.text2)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(status?.str("status") ?? T("checking…", "проверка…"))
                    .font(.system(size: 9))
                    .foregroundColor(ok == false ? Theme.red.opacity(0.9) : Theme.text3)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            .padding(10)
            .frame(maxWidth: .infinity, minHeight: 84, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: 8).fill(selected ? Theme.bg3 : (hover ? Theme.bg2.opacity(0.85) : Theme.bg2)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Theme.accent : Theme.stroke, lineWidth: selected ? 1.5 : 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }

    /// Short card titles for the built-in engines; the full engine name is the tooltip.
    static func title(_ e: JSONValue) -> String {
        switch e.str("id") {
        case "acestep": return "ACE-Step 1.5"
        case "gptunnel": return T("Suno via GPTunneL", "Suno через GPTunneL")
        case "demo": return T("Demo synth", "Демо-синтезатор")
        default: return e.str("name")
        }
    }
}

/// What to do when the selected engine is not available.
private struct EngineHint: View {
    @EnvironmentObject var store: StudioStore
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        let id = store.form.engine
        let ok = store.engineStatus[id]?["ok"]?.bool ?? true
        if !ok && (id == "acestep" || id == "gptunnel") {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "info.circle.fill").foregroundColor(Theme.yellow)
                VStack(alignment: .leading, spacing: 4) {
                    if id == "acestep" {
                        Text(T("Start the ACE-Step 1.5 API server on this Mac (it runs locally, Apple Silicon is supported):",
                               "Запустите API-сервер ACE-Step 1.5 на этом Mac (работает локально, Apple Silicon поддерживается):"))
                        Text("cd ACE-Step-1.5 && uv run acestep-api   # http://127.0.0.1:8001")
                            .font(Theme.mono)
                            .textSelection(.enabled)
                            .foregroundColor(Theme.accent2)
                    } else {
                        Text(T("Suno through GPTunneL needs an API key (paid). Add it in Settings → Generators; it is stored in the macOS Keychain.",
                               "Suno через GPTunneL требует API-ключ (платно). Добавьте его в Настройки → Генераторы; ключ хранится в связке ключей macOS."))
                    }
                }
                .font(.system(size: 11))
                .foregroundColor(Theme.text2)
                Spacer()
                VStack(spacing: 6) {
                    Button(T("Check again", "Проверить снова")) { Task { await store.refreshGenerator() } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button(T("Settings…", "Настройки…")) { openSettings() }
                        .buttonStyle(StudioButtonStyle(compact: true))
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Theme.yellow.opacity(0.07)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.yellow.opacity(0.35), lineWidth: 1))
        }
    }
}

// MARK: - Song (title, style, lyrics)

private struct SongCard: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Song", "Песня"), icon: "text.quote", collapsible: false) {
            VStack(alignment: .leading, spacing: 4) {
                Caption(text: T("Title", "Название"))
                StudioTextField(placeholder: T("Night Drive", "Ночная трасса"), text: $store.form.title)
            }
            VStack(alignment: .leading, spacing: 4) {
                Caption(text: T("Style", "Стиль"))
                StudioTextField(placeholder: T("synthwave, retro, dreamy pads, 80s drums, male vocals",
                                               "synthwave, retro, dreamy pads, 80s drums, male vocals"),
                                text: $store.form.style)
                StyleTags()
                Text(T("Tip: style prompts work best in English.", "Совет: стиль лучше писать по-английски — модели понимают его точнее."))
                    .font(.system(size: 9))
                    .foregroundColor(Theme.text3)
            }
            LyricsEditor()
        }
    }
}

private struct StyleTags: View {
    @EnvironmentObject var store: StudioStore
    private static let groups: [[String]] = [
        ["pop", "rock", "synthwave", "lo-fi", "hip-hop", "jazz", "edm", "ambient", "orchestral", "folk", "metal", "r&b"],
        ["dreamy", "energetic", "melancholic", "uplifting", "dark", "romantic", "epic"],
        ["piano", "acoustic guitar", "electric guitar", "strings", "808 bass", "synth pads", "brass"],
        ["male vocals", "female vocals", "choir", "duet"],
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Array(StyleTags.groups.enumerated()), id: \.offset) { _, tags in
                TagRow(tags: tags)
            }
        }
    }
}

private struct TagRow: View {
    @EnvironmentObject var store: StudioStore
    let tags: [String]

    var body: some View {
        FlowLayout(spacing: 4, lineSpacing: 4) {
            ForEach(tags, id: \.self) { tag in
                Chip(title: tag, isOn: has(tag), color: Theme.accent2) { toggle(tag) }
            }
        }
    }

    private func parts() -> [String] {
        store.form.style.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private func has(_ tag: String) -> Bool { parts().contains { $0.lowercased() == tag } }

    private func toggle(_ tag: String) {
        var p = parts()
        if let i = p.firstIndex(where: { $0.lowercased() == tag }) { p.remove(at: i) } else { p.append(tag) }
        store.form.style = p.joined(separator: ", ")
    }
}

private struct LyricsEditor: View {
    @EnvironmentObject var store: StudioStore
    private static let sections = ["Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Outro"]

    var body: some View {
        let instrumental = store.form.instrumental
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Caption(text: T("Lyrics", "Текст"))
                Spacer()
                Toggle(T("Instrumental", "Инструментал"), isOn: $store.form.instrumental)
                    .toggleStyle(.switch)
                    .controlSize(.mini)
                    .font(Theme.label)
                    .foregroundColor(Theme.text2)
            }
            HStack(spacing: 4) {
                ForEach(LyricsEditor.sections, id: \.self) { s in
                    Chip(title: "[\(s)]", isOn: false) { insert(s) }
                }
                Spacer(minLength: 0)
            }
            .disabled(instrumental)
            TextEditor(text: $store.form.lyrics)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Theme.text)
                .scrollContentBackground(.hidden)
                .padding(6)
                .frame(minHeight: 240)
                .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
                .disabled(instrumental)
                .opacity(instrumental ? 0.4 : 1)
            HStack {
                Text(T("Section tags like [Verse] and [Chorus] shape the song structure.",
                       "Теги разделов вроде [Verse] и [Chorus] задают структуру песни."))
                    .font(.system(size: 9))
                    .foregroundColor(Theme.text3)
                Spacer()
                Text(T("\(store.form.lyrics.count) characters", "символов: \(store.form.lyrics.count)"))
                    .font(Theme.monoSmall)
                    .foregroundColor(Theme.text3)
            }
        }
    }

    private func insert(_ section: String) {
        var t = store.form.lyrics
        if !t.isEmpty && !t.hasSuffix("\n") { t += "\n" }
        if !t.isEmpty { t += "\n" }
        t += "[\(section)]\n"
        store.form.lyrics = t
    }
}

// MARK: - Music parameters

private struct MusicCard: View {
    @EnvironmentObject var store: StudioStore

    private static let keys: [String] = {
        let notes = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
        var out: [String] = []
        for n in notes { out.append(n + " major"); out.append(n + " minor") }
        return out
    }()

    private var keyOptions: [(String, String)] {
        var out: [(String, String)] = [("", T("Automatic", "Автоматически"))]
        for k in MusicCard.keys { out.append((k, k)) }
        if !store.form.key.isEmpty && !MusicCard.keys.contains(store.form.key) { out.append((store.form.key, store.form.key)) }
        return out
    }

    var body: some View {
        let f = store.form
        SectionCard(title: T("Music", "Музыка"), icon: "metronome", collapsible: false) {
            ParamRow(label: T("Duration", "Длительность"), value: $store.form.duration, range: 10...600, step: 1,
                     defaultValue: 60, format: Fmt.clock, labelWidth: 92)
            ToggleRow(label: T("Automatic tempo", "Темп автоматически"), isOn: $store.form.autoBpm)
            ParamRow(label: T("Tempo", "Темп"), value: $store.form.bpm, range: 40...220, step: 1, defaultValue: 110,
                     format: { String(format: "%.0f BPM", $0) }, enabled: !f.autoBpm, labelWidth: 92)
            PickerRow(label: T("Key", "Тональность"), selection: $store.form.key, options: keyOptions, labelWidth: 92)
            PickerRow(label: T("Time signature", "Размер"), selection: $store.form.timeSignature,
                      options: [("2", "2/4"), ("3", "3/4"), ("4", "4/4"), ("6", "6/8")], labelWidth: 92)
            PickerRow(label: T("Vocal language", "Язык вокала"), selection: $store.form.language,
                      options: languageOptions, labelWidth: 92)
            ToggleRow(label: T("Random seed", "Случайный seed"), isOn: $store.form.randomSeed)
            ParamRow(label: "Seed", value: $store.form.seed, range: 0...99999, step: 1, defaultValue: 42,
                     format: { String(format: "%.0f", $0) }, enabled: !f.randomSeed, labelWidth: 92)
            ParamRow(label: T("Variations", "Варианты"), value: $store.form.variations, range: 1...4, step: 1, defaultValue: 1,
                     format: { String(format: "%.0f", $0) }, labelWidth: 92)
        }
    }

    private var languageOptions: [(String, String)] {
        var codes = store.languages
        if codes.isEmpty { codes = ["en", "ru"] }
        if !codes.contains(store.form.language) { codes.insert(store.form.language, at: 0) }
        let loc = Locale(identifier: L10n.code)
        return codes.map { code in
            let name = loc.localizedString(forLanguageCode: code) ?? code
            return (code, name.prefix(1).uppercased() + name.dropFirst())
        }
    }
}

// MARK: - Engine-specific options

private struct EngineOptionsCard: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Engine options", "Параметры движка"), icon: "gearshape.2", collapsible: false) {
            if store.models.isEmpty {
                Text(store.form.engine == "demo"
                     ? T("The built-in demo synthesizer has no extra options. It renders a short multitrack song with stems, offline.",
                         "У встроенного демо-синтезатора нет доп. параметров. Он офлайн синтезирует короткую многодорожечную песню со стемами.")
                     : T("Models appear when the engine is available.", "Модели появятся, когда движок станет доступен."))
                    .font(.system(size: 10))
                    .foregroundColor(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                PickerRow(label: T("Model", "Модель"),
                          selection: Binding(get: { store.form.model }, set: { store.selectModel($0) }),
                          options: store.models.map { ($0.str("id"), $0.str("name", $0.str("id"))) }, labelWidth: 92)
            }
            ForEach(store.schema.map { $0.str("key") }, id: \.self) { key in
                if let field = store.schema.first(where: { $0.str("key") == key }) {
                    SchemaField(field: field)
                }
            }
        }
    }
}

/// One dynamic field from the engine schema: number, boolean, enum or string.
private struct SchemaField: View {
    @EnvironmentObject var store: StudioStore
    let field: JSONValue

    var body: some View {
        let key = field.str("key")
        let label = field.str("label", key)
        switch field.str("type") {
        case "number":
            numberRow(key, label)
        case "boolean":
            ToggleRow(label: label, isOn: Binding(get: { store.form.extra[key]?.bool ?? false },
                                                  set: { store.form.extra[key] = .bool($0) }))
        case "enum":
            PickerRow(label: label, selection: Binding(get: { store.form.extra[key] ?? .null },
                                                       set: { store.form.extra[key] = $0 }),
                      options: enumOptions(), labelWidth: 92)
        default:
            TextRow(label: label, text: Binding(get: { store.form.extra[key]?.string ?? "" },
                                                set: { store.form.extra[key] = $0.isEmpty ? .null : .string($0) }),
                    labelWidth: 92)
        }
    }

    private func numberRow(_ key: String, _ label: String) -> some View {
        let integer = field.flag("integer")
        let def = field["default"]?.double ?? 0
        let lo = field["min"]?.double ?? min(0, def)
        var hi = field["max"]?.double ?? max(def * 4, 100)
        if hi <= lo { hi = lo + 1 }
        let unit = field.str("unit")
        return ParamRow(label: label,
                        value: Binding(get: { store.form.extra[key]?.double ?? def },
                                       set: { store.form.extra[key] = .number(integer ? $0.rounded() : $0) }),
                        range: lo...hi, step: integer ? 1 : field["step"]?.double, defaultValue: def,
                        format: { v in (integer ? String(format: "%.0f", v) : String(format: "%.2f", v)) + (unit.isEmpty ? "" : " " + unit) },
                        labelWidth: 92)
    }

    private func enumOptions() -> [(JSONValue, String)] {
        let opts = field.list("options")
        let labels = field.list("option_labels").map { $0.string ?? "" }
        return opts.enumerated().map { i, o in
            let text = i < labels.count && !labels[i].isEmpty ? labels[i] : (o.string ?? o.double.map { String(format: "%g", $0) } ?? "—")
            return (o, text)
        }
    }
}

// MARK: - Bottom bar

private struct GenerateBar: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let ready = store.engineState.isReady
        let ok = store.engineStatus[store.form.engine]?["ok"]?.bool ?? true
        HStack(spacing: 10) {
            if store.generating {
                VStack(alignment: .leading, spacing: 4) {
                    ProgressStrip(value: store.genProgress > 0 ? store.genProgress : nil)
                    Text(store.genMessage).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(1)
                }
                .frame(maxWidth: .infinity)
                Button(T("Cancel", "Отмена")) { store.cancelGeneration() }
                    .buttonStyle(StudioButtonStyle(destructive: true))
            } else {
                if store.form.engine != "demo" {
                    Button(T("Estimate price", "Оценить цену")) { Task { await store.estimatePrice() } }
                        .buttonStyle(StudioButtonStyle(compact: true))
                        .disabled(!ready)
                }
                Text(store.price ?? (store.genMessage.isEmpty ? T("Songs are saved to ", "Песни сохраняются в ")
                                     + store.projectRoot.appendingPathComponent("songs").path : store.genMessage))
                    .font(.system(size: 10))
                    .foregroundColor(Theme.text3)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Button { Task { await store.generate() } } label: {
                    Label(T("Generate", "Сгенерировать"), systemImage: "wand.and.stars")
                        .padding(.horizontal, 8)
                }
                .buttonStyle(StudioButtonStyle(prominent: true))
                .disabled(!ready || !ok)
                .help(T("Generate (⌘↩)", "Сгенерировать (⌘↩)"))
            }
        }
        .padding(.horizontal, 12)
        .frame(height: 50)
        .background(Theme.bg1)
    }
}
