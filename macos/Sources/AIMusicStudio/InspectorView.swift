import SwiftUI

/// Right-hand panel: every parameter of the selected channel, the room, the export or generation results.
struct InspectorView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            InspectorHeader()
            Rectangle().fill(Theme.stroke).frame(height: 1)
            ScrollView(.vertical, showsIndicators: true) {
                InspectorContent()
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .top)
            }
        }
        .background(Theme.bg1)
    }
}

private struct InspectorHeader: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let ch = store.selectedChannelData
        let channelMode = store.mode == .stage || store.mode == .mixer
        HStack(spacing: 8) {
            if channelMode, let ch {
                Circle().fill(store.color(of: ch)).frame(width: 10, height: 10)
                Text(ch.str("name")).font(Theme.title).foregroundColor(Theme.text).lineLimit(1)
                Spacer()
                IconButton(icon: "xmark", help: T("Back to room settings", "Назад к настройкам комнаты")) {
                    store.selectedChannel = nil
                }
            } else {
                Image(systemName: icon).font(.system(size: 12)).foregroundColor(Theme.accent)
                Text(title).font(Theme.title).foregroundColor(Theme.text).lineLimit(1)
                Spacer()
            }
        }
        .padding(.horizontal, 12)
        .frame(height: 40)
    }

    private var title: String {
        switch store.mode {
        case .generate: return T("Results", "Результаты")
        case .master: return T("Export", "Экспорт")
        case .release: return T("Publish queue", "Очередь публикации")
        case .stage, .mixer: return T("Room & recording", "Комната и запись")
        }
    }

    private var icon: String {
        switch store.mode {
        case .generate: return "music.note.list"
        case .master: return "square.and.arrow.up"
        case .release: return "tray.full"
        case .stage, .mixer: return "cube"
        }
    }
}

private struct InspectorContent: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        switch store.mode {
        case .generate:
            GenerationResultsPanel()
        case .master:
            if store.session != nil { ExportPanel() } else { InspectorPlaceholder() }
        case .release:
            PublishQueuePanel(rs: store.releases)
        case .stage, .mixer:
            if let id = store.selectedChannel, store.session?.channel(id) != nil {
                ChannelInspector(id: id)
            } else if store.session != nil {
                RoomInspector()
            } else {
                InspectorPlaceholder()
            }
        }
    }
}

struct InspectorPlaceholder: View {
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "slider.horizontal.3").font(.system(size: 26, weight: .light)).foregroundColor(Theme.text3)
            Text(T("Open a session to see its settings here.", "Откройте сессию — здесь появятся её настройки."))
                .font(.system(size: 11))
                .foregroundColor(Theme.text3)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }
}

// MARK: - Channel inspector

struct ChannelInspector: View {
    @EnvironmentObject var store: StudioStore
    let id: String

    var body: some View {
        if let ch = store.session?.channel(id) {
            VStack(spacing: 10) {
                ChannelSection(id: id, ch: ch)
                MicSection(id: id, ch: ch)
                PreampGateSection(id: id, ch: ch)
                CompressorSection(id: id, ch: ch)
                ChannelEQSection(id: id, ch: ch)
                OutputSection(id: id, ch: ch)
            }
        }
    }
}

