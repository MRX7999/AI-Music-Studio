import SwiftUI
import AppKit

/// Release & Publish: bandwidth (super-resolution) → cover → synced lyrics → AI check → package → publish.
struct ReleaseView: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        HStack(spacing: 0) {
            ReleaseList(rs: rs).frame(width: 230)
            Rectangle().fill(Theme.stroke).frame(width: 1)
            if rs.current != nil {
                ReleaseDetail(rs: rs).frame(minWidth: 0, maxWidth: .infinity)
            } else {
                ReleaseEmpty(rs: rs)
            }
        }
        .task { await rs.refresh() }
        .sheet(isPresented: $rs.showConfirm) { PublishConfirmSheet(rs: rs) }
    }
}

// MARK: - list

private struct ReleaseList: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Caption(text: T("Releases", "Релизы"))
                Spacer()
                NewReleaseMenu(rs: rs)
            }
            .padding(.horizontal, 10)
            .frame(height: 34)
            Rectangle().fill(Theme.stroke).frame(height: 1)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(rs.releases, id: \.self) { r in
                        let on = r.str("id") == rs.currentID
                        Button { Task { await rs.select(r.str("id")) } } label: {
                            HStack(spacing: 8) {
                                CoverThumb(path: r.str("cover"), size: 34)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(r.str("title")).font(.system(size: 11, weight: .semibold))
                                        .foregroundColor(Theme.text).lineLimit(1)
                                    Text(r.str("artist").isEmpty ? "—" : r.str("artist")).font(.system(size: 10))
                                        .foregroundColor(Theme.text3).lineLimit(1)
                                }
                                Spacer(minLength: 0)
                                if !r.str("verdict").isEmpty { VerdictDot(verdict: r.str("verdict")) }
                            }
                            .padding(6)
                            .background(RoundedRectangle(cornerRadius: 6).fill(on ? Theme.bg3 : Color.clear))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button(T("Show in Finder", "Показать в Finder")) {
                                store.reveal(store.projectRoot.appendingPathComponent("releases/\(r.str("id"))").path)
                            }
                        }
                    }
                }
                .padding(6)
            }
        }
        .background(Theme.bg1)
    }
}

private struct NewReleaseMenu: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        Menu {
            if !store.renders.isEmpty {
                Section(T("Finished mixes", "Готовые миксы")) {
                    ForEach(store.renders.prefix(20), id: \.self) { r in
                        Button(r.str("name")) {
                            Task { await rs.create(path: r.str("path"), title: r.str("name"), lyrics: "") }
                        }
                    }
                }
            }
            if !store.songs.isEmpty {
                Section(T("Generated songs", "Сгенерированные песни")) {
                    ForEach(store.songs.prefix(20), id: \.self) { s in
                        Button(s.str("title")) {
                            Task {
                                await rs.create(path: s.str("path"), title: s.str("title"), lyrics: s.str("lyrics"),
                                                meta: ["genre": .s(s["meta"]?.str("style") ?? ""),
                                                       "language": .s(s["meta"]?.str("language") ?? "")])
                            }
                        }
                    }
                }
            }
            Divider()
            Button(T("Choose a File…", "Выбрать файл…")) { rs.chooseFile() }
        } label: {
            Image(systemName: "plus").font(.system(size: 12, weight: .semibold))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help(T("New release from a mix, a song or a file", "Новый релиз из микса, песни или файла"))
    }
}

/// The reference, AI-check and package cards on their own (README screenshots).
struct ReleaseShowcase: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ReferenceCard(rs: rs)
            AICheckCard(rs: rs)
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.bg0)
    }
}

/// The distributor package card on its own (screenshots).
struct PackageShowcase: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        PackageCard(rs: rs)
            .padding(14)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Theme.bg0)
    }
}

private struct ReleaseEmpty: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "paperplane").font(.system(size: 34, weight: .light)).foregroundColor(Theme.text3)
            Text(T("Make a release from a finished mix", "Сделайте релиз из готового микса"))
                .font(Theme.title).foregroundColor(Theme.text)
            Text(T("Bandwidth check and super-resolution, cover, synced lyrics, an AI check with independent detectors, a distributor package and uploads to Telegram and YouTube.",
                   "Проверка полосы и расширение спектра, обложка, синхронный текст, проверка независимыми детекторами ИИ, пакет для дистрибьютора и загрузка в Telegram и YouTube."))
                .font(.system(size: 11)).foregroundColor(Theme.text3).multilineTextAlignment(.center)
                .frame(maxWidth: 460)
            HStack {
                NewReleaseMenu(rs: rs)
                Text(T("New release", "Новый релиз")).font(.system(size: 11)).foregroundColor(Theme.text2)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - detail

private struct ReleaseDetail: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                ReleaseHeader(rs: rs)
                ScrollView(.horizontal, showsIndicators: false) { StepStrip(rs: rs) }
                if let r = rs.running {
                    HStack(spacing: 8) {
                        ProgressStrip(value: rs.progress)
                        Text(rs.message).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(1)
                            .frame(width: 320, alignment: .leading)
                        Button(T("Cancel", "Отмена")) { rs.cancel() }
                            .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
                            .disabled(r == "publish")
                    }
                } else if !rs.message.isEmpty {
                    Text(rs.message).font(.system(size: 10)).foregroundColor(Theme.text3)
                }
                BandwidthCard(rs: rs)
                ReferenceCard(rs: rs)
                CoverCard(rs: rs)
                LyricsCard(rs: rs)
                HumanizeCard(rs: rs)
                AICheckCard(rs: rs)
                PackageCard(rs: rs)
                PublishCard(rs: rs)
            }
            .padding(14)
            .frame(maxWidth: 980, alignment: .leading)
        }
        .background(Theme.bg0)
    }
}

private struct ReleaseHeader: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            CoverThumb(path: rs.current?.str("thumb") ?? "", size: 120)
            VStack(alignment: .leading, spacing: 6) {
                TextRow(label: T("Title", "Название"), text: rs.field("title"), labelWidth: 90)
                TextRow(label: T("Artist", "Исполнитель"), text: rs.field("artist"), labelWidth: 90)
                HStack(spacing: 8) {
                    TextRow(label: T("Genre", "Жанр"), text: rs.metaStr("genre"), labelWidth: 90)
                    TextRow(label: T("Language", "Язык"), text: rs.metaStr("language"), placeholder: "en / ru", labelWidth: 60)
                        .frame(width: 160)
                }
                TextRow(label: T("Tags", "Теги"), text: rs.tagsText, placeholder: "synthpop, night drive", labelWidth: 90)
                Toggle(T("AI-generated (disclose)", "Создано ИИ (раскрыть)"), isOn: rs.aiGenerated)
                    .toggleStyle(.checkbox).font(.system(size: 11))
                    .fixedSize()
                    .help(T("Sets YouTube “altered or synthetic content”, the Telegram note and the ai{} block of the package. Platforms require it for AI music.",
                            "Ставит на YouTube «изменённый или синтетический контент», пометку в Telegram и блок ai{} в пакете. Площадки требуют это для ИИ-музыки."))
                HStack(spacing: 14) {
                    PickerRow(label: T("Vocals", "Вокал"), selection: rs.aiFlag("vocals"),
                              options: [("ai", T("AI", "ИИ")), ("human", T("Human", "Человек")), ("ai_converted", T("Human → RVC", "Человек → RVC"))],
                              labelWidth: 50)
                        .frame(minWidth: 150, maxWidth: 210)
                    PickerRow(label: T("Lyrics", "Текст"), selection: rs.aiFlag("lyrics"),
                              options: [("human", T("Human", "Человек")), ("ai", T("AI", "ИИ")), ("human_or_ai", T("Mixed", "Смешанно"))],
                              labelWidth: 50)
                        .frame(minWidth: 150, maxWidth: 200)
                }
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 6) {
                Button(T("Run All Steps", "Выполнить все шаги")) { Task { await rs.runAll() } }
                    .buttonStyle(StudioButtonStyle(prominent: true))
                    .disabled(rs.running != nil)
                Button(T("Show in Finder", "Показать в Finder")) {
                    if let c = rs.current { store.reveal(URL(fileURLWithPath: c.str("source")).deletingLastPathComponent().path) }
                }
                .buttonStyle(StudioButtonStyle(compact: true))
                Button(T("Listen", "Слушать")) {
                    if let c = rs.current { store.listen(c.str("master"), title: c.str("title")) }
                }
                .buttonStyle(StudioButtonStyle(compact: true))
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.bg1))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.stroke, lineWidth: 1))
    }
}

