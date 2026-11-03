import SwiftUI

/// Mixer mode: one console strip per musician plus the master section.
struct MixerView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        if store.session == nil {
            EmptySessionView()
        } else {
            HStack(spacing: 0) {
                ScrollView(.horizontal, showsIndicators: true) {
                    HStack(alignment: .top, spacing: 6) {
                        ForEach(store.channelIDs, id: \.self) { id in
                            ChannelStrip(id: id)
                        }
                        AddStripButton()
                    }
                    .padding(10)
                    .frame(maxHeight: .infinity, alignment: .top)
                }
                Rectangle().fill(Theme.stroke).frame(width: 1)
                MasterStrip(player: store.player)
                    .padding(10)
            }
        }
    }
}

// MARK: - Formatting helpers

enum KnobFmt {
    static func hz(_ v: Double) -> String { v >= 1000 ? String(format: "%.1fk", v / 1000) : String(format: "%.0f", v) }
    static func hpf(_ v: Double) -> String { v <= 20.5 ? T("Off", "Выкл") : hz(v) }
    static func lpf(_ v: Double) -> String { v >= 19000 ? T("Off", "Выкл") : hz(v) }
    static func send(_ v: Double) -> String { v <= -59.5 ? T("Off", "Выкл") : Fmt.dbShort(v) }
}

// MARK: - Channel strip

struct ChannelStrip: View {
    @EnvironmentObject var store: StudioStore
    let id: String

    var body: some View {
        if let ch = store.session?.channel(id) {
            StripBody(id: id, ch: ch, selected: store.selectedChannel == id)
        }
    }
}

private struct StripBody: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue
    let selected: Bool

    var body: some View {
        let color = Color(hex: ch.str("color", "#cba6f7"))
        VStack(spacing: 6) {
            StripHeader(id: id, ch: ch, color: color)
            StripMicMenu(id: id, ch: ch)
            StripChips(id: id, ch: ch)
            StripKnobs(id: id, ch: ch, color: color)
            EQCurveView(bands: Biquad.channelBands(ch), handles: [], dbRange: 18, showLabels: false, interactive: false)
                .frame(height: 34)
                .background(RoundedRectangle(cornerRadius: 4).fill(Color.black.opacity(0.3)))
                .clipShape(RoundedRectangle(cornerRadius: 4))
                .help(T("Channel EQ — edit it in the inspector", "EQ канала — настраивается в инспекторе"))
            StripMuteSolo(id: id, ch: ch)
            StripFader(id: id, ch: ch, color: color)
        }
        .padding(6)
        .frame(width: 116)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(RoundedRectangle(cornerRadius: 8).fill(selected ? Theme.bg3 : Theme.bg2))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Theme.accent : Theme.stroke, lineWidth: selected ? 1.5 : 1))
        .contentShape(Rectangle())
        .onTapGesture { store.selectedChannel = id }
    }
}

private struct StripHeader: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(height: 4)
            HStack(spacing: 2) {
                Text(ch.str("name"))
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Theme.text)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Menu {
                    Menu(T("Instrument preset", "Пресет инструмента")) {
                        ForEach(store.instruments.map { $0.str("id") }, id: \.self) { inst in
                            Button(store.name(in: store.instruments, inst)) { store.applyInstrument(id, inst) }
                        }
                    }
                    Button(T("Duplicate", "Дублировать")) { store.duplicateChannel(id) }
                    Button(T("Show source file", "Показать исходный файл")) { store.reveal(ch.str("source")) }
                    Divider()
                    Button(T("Remove channel", "Удалить канал"), role: .destructive) { store.removeChannel(id) }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(Theme.text2)
                        .frame(width: 18, height: 16)
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .menuIndicator(.hidden)
                .fixedSize()
            }
            Text(store.name(in: store.instruments, ch.str("instrument")))
                .font(.system(size: 9))
                .foregroundColor(Theme.text3)
                .lineLimit(1)
        }
    }
}

