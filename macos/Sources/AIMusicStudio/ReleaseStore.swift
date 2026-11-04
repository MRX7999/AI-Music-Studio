import SwiftUI
import AppKit

/// Release pipeline steps in the order the Release page runs them.
enum ReleaseStep: String, CaseIterable, Identifiable {
    case superres, refmaster, cover, lyrics, humanize, detect, package
    var id: String { rawValue }
    var title: String {
        switch self {
        case .superres: return T("Bandwidth", "Полоса")
        case .refmaster: return T("Reference", "Референс")
        case .cover: return T("Cover", "Обложка")
        case .lyrics: return T("Synced lyrics", "Текст и LRC")
        case .humanize: return T("Humanize", "Гуманизация")
        case .detect: return T("AI check", "Проверка на ИИ")
        case .package: return T("Package", "Пакет")
        }
    }
    var icon: String {
        switch self {
        case .superres: return "waveform.path.ecg.rectangle"
        case .refmaster: return "dial.medium"
        case .cover: return "photo"
        case .lyrics: return "text.quote"
        case .humanize: return "person.wave.2"
        case .detect: return "checkmark.shield"
        case .package: return "shippingbox"
        }
    }
}

struct SuperresOptions: Equatable {
    var exportSR: Double = 48000
    var mode = "mid"
    var backend = ""
    var force = false
    var highGainDb: Double = 0
    var steps: Double = 12
    var guidance: Double = 2
    var twoPass = true
}

struct RefMasterOptions: Equatable {
    var reference = UserDefaults.standard.string(forKey: "refmaster.reference") ?? "" {
        didSet { UserDefaults.standard.set(reference, forKey: "refmaster.reference") }
    }
    var backend = ""
    var strength: Double = 1
    var maxDb: Double = 6
    var limiter = true
    var bits: Double = 24
}

struct CoverOptions: Equatable {
    var prompt = ""
    var extra = ""
    var seed = ""
    var backend = ""
}

/// The humanization pass (the user's own humanize module): 12 subtle production steps.
struct HumanizeOptions: Equatable {
    private static func flag(_ key: String, _ def: Bool) -> Bool {
        UserDefaults.standard.object(forKey: key) as? Bool ?? def
    }
    var preset = UserDefaults.standard.string(forKey: "humanize.preset") ?? "ultra-low" {
        didSet { UserDefaults.standard.set(preset, forKey: "humanize.preset") }
    }
    var enabled = HumanizeOptions.flag("humanize.enabled", false) {
        didSet { UserDefaults.standard.set(enabled, forKey: "humanize.enabled") }
    }
    var seed = ""                                  // empty → engine default (42)
    var skipNoise = false
}

struct DetectOptions: Equatable {
    var fakeprint = true
    var aigm = true
    var sightengine = false
    var acrcloud = false
    var threshold: Double = 0.5
    var list: [String] {
        [("fakeprint", fakeprint), ("aigm", aigm), ("sightengine", sightengine), ("acrcloud", acrcloud)]
            .filter { $0.1 }.map { $0.0 }
    }
}

/// Distributor package format, chosen like in Export. Remembered between launches.
struct PackageOptions: Equatable {
    private static func num(_ key: String, _ def: Double) -> Double {
        let v = UserDefaults.standard.double(forKey: key)
        return v > 0 ? v : def
    }
    private static func flag(_ key: String) -> Bool { UserDefaults.standard.object(forKey: key) as? Bool ?? true }

