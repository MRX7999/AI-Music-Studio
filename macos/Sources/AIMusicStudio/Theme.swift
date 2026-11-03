import SwiftUI
import AppKit

enum Theme {
    static let bg0 = Color(hex: "#0F1014")       // window
    static let bg1 = Color(hex: "#15171C")       // panels
    static let bg2 = Color(hex: "#1B1E25")       // cards, strips
    static let bg3 = Color(hex: "#242832")       // controls
    static let bg4 = Color(hex: "#2E3340")       // hover / pressed
    static let stroke = Color(hex: "#2A2E38")
    static let strokeStrong = Color(hex: "#3A404D")
    static let text = Color(hex: "#E7E9EE")
    static let text2 = Color(hex: "#A2A9B6")
    static let text3 = Color(hex: "#6E7584")
    static let accent = Color(hex: "#FF9F43")    // warm amber: selection, primary actions
    static let accent2 = Color(hex: "#4FD1C5")   // teal: curves, analysis
    static let blue = Color(hex: "#6CA0FF")
    static let green = Color(hex: "#4ADE80")
    static let yellow = Color(hex: "#FACC15")
    static let red = Color(hex: "#F87171")
    static let purple = Color(hex: "#B794F6")

    static let mono = Font.system(size: 11, weight: .medium, design: .monospaced)
    static let monoSmall = Font.system(size: 10, weight: .regular, design: .monospaced)
    static let label = Font.system(size: 11, weight: .medium)
    static let small = Font.system(size: 10, weight: .medium)
    static let title = Font.system(size: 13, weight: .semibold)
    static let header = Font.system(size: 11, weight: .bold)

    static func meterColor(_ db: Double) -> Color {
        if db > -1 { return red }
        if db > -9 { return yellow }
        return green
    }
}

extension Color {
    init(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("#") { s.removeFirst() }
        var v: UInt64 = 0
        Scanner(string: s).scanHexInt64(&v)
        let r, g, b: Double
        if s.count == 6 {
            r = Double((v >> 16) & 0xFF) / 255; g = Double((v >> 8) & 0xFF) / 255; b = Double(v & 0xFF) / 255
        } else {
            r = 0.8; g = 0.65; b = 0.97
        }
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1)
    }
}

struct PanelBackground: ViewModifier {
    var fill: Color = Theme.bg1
    var radius: CGFloat = 8
    func body(content: Content) -> some View {
        content
            .background(RoundedRectangle(cornerRadius: radius).fill(fill))
            .overlay(RoundedRectangle(cornerRadius: radius).stroke(Theme.stroke, lineWidth: 1))
    }
}

extension View {
    func panel(_ fill: Color = Theme.bg1, radius: CGFloat = 8) -> some View {
        modifier(PanelBackground(fill: fill, radius: radius))
    }
}

/// Flat dark button used across the app.
struct StudioButtonStyle: ButtonStyle {
    var prominent = false
    var destructive = false
    var compact = false
    func makeBody(configuration: Configuration) -> some View {
        StudioButtonBody(configuration: configuration, prominent: prominent, destructive: destructive, compact: compact)
    }
}

private struct StudioButtonBody: View {
    let configuration: ButtonStyle.Configuration
    let prominent: Bool
    let destructive: Bool
    let compact: Bool
    @Environment(\.isEnabled) private var enabled
    @State private var hover = false

    var body: some View {
        let base: Color = prominent ? Theme.accent : (destructive ? Theme.red.opacity(0.85) : Theme.bg3)
        configuration.label
            .font(.system(size: compact ? 11 : 12, weight: prominent ? .semibold : .medium))
            .foregroundColor(prominent ? Color.black.opacity(0.85) : Theme.text)
            .padding(.horizontal, compact ? 8 : 12)
            .padding(.vertical, compact ? 4 : 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(base.opacity(configuration.isPressed ? 0.75 : (hover ? 0.92 : 1)))
            )
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(prominent ? Color.clear : Theme.strokeStrong, lineWidth: 1))
            .opacity(enabled ? 1 : 0.45)
            .onHover { hover = $0 }
            .contentShape(Rectangle())
    }
}