private struct StripMicMenu: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        let micID = ch.str("mic")
        Menu {
            ForEach(store.mics.map { $0.str("id") }, id: \.self) { m in
                Button(store.name(in: store.mics, m)) { store.setChannel(id, "mic", .s(m)) }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: micID == "di" ? "cable.connector" : "mic.fill")
                    .font(.system(size: 9))
                    .foregroundColor(Theme.accent2)
                Text(StripMicMenu.short(store.name(in: store.mics, micID)))
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(Theme.text)
                    .lineLimit(1)
                Spacer(minLength: 0)
                Image(systemName: "chevron.down").font(.system(size: 7, weight: .bold)).foregroundColor(Theme.text3)
            }
            .padding(.horizontal, 6)
            .frame(height: 20)
            .background(RoundedRectangle(cornerRadius: 4).fill(Theme.bg0))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Theme.stroke, lineWidth: 1))
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .help(T("Microphone model", "Модель микрофона") + ": " + store.name(in: store.mics, micID))
    }

    /// Strip label for a mic: the reference model ("Studio LDC (U87 style)" → "U87",
    /// "Ribbon (R-121 / Coles 4038 style)" → "R-121"), otherwise the name without its tail.
    static func short(_ name: String) -> String {
        if let open = name.range(of: " ("), let close = name.range(of: ")", options: .backwards),
           open.upperBound <= close.lowerBound {
            var inner = String(name[open.upperBound..<close.lowerBound])
            var isModel = false
            if inner.hasSuffix(" style") { inner = String(inner.dropLast(6)); isModel = true }
            if inner.hasPrefix("в духе ") { inner = String(inner.dropFirst(7)); isModel = true }
            if isModel {
                if let slash = inner.range(of: " / ") { inner = String(inner[..<slash.lowerBound]) }
                return inner
            }
            return String(name[..<open.lowerBound])
        }
        if let slash = name.range(of: " / ") { return String(name[..<slash.lowerBound]) }
        return name
    }
}

private struct StripChips: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        HStack(spacing: 3) {
            Chip(title: "Ø", isOn: ch.flag("phase_invert"), color: Theme.blue, width: 18,
                 help: T("Invert polarity", "Инвертировать полярность")) {
                store.setChannel(id, "phase_invert", .b(!ch.flag("phase_invert")))
            }
            Chip(title: "ST", isOn: ch.flag("stereo"), color: Theme.accent2, width: 22,
                 help: T("Stereo source (keep both channels)", "Стерео-источник (оба канала)")) {
                store.setChannel(id, "stereo", .b(!ch.flag("stereo")))
            }
            Chip(title: "GATE", isOn: ch.flag("gate_on"), color: Theme.green, width: 32,
                 help: T("Noise gate", "Гейт")) {
                store.setChannel(id, "gate_on", .b(!ch.flag("gate_on")))
            }
            Chip(title: "EQ", isOn: ch.flag("eq_on", true), color: Theme.accent, width: 22,
                 help: T("EQ bands on/off (filters always work)", "Полосы EQ вкл/выкл (фильтры работают всегда)")) {
                store.setChannel(id, "eq_on", .b(!ch.flag("eq_on", true)))
            }
        }
    }
}

private struct StripKnobs: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue
    let color: Color

    var body: some View {
        let manual = ch.str("comp_mode", "auto") == "manual"
        let eqOn = ch.flag("eq_on", true)
        VStack(spacing: 5) {
            HStack(spacing: 0) {
                knob("drive_db", T("Drive", "Драйв"), 0...24, fmt: Fmt.dbShort)
                knob("hpf_hz", "HPF", 20...1000, log: true, fmt: KnobFmt.hpf)
            }
            HStack(spacing: 0) {
                knob("lpf_hz", "LPF", 1000...20000, log: true, fmt: KnobFmt.lpf)
                if manual {
                    knob("comp_threshold_db", T("Thr", "Порог"), -60...0, fmt: Fmt.dbShort)
                } else {
                    knob("comp", T("Comp", "Комп"), 0...1, fmt: Fmt.pct)
                }
            }
            HStack(spacing: 0) {
                knob("eq_low_db", T("Low", "Низ"), -18...18, bipolar: true, enabled: eqOn, fmt: Fmt.dbShort)
                knob("eq_lowmid_db", T("LoMid", "НСер"), -18...18, bipolar: true, enabled: eqOn, fmt: Fmt.dbShort)
            }
            HStack(spacing: 0) {
                knob("eq_mid_db", T("HiMid", "ВСер"), -18...18, bipolar: true, enabled: eqOn, fmt: Fmt.dbShort)
                knob("eq_high_db", T("High", "Верх"), -18...18, bipolar: true, enabled: eqOn, fmt: Fmt.dbShort)
            }
            HStack(spacing: 0) {
                knob("reverb_send_db", T("Rev", "Рев"), -40...12, fmt: Fmt.dbShort)
                knob("delay_send_db", T("Dly", "Дил"), -60...0, fmt: KnobFmt.send)
            }
            HStack(spacing: 0) {
                PanKnob(id: id, ch: ch, color: color)
                    .frame(maxWidth: .infinity)
                knob("width", T("Width", "Шир"), 0...2, enabled: ch.flag("stereo"), fmt: Fmt.pct)
            }
        }
    }

    private func knob(_ key: String, _ label: String, _ range: ClosedRange<Double>, log: Bool = false,
                      bipolar: Bool = false, enabled: Bool = true, fmt: @escaping (Double) -> String) -> some View {
        let def = store.defaultValue("channel", key)?.double ?? (bipolar ? 0 : range.lowerBound)
        return Knob(value: store.chNum(id, key), range: range, defaultValue: def, label: label, format: fmt,
                    log: log, bipolar: bipolar, color: color, size: 28, enabled: enabled)
            .frame(maxWidth: .infinity)
    }
}