private struct StepStrip: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        HStack(spacing: 6) {
            ForEach(ReleaseStep.allCases) { s in
                let done = rs.current?["ready"]?[s.rawValue]?.bool ?? false
                let active = rs.running == s.rawValue
                HStack(spacing: 5) {
                    Image(systemName: active ? "hourglass" : (done ? "checkmark.circle.fill" : s.icon))
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(active ? Theme.accent : (done ? Theme.green : Theme.text3))
                    Text(s.title).font(.system(size: 11, weight: .medium))
                        .foregroundColor(done || active ? Theme.text : Theme.text2)
                }
                .padding(.horizontal, 9)
                .frame(height: 24)
                .background(Capsule().fill(Theme.bg2))
                .overlay(Capsule().stroke(active ? Theme.accent : Theme.stroke, lineWidth: 1))
                if s != ReleaseStep.allCases.last {
                    Image(systemName: "chevron.right").font(.system(size: 8)).foregroundColor(Theme.text3)
                }
            }
            Image(systemName: "chevron.right").font(.system(size: 8)).foregroundColor(Theme.text3)
            HStack(spacing: 5) {
                Image(systemName: "paperplane.fill").font(.system(size: 10)).foregroundColor(Theme.accent2)
                Text(T("Publish", "Публикация")).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.text2)
            }
            .padding(.horizontal, 9).frame(height: 24)
            .background(Capsule().fill(Theme.bg2))
            .overlay(Capsule().stroke(Theme.stroke, lineWidth: 1))
        }
    }
}

// MARK: - step cards

private struct StepButton: View {
    @ObservedObject var rs: ReleaseStore
    let step: ReleaseStep
    var title: String? = nil
    var extra: [String: JSONValue] = [:]

    var body: some View {
        Button(title ?? T("Run", "Выполнить")) { Task { await rs.run(step, extra: extra) } }
            .buttonStyle(StudioButtonStyle(prominent: true, compact: true))
            .disabled(rs.running != nil)
    }
}

private struct BandwidthCard: View {
    @ObservedObject var rs: ReleaseStore

    private var backends: [(String, String)] {
        var out: [(String, String)] = [("", T("Auto (MLX first)", "Авто (сначала MLX)"))]
        for id in ["flashsr", "audiosr"] {
            let t = rs.doctor["tools"]?[id]
            let st = t?.flag("installed") == true ? "" : (t?.flag("supported", true) == false ? T(" — not on this Mac", " — не для этого Mac") : T(" — not installed", " — не установлен"))
            out.append((id, (t?.str("label", id) ?? id) + st))
        }
        out.append(("builtin", T("Built-in harmonic extension (no model)", "Встроенное гармоническое расширение (без модели)")))
        out.append(("off", T("Off (resample only)", "Выкл. (только ресемплинг)")))
        return out
    }

    var body: some View {
        SectionCard(title: T("Bandwidth and super-resolution", "Полоса и расширение спектра"), icon: "waveform.path.ecg.rectangle",
                    trailing: AnyView(StepButton(rs: rs, step: .superres))) {
            let a = rs.analysis
            HStack(spacing: 8) {
                Readout(label: T("Source", "Исходник"), value: a.isNull ? "—" : String(format: "%.1f kHz", a.num("sr") / 1000))
                Readout(label: T("Real bandwidth", "Реальная полоса"), value: a.isNull ? "—" : String(format: "%.1f kHz", a.num("cutoff_hz") / 1000),
                        color: a.flag("needs_superres") ? Theme.yellow : Theme.green)
                Readout(label: T("Export", "Экспорт"), value: String(format: "%.1f kHz", rs.sr.exportSR / 1000))
                Readout(label: T("Verdict", "Вывод"), value: a.isNull ? "—" : (a.flag("needs_superres") ? T("extend", "расширить") : T("full band", "полная полоса")),
                        color: a.flag("needs_superres") ? Theme.yellow : Theme.green)
            }
            Text(T("Generators and MP3 sources often stop at 15–17 kHz. The model invents the missing top octave only above the detected cutoff; everything below is kept from the original (zero-phase crossover).",
                   "Генераторы и MP3 часто обрезаны на 15–17 кГц. Модель достраивает только верх выше найденного среза; всё ниже остаётся из оригинала (кроссовер с нулевой фазой)."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    PickerRow(label: T("Model", "Модель"), selection: $rs.sr.backend, options: backends, labelWidth: 110)
                    PickerRow(label: T("Export rate", "Частота экспорта"), selection: Binding(get: { rs.sr.exportSR }, set: { rs.sr.exportSR = $0; Task { await rs.analyze() } }),
                              options: [(44100.0, "44.1 kHz"), (48000.0, "48 kHz"), (96000.0, "96 kHz")], labelWidth: 110)
                    PickerRow(label: T("Stereo", "Стерео"), selection: $rs.sr.mode,
                              options: [("mid", T("Mid only (keeps the stereo image)", "Только Mid (сохраняет стереобазу)")),
                                        ("lr", T("Left and right separately", "Левый и правый отдельно"))], labelWidth: 110)
                    ToggleRow(label: T("Run even if the band is full", "Запускать даже при полной полосе"), isOn: $rs.sr.force)
                }
                VStack(alignment: .leading, spacing: 6) {
                    ParamRow(label: T("New highs level", "Уровень верха"), value: $rs.sr.highGainDb, range: -12...6, step: 0.5,
                             defaultValue: 0, bipolar: true, format: { String(format: "%+.1f dB", $0) })
                    ParamRow(label: T("Diffusion steps", "Шаги диффузии"), value: $rs.sr.steps, range: 4...50, step: 1,
                             defaultValue: 12, format: { "\(Int($0))" },
                             help: T("AudioSR only. FlashSR is a one-step model.", "Только AudioSR. FlashSR — одношаговая модель."))
                    ParamRow(label: T("Guidance", "Guidance"), value: $rs.sr.guidance, range: 1...6, step: 0.1, defaultValue: 2,
                             format: { String(format: "%.1f", $0) })
                    ToggleRow(label: T("Two passes (hides window seams)", "Два прохода (скрывает стыки окон)"), isOn: $rs.sr.twoPass)
                }
            }
            if let rep = rs.current?["superres"], !rep.isNull, rep.object?.isEmpty == false {
                if !rep.str("skipped").isEmpty {
                    Label(rep.str("skipped"), systemImage: "info.circle").font(.system(size: 10)).foregroundColor(Theme.text2)
                } else {
                    Label(String(format: T("%@: %.1f → %.1f kHz", "%@: %.1f → %.1f кГц"), rep.str("backend"),
                                 rep.num("cutoff_before_hz") / 1000, rep.num("cutoff_after_hz") / 1000),
                          systemImage: "checkmark.circle").font(.system(size: 10)).foregroundColor(Theme.green)
                }
            }
            HStack(spacing: 10) {
                SpectrogramBox(title: T("Before", "До"), path: rs.specBefore)
                SpectrogramBox(title: T("After", "После"), path: rs.specAfter)
            }
        }
    }
}