    var format = UserDefaults.standard.string(forKey: "package.format") ?? "wav" {
        didSet {
            UserDefaults.standard.set(format, forKey: "package.format")
            if format == "flac" || format == "alac", bitDepth > 24 { bitDepth = 24 }
            if format == "mp3", sampleRate > 48000 { sampleRate = 48000 }
        }
    }
    var sampleRate = PackageOptions.num("package.sampleRate", 44100) {
        didSet { UserDefaults.standard.set(sampleRate, forKey: "package.sampleRate") }
    }
    var bitDepth = PackageOptions.num("package.bitDepth", 24) {
        didSet { UserDefaults.standard.set(bitDepth, forKey: "package.bitDepth") }
    }
    var mp3Bitrate = PackageOptions.num("package.mp3Bitrate", 320) {
        didSet { UserDefaults.standard.set(mp3Bitrate, forKey: "package.mp3Bitrate") }
    }
    var dither = UserDefaults.standard.string(forKey: "package.dither") ?? "tpdf" {
        didSet { UserDefaults.standard.set(dither, forKey: "package.dither") }
    }
    var embedCover = PackageOptions.flag("package.embedCover") {
        didSet { UserDefaults.standard.set(embedCover, forKey: "package.embedCover") }
    }
    var embedLyrics = PackageOptions.flag("package.embedLyrics") {
        didSet { UserDefaults.standard.set(embedLyrics, forKey: "package.embedLyrics") }
    }

    var lossless: Bool { format != "mp3" }

    /// "WAV 44.1 kHz / 24-bit", "MP3 320 kbps / 48 kHz"
    var summary: String {
        let khz = String(format: sampleRate.truncatingRemainder(dividingBy: 1000) == 0 ? "%.0f" : "%.1f", sampleRate / 1000)
        if format == "mp3" { return "MP3 \(Int(mp3Bitrate)) kbps / \(khz) kHz" }
        let depth = bitDepth >= 32 ? "32-bit float" : "\(Int(bitDepth))-bit"
        return "\(format.uppercased()) \(khz) kHz / \(depth)"
    }

    var payload: [String: JSONValue] {
        ["format": .s(format), "sample_rate": .n(Int(sampleRate)), "bit_depth": .n(Int(bitDepth)),
         "mp3_bitrate": .n(Int(mp3Bitrate)), "dither": .s(dither), "embed_cover": .b(embedCover),
         "embed_lyrics": .b(embedLyrics)]
    }
}

struct PublishOptions: Equatable {
    var telegram = false
    var youtube = false
    var package = true
    var caption = ""
    var silent = false
    var aiNote = true
    var chatOverride = ""
    var ytTitle = ""
    var ytDescription = ""
    var privacy = "private"
    var schedule = false
    var publishAt = Date().addingTimeInterval(86400)
    var videoStyle = "waveform"
}

/// State of the Release & Publish page. Talks to `release.*` and `publish.*` engine methods.
@MainActor
final class ReleaseStore: ObservableObject {
    unowned let studio: StudioStore
    init(studio: StudioStore) { self.studio = studio }

    @Published var releases: [JSONValue] = []
    @Published var current: JSONValue?
    @Published var running: String?
    @Published var progress: Double?
    @Published var message = ""
    @Published var analysis: JSONValue = .null
    @Published var specBefore: String?
    @Published var specAfter: String?
    @Published var jobs: [JSONValue] = []
    @Published var log: [JSONValue] = []
    @Published var doctor: JSONValue = .null

    @Published var sr = SuperresOptions()
    @Published var refOpts = RefMasterOptions()
    @Published var coverOpts = CoverOptions()
    @Published var detectOpts = DetectOptions()
    @Published var humOpts = HumanizeOptions()
    @Published var pub = PublishOptions()
    @Published var pkg = PackageOptions()
    @Published var lrcText = ""
    @Published var lrcLanguage = ""
    @Published var showConfirm = false
    @Published var confirmPublic = false

    private var engine: EngineClient { studio.engine }
    private var root: String { studio.projectRoot.path }
    var currentID: String? { current?.str("id") }

    // MARK: list / select

    func refresh() async {
        guard studio.engineState.isReady else { return }
        if let r = try? await engine.call("release.list", ["root": .s(root)]) { releases = r.list("releases") }
        if let id = currentID, !releases.contains(where: { $0.str("id") == id }) { current = nil }
        await refreshQueue()
        if doctor.isNull { await refreshDoctor() }
    }

    func refreshDoctor() async {
        if let d = try? await engine.call("tools.doctor") { doctor = d }
    }

