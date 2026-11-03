import SwiftUI

/// Master mode: bus EQ, bus compressor, color (preamp and tape), loudness and limiter.
struct MasterView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        if store.session == nil {
            EmptySessionView()
        } else {
            ScrollView(.vertical, showsIndicators: true) {
                VStack(spacing: 12) {
                    MasterChainHeader()
                    MasterEQCard()
                    HStack(alignment: .top, spacing: 12) {
                        BusCompCard().frame(maxWidth: .infinity)
                        LoudnessCard().frame(maxWidth: .infinity)
                    }
                    ColorCard()
                }
                .padding(12)
            }
        }
    }
}

/// Signal flow of the master bus, in processing order.
private struct MasterChainHeader: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let rec = store.session?["recording"] ?? .null
        HStack(spacing: 6) {
            VStack(alignment: .leading, spacing: 1) {
                Text(T("Master bus", "Мастер-шина"))
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(Theme.text)
                Text(T("Processing order of the final mix", "Порядок обработки финального микса"))
                    .font(Theme.small)
                    .foregroundColor(Theme.text3)
            }
            Spacer(minLength: 10)
            ChainStep(title: T("Width", "Ширина"), on: abs(rec.num("stereo_width", 1) - 1) > 0.01)
            ChainArrow()
            ChainStep(title: "EQ", on: rec.flag("master_eq_on", true) && !Biquad.masterBands(rec).isEmpty)
            ChainArrow()
            ChainStep(title: T("Bus comp", "Компрессор"),
                      on: rec.str("bus_comp_mode", "auto") == "manual" ? rec.num("bus_ratio", 2) > 1 : rec.num("bus_comp", 0.3) > 0.01)
            ChainArrow()
            ChainStep(title: T("Tape", "Лента"), on: rec.str("tape", "off") != "off")
            ChainArrow()
            ChainStep(title: T("Loudness", "Громкость"), on: rec.flag("normalize", true))
            ChainArrow()
            ChainStep(title: T("Limiter", "Лимитер"), on: rec.flag("limiter", true))
        }
    }
}

private struct ChainStep: View {
    let title: String
    let on: Bool

    var body: some View {
        Text(title)
            .font(.system(size: 10, weight: .semibold))
            .foregroundColor(on ? Theme.text : Theme.text3)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 5).fill(on ? Theme.accent.opacity(0.18) : Theme.bg2))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(on ? Theme.accent.opacity(0.7) : Theme.stroke, lineWidth: 1))
            .lineLimit(1)
            .fixedSize()
    }
}

private struct ChainArrow: View {
    var body: some View {
        Image(systemName: "chevron.right").font(.system(size: 8, weight: .bold)).foregroundColor(Theme.text3)
    }
}

// MARK: - Master EQ