/// Pan knob: "A" while the pan follows the stage position; double-click returns to auto.
private struct PanKnob: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue
    let color: Color

    var body: some View {
        let auto = ch["pan"]?.isNull ?? true
        Knob(value: store.chPan(id), range: -1...1, defaultValue: 0, label: T("Pan", "Пан"),
             format: { auto ? "A·" + Fmt.pan($0) : Fmt.pan($0) }, bipolar: true,
             color: auto ? Theme.text2 : color, size: 28,
             onReset: { store.chPanAuto(id).wrappedValue = true },
             tooltip: auto
                ? T("A = auto: the pan follows the musician's place on the stage. Turn the knob to set it by hand.",
                    "A = авто: панорама следует за местом музыканта на сцене. Покрутите ручку, чтобы задать вручную.")
                : T("Manual pan. Double-click to follow the stage position again.",
                    "Ручная панорама. Двойной щелчок вернёт панораму по сцене."))
    }
}

private struct StripMuteSolo: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue

    var body: some View {
        HStack(spacing: 4) {
            Chip(title: "M", isOn: ch.flag("mute"), color: Theme.red, width: 30, help: T("Mute", "Заглушить")) {
                store.toggleMute(id)
            }
            Chip(title: "S", isOn: ch.flag("solo"), color: Theme.yellow, width: 30, help: T("Solo", "Соло")) {
                store.toggleSolo(id)
            }
            Spacer(minLength: 0)
            Text(Fmt.pan(store.chPan(id).wrappedValue))
                .font(Theme.monoSmall)
                .foregroundColor(Theme.text3)
        }
    }
}

private struct StripFader: View {
    @EnvironmentObject var store: StudioStore
    let id: String
    let ch: JSONValue
    let color: Color

    var body: some View {
        VStack(spacing: 3) {
            HStack(spacing: 4) {
                VerticalFader(value: store.chNum(id, "gain_db"), range: -60...12, defaultValue: 0, color: color)
                    .frame(width: 58)
                ChannelMeter(player: store.player, id: id, width: 9)
                    .padding(.vertical, 12)
                Spacer(minLength: 0)
            }
            .frame(minHeight: 110, maxHeight: .infinity)
            Text(Fmt.db(ch.num("gain_db")))
                .font(Theme.mono)
                .foregroundColor(Theme.text)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 2)
                .background(RoundedRectangle(cornerRadius: 4).fill(Color.black.opacity(0.4)))
        }
    }
}

/// Level of a channel (or the master when id == nil) at the playhead, from the preview meters.
struct ChannelMeter: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer
    let id: String?
    var width: CGFloat = 8

    var body: some View {
        let m = store.meter(channel: id, at: player.position)
        LevelMeter(peak: m.0, rms: m.1, hold: m.2, width: width)
    }
}

private struct AddStripButton: View {
    @EnvironmentObject var store: StudioStore
    @State private var hover = false

    var body: some View {
        Button { store.addChannels() } label: {
            VStack(spacing: 8) {
                Image(systemName: "plus.circle")
                    .font(.system(size: 22, weight: .light))
                Text(T("Add tracks", "Добавить дорожки"))
                    .font(.system(size: 11, weight: .medium))
                    .multilineTextAlignment(.center)
            }
            .foregroundColor(hover ? Theme.accent : Theme.text3)
            .frame(width: 96)
            .frame(maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 8).strokeBorder(hover ? Theme.accent : Theme.strokeStrong,
                                                                       style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

// MARK: - Master strip

struct MasterStrip: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Text(T("MASTER", "МАСТЕР"))
                    .font(.system(size: 11, weight: .heavy))
                    .tracking(1.2)
                    .foregroundColor(Theme.accent)
                Spacer()
                if store.previewing { ProgressView().controlSize(.mini) }
            }
            MasterReadouts()
            MasterKnobs()
            HStack(spacing: 6) {
                MasterMeters(player: player)
                MeterScale()
            }
            .frame(minHeight: 120, maxHeight: .infinity)
            MonitorVolume(player: player)
        }
        .padding(8)
        .frame(width: 164)
        .frame(maxHeight: .infinity)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.bg2))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.strokeStrong, lineWidth: 1))
    }
}

