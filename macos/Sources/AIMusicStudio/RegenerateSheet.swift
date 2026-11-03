import SwiftUI
import AppKit

/// A song (any source: ACE-Step, Suno via GPTunneL, an imported file) opened for regeneration of a part.
struct RegenTarget: Identifiable, Equatable {
    let id = UUID()
    let path: String
    let title: String
    let lyrics: String
}

extension StudioStore {
    func regenerate(_ track: JSONValue) {
        regenTarget = RegenTarget(path: track.str("path"), title: track.str("title"), lyrics: track.str("lyrics"))
    }

    /// The song behind the open session (its original mix).
    func regenerateSessionSong() {
        guard let p = sourceMixPath else { return }
        regenTarget = RegenTarget(path: p, title: session?["meta"]?.str("title") ?? session?.str("name") ?? "",
                                  lyrics: session?["meta"]?.str("lyrics") ?? "")
    }
}

private let editTasks: [(String, String, String)] = [
    ("repaint", T("Regenerate region", "Перегенерировать фрагмент"),
     T("Re-creates the selected time range (e.g. the second verse) with a new prompt or lyrics; the rest of the song is kept bit-exact.",
       "Пересоздаёт выбранный отрезок (например, второй куплет) с новым промптом или текстом; остальная песня остаётся бит-в-бит.")),
    ("cover", T("Cover / restyle", "Кавер / смена стиля"),
     T("Keeps melody and structure, changes the style. Strength = how close to the original.",
       "Сохраняет мелодию и структуру, меняет стиль. Сила — насколько близко к оригиналу.")),
    ("extract", T("Extract a track", "Извлечь дорожку"),
     T("Pulls one instrument out of the mix. Needs the ACE-Step base model.", "Вынимает один инструмент из микса. Нужна base-модель ACE-Step.")),
    ("lego", T("Add a track", "Добавить дорожку"),
     T("Generates a new instrument part that fits the song. Needs the base model.", "Генерирует новую партию инструмента под песню. Нужна base-модель.")),
    ("complete", T("Complete arrangement", "Дополнить аранжировку"),
     T("Fills in the instruments you pick. Needs the base model.", "Дописывает выбранные инструменты. Нужна base-модель.")),
]

private let trackNames = ["vocals", "backing_vocals", "drums", "bass", "guitar", "keyboard", "synth", "strings",
                          "brass", "woodwinds", "percussion", "fx"]

struct RegenerateSheet: View {
    @EnvironmentObject var store: StudioStore
    let target: RegenTarget

    @State private var waveform: JSONValue = .null
    @State private var duration: Double = 0
    @State private var start: Double = 0
    @State private var end: Double = 0
    @State private var dragFrom: Double?
    @State private var sections: [JSONValue] = []
    @State private var lines: [JSONValue] = []
    @State private var task = "repaint"
    @State private var prompt = ""
    @State private var lyrics = ""
    @State private var model = ""
    @State private var strength: Double = 0.5
    @State private var repaintMode = "balanced"
    @State private var repaintStrength: Double = 0.5
    @State private var track = "vocals"
    @State private var classes: Set<String> = ["drums", "bass"]
    @State private var seed = ""
    @State private var variations: Double = 2
    @State private var keepOutside = true
    @State private var xfade: Double = 0.35
    @State private var running = false
    @State private var progress: Double = 0
    @State private var message = ""
    @State private var results: [JSONValue] = []
    @State private var findingSections = false