private struct MasterEQCard: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let rec = store.session?["recording"] ?? .null
        let on = rec.flag("master_eq_on", true)
        SectionCard(title: T("Master EQ", "Мастер-эквалайзер"), icon: "slider.horizontal.3",
                    trailing: AnyView(Toggle("", isOn: store.recBool("master_eq_on")).toggleStyle(.switch).controlSize(.mini)
                        .labelsHidden())) {
            EQCurveView(bands: Biquad.masterBands(rec), handles: handles(on), sampleRate: rec.num("sample_rate", 48000))
                .frame(height: 190)
            HStack(alignment: .top, spacing: 14) {
                VStack(spacing: 8) {
                    ParamRow(label: T("High-pass", "Срез низа"), value: store.recNum("master_hpf_hz"), range: 0...300,
                             defaultValue: 0, format: { $0 < 15 ? T("Off", "Выкл") : Fmt.hz($0) }, enabled: on, labelWidth: 96)
                    ParamRow(label: T("Low shelf", "Низ"), value: store.recNum("master_low_db"), range: -12...12, defaultValue: 0,
                             bipolar: true, format: { Fmt.db($0) }, enabled: on, labelWidth: 96)
                    ParamRow(label: T("Low freq", "Частота низа"), value: store.recNum("master_low_freq"), range: 30...400, log: true,
                             defaultValue: 100, format: Fmt.hz, enabled: on, labelWidth: 96)
                    ParamRow(label: T("High shelf", "Верх"), value: store.recNum("master_high_db"), range: -12...12, defaultValue: 0,
                             bipolar: true, format: { Fmt.db($0) }, enabled: on, labelWidth: 96)
                }
                VStack(spacing: 8) {
                    ParamRow(label: T("Mid", "Середина"), value: store.recNum("master_mid_db"), range: -12...12, defaultValue: 0,
                             bipolar: true, format: { Fmt.db($0) }, enabled: on, labelWidth: 96)
                    ParamRow(label: T("Mid freq", "Частота сер."), value: store.recNum("master_mid_freq"), range: 200...8000, log: true,
                             defaultValue: 1000, format: Fmt.hz, enabled: on, labelWidth: 96)
                    ParamRow(label: T("Mid Q", "Добротность"), value: store.recNum("master_mid_q"), range: 0.2...4, log: true,
                             defaultValue: 0.8, format: { String(format: "%.2f", $0) }, enabled: on, labelWidth: 96)
                    ParamRow(label: T("High freq", "Частота верха"), value: store.recNum("master_high_freq"), range: 2000...18000,
                             log: true, defaultValue: 10000, format: Fmt.hz, enabled: on, labelWidth: 96)
                }
            }
        }
    }

    private func handles(_ on: Bool) -> [EQHandle] {
        [
            EQHandle(id: "hpf", label: "HP", color: Theme.blue, freq: store.recNum("master_hpf_hz"), gain: nil,
                     freqRange: 15...300, enabled: on),
            EQHandle(id: "low", label: "L", color: Theme.accent, freq: store.recNum("master_low_freq"),
                     gain: store.recNum("master_low_db"), freqRange: 30...400, gainRange: -12...12, enabled: on),
            EQHandle(id: "mid", label: "M", color: Theme.green, freq: store.recNum("master_mid_freq"),
                     gain: store.recNum("master_mid_db"), freqRange: 200...8000, gainRange: -12...12, enabled: on),
            EQHandle(id: "high", label: "H", color: Theme.purple, freq: store.recNum("master_high_freq"),
                     gain: store.recNum("master_high_db"), freqRange: 2000...18000, gainRange: -12...12, enabled: on),
        ]
    }
}

// MARK: - Bus compressor

private struct BusCompCard: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let rec = store.session?["recording"] ?? .null
        let manual = rec.str("bus_comp_mode", "auto") == "manual"
        let c = rec.num("bus_comp", 0.3)
        let thr = manual ? rec.num("bus_threshold_db", -18) : -14 - 8 * c
        let ratio = manual ? rec.num("bus_ratio", 2) : (c > 0.01 ? 1.3 + 2.2 * c : 1)
        SectionCard(title: T("Bus compressor", "Компрессор шины"), icon: "rectangle.compress.vertical") {
            Segmented(selection: store.recStr("bus_comp_mode"),
                      options: [("auto", T("Auto (glue)", "Авто (склейка)")), ("manual", T("Manual", "Ручной"))])
            if manual {
                ParamRow(label: T("Threshold", "Порог"), value: store.recNum("bus_threshold_db"), range: -40...0, defaultValue: -18,
                         format: { Fmt.db($0) }, labelWidth: 96)
                ParamRow(label: T("Ratio", "Соотношение"), value: store.recNum("bus_ratio"), range: 1...10, log: true, defaultValue: 2,
                         format: Fmt.ratio, labelWidth: 96)
                ParamRow(label: T("Attack", "Атака"), value: store.recNum("bus_attack_ms"), range: 0.1...200, log: true,
                         defaultValue: 30, format: Fmt.ms, labelWidth: 96)
                ParamRow(label: T("Release", "Восстановл."), value: store.recNum("bus_release_ms"), range: 10...2000, log: true,
                         defaultValue: 250, format: Fmt.ms, labelWidth: 96)
                ParamRow(label: T("Make-up", "Компенсация"), value: store.recNum("bus_makeup_db"), range: 0...12, defaultValue: 0,
                         format: { Fmt.db($0) }, labelWidth: 96)
            } else {
                ParamRow(label: T("Amount", "Степень"), value: store.recNum("bus_comp"), range: 0...1, defaultValue: 0.3,
                         format: Fmt.pct, labelWidth: 96)
                InfoLine(label: T("Resulting", "Получается"),
                         value: c > 0.01 ? Fmt.db(thr) + " · " + Fmt.ratio(ratio) + " · 30/250 " + Fmt.Unit.ms : T("off", "выкл"))
            }
            CompCurveView(threshold: thr, ratio: ratio, knee: 8, makeup: manual ? rec.num("bus_makeup_db") : 0)
                .frame(height: 120)
        }
    }
}

// MARK: - Loudness

private struct LoudnessCard: View {
    @EnvironmentObject var store: StudioStore

