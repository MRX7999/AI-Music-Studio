import Foundation

/// Two-language UI: every string is written as an English/Russian pair next to where it is used,
/// so a translation can never go missing. English is the default unless the system prefers Russian.
enum AppLanguage: String, CaseIterable, Identifiable {
    case system, en, ru
    var id: String { rawValue }
    var title: String {
        switch self {
        case .system: return T("System", "Как в системе")
        case .en: return "English"
        case .ru: return "Русский"
        }
    }
}

enum L10n {
    static var isRussian: Bool = resolve(UserDefaults.standard.string(forKey: "language") ?? "system")

    static func resolve(_ raw: String) -> Bool {
        switch AppLanguage(rawValue: raw) ?? .system {
        case .ru: return true
        case .en: return false
        case .system:
            let pref = Locale.preferredLanguages.first?.lowercased() ?? "en"
            return pref.hasPrefix("ru")
        }
    }

    static var code: String { isRussian ? "ru" : "en" }
}

/// Localized string: T("Mixer", "Микшер").
@inline(__always)
func T(_ en: String, _ ru: String) -> String { L10n.isRussian ? ru : en }

enum Fmt {
    /// Unit symbols follow the interface language (дБ, Гц, мс, с, м, см); LUFS and dBTP stay as they are.
    enum Unit {
        static var dB: String { T("dB", "дБ") }
        static var hz: String { T("Hz", "Гц") }
        static var khz: String { T("kHz", "кГц") }
        static var ms: String { T("ms", "мс") }
        static var s: String { T("s", "с") }
        static var m: String { T("m", "м") }
        static var cm: String { T("cm", "см") }
    }

    static func db(_ v: Double, digits: Int = 1) -> String {
        if v <= -89.5 { return "−∞" }
        let s = String(format: "%+.\(digits)f", v)
        return s.replacingOccurrences(of: "-", with: "−") + " " + Unit.dB
    }
    static func dbShort(_ v: Double) -> String {
        if v <= -59.5 { return "−∞" }
        return String(format: "%+.1f", v).replacingOccurrences(of: "-", with: "−")
    }
    static func hz(_ v: Double) -> String {
        v >= 1000 ? String(format: v >= 10000 ? "%.1f " : "%.2f ", v / 1000) + Unit.khz : String(format: "%.0f ", v) + Unit.hz
    }
    static func ms(_ v: Double) -> String { String(format: v >= 100 ? "%.0f " : "%.1f ", v) + Unit.ms }
    static func sec(_ v: Double) -> String { String(format: "%.1f ", v) + Unit.s }
    static func meters(_ v: Double) -> String { String(format: "%.1f ", v) + Unit.m }
    static func metersFine(_ v: Double) -> String { String(format: "%.2f ", v) + Unit.m }
    static func cm(_ v: Double) -> String { String(format: "%.0f ", v) + Unit.cm }
    static func pct(_ v: Double) -> String { String(format: "%.0f%%", v * 100) }
    static func ratio(_ v: Double) -> String { v >= 19.5 ? "∞:1" : String(format: "%.1f:1", v) }
    static func deg(_ v: Double) -> String { String(format: "%.0f°", v) }
    static func pan(_ v: Double) -> String {
        if abs(v) < 0.02 { return "C" }
        return v < 0 ? String(format: "L%.0f", -v * 100) : String(format: "R%.0f", v * 100)
    }
    static func time(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00.0" }
        let m = Int(s) / 60
        return String(format: "%d:%04.1f", m, s - Double(m * 60))
    }
    static func clock(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let m = Int(s) / 60
        return String(format: "%d:%02d", m, Int(s) % 60)
    }
    static func lufs(_ v: Double?) -> String {
        guard let v, v.isFinite, v > -70 else { return "—" }
        return String(format: "%.1f LUFS", v).replacingOccurrences(of: "-", with: "−")
    }
    static func date(_ ts: Double) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.isRussian ? "ru_RU" : "en_US")
        f.dateStyle = .medium
        f.timeStyle = .short
        return f.string(from: Date(timeIntervalSince1970: ts))
    }
}