private struct MasterReadouts: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let tp = store.previewTruePeak
        VStack(spacing: 4) {
            Readout(label: T("Loudness", "Громкость"), value: Fmt.lufs(store.previewLufs), color: Theme.accent2)
            Readout(label: T("True peak", "Истинный пик"),
                    value: tp.map { String(format: "%.1f dBTP", $0).replacingOccurrences(of: "-", with: "−") } ?? "—",
                    color: (tp ?? -99) > -0.5 ? Theme.red : Theme.text)
        }
        .help(T("Measured on the last preview render", "Измерено на последнем рендере превью"))
    }
}

private struct MasterKnobs: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let manual = store.session?["recording"]?.str("bus_comp_mode", "auto") == "manual"
        VStack(spacing: 5) {
            HStack(spacing: 0) {
                if manual {
                    knob("bus_threshold_db", T("Bus thr", "Порог шины"), -40...0, fmt: Fmt.dbShort)
                } else {
                    knob("bus_comp", T("Bus comp", "Комп шины"), 0...1, fmt: Fmt.pct)
                }
                knob("stereo_width", T("Width", "Ширина"), 0...2, fmt: Fmt.pct)
            }
            HStack(spacing: 0) {
                knob("room_mics_db", T("Room", "Комната"), -40...6, fmt: Fmt.dbShort)
                knob("reverb_return_db", T("Reverb", "Ревер"), -24...12, fmt: Fmt.dbShort)
            }
            HStack(spacing: 0) {
                knob("delay_return_db", T("Delay", "Дилей"), -24...12, fmt: Fmt.dbShort)
                knob("target_lufs", T("Target", "Цель"), -30...(-6), fmt: { String(format: "%.0f", $0) })
            }
        }
    }

    private func knob(_ key: String, _ label: String, _ range: ClosedRange<Double>,
                      fmt: @escaping (Double) -> String) -> some View {
        let def = store.defaultValue("recording", key)?.double ?? range.lowerBound
        return Knob(value: store.recNum(key), range: range, defaultValue: def, label: label, format: fmt,
                    color: Theme.accent, size: 30)
            .frame(maxWidth: .infinity)
    }
}

private struct MasterMeters: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var player: AudioPlayer

    var body: some View {
        let snap = store.meter(channel: nil, at: player.position)
        let l = player.isPlaying ? player.outPeak.0 : snap.0
        let r = player.isPlaying ? player.outPeak.1 : snap.0
        let hl = player.isPlaying ? player.outHold.0 : snap.2
        let hr = player.isPlaying ? player.outHold.1 : snap.2
        HStack(spacing: 3) {
            VStack(spacing: 2) {
                LevelMeter(peak: l, rms: l - 6, hold: hl, width: 12)
                Text("L").font(.system(size: 8, weight: .bold)).foregroundColor(Theme.text3)
            }
            VStack(spacing: 2) {
                LevelMeter(peak: r, rms: r - 6, hold: hr, width: 12)
                Text("R").font(.system(size: 8, weight: .bold)).foregroundColor(Theme.text3)
            }
        }
    }
}

/// dBFS marks next to the master meters (same −60…+6 scale as LevelMeter).
private struct MeterScale: View {
    var body: some View {
        GeometryReader { geo in
            let h = geo.size.height - 12
            ZStack(alignment: .topLeading) {
                ForEach([6.0, 0, -6, -12, -18, -24, -36, -48, -60], id: \.self) { db in
                    Text(db > 0 ? "+\(Int(db))" : "\(Int(db))")
                        .font(.system(size: 7, weight: .medium, design: .monospaced))
                        .foregroundColor(db == 0 ? Theme.text2 : Theme.text3)
                        .offset(y: h * (1 - CGFloat(meterNorm(db))) - 5)
                }
            }
        }
        .frame(width: 22)
    }
}

private struct MonitorVolume: View {
    @ObservedObject var player: AudioPlayer

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Caption(text: T("Monitor", "Мониторы"))
                Spacer()
                Text(player.volume <= 0.001 ? "−∞" : Fmt.db(20 * log10(player.volume)))
                    .font(Theme.monoSmall)
                    .foregroundColor(Theme.text2)
            }
            StudioSlider(value: Binding(get: { player.volume }, set: { player.volume = $0 }), range: 0...1,
                         defaultValue: 1, color: Theme.accent2)
        }
        .help(T("Listening volume only — does not change the mix", "Только громкость прослушивания — на микс не влияет"))
    }
}