private struct ChannelSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let geo = store.describe["channels"]?[id]
        let room = store.roomSize
        SectionCard(title: T("Channel", "Канал"), icon: "person.wave.2") {
            TextRow(label: T("Name", "Имя"), text: store.chStr(id, "name"))
            PickerRow(label: T("Instrument preset", "Инструмент"),
                      selection: Binding(get: { ch.str("instrument") }, set: { store.applyInstrument(id, $0) }),
                      options: store.instruments.map { ($0.str("id"), $0.str("name")) },
                      help: T("Applies the preset mic, distance, filters, compressor, EQ and reverb send",
                              "Применяет пресет: микрофон, дистанцию, фильтры, компрессор, EQ и посыл в ревер"))
            ColorSwatches(id: id, current: ch.str("color"))
            HStack(spacing: 6) {
                Text(T("Source", "Источник")).font(Theme.label).foregroundColor(Theme.text2).frame(width: 112, alignment: .leading)
                Text(fileName(ch.str("source"))).font(Theme.monoSmall).foregroundColor(Theme.text).lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                IconButton(icon: "magnifyingglass", help: T("Show in Finder", "Показать в Finder"), size: 11) {
                    store.reveal(ch.str("source"))
                }
            }
            ParamRow(label: T("Position X", "Позиция X"),
                     value: Binding(get: { store.session?.channel(id)?.num("x") ?? 0 },
                                    set: { store.move(id, x: $0, y: store.session?.channel(id)?.num("y") ?? 0) }),
                     range: 0...max(room.0, 1), step: 0.05, format: Fmt.meters,
                     help: T("Left ↔ right on the stage plan", "Влево ↔ вправо на плане"))
            ParamRow(label: T("Position Y", "Позиция Y"),
                     value: Binding(get: { store.session?.channel(id)?.num("y") ?? 0 },
                                    set: { store.move(id, x: store.session?.channel(id)?.num("x") ?? 0, y: $0) }),
                     range: 0...max(room.1, 1), step: 0.05, format: Fmt.meters,
                     help: T("Front (stage) ↔ back of the room", "Сцена ↔ глубина комнаты"))
            if let geo {
                InfoLine(label: T("Distance to listener", "До слушателя"), value: Fmt.meters(geo.num("distance_m")))
                InfoLine(label: T("Arrival delay", "Задержка прихода"), value: Fmt.ms(geo.num("delay_ms")))
                InfoLine(label: T("Direction", "Направление"), value: Fmt.deg(geo.num("azimuth_deg")))
                InfoLine(label: T("Field", "Поле"),
                         value: geo.flag("beyond_critical") ? T("reverberant (beyond critical)", "диффузное (дальше критического)")
                                                            : T("direct", "прямое"),
                         color: geo.flag("beyond_critical") ? Theme.yellow : Theme.green)
            }
            HStack(spacing: 6) {
                Button { store.duplicateChannel(id) } label: { Label(T("Duplicate", "Дублировать"), systemImage: "plus.square.on.square") }
                    .buttonStyle(StudioButtonStyle(compact: true))
                Spacer()
                Button { store.removeChannel(id) } label: { Label(T("Remove", "Удалить"), systemImage: "trash") }
                    .buttonStyle(StudioButtonStyle(destructive: true, compact: true))
            }
        }
    }
}

private struct ColorSwatches: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let current: String

    var body: some View {
        HStack(spacing: 5) {
            Text(T("Color", "Цвет")).font(Theme.label).foregroundColor(Theme.text2).frame(width: 112, alignment: .leading)
            ForEach(Instruments.palette, id: \.self) { hex in
                Circle()
                    .fill(Color(hex: hex))
                    .frame(width: 13, height: 13)
                    .overlay(Circle().stroke(Color.white, lineWidth: hex.lowercased() == current.lowercased() ? 2 : 0))
                    .onTapGesture { store.setChannel(id, "color", .s(hex)) }
            }
            Spacer(minLength: 0)
        }
    }
}