    private var baseOnly: Bool { ["extract", "lego", "complete"].contains(task) }
    private var acestepReady: Bool { store.engineStatus["acestep"]?["ok"]?.bool == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "wand.and.rays").foregroundColor(Theme.accent)
                Text(T("Regenerate part of “\(target.title)”", "Перегенерация части «\(target.title)»"))
                    .font(Theme.title).foregroundColor(Theme.text).lineLimit(1)
                Spacer()
                if !acestepReady {
                    Badge(text: T("ACE-Step server is not running", "Сервер ACE-Step не запущен"), color: Theme.yellow)
                }
            }
            regionEditor
            HStack(alignment: .top, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    Caption(text: T("Task", "Задача"))
                    ForEach(editTasks, id: \.0) { t in
                        Button { task = t.0 } label: {
                            HStack(alignment: .top, spacing: 6) {
                                Image(systemName: task == t.0 ? "largecircle.fill.circle" : "circle")
                                    .foregroundColor(task == t.0 ? Theme.accent : Theme.text3).font(.system(size: 11))
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(t.1).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.text)
                                    Text(t.2).font(.system(size: 9)).foregroundColor(Theme.text3)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .frame(width: 270)
                VStack(alignment: .leading, spacing: 6) {
                    TextRow(label: T("Prompt / style", "Промпт / стиль"), text: $prompt,
                            placeholder: T("e.g. softer verse, piano only", "напр. тише, только фортепиано"), labelWidth: 110)
                    if task == "repaint" || task == "cover" {
                        Caption(text: T("Lyrics for this part (empty = keep)", "Текст этой части (пусто — оставить)"))
                        TextEditor(text: $lyrics)
                            .font(.system(size: 11)).scrollContentBackground(.hidden).padding(4).frame(height: 74)
                            .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
                            .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
                    }
                    if task == "repaint" {
                        PickerRow(label: T("Mode", "Режим"), selection: $repaintMode,
                                  options: [("conservative", T("Conservative", "Бережно")), ("balanced", T("Balanced", "Сбалансированно")),
                                            ("aggressive", T("Aggressive", "Смело"))], labelWidth: 110)
                        ParamRow(label: T("Change amount", "Сила изменения"), value: $repaintStrength, range: 0...1, step: 0.05,
                                 defaultValue: 0.5, format: { String(format: "%.2f", $0) }, labelWidth: 110)
                        ToggleRow(label: T("Keep the rest bit-exact (splice)", "Остальное бит-в-бит (склейка)"), isOn: $keepOutside,
                                  help: T("ACE-Step re-decodes the whole song; splicing keeps the original outside the region, important for Suno/GPTunneL tracks.",
                                          "ACE-Step заново декодирует всю песню; склейка оставляет оригинал вне фрагмента — важно для треков Suno/GPTunneL."))
                        if keepOutside {
                            ParamRow(label: T("Crossfade", "Кроссфейд"), value: $xfade, range: 0.05...2, step: 0.05, defaultValue: 0.35,
                                     format: { String(format: "%.2f s", $0) }, labelWidth: 110)
                        }
                    }
                    if task == "cover" {
                        ParamRow(label: T("Closeness", "Близость"), value: $strength, range: 0...1, step: 0.05, defaultValue: 0.5,
                                 format: { String(format: "%.2f", $0) }, labelWidth: 110)
                    }
                    if task == "extract" || task == "lego" {
                        PickerRow(label: T("Track", "Дорожка"), selection: $track, options: trackNames.map { ($0, $0) }, labelWidth: 110)
                    }
                    if task == "complete" {
                        FlowLayout(spacing: 4) {
                            ForEach(trackNames, id: \.self) { n in
                                Chip(title: n, isOn: classes.contains(n)) {
                                    if classes.contains(n) { classes.remove(n) } else { classes.insert(n) }
                                }
                            }
                        }
                    }
                    TextRow(label: T("Model", "Модель"), text: $model,
                            placeholder: baseOnly ? "acestep-v15-base" : T("server default", "по умолчанию сервера"), labelWidth: 110)
                    HStack(spacing: 8) {
                        TextRow(label: "Seed", text: $seed, placeholder: T("random", "случайный"), labelWidth: 110)
                        ParamRow(label: T("Variants", "Вариантов"), value: $variations, range: 1...4, step: 1, defaultValue: 2,
                                 format: { "\(Int($0))" }, labelWidth: 70)
                    }
                    if baseOnly && !model.contains("base") {
                        Text(T("Turbo and SFT models support only regenerate and cover. Enter a base model id.",
                               "Модели turbo и SFT умеют только перегенерацию и кавер. Укажите base-модель."))
                            .font(.system(size: 10)).foregroundColor(Theme.yellow)
                    }
                }
            }
            if running || !message.isEmpty {
                HStack(spacing: 8) {
                    if running { ProgressStrip(value: progress).frame(width: 160, height: 4) }
                    Text(message).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                }
            }
            if !results.isEmpty {
                Caption(text: T("Results", "Результаты"))
                ForEach(results, id: \.self) { r in
                    HStack(spacing: 8) {
                        Image(systemName: "music.note").foregroundColor(Theme.accent2)
                        Text(URL(fileURLWithPath: r.str("path")).lastPathComponent).font(.system(size: 11)).foregroundColor(Theme.text)
                            .lineLimit(1).truncationMode(.middle)
                        Spacer()
                        Button(T("Play", "Слушать")) { playFrom(r.str("path")) }.buttonStyle(StudioButtonStyle(compact: true))
                        Button(T("Original", "Оригинал")) { playFrom(target.path) }.buttonStyle(StudioButtonStyle(compact: true))
                        Button(T("Open in Studio", "Открыть в студии")) {
                            store.regenTarget = nil
                            Task { await store.openTrack(r) }
                        }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    }
                }
            }
            HStack {
                Button(T("Find Sections (Whisper)", "Найти секции (Whisper)")) { Task { await findSections() } }
                    .buttonStyle(StudioButtonStyle(compact: true))
                    .disabled(findingSections || running || target.lyrics.isEmpty)
                    .help(T("Aligns the lyrics to the audio to place [Verse]/[Chorus] markers on the timeline",
                            "Выравнивает текст по аудио и ставит метки [Verse]/[Chorus] на таймлайне"))
                Spacer()
                Button(T("Close", "Закрыть")) {
                    if running { cancel() }
                    store.regenTarget = nil
                }
                .buttonStyle(StudioButtonStyle())
                .keyboardShortcut(.cancelAction)
                Button(running ? T("Cancel", "Отмена") : T("Generate", "Сгенерировать")) {
                    if running { cancel() } else { Task { await run() } }
                }
                .buttonStyle(StudioButtonStyle(prominent: !running, destructive: running))
                .disabled(!running && (task == "repaint" && end - start < 1))
            }
        }
        .padding(18)
        .frame(width: 820)
        .background(Theme.bg1)
        .preferredColorScheme(.dark)
        .task { await load() }
    }

    // MARK: region editor

    private var regionEditor: some View {
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { g in
                let w = g.size.width, h = g.size.height
                let dur = max(duration, 0.001)
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: 6).fill(Theme.bg0)
                    MiniWaveform(waveform: waveform)
                    if task == "repaint" {
                        Rectangle().fill(Theme.accent.opacity(0.18))
                            .overlay(Rectangle().stroke(Theme.accent, lineWidth: 1))
                            .frame(width: max(2, CGFloat((end - start) / dur) * w), height: h)
                            .offset(x: CGFloat(start / dur) * w)
                            .allowsHitTesting(false)
                    }
                    ForEach(Array(sections.enumerated()), id: \.offset) { _, s in
                        let x = CGFloat(s.num("start") / dur) * w
                        Rectangle().fill(Theme.accent2.opacity(0.8)).frame(width: 1, height: h).offset(x: x)
                            .allowsHitTesting(false)
                        Text(s.str("name")).font(.system(size: 9, weight: .semibold)).foregroundColor(Theme.accent2)
                            .padding(.horizontal, 3).background(Theme.bg0.opacity(0.8)).offset(x: x + 2, y: 2)
                            .allowsHitTesting(false)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { v in
                    let t0 = Double(v.startLocation.x / max(w, 1)) * dur
                    let t1 = Double(v.location.x / max(w, 1)) * dur
                    dragFrom = t0
                    start = max(0, min(t0, t1))
                    end = min(dur, max(t0, t1))
                }.onEnded { _ in
                    dragFrom = nil
                    if end - start < 0.5 { snapToSection(at: start) }
                })
            }
            .frame(height: 92)
            HStack(spacing: 10) {
                Text(T("Drag to select · click a section to select it", "Тяните, чтобы выделить · клик по секции выделяет её"))
                    .font(.system(size: 9)).foregroundColor(Theme.text3)
                Spacer()
                TimeField(label: T("Start", "Начало"), value: $start, max: duration)
                TimeField(label: T("End", "Конец"), value: $end, max: duration)
                Text(Fmt.clock(max(0, end - start))).font(Theme.mono).foregroundColor(Theme.accent)
            }
            if !sections.isEmpty {
                FlowLayout(spacing: 4) {
                    ForEach(Array(sections.enumerated()), id: \.offset) { i, s in
                        Chip(title: "\(s.str("name")) \(Fmt.clock(s.num("start")))",
                             isOn: abs(start - s.num("start")) < 0.05) { selectSection(i) }
                    }
                }
            }
        }
    }

    private func selectSection(_ i: Int) {
        guard i < sections.count else { return }
        start = sections[i].num("start")
        end = sections[i].num("end", i + 1 < sections.count ? sections[i + 1].num("start") : duration)
        if end <= start { end = i + 1 < sections.count ? sections[i + 1].num("start") : duration }
        // lyrics of that section prefill the editor
        let ls = lines.filter { $0.str("section") == sections[i].str("name") && $0.num("start") >= start - 0.01 && $0.num("start") < end }
        if lyrics.isEmpty, !ls.isEmpty {
            lyrics = "[\(sections[i].str("name"))]\n" + ls.map { $0.str("text") }.joined(separator: "\n")
        }
    }

    private func snapToSection(at t: Double) {
        if let i = sections.lastIndex(where: { $0.num("start") <= t }) { selectSection(i) }
    }

    // MARK: engine

    private func load() async {
        if let w = try? await store.engine.call("analyze", ["path": .s(target.path), "points": 1200]) {
            waveform = w
            duration = w.num("duration")
            if end == 0 { start = min(30, duration * 0.3); end = min(duration, start + 20) }
        }
        // LRC next to the song or in a release made from it
        let lrc = URL(fileURLWithPath: target.path).deletingPathExtension().appendingPathExtension("lrc")
        if let text = try? String(contentsOf: lrc, encoding: .utf8) {
            await applyLRC(text)
        }
    }

    private func applyLRC(_ text: String) async {
        if let r = try? await store.engine.call("lyrics.parse", ["lrc": .s(text)]) {
            lines = r.list("lines")
            sections = r.list("sections")
            mergeSectionNames()
        }
    }

    /// LRC files have no section tags; take them from the song's tagged lyrics by line order.
    private func mergeSectionNames() {
        guard !target.lyrics.isEmpty else { return }
        Task {
            guard let p = try? await store.engine.call("lyrics.parse", ["lyrics": .s(target.lyrics)]) else { return }
            let tagged = p.list("lines")
            guard tagged.count == lines.count, !tagged.isEmpty else { return }
            var merged: [JSONValue] = []
            for (i, l) in lines.enumerated() {
                var x = l
                x["section"] = tagged[i]["section"]
                merged.append(x)
            }
            lines = merged
            var secs: [JSONValue] = []
            for l in merged {
                let name = l.str("section")
                if secs.last?.str("name") != name {
                    secs.append(["name": .s(name), "start": .n(l.num("start")), "end": .n(l.num("end"))])
                } else if var last = secs.popLast() {
                    last["end"] = .n(l.num("end"))
                    secs.append(last)
                }
            }
            sections = secs
        }
    }

    private func findSections() async {
        findingSections = true
        message = T("Aligning lyrics with Whisper…", "Выравниваю текст через Whisper…")
        defer { findingSections = false }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("ams-sections-\(UUID().uuidString.prefix(6))")
        do {
            let r = try await store.engine.call("lyrics.build", ["path": .s(target.path), "lyrics": .s(target.lyrics),
                                                                 "out_dir": .s(dir.path), "title": .s(target.title),
                                                                 "_group": "regen"]) { f, m in
                progress = f
                if !m.isEmpty { message = m }
            }
            lines = r.list("lines")
            sections = r.list("sections")
            message = T("\(sections.count) sections found", "Найдено секций: \(sections.count)")
            if let text = try? String(contentsOfFile: r.str("lrc"), encoding: .utf8) {
                let dst = URL(fileURLWithPath: target.path).deletingPathExtension().appendingPathExtension("lrc")
                try? text.write(to: dst, atomically: true, encoding: .utf8)
            }
        } catch { message = error.localizedDescription }
    }

    private func run() async {
        running = true
        progress = 0
        message = T("Sending to ACE-Step…", "Отправляю в ACE-Step…")
        results = []
        defer { running = false }
        var p: [String: JSONValue] = [
            "path": .s(target.path), "task": .s(task), "root": .s(store.projectRoot.path), "title": .s(target.title),
            "prompt": .s(prompt), "variations": .n(Int(variations)), "_group": "regen",
        ]
        if !model.isEmpty { p["model"] = .s(model) }
        if let s = Int(seed) { p["seed"] = .n(s) }
        switch task {
        case "repaint":
            p["start"] = .n(start); p["end"] = .n(end)
            p["repaint_mode"] = .s(repaintMode); p["repaint_strength"] = .n(repaintStrength)
            p["keep_outside"] = .b(keepOutside); p["xfade"] = .n(xfade)
            if !lyrics.isEmpty { p["lyrics"] = .s(lyrics) }
        case "cover":
            p["strength"] = .n(strength)
            p["lyrics"] = .s(lyrics.isEmpty ? target.lyrics : lyrics)
        case "extract", "lego":
            p["track"] = .s(track)
        case "complete":
            p["track_classes"] = .array(classes.sorted().map { .s($0) })
        default: break
        }
        do {
            let r = try await store.engine.call("edit.run", p) { f, m in
                progress = f
                if !m.isEmpty { message = m }
            }
            results = r.list("tracks")
            message = T("Done: \(results.count) variant(s), saved to the library", "Готово: вариантов — \(results.count), сохранено в библиотеку")
            await store.refreshLibrary()
        } catch let e as EngineError where e.isCancelled {
            message = T("Cancelled", "Отменено")
        } catch { message = error.localizedDescription }
    }

    private func cancel() {
        Task { _ = try? await store.engine.call("cancel", ["group": "regen"]) }
    }

    private func playFrom(_ path: String) {
        do {
            try store.player.load(URL(fileURLWithPath: path), timelineStart: 0, keepPosition: false, autoplay: false)
            store.player.seek(max(0, start - 2))
            store.player.play()
        } catch { store.fail(error) }
    }
}

