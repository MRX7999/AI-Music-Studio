import SwiftUI

extension StudioStore {
    /// Listener position in meters: the session override or the scene default from describe.
    var listenerPosition: (Double, Double) {
        if let x = session?["listener_x"]?.double, let y = session?["listener_y"]?.double { return (x, y) }
        let l = describe["listener"]?.doubles ?? []
        if l.count == 2 { return (l[0], l[1]) }
        let r = roomSize
        return (r.0 / 2, r.1 * 0.7)
    }
}

private func times(_ v: Double) -> String { String(format: "×%.2f", v) }

// MARK: - Room inspector

struct RoomInspector: View {
    var body: some View {
        VStack(spacing: 10) {
            RoomSection()
            AcousticsSection()
            RoomMicsSection()
            ReverbDelaySection()
            ListenerSection()
        }
    }
}

private struct RoomSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let size = store.roomSize
        let sceneID = store.session?.str("scene") ?? ""
        let custom = store.session.map { !($0["room_width"]?.isNull ?? true) || !($0["room_depth"]?.isNull ?? true)
            || !($0["room_height"]?.isNull ?? true) } ?? false
        SectionCard(title: T("Room", "Помещение"), icon: "cube") {
            PickerRow(label: T("Scene preset", "Пресет сцены"),
                      selection: Binding(get: { sceneID }, set: { store.setScene($0) }),
                      options: store.scenes.map { ($0.str("id"), $0.str("name")) })
            Text(store.scene(sceneID)?.str("description") ?? "")
                .font(.system(size: 10))
                .foregroundColor(Theme.text3)
                .fixedSize(horizontal: false, vertical: true)
            ParamRow(label: T("Width", "Ширина"), value: Binding(get: { store.roomSize.0 }, set: { store.setRoomSize(width: $0) }),
                     range: 1.5...160, log: true, step: 0.1, format: Fmt.meters)
            ParamRow(label: T("Depth", "Глубина"), value: Binding(get: { store.roomSize.1 }, set: { store.setRoomSize(depth: $0) }),
                     range: 1.5...160, log: true, step: 0.1, format: Fmt.meters)
            ParamRow(label: T("Height", "Высота"), value: Binding(get: { store.roomSize.2 }, set: { store.setRoomSize(height: $0) }),
                     range: 1.8...45, log: true, step: 0.1, format: Fmt.meters)
            InfoLine(label: T("Volume", "Объём"), value: String(format: "%.0f m³", size.0 * size.1 * size.2))
            HStack {
                Text(custom ? T("Custom size: musicians were scaled with the room", "Свой размер: расстановка масштабирована вместе с комнатой")
                            : T("Preset size", "Размер пресета"))
                    .font(.system(size: 10))
                    .foregroundColor(custom ? Theme.accent : Theme.text3)
                Spacer()
                Button(T("Reset size", "Сбросить размер")) { store.resetRoomSize() }
                    .buttonStyle(StudioButtonStyle(compact: true))
                    .disabled(!custom)
            }
        }
    }
}

private struct AcousticsSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let room = store.describe["room"]
        SectionCard(title: T("Acoustics", "Акустика"), icon: "waveform.path.ecg") {
            ParamRow(label: T("Reverb time", "Время реверберации"), value: store.sesNum("rt60_scale"), range: 0.25...3, log: true,
                     defaultValue: 1, format: times,
                     help: T("Multiplies the RT60 of the preset", "Множитель RT60 пресета"))
            InfoLine(label: "RT60", value: Fmt.sec(room?.num("rt60") ?? 0), color: Theme.accent2)
            ParamRow(label: T("High damping", "Затухание ВЧ"), value: store.sesNum("hf_damping"), range: 0.3...1.5, defaultValue: 1,
                     format: times, help: T("Less = darker reverb tail", "Меньше — темнее хвост"))
            ParamRow(label: T("Low-end decay", "Затухание НЧ"), value: store.sesNum("lf_ratio_scale"), range: 0.5...2, defaultValue: 1,
                     format: times, help: T("More = boomier room", "Больше — гулче низ"))
            ParamRow(label: T("Early reflections", "Ранние отражения"), value: store.sesNum("early_db_offset"), range: -12...12,
                     defaultValue: 0, bipolar: true, format: { Fmt.db($0) })
            PickerRow(label: T("Ambience", "Атмосфера"), selection: store.sesStr("ambience_kind"),
                      options: [("", T("As in preset", "Как в пресете"))]
                        + store.ambienceKinds.map { ($0.str("id"), $0.str("name")) },
                      help: T("Background of the room: room tone, crowd, outdoor", "Фон помещения: тишина зала, публика, улица"))
            ParamRow(label: T("Ambience level", "Уровень атмосферы"), value: store.sesNum("ambience_db_offset"), range: -30...12,
                     defaultValue: 0, bipolar: true, format: { Fmt.db($0) })
        }
    }
}