private struct MicSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let micID = ch.str("mic")
        let mic = store.mic(micID)
        let isDI = micID == "di"
        SectionCard(title: T("Microphone", "Микрофон"), icon: "mic") {
            PickerRow(label: T("Model", "Модель"), selection: store.chStr(id, "mic"),
                      options: store.mics.map { ($0.str("id"), $0.str("name")) })
            HStack(alignment: .top, spacing: 10) {
                PolarPatternView(a: store.patternA(mic: micID) ?? 1)
                    .frame(width: 70, height: 70)
                    .opacity(isDI ? 0.25 : 1)
                VStack(alignment: .leading, spacing: 4) {
                    Text(isDI ? T("Direct input (no microphone)", "Линейный вход (без микрофона)") : store.patternName(mic: micID))
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Theme.text)
                    Text(mic?.str("description") ?? "")
                        .font(.system(size: 10))
                        .foregroundColor(Theme.text2)
                        .fixedSize(horizontal: false, vertical: true)
                    if let n = mic?["self_noise_dba"]?.double, !isDI {
                        Text(T("Self-noise ", "Собственный шум ") + String(format: "%.0f ", n) + Fmt.Unit.dB + "-A")
                            .font(Theme.monoSmall)
                            .foregroundColor(Theme.text3)
                    }
                }
            }
            ParamRow(label: T("Distance", "Дистанция"), value: store.chNum(id, "mic_distance_cm"), range: 1...400, log: true,
                     defaultValue: 30, format: Fmt.cm, help: T("Closer = drier, more proximity bass", "Ближе — суше и больше эффекта близости"),
                     enabled: !isDI)
            ParamRow(label: T("Off-axis angle", "Угол к оси"), value: store.chNum(id, "mic_angle_deg"), range: 0...180, step: 1,
                     defaultValue: 0, format: Fmt.deg, help: T("0° = aimed at the source", "0° — микрофон направлен на источник"),
                     enabled: !isDI)
        }
    }
}

private struct PreampGateSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let gate = ch.flag("gate_on")
        SectionCard(title: T("Preamp & gate", "Предусилитель и гейт"), icon: "dial.medium") {
            ParamRow(label: T("Drive", "Драйв"), value: store.chNum(id, "drive_db"), range: 0...24, defaultValue: 0,
                     format: { Fmt.db($0) }, help: T("Extra drive on top of the session preamp (Master → Color)",
                                                  "Дополнительный драйв поверх предусилителя сессии (Мастер → Окраска)"))
            ToggleRow(label: T("Invert polarity (Ø)", "Инверсия полярности (Ø)"), isOn: store.chBool(id, "phase_invert"))
            ToggleRow(label: T("Noise gate", "Гейт"), isOn: store.chBool(id, "gate_on"))
            ParamRow(label: T("Threshold", "Порог"), value: store.chNum(id, "gate_threshold_db"), range: -80...0, defaultValue: -50,
                     format: { Fmt.db($0) }, enabled: gate)
            ParamRow(label: T("Range", "Глубина"), value: store.chNum(id, "gate_range_db"), range: 0...80, defaultValue: 30,
                     format: { Fmt.db($0) }, help: T("How much the gate turns the signal down", "Насколько гейт приглушает сигнал"),
                     enabled: gate)
            ParamRow(label: T("Release", "Восстановление"), value: store.chNum(id, "gate_release_ms"), range: 10...1000, log: true,
                     defaultValue: 80, format: Fmt.ms, enabled: gate)
        }
    }
}

private struct CompressorSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let manual = ch.str("comp_mode", "auto") == "manual"
        let c = ch.num("comp", 0.3)
        let thr = manual ? ch.num("comp_threshold_db", -18) : -10 - 20 * c
        let ratio = manual ? ch.num("comp_ratio", 3) : 1 + 5 * c
        let knee = manual ? ch.num("comp_knee_db", 6) : 6
        SectionCard(title: T("Compressor", "Компрессор"), icon: "rectangle.compress.vertical") {
            Segmented(selection: store.chStr(id, "comp_mode"),
                      options: [("auto", T("Auto (one knob)", "Авто (одна ручка)")), ("manual", T("Manual", "Ручной"))])
            if manual {
                ParamRow(label: T("Threshold", "Порог"), value: store.chNum(id, "comp_threshold_db"), range: -60...0,
                         defaultValue: -18, format: { Fmt.db($0) })
                ParamRow(label: T("Ratio", "Соотношение"), value: store.chNum(id, "comp_ratio"), range: 1...20, log: true,
                         defaultValue: 3, format: Fmt.ratio)
                ParamRow(label: T("Attack", "Атака"), value: store.chNum(id, "comp_attack_ms"), range: 0.1...200, log: true,
                         defaultValue: 10, format: Fmt.ms)
                ParamRow(label: T("Release", "Восстановление"), value: store.chNum(id, "comp_release_ms"), range: 10...2000, log: true,
                         defaultValue: 120, format: Fmt.ms)
                ParamRow(label: T("Knee", "Колено"), value: store.chNum(id, "comp_knee_db"), range: 0...24, defaultValue: 6,
                         format: { Fmt.db($0) })
                ParamRow(label: T("Make-up gain", "Компенсация"), value: store.chNum(id, "comp_makeup_db"), range: 0...24,
                         defaultValue: 0, format: { Fmt.db($0) })
            } else {
                ParamRow(label: T("Amount", "Степень"), value: store.chNum(id, "comp"), range: 0...1, defaultValue: 0.3,
                         format: Fmt.pct, help: T("One knob: threshold, ratio and attack follow it", "Одна ручка: порог, соотношение и атака следуют за ней"))
                InfoLine(label: T("Resulting", "Получается"),
                         value: c > 0.01 ? Fmt.db(thr) + " · " + Fmt.ratio(ratio) : T("off", "выкл"))
            }
            CompCurveView(threshold: thr, ratio: (manual || c > 0.01) ? ratio : 1, knee: knee,
                          makeup: manual ? ch.num("comp_makeup_db") : 0)
                .frame(height: 110)
        }
    }
}