private struct TimeField: View {
    let label: String
    @Binding var value: Double
    let max: Double

    var body: some View {
        HStack(spacing: 4) {
            Text(label).font(.system(size: 10)).foregroundColor(Theme.text3)
            TextField("", value: Binding(get: { (value * 10).rounded() / 10 }, set: { value = Swift.min(Swift.max(0, $0), max) }),
                      format: .number.precision(.fractionLength(1)))
                .textFieldStyle(.plain).font(Theme.mono).frame(width: 52)
                .padding(.horizontal, 4).frame(height: 20)
                .background(RoundedRectangle(cornerRadius: 4).fill(Theme.bg0))
            Text("s").font(.system(size: 10)).foregroundColor(Theme.text3)
        }
    }
}

private struct MiniWaveform: View {
    let waveform: JSONValue

    var body: some View {
        Canvas { ctx, size in
            let peaks = waveform["peaks"]?[0]?.doubles ?? []
            let n = peaks.count
            guard n > 1 else { return }
            let cols = max(1, Int(size.width / 2))
            let mid = size.height / 2
            var path = Path()
            for c in 0..<cols {
                let a = c * n / cols, b = Swift.max(a + 1, (c + 1) * n / cols)
                var pk = 0.0
                for i in a..<Swift.min(b, n) { pk = Swift.max(pk, peaks[i]) }
                let x = CGFloat(c) * size.width / CGFloat(cols)
                let ph = Swift.max(0.5, CGFloat(Swift.min(pk, 1)) * (mid - 2))
                path.addRect(CGRect(x: x, y: mid - ph, width: 1.2, height: ph * 2))
            }
            ctx.fill(path, with: .color(Theme.text2.opacity(0.7)))
        }
    }
}