private struct RoomMicsSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let tech = store.session?["recording"]?.str("room_technique") ?? "ab"
        let maxH = max(min(store.roomSize.2 - 0.2, 12), 0.8)
        SectionCard(title: T("Room microphones", "Комнатные микрофоны"), icon: "mic.and.signal.meter") {
            ParamRow(label: T("Room mics level", "Уровень комнатных"), value: store.recNum("room_mics_db"), range: -40...6,
                     defaultValue: -6, format: { Fmt.db($0) })
            PickerRow(label: T("Stereo technique", "Стерео-техника"), selection: store.recStr("room_technique"),
                      options: store.techniques.map { ($0.str("id"), $0.str("name")) })
            ParamRow(label: T("A-B spacing", "База A-B"), value: store.recNum("pair_spacing_m"), range: 0.1...3, step: 0.01,
                     defaultValue: 0.6, format: Fmt.metersFine, enabled: tech == "ab")
            ParamRow(label: T("Mic height", "Высота микрофонов"), value: store.recNum("room_height_m"), range: 0.5...maxH, step: 0.05,
                     defaultValue: 2.2, format: Fmt.metersFine)
            ToggleRow(label: T("Time-align room mics", "Выровнять по времени"), isOn: store.recBool("align_room_mics"),
                      help: T("Removes the travel delay of the room pair relative to the close mics",
                              "Убирает задержку прихода в комнатную пару относительно близких микрофонов"))
        }
    }
}

private struct ReverbDelaySection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Reverb & delay", "Ревер и дилей"), icon: "dot.radiowaves.left.and.right") {
            ParamRow(label: T("Pre-delay", "Предзадержка"), value: store.recNum("predelay_ms"), range: 0...200, defaultValue: 0,
                     format: Fmt.ms)
            ParamRow(label: T("Reverb return", "Возврат ревера"), value: store.recNum("reverb_return_db"), range: -24...12,
                     defaultValue: 0, bipolar: true, format: { Fmt.db($0) })
            Caption(text: T("Delay bus", "Шина дилея"))
            ParamRow(label: T("Time", "Время"), value: store.recNum("delay_time_ms"), range: 20...2000, log: true, defaultValue: 375,
                     format: Fmt.ms)
            ParamRow(label: T("Feedback", "Обратная связь"), value: store.recNum("delay_feedback"), range: 0...0.95, defaultValue: 0.35,
                     format: Fmt.pct)
            ParamRow(label: T("High cut", "Срез ВЧ"), value: store.recNum("delay_hicut_hz"), range: 1000...20000, log: true,
                     defaultValue: 6000, format: Fmt.hz)
            ToggleRow(label: T("Ping-pong", "Пинг-понг"), isOn: store.recBool("delay_pingpong"))
            ParamRow(label: T("Delay return", "Возврат дилея"), value: store.recNum("delay_return_db"), range: -24...12,
                     defaultValue: 0, bipolar: true, format: { Fmt.db($0) },
                     help: T("Channels feed the delay with their Delay send", "Каналы подают сигнал в дилей ручкой «Посыл в дилей»"))
        }
    }
}

private struct ListenerSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let size = store.roomSize
        SectionCard(title: T("Listener", "Слушатель"), icon: "headphones") {
            ParamRow(label: "X", value: Binding(get: { store.listenerPosition.0 },
                                                set: { store.move(nil, x: $0, y: store.listenerPosition.1) }),
                     range: 0...max(size.0, 1), step: 0.05, format: Fmt.meters)
            ParamRow(label: "Y", value: Binding(get: { store.listenerPosition.1 },
                                                set: { store.move(nil, x: store.listenerPosition.0, y: $0) }),
                     range: 0...max(size.1, 1), step: 0.05, format: Fmt.meters)
            InfoLine(label: T("Reference distance", "Опорное расстояние"), value: Fmt.meters(store.describe.num("ref_distance_m")))
            InfoLine(label: T("Critical distance", "Критическое расстояние"),
                     value: Fmt.meters(store.describe.num("critical_distance_m")))
            HStack {
                Spacer()
                Button(T("Reset listener", "Сбросить слушателя")) { store.resetListener() }
                    .buttonStyle(StudioButtonStyle(compact: true))
            }
        }
    }
}

// MARK: - Export panel (Master mode inspector)

struct ExportPanel: View {
    var body: some View {
        VStack(spacing: 10) {
            RenderSection()
            FormatSection()
            EdgesSection()
            MetadataSection()
        }
    }
}