private struct ReferenceCard: View {
    @ObservedObject var rs: ReleaseStore

    private var backends: [(String, String)] {
        let m = rs.doctor["tools"]?["matchering"]
        let st = m?.flag("installed") == true ? "" : T(" — not installed", " — не установлен")
        return [("", T("Auto (Matchering if installed)", "Авто (Matchering, если установлен)")),
                ("matchering", "Matchering 2.0.6 (GPLv3, separate process)" + st),
                ("builtin", T("Built-in EQ + loudness match", "Встроенный: EQ и громкость"))]
    }

    var body: some View {
        SectionCard(title: T("Reference mastering", "Мастеринг по референсу"), icon: "dial.medium",
                    trailing: AnyView(HStack(spacing: 6) {
                        Button(T("Choose Reference…", "Выбрать референс…")) { rs.chooseReference() }
                            .buttonStyle(StudioButtonStyle(compact: true)).disabled(rs.running != nil)
                        StepButton(rs: rs, step: .refmaster, title: T("Match", "Подогнать"))
                            .disabled(rs.refOpts.reference.isEmpty)
                    })) {
            HStack(spacing: 8) {
                Image(systemName: "music.note").font(.system(size: 11)).foregroundColor(Theme.text3)
                Text(rs.refOpts.reference.isEmpty ? T("No reference: the step is skipped", "Референс не выбран — шаг пропускается")
                     : URL(fileURLWithPath: rs.refOpts.reference).lastPathComponent)
                    .font(.system(size: 11)).foregroundColor(rs.refOpts.reference.isEmpty ? Theme.text3 : Theme.text)
                    .lineLimit(1).truncationMode(.middle)
                if !rs.refOpts.reference.isEmpty {
                    Button { rs.refOpts.reference = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundColor(Theme.text3)
                }
                Spacer()
            }
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    PickerRow(label: T("Engine", "Движок"), selection: $rs.refOpts.backend, options: backends, labelWidth: 110)
                    PickerRow(label: T("Bit depth", "Разрядность"), selection: $rs.refOpts.bits,
                              options: [(16.0, "16-bit"), (24.0, "24-bit")], labelWidth: 110)
                    ToggleRow(label: T("True-peak limiter at −1 dBTP", "Лимитер true peak −1 dBTP"), isOn: $rs.refOpts.limiter)
                }
                VStack(alignment: .leading, spacing: 6) {
                    ParamRow(label: T("EQ strength", "Сила EQ"), value: $rs.refOpts.strength, range: 0...1, step: 0.05,
                             defaultValue: 1, format: { "\(Int(($0 * 100).rounded())) %" },
                             help: T("Built-in only. 0 % matches loudness only.", "Только встроенный. 0 % — только громкость."))
                    ParamRow(label: T("EQ range", "Диапазон EQ"), value: $rs.refOpts.maxDb, range: 1...12, step: 0.5,
                             defaultValue: 6, format: { String(format: "±%.1f dB", $0) })
                }
            }
            Text(T("Moves the tonal balance and loudness of the master toward a commercial track you like. Runs after the bandwidth step; running it again starts from the pre-match master.",
                   "Подгоняет тональный баланс и громкость мастера под понравившийся трек. Идёт после шага полосы; повторный запуск начинается с мастера до подгонки."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
            if let rep = rs.current?["meta"]?["refmaster"], !rep.isNull, rep.object?.isEmpty == false {
                if !rep.str("skipped").isEmpty {
                    Label(rep.str("skipped"), systemImage: "info.circle").font(.system(size: 10)).foregroundColor(Theme.text2)
                } else {
                    VStack(alignment: .leading, spacing: 4) {
                        if rep.str("backend") == "builtin" {
                            Label(String(format: T("built-in: %.1f → %.1f LUFS (reference %.1f), peak %.1f dBTP",
                                                   "встроенный: %.1f → %.1f LUFS (референс %.1f), пик %.1f dBTP"),
                                         rep.num("lufs_before"), rep.num("lufs_after"), rep.num("reference_lufs"), rep.num("true_peak_db")),
                                  systemImage: "checkmark.circle").font(.system(size: 10)).foregroundColor(Theme.green)
                            HStack(spacing: 4) {
                                ForEach(Array(rep.list("eq_db").enumerated()), id: \.offset) { _, p in
                                    let f = p.array?.first?.double ?? 0, g = p.array?.last?.double ?? 0
                                    VStack(spacing: 1) {
                                        Text(String(format: "%+.1f", g)).font(Theme.monoSmall)
                                            .foregroundColor(abs(g) < 0.5 ? Theme.text3 : (g > 0 ? Theme.accent : Theme.accent2))
                                        Text(f >= 1000 ? String(format: "%gk", f / 1000) : String(format: "%g", f))
                                            .font(.system(size: 9)).foregroundColor(Theme.text3)
                                    }
                                    .frame(minWidth: 34)
                                }
                            }
                        } else {
                            Label(T("Matchering: done", "Matchering: готово"), systemImage: "checkmark.circle")
                                .font(.system(size: 10)).foregroundColor(Theme.green)
                        }
                        if !rep.str("note").isEmpty {
                            Text(rep.str("note")).font(.system(size: 10)).foregroundColor(Theme.yellow)
                        }
                    }
                }
            }
        }
    }
}

private struct SpectrogramBox: View {
    let title: String
    let path: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Caption(text: title)
            ZStack {
                RoundedRectangle(cornerRadius: 6).fill(Color.black)
                if let path, let img = NSImage(contentsOfFile: path) {
                    Image(nsImage: img).resizable().interpolation(.medium)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                } else {
                    Text("—").font(.system(size: 11)).foregroundColor(Theme.text3)
                }
            }
            .frame(height: 130)
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
        }
        .frame(maxWidth: .infinity)
    }
}