    private static let targets: [(String, Double)] = [("Spotify", -14), ("Apple Music", -16), ("YouTube", -14),
                                                      ("Club", -9), ("EBU R128", -23)]

    var body: some View {
        let rec = store.session?["recording"] ?? .null
        let normalize = rec.flag("normalize", true)
        let target = rec.num("target_lufs", -14)
        SectionCard(title: T("Loudness & limiter", "Громкость и лимитер"), icon: "speaker.wave.3") {
            ToggleRow(label: T("Normalize loudness", "Нормализовать громкость"), isOn: store.recBool("normalize"),
                      help: T("Integrated LUFS (ITU-R BS.1770) of the whole song", "Интегральная громкость LUFS (ITU-R BS.1770) по всей песне"))
            ParamRow(label: T("Target", "Цель"), value: store.recNum("target_lufs"), range: -30...(-6), step: 0.5, defaultValue: -14,
                     format: { String(format: "%.1f LUFS", $0).replacingOccurrences(of: "-", with: "−") }, enabled: normalize,
                     labelWidth: 96)
            HStack(spacing: 4) {
                ForEach(Array(LoudnessCard.targets.enumerated()), id: \.offset) { _, t in
                    Chip(title: t.0 == "Club" ? T("Club", "Клуб") : t.0, isOn: abs(target - t.1) < 0.05, color: Theme.accent2,
                         help: String(format: "%.0f LUFS", t.1)) {
                        store.setRecording("target_lufs", .n(t.1))
                    }
                }
            }
            .disabled(!normalize)
            ParamRow(label: T("Ceiling", "Потолок"), value: store.recNum("ceiling_db"), range: -6...0, step: 0.1, defaultValue: -1,
                     format: { String(format: "%.1f dBTP", $0).replacingOccurrences(of: "-", with: "−") }, labelWidth: 96)
            ToggleRow(label: T("True-peak limiter", "Лимитер истинного пика"), isOn: store.recBool("limiter"))
            LoudnessReadouts()
        }
    }
}

private struct LoudnessReadouts: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let m = store.previewReport["master"] ?? .null
        let tp = m["true_peak_db"]?.double
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Readout(label: T("Before", "До"), value: Fmt.lufs(m["lufs_before"]?.double ?? m["lufs"]?.double))
                Readout(label: T("After", "После"), value: Fmt.lufs(m["lufs_after"]?.double ?? m["lufs"]?.double), color: Theme.accent2)
            }
            HStack(spacing: 6) {
                Readout(label: T("Gain", "Усиление"), value: m["gain_db"]?.double.map { Fmt.db($0) } ?? "—")
                Readout(label: T("True peak", "Истинный пик"),
                        value: tp.map { String(format: "%.1f dBTP", $0).replacingOccurrences(of: "-", with: "−") } ?? "—",
                        color: (tp ?? -99) > -0.5 ? Theme.red : Theme.text)
            }
            Text(m.isNull ? T("Play the preview to measure", "Запустите превью, чтобы измерить")
                          : T("Measured on the preview loop; the final render measures the whole song",
                              "Измерено на петле превью; финальный рендер меряет всю песню"))
                .font(.system(size: 9))
                .foregroundColor(Theme.text3)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Color

private struct ColorCard: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        SectionCard(title: T("Color", "Окраска"), icon: "flame") {
            HStack(alignment: .top, spacing: 14) {
                VStack(spacing: 8) {
                    PickerRow(label: T("Preamp", "Предусилитель"), selection: store.recStr("preamp"),
                              options: store.preamps.map { ($0.str("id"), $0.str("name")) },
                              help: T("Console preamp on every channel", "Предусилитель пульта на каждом канале"), labelWidth: 96)
                    ParamRow(label: T("Preamp drive", "Драйв"), value: store.recNum("preamp_drive_db"), range: 0...24, defaultValue: 0,
                             format: { Fmt.db($0) }, labelWidth: 96)
                }
                VStack(spacing: 8) {
                    PickerRow(label: T("Tape", "Лента"), selection: store.recStr("tape"),
                              options: store.tapes.map { ($0.str("id"), $0.str("name")) },
                              help: T("Tape saturation, wow & flutter and hiss on the master", "Насыщение, детонация и шум ленты на мастере"),
                              labelWidth: 96)
                    ParamRow(label: T("Stereo width", "Ширина стерео"), value: store.recNum("stereo_width"), range: 0...2,
                             defaultValue: 1, format: Fmt.pct, labelWidth: 96)
                }
            }
        }
    }
}