private struct FormatSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let fmt = store.session?["recording"]?.str("output_format", "wav") ?? "wav"
        let bits = store.session?["recording"]?.num("bit_depth", 24) ?? 24
        let needsFFmpeg = fmt == "mp3" || fmt == "alac"
        let hasFFmpeg = store.info["deps"]?.flag("ffmpeg") ?? false
        let formats = store.formats.isEmpty ? ["wav", "flac", "alac", "mp3"] : store.formats
        SectionCard(title: T("Format", "Формат"), icon: "doc.badge.gearshape") {
            Segmented(selection: store.recStr("output_format"), options: formats.map { ($0, $0.uppercased()) })
            PickerRow(label: T("Sample rate", "Частота"), selection: store.recNum("sample_rate"),
                      options: [(44100.0, "44.1 kHz"), (48000.0, "48 kHz"), (88200.0, "88.2 kHz"), (96000.0, "96 kHz")])
            if fmt == "mp3" {
                PickerRow(label: T("Bitrate", "Битрейт"), selection: store.recNum("mp3_bitrate"),
                          options: [(128.0, "128 kbps"), (192.0, "192 kbps"), (256.0, "256 kbps"), (320.0, "320 kbps")])
            } else {
                PickerRow(label: T("Bit depth", "Разрядность"), selection: store.recNum("bit_depth"),
                          options: [(16.0, "16-bit"), (24.0, "24-bit"), (32.0, T("32-bit float", "32-bit float"))])
                PickerRow(label: T("Dither", "Дизеринг"), selection: store.recStr("dither"),
                          options: [("tpdf", "TPDF"), ("off", T("Off", "Выкл"))],
                          help: bits >= 32 ? T("Not used for 32-bit float", "Для 32-bit float не нужен") : T("Applied when reducing to 16/24-bit", "Применяется при понижении до 16/24 бит"))
            }
            if needsFFmpeg && !hasFFmpeg {
                Label(T("This format needs ffmpeg (brew install ffmpeg)", "Для этого формата нужен ffmpeg (brew install ffmpeg)"),
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 10))
                    .foregroundColor(Theme.yellow)
            }
        }
    }
}

private struct EdgesSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Start & end", "Начало и конец"), icon: "timeline.selection") {
            ParamRow(label: T("Fade in", "Нарастание"), value: store.recNum("fade_in_s"), range: 0...10, step: 0.1, defaultValue: 0,
                     format: Fmt.sec)
            ParamRow(label: T("Fade out", "Затухание"), value: store.recNum("fade_out_s"), range: 0...20, step: 0.1, defaultValue: 0,
                     format: Fmt.sec)
            ParamRow(label: T("Room tail", "Хвост помещения"), value: store.recNum("tail_s"), range: 0...10, step: 0.1,
                     defaultValue: 1.5, format: Fmt.sec, help: T("How much reverb tail to keep after the song ends",
                                                                  "Сколько хвоста реверберации оставить после конца песни"))
        }
    }
}

private struct MetadataSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Metadata", "Метаданные"), icon: "tag") {
            TextRow(label: T("Title", "Название"), text: store.metaStr("title"))
            TextRow(label: T("Artist", "Исполнитель"), text: store.metaStr("artist"))
            TextRow(label: T("Album", "Альбом"), text: store.metaStr("album"))
            TextRow(label: T("Year", "Год"), text: store.metaStr("year"))
            TextRow(label: T("Genre", "Жанр"), text: store.metaStr("genre"))
            TextRow(label: T("Comment", "Комментарий"), text: store.metaStr("comment"))
        }
    }
}

private struct RenderSection: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Render", "Рендер"), icon: "square.and.arrow.up", collapsible: false) {
            ToggleRow(label: T("Also export stems", "Экспортировать стемы"), isOn: $store.exportStems,
                      help: T("One processed WAV per channel next to the mix", "По обработанному WAV на канал рядом с миксом"))
            if let p = store.renderProgress {
                VStack(alignment: .leading, spacing: 6) {
                    ProgressStrip(value: p)
                    HStack {
                        Text(store.renderMessage).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                        Spacer()
                        Text(String(format: "%.0f%%", p * 100)).font(Theme.monoSmall).foregroundColor(Theme.text2)
                    }
                    Button(T("Cancel", "Отмена")) { store.cancelRender() }
                        .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
                }
            } else {
                Button { Task { await store.renderFinal() } } label: {
                    Label(T("Render mix", "Рендер микса"), systemImage: "record.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(StudioButtonStyle(prominent: true))
            }
            Text(T("Saved to ", "Сохраняется в ") + store.projectRoot.appendingPathComponent("mixes").path)
                .font(.system(size: 9))
                .foregroundColor(Theme.text3)
                .lineLimit(2)
                .truncationMode(.middle)
            LastRenderView()
        }
    }
}