private struct CoverCard: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    private var mflux: JSONValue { rs.doctor["tools"]?["mflux"] ?? .null }
    private var modelReady: Bool { mflux["model"]?.flag("complete") ?? false }

    private var backends: [(String, String)] {
        let st: String
        if !mflux.flag("installed") { st = T(" — not installed", " — не установлен") }
        else if mflux["model"] != nil && !modelReady { st = T(" — model not downloaded yet", " — модель ещё не скачана") }
        else { st = "" }
        return [("", T("Auto", "Авто")), ("mflux", "Z-Image Turbo (MLX, mflux)" + st),
                ("builtin", T("Procedural (from the song spectrum)", "Процедурная (из спектра песни)"))]
    }

    /// "5.6 GB left; 3.2 GB of unfinished files from earlier attempts will be removed"
    private var modelNote: String? {
        guard mflux.flag("installed"), let m = mflux["model"], !m.isNull, !m.flag("complete"),
              rs.coverOpts.backend != "builtin" else { return nil }
        let total = m.num("total_bytes", 5.91e9), have = m.num("bytes"), stale = m.num("stale_bytes")
        let left = String(format: "%.1f", max(0, total - have) / 1e9), all = String(format: "%.1f", total / 1e9)
        var en = "Z-Image Turbo model (\(all) GB) is downloaded once, on the first Generate: \(left) GB left, progress is shown here."
        var ru = "Модель Z-Image Turbo (\(all) ГБ) скачивается один раз при первом «Сгенерировать»: осталось \(left) ГБ, прогресс виден здесь."
        if stale > 50e6 {
            let s = String(format: "%.1f", stale / 1e9)
            en += " Unfinished files of earlier attempts (\(s) GB) are removed first."
            ru += " Сначала удаляются недокачанные файлы прошлых попыток (\(s) ГБ)."
        }
        return T(en, ru)
    }

    var body: some View {
        SectionCard(title: T("Cover", "Обложка"), icon: "photo",
                    trailing: AnyView(HStack(spacing: 6) {
                        Button(T("Choose Image…", "Выбрать картинку…")) { rs.chooseCoverFile() }
                            .buttonStyle(StudioButtonStyle(compact: true)).disabled(rs.running != nil)
                        StepButton(rs: rs, step: .cover, title: T("Generate", "Сгенерировать"))
                    })) {
            HStack(alignment: .top, spacing: 14) {
                CoverThumb(path: rs.current?.str("cover") ?? "", size: 170)
                VStack(alignment: .leading, spacing: 6) {
                    PickerRow(label: T("Model", "Модель"), selection: $rs.coverOpts.backend, options: backends, labelWidth: 90)
                    if let note = modelNote {
                        Text(note).font(.system(size: 10)).foregroundColor(Theme.yellow)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Caption(text: T("Prompt (empty = from title, genre and mood)", "Промпт (пусто — из названия, жанра и настроения)"))
                    TextEditor(text: $rs.coverOpts.prompt)
                        .font(.system(size: 11)).scrollContentBackground(.hidden)
                        .padding(4).frame(height: 64)
                        .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
                    TextRow(label: T("Add to prompt", "Добавить"), text: $rs.coverOpts.extra, placeholder: T("neon, rain, 35mm", "неон, дождь, 35mm"), labelWidth: 90)
                    TextRow(label: "Seed", text: $rs.coverOpts.seed, placeholder: T("random", "случайный"), labelWidth: 90)
                    if let info = rs.current?["meta"]?["cover_info"], !info.isNull {
                        Text("\(info.str("backend")) · seed \(info.str("seed", "—"))")
                            .font(Theme.monoSmall).foregroundColor(Theme.text3).lineLimit(1)
                    }
                    Text(T("3000 × 3000 JPEG for stores, 320 px thumbnail for Telegram. No text on the image: stores reject covers with URLs or logos.",
                           "JPEG 3000 × 3000 для магазинов и миниатюра 320 px для Telegram. Без текста на картинке: магазины отклоняют обложки с адресами и логотипами."))
                        .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private struct LyricsCard: View {
    @ObservedObject var rs: ReleaseStore

    /// Which Whisper the step will use, and from where — the doctor finds pip installs in pyenv/venv/conda.
    private var whisperNote: String? {
        guard let f = rs.doctor["features"]?["lyrics"], !f.isNull else { return nil }
        let b = f.str("backend")
        if b.hasPrefix("missing") || b == "off" {
            return T("No Whisper found. Install mlx-whisper (Settings → Tools) or point the app to your openai-whisper.",
                     "Whisper не найден. Установите mlx-whisper (Настройки → Инструменты) или укажите путь к своему openai-whisper.")
        }
        let t = rs.doctor["tools"]?[b] ?? .null
        var s = t.str("label", b)
        if let m = t["model"], !m.isNull {
            s += ", " + m.str("name") + (m.flag("complete") ? T(" (downloaded)", " (скачана)") : T(" (downloaded on first run)", " (скачается при первом запуске)"))
        }
        let path = t.str("path")
        var line = T("Engine: ", "Движок: ") + s + (path.isEmpty ? "" : " — " + path)
        if f.flag("fallback") {
            let w = rs.doctor["tools"]?[f.str("wanted")]?.str("label") ?? f.str("wanted")
            line += T(" (\(w) selected in Settings is not installed)", " (выбранный в настройках \(w) не установлен)")
        }
        return line
    }

    var body: some View {
        SectionCard(title: T("Lyrics and synced LRC", "Текст и синхронный LRC"), icon: "text.quote",
                    trailing: AnyView(HStack(spacing: 6) {
                        Button(T("Save LRC", "Сохранить LRC")) { Task { await rs.saveLRC() } }
                            .buttonStyle(StudioButtonStyle(compact: true))
                            .disabled(rs.running != nil || rs.lrcText.isEmpty)
                        StepButton(rs: rs, step: .lyrics, title: T("Transcribe and Align", "Распознать и выровнять"))
                    })) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Caption(text: T("Lyrics ([Verse], [Chorus] tags become sections)", "Текст (теги [Verse], [Chorus] — секции)"))
                    TextEditor(text: rs.field("lyrics_text"))
                        .font(.system(size: 11)).scrollContentBackground(.hidden)
                        .padding(4).frame(height: 170)
                        .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
                }
                VStack(alignment: .leading, spacing: 4) {
                    Caption(text: "LRC")
                    TextEditor(text: $rs.lrcText)
                        .font(Theme.monoSmall).scrollContentBackground(.hidden)
                        .padding(4).frame(height: 170)
                        .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
                }
            }
            HStack(spacing: 10) {
                TextRow(label: T("Language", "Язык"), text: $rs.lrcLanguage, placeholder: T("auto", "авто"), labelWidth: 70)
                    .frame(width: 200)
                if let li = rs.current?["meta"]?["lyrics_info"], !li.isNull {
                    Text(T("\(li.str("backend")): \(li.str("matched")) of \(li.str("total")) lines matched, language \(li.str("language"))",
                           "\(li.str("backend")): совпало \(li.str("matched")) из \(li.str("total")) строк, язык \(li.str("language"))"))
                        .font(.system(size: 10)).foregroundColor(Theme.text2)
                }
                Spacer()
            }
            if let note = whisperNote {
                Text(note).font(.system(size: 10)).foregroundColor(rs.doctor["features"]?["lyrics"]?.str("backend").hasPrefix("missing") == true ? Theme.yellow : Theme.text2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(T("Whisper (mlx-whisper on Apple Silicon) gives word timestamps; the app aligns your lyrics to them, so the LRC keeps your spelling. Lines Whisper missed are interpolated — check them by ear and edit times here.",
                   "Whisper (mlx-whisper на Apple Silicon) даёт тайминги слов; приложение выравнивает по ним ваш текст, поэтому в LRC остаётся ваше написание. Строки, которые Whisper не услышал, интерполируются — проверьте на слух и поправьте время здесь."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The user's own humanization pass (humanize.py since 1.0.0): 12 subtle production steps,
/// run once before the AI check. It is a sound-design step: disclosure of AI origin does not change.
private struct HumanizeCard: View {
    @ObservedObject var rs: ReleaseStore

    private static let presets: [(String, String)] = [
        ("ultra-low", "Ultra-low"), ("low", "Low"), ("medium", "Medium"), ("high", "High")]

    var body: some View {
        SectionCard(title: T("Humanize (before the AI check)", "Гуманизация (до проверки на ИИ)"), icon: "person.wave.2",
                    trailing: AnyView(StepButton(rs: rs, step: .humanize, title: T("Process", "Обработать")))) {
            ToggleRow(label: T("Use in this studio session", "Применять в этой сессии"), isOn: $rs.humOpts.enabled,
                      help: T("On: Run All also runs this step. Off: run it only with the Process button.",
                              "Вкл: «Сделать всё» тоже выполняет этот шаг. Выкл: шаг запускается только кнопкой «Обработать»."))
            HStack(alignment: .top, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    PickerRow(label: T("Preset", "Пресет"), selection: $rs.humOpts.preset, options: Self.presets, labelWidth: 70)
                    TextRow(label: "Seed", text: $rs.humOpts.seed, placeholder: "42", labelWidth: 70)
                }
                ToggleRow(label: T("Without organic noise", "Без живого шума"), isOn: $rs.humOpts.skipNoise,
                          help: T("Skip the pink noise, crackle and wow&flutter step (vinyl/room tone).",
                                  "Пропустить шаг с розовым шумом, треском и wow&flutter (шум винила/комнаты)."))
            }
            Text(T("Your humanize module from the audio pipeline: pitch micro-warp, timing jitter, tape saturation, air exciter, stereo drift, EQ randomize, phase dither, subsample scatter and micro room reverb. ultra-low keeps the spectrum and timing intact and only changes the signature; medium and high are clearly audible. The step runs once before the AI check; the check itself never changes audio, and the AI disclosure in the publish step stays as it is.",
                   "Твой модуль humanize из аудиоконвейера: питч-микроварп, джиттер тайминга, лентовая сатурация, воздух, стерео-дрейф, EQ-рандомизация, фазовый дизер, субсэмплинг-разброс и микрореверб комнаты. ultra-low сохраняет спектр и тайминг, меняя только сигнатуру; medium и high заметны на слух. Шаг выполняется один раз до проверки на ИИ; сама проверка звук не меняет, и раскрытие ИИ при публикации остаётся как есть."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
            if let h = rs.current?["meta"]?["humanize"], !h.isNull {
                let restored = h.flag("restored")
                Text(restored
                     ? T("Previous master restored (the pre-humanize file).", "Восстановлен прежний мастер (файл до гуманизации).")
                     : T("Processed: \(h.str("preset")) preset, master_humanized.wav. Package and AI check use it.",
                         "Обработано: пресет \(h.str("preset")), master_humanized.wav. Пакет и проверка на ИИ используют его."))
                    .font(.system(size: 10)).foregroundColor(restored ? Theme.text3 : Theme.green)
                if !restored {
                    Button(T("Restore the pre-humanize master", "Вернуть мастер до гуманизации")) {
                        Task { await rs.run(.humanize, extra: ["restore": .b(true)]) }
                    }
                    .buttonStyle(StudioButtonStyle(compact: true)).disabled(rs.running != nil)
                }
            }
        }
    }
}

private struct AICheckCard: View {
    @ObservedObject var rs: ReleaseStore

    private func avail(_ id: String) -> Bool { rs.doctor["detectors"]?[id]?.bool ?? (id == "fakeprint") }

    var body: some View {
        SectionCard(title: T("AI check (independent detectors)", "Проверка на ИИ (независимые детекторы)"), icon: "checkmark.shield",
                    trailing: AnyView(StepButton(rs: rs, step: .detect, title: T("Check", "Проверить")))) {
            FlowLayout(spacing: 6) {
                DetectorChip(title: "Fakeprint", sub: T("built-in, offline", "встроенный, офлайн"), on: $rs.detectOpts.fakeprint, ok: avail("fakeprint"))
                DetectorChip(title: "AIGM (SpecTTTra, MLX)", sub: T("local", "локально"), on: $rs.detectOpts.aigm, ok: avail("aigm"))
                DetectorChip(title: "Sightengine", sub: T("cloud, Pro plan", "облако, тариф Pro"), on: $rs.detectOpts.sightengine, ok: avail("sightengine"))
                DetectorChip(title: "ACRCloud", sub: T("cloud", "облако"), on: $rs.detectOpts.acrcloud, ok: avail("acrcloud"))
            }
            ParamRow(label: T("Flag threshold", "Порог"), value: $rs.detectOpts.threshold, range: 0.1...0.95, step: 0.05,
                     defaultValue: 0.5, format: { String(format: "%.2f", $0) })
            if let rep = rs.current?["ai_report"], rep.object?.isEmpty == false {
                HStack(spacing: 8) {
                    VerdictDot(verdict: rep.str("verdict"))
                    Text(verdictText(rep.str("verdict"))).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.text)
                    Text(String(format: T("max score %.2f", "макс. оценка %.2f"), rep.num("max_score")))
                        .font(Theme.monoSmall).foregroundColor(Theme.text3)
                    Spacer()
                }
                ForEach(Array((rep["results"]?.object ?? [:]).keys.sorted()), id: \.self) { k in
                    let r = rep["results"]?[k] ?? .null
                    HStack(spacing: 8) {
                        Text(r.str("label", k)).font(.system(size: 11)).foregroundColor(Theme.text2)
                            .frame(width: 260, alignment: .leading).lineLimit(1)
                        if r.flag("ok") {
                            ScoreBar(score: r.num("score"), threshold: rep.num("threshold", 0.5))
                            Text(String(format: "%.2f", r.num("score"))).font(Theme.monoSmall)
                                .foregroundColor(r.flag("flagged") ? Theme.red : Theme.green).frame(width: 40)
                            if !r.str("likely_source").isEmpty {
                                Text(r.str("likely_source")).font(.system(size: 10)).foregroundColor(Theme.text3)
                            }
                            if let ms = r["models"]?.object, !ms.isEmpty {     // AIGM: score of each model in the ensemble
                                Text(ms.keys.sorted().map { "\($0) \(String(format: "%.2f", ms[$0]?.double ?? 0))" }.joined(separator: " · "))
                                    .font(.system(size: 10)).foregroundColor(Theme.text3).lineLimit(1).textSelection(.enabled)
                            }
                        } else {
                            Text(r.str("error")).font(.system(size: 10)).foregroundColor(Theme.text3).lineLimit(2)
                                .textSelection(.enabled)
                        }
                        Spacer(minLength: 0)
                    }
                }
                Text(rep.str("note")).font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
            }
            Text(T("Detectors are for honest labeling: they show how stores and listeners will see the track. Disclosure flags come from the project, not from the score, and are always recommended for generated music.",
                   "Детекторы нужны для честной маркировки: они показывают, как трек увидят магазины и слушатели. Флаги раскрытия берутся из проекта, а не из оценки, и для сгенерированной музыки рекомендуются всегда."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func verdictText(_ v: String) -> String {
        switch v {
        case "ai": return T("Detected as AI", "Определено как ИИ")
        case "mixed": return T("Detectors disagree", "Детекторы расходятся")
        case "not_detected": return T("Not detected", "Не определено")
        default: return T("No result", "Нет результата")
        }
    }
}

private struct DetectorChip: View {
    let title: String
    let sub: String
    @Binding var on: Bool
    let ok: Bool

    var body: some View {
        Button { on.toggle() } label: {
            HStack(spacing: 6) {
                Image(systemName: on ? "checkmark.square.fill" : "square").font(.system(size: 11))
                    .foregroundColor(on ? Theme.accent : Theme.text3)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.system(size: 11, weight: .medium)).foregroundColor(Theme.text)
                    Text(ok ? sub : sub + T(" · not set up", " · не настроен")).font(.system(size: 9))
                        .foregroundColor(ok ? Theme.text3 : Theme.yellow)
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg3))
        }
        .buttonStyle(.plain)
    }
}

private struct ScoreBar: View {
    let score: Double
    let threshold: Double

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.bg0)
                Capsule().fill(score >= threshold ? Theme.red : Theme.green)
                    .frame(width: max(3, g.size.width * CGFloat(min(max(score, 0), 1))))
                Rectangle().fill(Theme.text3).frame(width: 1).offset(x: g.size.width * CGFloat(threshold))
            }
        }
        .frame(width: 160, height: 6)
    }
}

private struct VerdictDot: View {
    let verdict: String
    var body: some View {
        Circle().fill(verdict == "ai" ? Theme.red : (verdict == "mixed" ? Theme.yellow : (verdict == "not_detected" ? Theme.green : Theme.text3)))
            .frame(width: 8, height: 8)
    }
}

private struct PackageCard: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        SectionCard(title: T("Distributor package", "Пакет для дистрибьютора"), icon: "shippingbox",
                    trailing: AnyView(StepButton(rs: rs, step: .package, title: T("Build", "Собрать")))) {
            Text(T("Spotify, Apple Music, Yandex Music, VK Music and Deezer accept music only through distributors (DistroKid, TuneCore, CD Baby, Onerpm, Zvonko…). The package has everything their upload forms ask for.",
                   "Spotify, Apple Music, Яндекс Музыка, VK Музыка и Deezer принимают музыку только через дистрибьюторов (DistroKid, TuneCore, CD Baby, Onerpm, Zvonko…). В пакете всё, что спрашивают их формы загрузки."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top, spacing: 18) {
                PackageFormatColumn(rs: rs).frame(width: 300)
                Rectangle().fill(Theme.stroke).frame(width: 1)
                PackageTagsColumn(rs: rs).frame(maxWidth: .infinity)
            }
            .padding(.vertical, 4)
            if let pk = rs.current?["meta"]?["package"], !pk.isNull {
                Rectangle().fill(Theme.stroke).frame(height: 1)
                ForEach(pk.list("checks"), id: \.self) { c in
                    HStack(spacing: 6) {
                        Image(systemName: c.flag("ok") ? "checkmark.circle.fill" : (c.str("level") == "error" ? "xmark.octagon.fill" : "exclamationmark.triangle.fill"))
                            .font(.system(size: 10))
                            .foregroundColor(c.flag("ok") ? Theme.green : (c.str("level") == "error" ? Theme.red : Theme.yellow))
                        Text(c.str("message")).font(.system(size: 10)).foregroundColor(Theme.text2)
                    }
                }
                HStack {
                    Text(pk.str("folder")).font(Theme.monoSmall).foregroundColor(Theme.text3).lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button(T("Show in Finder", "Показать в Finder")) { store.reveal(pk.str("folder")) }
                        .buttonStyle(StudioButtonStyle(compact: true))
                }
            }
        }
    }
}

/// Format of the audio file in the package — the same choices as Export (Master → Format).
private struct PackageFormatColumn: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        let o = rs.pkg
        let needsFFmpeg = o.format == "mp3" || o.format == "alac"
        let hasFFmpeg = store.info["deps"]?.flag("ffmpeg") ?? false
        let rates: [(Double, String)] = o.format == "mp3"
            ? [(44100.0, "44.1 kHz"), (48000.0, "48 kHz")]
            : [(44100.0, "44.1 kHz"), (48000.0, "48 kHz"), (88200.0, "88.2 kHz"), (96000.0, "96 kHz")]
        let depths: [(Double, String)] = o.format == "wav"
            ? [(16.0, "16-bit"), (24.0, "24-bit"), (32.0, "32-bit float")]
            : [(16.0, "16-bit"), (24.0, "24-bit")]
        let hasCover = !(rs.current?.str("cover").isEmpty ?? true)
        let hasLyrics = !(rs.current?.str("lyrics_text").isEmpty ?? true) || !(rs.current?.str("lrc").isEmpty ?? true)
        VStack(alignment: .leading, spacing: 7) {
            Caption(text: T("Audio file", "Аудиофайл"))
            Segmented(selection: $rs.pkg.format, options: [("wav", "WAV"), ("flac", "FLAC"), ("alac", "ALAC"), ("mp3", "MP3")])
            PickerRow(label: T("Sample rate", "Частота"), selection: $rs.pkg.sampleRate, options: rates, labelWidth: 96)
            if o.format == "mp3" {
                PickerRow(label: T("Bitrate", "Битрейт"), selection: $rs.pkg.mp3Bitrate,
                          options: [(128.0, "128 kbps"), (192.0, "192 kbps"), (256.0, "256 kbps"), (320.0, "320 kbps")],
                          labelWidth: 96)
            } else {
                PickerRow(label: T("Bit depth", "Разрядность"), selection: $rs.pkg.bitDepth, options: depths, labelWidth: 96)
                PickerRow(label: T("Dither", "Дизеринг"), selection: $rs.pkg.dither,
                          options: [("tpdf", "TPDF"), ("off", T("Off", "Выкл"))],
                          help: o.bitDepth >= 32 ? T("Not used for 32-bit float", "Для 32-bit float не нужен")
                                                 : T("Applied when reducing to 16/24-bit", "Применяется при понижении до 16/24 бит"),
                          labelWidth: 96)
            }
            ToggleRow(label: T("Cover in the file", "Обложка в файле"), isOn: $rs.pkg.embedCover,
                      help: T("Embeds the 3000 px cover (ID3 APIC, FLAC PICTURE, M4A covr)", "Встраивает обложку 3000 px (ID3 APIC, FLAC PICTURE, M4A covr)"))
            ToggleRow(label: T("Lyrics in the file", "Текст в файле"), isOn: $rs.pkg.embedLyrics,
                      help: T("Plain lyrics without [Verse] tags (ID3 USLT, FLAC LYRICS, M4A ©lyr)", "Текст без меток [Куплет] (ID3 USLT, FLAC LYRICS, M4A ©lyr)"))
            if o.embedCover && !hasCover {
                note(T("No cover yet: run the Cover step first.", "Обложки пока нет: сначала выполните шаг «Обложка»."), Theme.text3)
            }
            if o.embedLyrics && !hasLyrics {
                note(T("This release has no lyrics.", "В этом релизе нет текста."), Theme.text3)
            }
            if o.format == "mp3" {
                note(T("MP3 is lossy. Distributors ask for WAV or FLAC; use MP3 for previews and promo.",
                       "MP3 сжат с потерями. Дистрибьюторы просят WAV или FLAC; MP3 — для превью и промо."), Theme.yellow)
            } else if o.bitDepth >= 32 {
                note(T("Many distributors accept only 16- or 24-bit WAV.", "Многие дистрибьюторы принимают только WAV 16 или 24 бит."), Theme.yellow)
            }
            if needsFFmpeg && !hasFFmpeg {
                note(T("This format needs ffmpeg (brew install ffmpeg)", "Для этого формата нужен ffmpeg (brew install ffmpeg)"), Theme.yellow)
            }
        }
    }

    private func note(_ text: String, _ color: Color) -> some View {
        Text(text).font(.system(size: 10)).foregroundColor(color).fixedSize(horizontal: false, vertical: true)
    }
}

/// Release metadata written into the file tags and metadata.json. Saved with the release.
private struct PackageTagsColumn: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        let title = rs.current?.str("title") ?? ""
        let artist = rs.current?.str("artist") ?? ""
        let year = Calendar.current.component(.year, from: Date())
        VStack(alignment: .leading, spacing: 7) {
            Caption(text: T("Tags in the file", "Теги в файле"))
            HStack(alignment: .top, spacing: 12) {
                VStack(spacing: 6) {
                    TextRow(label: T("Album", "Альбом"), text: rs.metaStr("album"),
                            placeholder: title.isEmpty ? T("= title", "= название") : title, labelWidth: 86)
                    TextRow(label: T("Release date", "Дата релиза"), text: rs.metaStr("release_date"),
                            placeholder: T("e.g. ", "напр. ") + "\(year)-12-01", labelWidth: 86)
                    TextRow(label: T("Composer", "Композитор"), text: rs.metaStr("composer"), placeholder: T("optional", "необязательно"), labelWidth: 86)
                    TextRow(label: T("Lyricist", "Автор текста"), text: rs.metaStr("lyricist"), placeholder: T("optional", "необязательно"), labelWidth: 86)
                    TextRow(label: T("Producer", "Продюсер"), text: rs.metaStr("producer"), placeholder: T("optional", "необязательно"), labelWidth: 86)
                }
                VStack(spacing: 6) {
                    TextRow(label: T("Label", "Лейбл"), text: rs.metaStr("label"),
                            placeholder: T("optional", "необязательно"), labelWidth: 70)
                    TextRow(label: "Copyright", text: rs.metaStr("copyright"),
                            placeholder: T("e.g. ", "напр. ") + (artist.isEmpty ? "\(year)" : "\(year) \(artist)"), labelWidth: 70)
                    TextRow(label: "ISRC", text: rs.metaStr("isrc"), placeholder: "CC-XXX-YY-NNNNN", labelWidth: 70)
                    TextRow(label: "UPC", text: rs.metaStr("upc"),
                            placeholder: T("from the distributor", "от дистрибьютора"), labelWidth: 70)
                    HStack {
                        Toggle(T("Explicit lyrics", "Ненормативная лексика"), isOn: rs.metaBool("explicit"))
                            .toggleStyle(.checkbox).font(.system(size: 11))
                        Spacer(minLength: 0)
                    }
                    .frame(height: 24)
                }
            }
            Text(T("Title, artist, genre and language come from the header; the cover and lyrics from their steps; the AI note from the disclosure. Empty fields are left out. ISRC and UPC usually come from the distributor after upload; add them here and rebuild if you have them.",
                   "Название, исполнитель, жанр и язык берутся из шапки релиза, обложка и текст — из своих шагов, пометка ИИ — из раскрытия. Пустые поля не пишутся. ISRC и UPC обычно выдаёт дистрибьютор при загрузке: если они есть, впишите и пересоберите."))
                .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct PublishCard: View {
    @ObservedObject var rs: ReleaseStore

    private var tgReady: Bool { !(Keychain.get("telegram_token") ?? "").isEmpty }
    private var ytReady: Bool { !(Keychain.get("youtube_refresh") ?? "").isEmpty }

    var body: some View {
        SectionCard(title: T("Publish", "Публикация"), icon: "paperplane",
                    trailing: AnyView(Button(T("Publish…", "Опубликовать…")) { rs.showConfirm = true }
                        .buttonStyle(StudioButtonStyle(prominent: true, compact: true))
                        .disabled(rs.running != nil || rs.services.isEmpty))) {
            HStack(alignment: .top, spacing: 14) {
                VStack(alignment: .leading, spacing: 8) {
                    ServiceToggle(title: T("Distributor package", "Пакет для дистрибьютора"), icon: "shippingbox", on: $rs.pub.package, ready: true,
                                  hint: T("local folder", "локальная папка"))
                    ServiceToggle(title: "Telegram", icon: "paperplane.circle", on: $rs.pub.telegram, ready: tgReady,
                                  hint: tgReady ? T("bot connected", "бот подключён") : T("Settings → Publishing", "Настройки → Публикация"))
                    ServiceToggle(title: "YouTube", icon: "play.rectangle", on: $rs.pub.youtube, ready: ytReady,
                                  hint: ytReady ? T("channel connected", "канал подключён") : T("Settings → Publishing", "Настройки → Публикация"))
                    HStack(spacing: 6) {
                        Button(T("Test Telegram", "Проверить Telegram")) { Task { await rs.check("telegram") } }
                            .buttonStyle(StudioButtonStyle(compact: true)).disabled(!tgReady)
                        Button(T("Test YouTube", "Проверить YouTube")) { Task { await rs.check("youtube") } }
                            .buttonStyle(StudioButtonStyle(compact: true)).disabled(!ytReady)
                    }
                }
                .frame(width: 250, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    if rs.pub.telegram {
                        Caption(text: "Telegram")
                        TextRow(label: T("Caption", "Подпись"), text: $rs.pub.caption, placeholder: T("optional", "необязательно"), labelWidth: 90)
                        TextRow(label: T("Chat", "Чат"), text: $rs.pub.chatOverride, placeholder: Keychain.get("telegram_chat") ?? "@channel", labelWidth: 90)
                        HStack(spacing: 14) {
                            Toggle(T("Silent", "Без звука"), isOn: $rs.pub.silent).toggleStyle(.checkbox)
                            Toggle(T("“Made with AI” note", "Пометка «Создано с помощью ИИ»"), isOn: $rs.pub.aiNote).toggleStyle(.checkbox)
                        }
                        .font(.system(size: 11))
                    }
                    if rs.pub.youtube {
                        Caption(text: "YouTube")
                        TextRow(label: T("Title", "Название"), text: $rs.pub.ytTitle, labelWidth: 90)
                        TextRow(label: T("Description", "Описание"), text: $rs.pub.ytDescription,
                                placeholder: T("empty = lyrics + AI note", "пусто — текст песни и пометка ИИ"), labelWidth: 90)
                        HStack(spacing: 8) {
                            Text(T("Visibility", "Доступ")).font(Theme.label).foregroundColor(Theme.text2).frame(width: 90, alignment: .leading)
                            Segmented(selection: $rs.pub.privacy, options: [("private", T("Private", "Приватно")),
                                                                          ("unlisted", T("Unlisted", "По ссылке")),
                                                                          ("public", T("Public", "Публично"))], height: 22)
                                .frame(width: 270)
                                .disabled(rs.pub.schedule)
                        }
                        HStack(spacing: 8) {
                            Toggle(T("Schedule", "Запланировать"), isOn: $rs.pub.schedule).toggleStyle(.checkbox).font(.system(size: 11))
                                .frame(width: 90, alignment: .leading)
                            DatePicker("", selection: $rs.pub.publishAt, in: Date()...).labelsHidden().disabled(!rs.pub.schedule)
                        }
                        PickerRow(label: T("Video", "Видео"), selection: $rs.pub.videoStyle,
                                  options: [("waveform", T("Cover + waveform", "Обложка + волна")), ("spectrum", T("Cover + spectrum", "Обложка + спектр")),
                                            ("still", T("Still cover", "Статичная обложка"))], labelWidth: 90)
                        Text(T("Uploads start as private unless you confirm public visibility. Unverified API projects are locked to private by Google.",
                               "Загрузка начинается приватной, пока вы не подтвердите публичный доступ. Непроверенные проекты API Google принудительно делает приватными."))
                            .font(.system(size: 10)).foregroundColor(Theme.text3).fixedSize(horizontal: false, vertical: true)
                    }
                    if !rs.pub.telegram && !rs.pub.youtube {
                        Text(T("Pick a service on the left. Nothing is sent until you confirm the summary.",
                               "Выберите сервис слева. Ничего не отправляется, пока вы не подтвердите сводку."))
                            .font(.system(size: 10)).foregroundColor(Theme.text3)
                    }
                }
            }
        }
    }
}

private struct ServiceToggle: View {
    let title: String
    let icon: String
    @Binding var on: Bool
    let ready: Bool
    let hint: String

    var body: some View {
        Button { if ready { on.toggle() } } label: {
            HStack(spacing: 8) {
                Image(systemName: on ? "checkmark.square.fill" : "square").foregroundColor(on ? Theme.accent : Theme.text3)
                Image(systemName: icon).foregroundColor(Theme.text2)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.system(size: 11, weight: .medium)).foregroundColor(ready ? Theme.text : Theme.text3)
                    Text(hint).font(.system(size: 9)).foregroundColor(ready ? Theme.text3 : Theme.yellow)
                }
                Spacer(minLength: 0)
            }
            .padding(6)
            .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg3))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - confirmation

struct PublishConfirmSheet: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "paperplane.fill").foregroundColor(Theme.accent)
                Text(T("Confirm publishing", "Подтвердите публикацию")).font(Theme.title).foregroundColor(Theme.text)
            }
            Text(T("The app will do exactly this:", "Приложение сделает ровно это:")).font(.system(size: 11)).foregroundColor(Theme.text2)
            ForEach(Array(rs.plan.enumerated()), id: \.offset) { i, line in
                HStack(alignment: .top, spacing: 8) {
                    Text("\(i + 1).").font(Theme.mono).foregroundColor(Theme.accent)
                    Text(line).font(.system(size: 11)).foregroundColor(Theme.text).fixedSize(horizontal: false, vertical: true)
                }
            }
            if let v = rs.current?["ai_report"]?.str("verdict"), !v.isEmpty {
                Text(T("AI check: \(v). Disclosure: \(rs.aiGenerated.wrappedValue ? "on" : "off").",
                       "Проверка ИИ: \(v). Раскрытие: \(rs.aiGenerated.wrappedValue ? "включено" : "выключено")."))
                    .font(.system(size: 10)).foregroundColor(Theme.text3)
            } else {
                Text(T("The AI check has not been run for this release.", "Проверка на ИИ для этого релиза не запускалась."))
                    .font(.system(size: 10)).foregroundColor(Theme.yellow)
            }
            if rs.needsPublicConfirm {
                Toggle(T("I understand the video becomes public immediately", "Понимаю, что видео сразу станет публичным"), isOn: $rs.confirmPublic)
                    .toggleStyle(.checkbox).font(.system(size: 11)).foregroundColor(Theme.yellow)
            }
            HStack {
                Spacer()
                Button(T("Cancel", "Отмена")) { rs.showConfirm = false; rs.confirmPublic = false }
                    .buttonStyle(StudioButtonStyle())
                    .keyboardShortcut(.cancelAction)
                Button(T("Publish", "Опубликовать")) { Task { await rs.publish() } }
                    .buttonStyle(StudioButtonStyle(prominent: true))
                    .disabled(rs.needsPublicConfirm && !rs.confirmPublic)
            }
        }
        .padding(18)
        .frame(width: 560)
        .background(Theme.bg1)
        .preferredColorScheme(.dark)
    }
}