    func refreshQueue() async {
        if let q = try? await engine.call("publish.queue", ["root": .s(root), "limit": 200]) {
            jobs = q.list("jobs")
            log = q.list("log")
        }
    }

    func select(_ id: String) async {
        do {
            let r = try await engine.call("release.get", ["root": .s(root), "id": .s(id)])
            setCurrent(r)
            await loadSpectrograms()
        } catch { studio.fail(error) }
    }

    private func setCurrent(_ r: JSONValue) {
        let changed = r.str("id") != currentID
        current = r
        if changed {
            lrcText = (try? String(contentsOfFile: r.str("lrc"), encoding: .utf8)) ?? ""
            analysis = .null
            specBefore = nil
            specAfter = nil
            let ai = r["meta"]?["ai"]
            pub.aiNote = ai?["generated"]?.bool ?? true
            pub.ytTitle = r.str("artist").isEmpty ? r.str("title") : "\(r.str("artist")) — \(r.str("title"))"
            pub.ytDescription = ""
            coverOpts.prompt = ""
        }
    }

    /// New release from a library song or a finished mix (the file is copied into releases/<id>/).
    func create(path: String, title: String, lyrics: String, meta: [String: JSONValue] = [:]) async {
        do {
            let artist = UserDefaults.standard.string(forKey: "releaseArtist") ?? ""
            let r = try await engine.call("release.create", [
                "root": .s(root), "source": .s(path), "title": .s(title), "artist": .s(artist),
                "lyrics": .s(lyrics), "meta": .object(meta),
            ])
            await refresh()
            setCurrent(r)
            studio.mode = .release
            await loadSpectrograms()
            await analyze()
        } catch { studio.fail(error) }
    }