private struct LastRenderView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let r = store.lastRender
        if !r.isNull {
            let rep = r["report"] ?? .null
            let master = rep["master"] ?? .null
            let path = r.str("path")
            VStack(alignment: .leading, spacing: 5) {
                Rectangle().fill(Theme.stroke).frame(height: 1)
                Caption(text: T("Last render", "Последний рендер"))
                Text(fileName(path)).font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.text).lineLimit(1)
                    .truncationMode(.middle)
                InfoLine(label: T("Loudness", "Громкость"), value: Fmt.lufs(master["lufs_after"]?.double ?? master["lufs"]?.double),
                         color: Theme.accent2)
                InfoLine(label: T("True peak", "Истинный пик"),
                         value: String(format: "%.1f dBTP", master.num("true_peak_db")).replacingOccurrences(of: "-", with: "−"))
                InfoLine(label: T("Duration", "Длительность"), value: Fmt.time(rep.num("duration_s")))
                InfoLine(label: T("Render time", "Время рендера"), value: Fmt.sec(rep.num("render_time_s")))
                HStack(spacing: 6) {
                    Button { store.listen(path, title: fileName(path)) } label: { Label(T("Play", "Слушать"), systemImage: "play.fill") }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    Button { store.reveal(path) } label: { Label(T("Show", "Показать"), systemImage: "folder") }
                        .buttonStyle(StudioButtonStyle(compact: true))
                    if let stems = r["stems_dir"]?.string, !stems.isEmpty {
                        Button { store.reveal(stems) } label: { Label(T("Stems", "Стемы"), systemImage: "square.stack.3d.up") }
                            .buttonStyle(StudioButtonStyle(compact: true))
                    }
                }
            }
        }
    }
}

// MARK: - Generation results (Generate mode inspector)

struct GenerationResultsPanel: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 10) {
            if store.generating {
                SectionCard(title: T("Generating", "Генерация"), icon: "hourglass", collapsible: false) {
                    ProgressStrip(value: store.genProgress > 0 ? store.genProgress : nil)
                    Text(store.genMessage).font(.system(size: 11)).foregroundColor(Theme.text2).lineLimit(3)
                    Button(T("Cancel", "Отмена")) { store.cancelGeneration() }
                        .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
                }
            }
            if !store.genResults.isEmpty {
                SectionCard(title: T("New songs", "Новые песни"), icon: "sparkles", collapsible: false) {
                    ForEach(store.genResults, id: \.self) { t in TrackCard(track: t, highlight: true) }
                }
            }
            SectionCard(title: T("Library", "Библиотека"), icon: "music.note.list", collapsible: false) {
                let songs = Array(store.library.list("songs").prefix(12))
                if songs.isEmpty {
                    Text(T("Generated songs appear here.", "Здесь появятся сгенерированные песни."))
                        .font(.system(size: 11))
                        .foregroundColor(Theme.text3)
                } else {
                    ForEach(songs, id: \.self) { t in TrackCard(track: t, highlight: false) }
                }
            }
        }
    }
}

struct TrackCard: View {
    @EnvironmentObject var store: StudioStore
    let track: JSONValue
    var highlight = false

    var body: some View {
        let path = track.str("path")
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "music.note")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(highlight ? Theme.accent : Theme.accent2)
                Text(track.str("title", fileName(path)))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(Theme.text)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if let d = track["duration"]?.double { Text(Fmt.clock(d)).font(Theme.monoSmall).foregroundColor(Theme.text3) }
            }
            HStack(spacing: 4) {
                if !track.str("engine").isEmpty { Badge(text: track.str("engine").uppercased()) }
                if !(track["stems"]?.object?.isEmpty ?? true) { Badge(text: T("STEMS", "СТЕМЫ"), color: Theme.green) }
                Spacer()
            }
            HStack(spacing: 6) {
                Button { Task { await store.openTrack(track) } } label: {
                    Label(T("Open in studio", "В студию"), systemImage: "slider.vertical.3")
                }
                .buttonStyle(StudioButtonStyle(prominent: highlight, compact: true))
                IconButton(icon: "play.fill", help: T("Listen", "Слушать"), size: 11) { store.listen(path, title: track.str("title")) }
                IconButton(icon: "folder", help: T("Show in Finder", "Показать в Finder"), size: 11) { store.reveal(path) }
                Spacer()
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 6).fill(highlight ? Theme.bg3 : Theme.bg1))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(highlight ? Theme.accent.opacity(0.6) : Theme.stroke, lineWidth: 1))
    }
}