// MARK: - queue (inspector)

struct PublishQueuePanel: View {
    @ObservedObject var rs: ReleaseStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Caption(text: T("Jobs", "Задачи"))
                Spacer()
                Button(T("Retry Due", "Повторить")) { Task { await rs.retry(nil) } }
                    .buttonStyle(StudioButtonStyle(compact: true))
                    .disabled(rs.running != nil || !rs.jobs.contains { ["pending", "waiting"].contains($0.str("status")) })
                IconButton(icon: "arrow.clockwise", help: T("Refresh", "Обновить")) { Task { await rs.refreshQueue() } }
            }
            if rs.jobs.isEmpty {
                Text(T("No jobs yet.", "Задач пока нет.")).font(.system(size: 10)).foregroundColor(Theme.text3)
            }
            ForEach(rs.jobs.reversed(), id: \.self) { j in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Circle().fill(color(j.str("status"))).frame(width: 7, height: 7)
                        Text(j.str("service")).font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.text)
                        Text(statusText(j.str("status"))).font(.system(size: 10)).foregroundColor(Theme.text2)
                        Spacer()
                        if ["failed", "waiting", "pending"].contains(j.str("status")) {
                            IconButton(icon: "arrow.counterclockwise", help: T("Retry now", "Повторить сейчас"), size: 11) {
                                Task { await rs.retry(j.str("id")) }
                            }
                        }
                        IconButton(icon: "trash", help: T("Remove", "Удалить"), size: 11) { Task { await rs.remove(j.str("id")) } }
                    }
                    Text(j.str("release")).font(Theme.monoSmall).foregroundColor(Theme.text3).lineLimit(1)
                    if !j.str("error").isEmpty {
                        Text(j.str("error")).font(.system(size: 10)).foregroundColor(Theme.red).lineLimit(3).textSelection(.enabled)
                    }
                    if j.str("status") == "waiting", j.num("next_try") > 0 {
                        Text(T("next try ", "следующая попытка ") + Date(timeIntervalSince1970: j.num("next_try")).formatted(date: .omitted, time: .shortened)
                             + " · " + T("attempt", "попытка") + " \(j.str("attempts"))")
                            .font(.system(size: 9)).foregroundColor(Theme.text3)
                    }
                    let url = j["result"]?.str("url") ?? ""
                    if !url.isEmpty, let u = URL(string: url) {
                        Link(url, destination: u).font(.system(size: 10))
                    }
                }
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg2))
            }
            Caption(text: T("Published", "Опубликовано"))
            if rs.log.isEmpty {
                Text("—").font(.system(size: 10)).foregroundColor(Theme.text3)
            }
            ForEach(Array(rs.log.enumerated()), id: \.offset) { _, e in
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(e.str("service")) · \(e.str("time").replacingOccurrences(of: "T", with: " "))")
                        .font(.system(size: 10, weight: .medium)).foregroundColor(Theme.text2)
                    if let u = URL(string: e.str("url")), !e.str("url").isEmpty {
                        Link(e.str("url"), destination: u).font(.system(size: 10))
                    } else if !e.str("folder").isEmpty {
                        Text(e.str("folder")).font(Theme.monoSmall).foregroundColor(Theme.text3).lineLimit(1).truncationMode(.middle)
                    }
                }
            }
        }
        .task { await rs.refreshQueue() }
    }

    private func color(_ s: String) -> Color {
        switch s {
        case "done": return Theme.green
        case "failed": return Theme.red
        case "running": return Theme.accent
        case "waiting": return Theme.yellow
        default: return Theme.text3
        }
    }

    private func statusText(_ s: String) -> String {
        switch s {
        case "done": return T("done", "готово")
        case "failed": return T("failed", "ошибка")
        case "running": return T("running", "выполняется")
        case "waiting": return T("waiting to retry", "ждёт повтора")
        default: return T("pending", "в очереди")
        }
    }
}

// MARK: - shared

struct CoverThumb: View {
    let path: String
    let size: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size > 60 ? 8 : 5).fill(Theme.bg3)
            if !path.isEmpty, let img = NSImage(contentsOfFile: path) {
                Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
            } else {
                Image(systemName: "music.note").font(.system(size: size * 0.3)).foregroundColor(Theme.text3)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size > 60 ? 8 : 5))
        .overlay(RoundedRectangle(cornerRadius: size > 60 ? 8 : 5).stroke(Theme.stroke, lineWidth: 1))
    }
}