private struct ChannelEQSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let on = ch.flag("eq_on", true)
        SectionCard(title: T("Equalizer", "Эквалайзер"), icon: "slider.horizontal.3",
                    trailing: AnyView(Toggle("", isOn: store.chBool(id, "eq_on")).toggleStyle(.switch).controlSize(.mini).labelsHidden())) {
            EQCurveView(bands: Biquad.channelBands(ch), handles: handles(on))
                .frame(height: 150)
            ParamRow(label: T("High-pass", "Срез низа (HPF)"), value: store.chNum(id, "hpf_hz"), range: 20...1000, log: true,
                     defaultValue: 30, format: { $0 <= 20.5 ? T("Off", "Выкл") : Fmt.hz($0) })
            ParamRow(label: T("Low-pass", "Срез верха (LPF)"), value: store.chNum(id, "lpf_hz"), range: 1000...20000, log: true,
                     defaultValue: 20000, format: { $0 >= 19000 ? T("Off", "Выкл") : Fmt.hz($0) })
            Group {
                Caption(text: T("Low shelf", "Низкая полка"))
                ParamRow(label: T("Gain", "Усиление"), value: store.chNum(id, "eq_low_db"), range: -18...18, defaultValue: 0,
                         bipolar: true, format: { Fmt.db($0) }, enabled: on)
                ParamRow(label: T("Frequency", "Частота"), value: store.chNum(id, "eq_low_freq"), range: 30...500, log: true,
                         defaultValue: 100, format: Fmt.hz, enabled: on)
                Caption(text: T("Low-mid bell", "Низкая середина"))
                ParamRow(label: T("Gain", "Усиление"), value: store.chNum(id, "eq_lowmid_db"), range: -18...18, defaultValue: 0,
                         bipolar: true, format: { Fmt.db($0) }, enabled: on)
                ParamRow(label: T("Frequency", "Частота"), value: store.chNum(id, "eq_lowmid_freq"), range: 100...2000, log: true,
                         defaultValue: 400, format: Fmt.hz, enabled: on)
                ParamRow(label: "Q", value: store.chNum(id, "eq_lowmid_q"), range: 0.2...8, log: true, defaultValue: 1,
                         format: { String(format: "%.2f", $0) }, enabled: on)
            }
            Group {
                Caption(text: T("High-mid bell", "Высокая середина"))
                ParamRow(label: T("Gain", "Усиление"), value: store.chNum(id, "eq_mid_db"), range: -18...18, defaultValue: 0,
                         bipolar: true, format: { Fmt.db($0) }, enabled: on)
                ParamRow(label: T("Frequency", "Частота"), value: store.chNum(id, "eq_mid_freq"), range: 500...12000, log: true,
                         defaultValue: 1000, format: Fmt.hz, enabled: on)
                ParamRow(label: "Q", value: store.chNum(id, "eq_mid_q"), range: 0.2...8, log: true, defaultValue: 1,
                         format: { String(format: "%.2f", $0) }, enabled: on)
                Caption(text: T("High shelf", "Высокая полка"))
                ParamRow(label: T("Gain", "Усиление"), value: store.chNum(id, "eq_high_db"), range: -18...18, defaultValue: 0,
                         bipolar: true, format: { Fmt.db($0) }, enabled: on)
                ParamRow(label: T("Frequency", "Частота"), value: store.chNum(id, "eq_high_freq"), range: 2000...18000, log: true,
                         defaultValue: 10000, format: Fmt.hz, enabled: on)
            }
        }
    }

    private func handles(_ on: Bool) -> [EQHandle] {
        [
            EQHandle(id: "hpf", label: "HP", color: Theme.blue, freq: store.chNum(id, "hpf_hz"), gain: nil, freqRange: 20...1000),
            EQHandle(id: "low", label: "L", color: Theme.accent, freq: store.chNum(id, "eq_low_freq"),
                     gain: store.chNum(id, "eq_low_db"), freqRange: 30...500, enabled: on),
            EQHandle(id: "lowmid", label: "LM", color: Theme.yellow, freq: store.chNum(id, "eq_lowmid_freq"),
                     gain: store.chNum(id, "eq_lowmid_db"), freqRange: 100...2000, enabled: on),
            EQHandle(id: "mid", label: "HM", color: Theme.green, freq: store.chNum(id, "eq_mid_freq"),
                     gain: store.chNum(id, "eq_mid_db"), freqRange: 500...12000, enabled: on),
            EQHandle(id: "high", label: "H", color: Theme.purple, freq: store.chNum(id, "eq_high_freq"),
                     gain: store.chNum(id, "eq_high_db"), freqRange: 2000...18000, enabled: on),
            EQHandle(id: "lpf", label: "LP", color: Theme.blue, freq: store.chNum(id, "lpf_hz"), gain: nil, freqRange: 1000...20000),
        ]
    }
}