    func chooseFile() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.prompt = T("Create Release", "Создать релиз")
        guard p.runModal() == .OK, let u = p.url else { return }
        Task { await create(path: u.path, title: u.deletingPathExtension().lastPathComponent, lyrics: "") }
    }

    // MARK: metadata

    func update(_ fields: [String: JSONValue], meta: [String: JSONValue]? = nil) async {
        guard let id = currentID else { return }
        var p: [String: JSONValue] = ["root": .s(root), "id": .s(id)]
        for (k, v) in fields { p[k] = v }
        if let meta { p["meta"] = .object(meta) }
        do { setCurrent(try await engine.call("release.update", p)) } catch { studio.fail(error) }
        if let a = fields["artist"]?.string { UserDefaults.standard.set(a, forKey: "releaseArtist") }
    }

    func metaStr(_ key: String) -> Binding<String> {
        Binding(get: { self.current?["meta"]?[key]?.string ?? "" },
                set: { v in
                    self.current?.updateObject("meta") { $0[key] = .s(v) }
                    self.scheduleMetaSave()
                })
    }

    func metaBool(_ key: String) -> Binding<Bool> {
        Binding(get: { self.current?["meta"]?[key]?.bool ?? false },
                set: { v in
                    self.current?.updateObject("meta") { $0[key] = .b(v) }
                    self.scheduleMetaSave()
                })
    }

    func field(_ key: String) -> Binding<String> {
        Binding(get: { self.current?[key]?.string ?? "" },
                set: { v in
                    self.current?[key] = .s(v)
                    self.scheduleMetaSave()
                })
    }

    func aiFlag(_ key: String) -> Binding<String> {
        Binding(get: { self.current?["meta"]?["ai"]?[key]?.string ?? "" },
                set: { v in
                    self.current?.updateObject("meta") { m in
                        var ai = m["ai"] ?? .object([:])
                        ai[key] = .s(v)
                        m["ai"] = ai
                    }
                    self.scheduleMetaSave()
                })
    }

    var aiGenerated: Binding<Bool> {
        Binding(get: { self.current?["meta"]?["ai"]?["generated"]?.bool ?? true },
                set: { v in
                    self.current?.updateObject("meta") { m in
                        var ai = m["ai"] ?? .object([:])
                        ai["generated"] = .b(v)
                        m["ai"] = ai
                    }
                    self.pub.aiNote = v
                    self.scheduleMetaSave()
                })
    }

    private var metaTask: Task<Void, Never>?
    private var metaDirty = false
    private func scheduleMetaSave() {
        metaDirty = true
        metaTask?.cancel()
        metaTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 600_000_000)
            guard let self, !Task.isCancelled else { return }
            await self.saveMeta()
        }
    }

    /// Sends edits that are still waiting for the debounce, so a step started right after typing
    /// (for example Build package after filling ISRC) uses them and does not overwrite them.
    func flushMeta() async {
        metaTask?.cancel()
        metaTask = nil
        await saveMeta()
    }

    private func saveMeta() async {
        guard metaDirty, let c = current else { return }
        metaDirty = false
        var meta = c["meta"]?.object ?? [:]
        if let tags = meta["tags"]?.string {           // "a, b" → ["a", "b"]
            meta["tags"] = .array(tags.split(separator: ",").map { .s($0.trimmingCharacters(in: .whitespaces)) }
                .filter { $0.string?.isEmpty == false })
        }
        await update(["title": .s(c.str("title")), "artist": .s(c.str("artist")),
                      "lyrics_text": .s(c.str("lyrics_text"))], meta: meta)
    }

    var tagsText: Binding<String> {
        Binding(get: {
            if let a = self.current?["meta"]?["tags"]?.array { return a.compactMap { $0.string }.joined(separator: ", ") }
            return self.current?["meta"]?["tags"]?.string ?? ""
        }, set: { v in
            self.current?.updateObject("meta") { $0["tags"] = .s(v) }
            self.scheduleMetaSave()
        })
    }

    // MARK: steps

    func analyze() async {
        guard let c = current else { return }
        analysis = (try? await engine.call("superres.analyze", ["path": .s(c.str("source")), "export_sr": .n(sr.exportSR)])) ?? .null
    }

    func loadSpectrograms() async {
        guard let c = current else { return }
        let folder = URL(fileURLWithPath: c.str("source")).deletingLastPathComponent()
        if let r = try? await engine.call("spectrum.image", ["path": .s(c.str("source")),
                                                             "out": .s(folder.appendingPathComponent("spectrum_source.png").path)]) {
            specBefore = r.str("path")
        }
        let master = c.str("master")
        if !master.isEmpty, master != c.str("source") {
            let out = folder.appendingPathComponent("spectrum_master.png")
            try? FileManager.default.removeItem(at: out)
            if let r = try? await engine.call("spectrum.image", ["path": .s(master), "out": .s(out.path)]) {
                specAfter = r.str("path")
            }
        } else {
            specAfter = nil
        }
    }

    func options(for step: ReleaseStep) -> [String: JSONValue] {
        switch step {
        case .superres:
            return ["export_sr": .n(sr.exportSR), "mode": .s(sr.mode), "backend": .s(sr.backend), "force": .b(sr.force),
                    "high_gain_db": .n(sr.highGainDb), "steps": .n(Int(sr.steps)), "guidance": .n(sr.guidance),
                    "two_pass": .b(sr.twoPass)]
        case .refmaster:
            return ["reference": .s(refOpts.reference), "backend": .s(refOpts.backend), "strength": .n(refOpts.strength),
                    "max_db": .n(refOpts.maxDb), "use_limiter": .b(refOpts.limiter), "bits": .n(Int(refOpts.bits))]
        case .cover:
            return ["prompt": .s(coverOpts.prompt), "extra": .s(coverOpts.extra), "seed": .s(coverOpts.seed),
                    "backend": .s(coverOpts.backend)]
        case .lyrics:
            return ["language": .s(lrcLanguage)]
        case .humanize:
            return ["preset": .s(humOpts.preset), "seed": .s(humOpts.seed), "skip_noise": .b(humOpts.skipNoise),
                    "enabled": .b(humOpts.enabled)]
        case .detect:
            return ["detectors": .array(detectOpts.list.map { .s($0) }), "threshold": .n(detectOpts.threshold)]
        case .package:
            return pkg.payload
        }
    }

    func run(_ step: ReleaseStep, extra: [String: JSONValue] = [:]) async {
        guard let id = currentID, running == nil else { return }
        await flushMeta()
        running = step.rawValue
        progress = 0
        message = step.title + "…"
        defer { running = nil; progress = nil }
        var opts = options(for: step)
        for (k, v) in extra { opts[k] = v }
        do {
            let r = try await engine.call("release.step", ["root": .s(root), "id": .s(id), "step": .s(step.rawValue),
                                                           "options": .object(opts), "_group": "release"]) { [weak self] f, m in
                self?.progress = f
                if !m.isEmpty { self?.message = m }
            }
            setCurrent(r)
            if step == .lyrics { lrcText = (try? String(contentsOfFile: r.str("lrc"), encoding: .utf8)) ?? "" }
            if step == .superres || step == .refmaster { await loadSpectrograms() }
            message = step.title + " — " + T("done", "готово")
            await refresh()
        } catch let e as EngineError where e.isCancelled {
            message = T("Cancelled", "Отменено")
        } catch {
            message = error.localizedDescription
            studio.fail(error)
        }
        // the cover step may have downloaded the image model, lyrics may have fetched Whisper weights
        if step == .cover || step == .lyrics { await refreshDoctor() }
    }

    func runAll() async {
        for s in ReleaseStep.allCases {
            if s == .lyrics && (current?.str("lyrics_text").isEmpty ?? true) && lrcText.isEmpty { continue }
            if s == .refmaster && refOpts.reference.isEmpty { continue }
            if s == .humanize && !humOpts.enabled { continue }
            await run(s)
            if message == T("Cancelled", "Отменено") { return }
        }
    }

    func saveLRC() async {
        await run(.lyrics, extra: ["lrc_text": .s(lrcText)])
    }

    func chooseReference() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.prompt = T("Use as Reference", "Взять как референс")
        guard p.runModal() == .OK, let u = p.url else { return }
        refOpts.reference = u.path
    }

    func chooseCoverFile() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.image]
        guard p.runModal() == .OK, let u = p.url else { return }
        Task { await run(.cover, extra: ["file": .s(u.path)]) }
    }

    func cancel() {
        Task { _ = try? await engine.call("cancel", ["group": "release"]) }
    }

    // MARK: publishing

    var services: [String: JSONValue] {
        var s: [String: JSONValue] = [:]
        if pub.package { s["package"] = .object(pkg.payload) }
        if pub.telegram {
            var t: [String: JSONValue] = ["caption": .s(pub.caption), "silent": .b(pub.silent), "ai_note": .b(pub.aiNote)]
            if !pub.chatOverride.isEmpty { t["chat_id"] = .s(pub.chatOverride) }
            s["telegram"] = .object(t)
        }
        if pub.youtube {
            var y: [String: JSONValue] = ["title": .s(pub.ytTitle), "description": .s(pub.ytDescription),
                                          "privacy": .s(pub.privacy), "video_style": .s(pub.videoStyle)]
            if pub.schedule {
                let f = ISO8601DateFormatter()
                f.formatOptions = [.withInternetDateTime]
                y["publish_at"] = .s(f.string(from: pub.publishAt))
            }
            s["youtube"] = .object(y)
        }
        return s
    }

    var needsPublicConfirm: Bool { pub.youtube && pub.privacy == "public" && !pub.schedule }

    /// Plain-language list of what pressing "Publish" will do (shown in the confirmation sheet).
    var plan: [String] {
        guard let c = current else { return [] }
        var out: [String] = []
        let name = c.str("artist").isEmpty ? c.str("title") : "\(c.str("artist")) — \(c.str("title"))"
        if pub.package {
            out.append(T("Build the distributor package (\(pkg.summary), tags with cover and lyrics in the file, 3000 px cover, metadata, LRC, AI report) in releases/\(c.str("id"))/package.",
                         "Собрать пакет для дистрибьютора (\(pkg.summary), теги с обложкой и текстом в файле, обложка 3000 px, метаданные, LRC, отчёт ИИ) в releases/\(c.str("id"))/package."))
        }
        if pub.telegram {
            let chat = pub.chatOverride.isEmpty ? (Keychain.get("telegram_chat") ?? "") : pub.chatOverride
            out.append(T("Send “\(name)” as MP3 320 kbps to Telegram \(chat.isEmpty ? "(chat not set)" : chat)\(pub.silent ? " without a notification" : "")\(pub.aiNote ? ", caption marked “Made with AI”" : "").",
                         "Отправить «\(name)» в Telegram \(chat.isEmpty ? "(чат не задан)" : chat) как MP3 320 кбит/с\(pub.silent ? " без уведомления" : "")\(pub.aiNote ? ", с пометкой «Создано с помощью ИИ»" : "")."))
        }
        if pub.youtube {
            let vis: String
            if pub.schedule {
                vis = T("private until \(pub.publishAt.formatted(date: .abbreviated, time: .shortened)), then public",
                        "приватно до \(pub.publishAt.formatted(date: .abbreviated, time: .shortened)), затем публично")
            } else {
                vis = pub.privacy == "public" ? T("PUBLIC immediately", "ПУБЛИЧНО сразу")
                    : (pub.privacy == "unlisted" ? T("unlisted (link only)", "по ссылке") : T("private", "приватно"))
            }
            out.append(T("Render a 1080p video and upload it to YouTube as “\(pub.ytTitle)”, \(vis), category Music, “altered or synthetic content” = \(aiGenerated.wrappedValue ? "yes" : "no"). Uses ~1 upload of the daily quota.",
                         "Собрать видео 1080p и загрузить на YouTube как «\(pub.ytTitle)», \(vis), категория Music, «изменённый или синтетический контент» = \(aiGenerated.wrappedValue ? "да" : "нет"). Тратит 1 загрузку из дневной квоты."))
        }
        return out
    }

    func publish() async {
        guard let id = currentID, running == nil else { return }
        await flushMeta()
        showConfirm = false
        running = "publish"
        progress = 0
        message = T("Publishing…", "Публикация…")
        defer { running = nil; progress = nil; confirmPublic = false }
        do {
            let r = try await engine.call("publish.submit", [
                "root": .s(root), "id": .s(id), "services": .object(services), "confirmed": .b(true),
                "confirm_public": .b(confirmPublic), "_group": "release",
            ]) { [weak self] f, m in
                self?.progress = f
                if !m.isEmpty { self?.message = m }
            }
            let res = r.list("jobs")
            let ok = res.filter { $0.str("status") == "done" }.count
            message = T("\(ok) of \(res.count) done", "Готово \(ok) из \(res.count)")
            for j in res where j.str("status") != "done" {
                studio.show("\(j.str("service")): \(j.str("error"))", error: true)
            }
            if let url = res.compactMap({ $0["result"]?.str("url") }).first(where: { !$0.isEmpty }) {
                studio.show(T("Published: ", "Опубликовано: ") + url)
            }
        } catch { studio.fail(error) }
        await refreshQueue()
        if let id = currentID { await select(id) }
    }

    func retry(_ jobID: String?) async {
        running = "publish"
        defer { running = nil; progress = nil }
        var p: [String: JSONValue] = ["root": .s(root), "_group": "release"]
        if let jobID { p["job_id"] = .s(jobID) }
        do {
            _ = try await engine.call("publish.retry", p) { [weak self] f, m in
                self?.progress = f
                if !m.isEmpty { self?.message = m }
            }
        } catch { studio.fail(error) }
        await refreshQueue()
    }

    func remove(_ jobID: String) async {
        _ = try? await engine.call("publish.remove", ["root": .s(root), "job_id": .s(jobID)])
        await refreshQueue()
    }

    func check(_ service: String) async {
        do {
            let r = try await engine.call("publish.check", ["service": .s(service)])
            let name = service == "telegram" ? r.str("chat_title") : r.str("title")
            studio.show(T("Connected: ", "Подключено: ") + "\(service) · \(name)")
        } catch { studio.fail(error) }
    }
}