private struct OutputSection: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let auto = ch["pan"]?.isNull ?? true
        let stereo = ch.flag("stereo")
        SectionCard(title: T("Output", "Выход"), icon: "speaker.wave.2") {
            ParamRow(label: T("Fader", "Фейдер"), value: store.chNum(id, "gain_db"), range: -60...12, defaultValue: 0,
                     format: { Fmt.db($0) })
            ToggleRow(label: T("Pan follows the stage", "Панорама по сцене"), isOn: store.chPanAuto(id),
                      help: T("Pan is computed from the musician position", "Панорама считается из позиции музыканта"))
            ParamRow(label: T("Pan", "Панорама"), value: store.chPan(id), range: -1...1, step: 0.01, defaultValue: 0, bipolar: true,
                     format: { (auto ? "A · " : "") + Fmt.pan($0) })
            ToggleRow(label: T("Stereo source", "Стерео-источник"), isOn: store.chBool(id, "stereo"))
            ParamRow(label: T("Stereo width", "Ширина стерео"), value: store.chNum(id, "width"), range: 0...2, defaultValue: 1,
                     format: Fmt.pct, enabled: stereo)
            ParamRow(label: T("Reverb send", "Посыл в ревер"), value: store.chNum(id, "reverb_send_db"), range: -40...12,
                     defaultValue: 0, format: { Fmt.db($0) })
            ParamRow(label: T("Delay send", "Посыл в дилей"), value: store.chNum(id, "delay_send_db"), range: -60...0,
                     defaultValue: -60, format: { $0 <= -59.5 ? T("Off", "Выкл") : Fmt.db($0) })
            HStack(spacing: 6) {
                Chip(title: T("Mute", "Mute"), isOn: ch.flag("mute"), color: Theme.red) { store.toggleMute(id) }
                Chip(title: T("Solo", "Соло"), isOn: ch.flag("solo"), color: Theme.yellow) { store.toggleSolo(id) }
                Spacer()
            }
        }
    }
}
