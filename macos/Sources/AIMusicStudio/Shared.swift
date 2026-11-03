import SwiftUI
import AppKit

// MARK: - Window chrome

/// Empty area of the custom title bar: drag moves the window, double-click zooms it.
struct WindowDragArea: NSViewRepresentable {
    final class DragView: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 {
                window?.performZoom(nil)
            } else {
                window?.performDrag(with: event)
            }
        }
    }

    func makeNSView(context: Context) -> NSView { DragView() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

// MARK: - Small controls

/// Compact segmented control in the studio style.
struct Segmented<T: Hashable>: View {
    @Binding var selection: T
    let options: [(T, String)]
    var height: CGFloat = 22

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                SegmentButton(title: option.1, isOn: option.0 == selection) { selection = option.0 }
            }
        }
        .padding(2)
        .frame(height: height)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
    }
}

private struct SegmentButton: View {
    let title: String
    let isOn: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .lineLimit(1)
                .foregroundColor(isOn ? Color.black.opacity(0.85) : (hover ? Theme.text : Theme.text2))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(.horizontal, 6)
                .background(RoundedRectangle(cornerRadius: 4).fill(isOn ? Theme.accent : (hover ? Theme.bg3 : Color.clear)))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

/// Label + text field row used in the inspectors.
struct TextRow: View {
    let label: String
    @Binding var text: String
    var placeholder = ""
    var labelWidth: CGFloat = 112

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .font(Theme.label)
                .foregroundColor(Theme.text2)
                .frame(width: labelWidth, alignment: .leading)
            StudioTextField(placeholder: placeholder, text: $text)
        }
    }
}

struct StudioTextField: View {
    var placeholder = ""
    @Binding var text: String

    var body: some View {
        TextField(placeholder, text: $text)
            .textFieldStyle(.plain)
            .font(.system(size: 12))
            .foregroundColor(Theme.text)
            .padding(.horizontal, 7)
            .frame(height: 24)
            .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg0))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(Theme.stroke, lineWidth: 1))
    }
}

/// Small uppercase caption above a group of controls.
struct Caption: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .bold))
            .tracking(0.8)
            .foregroundColor(Theme.text3)
    }
}

/// Large monospaced readout (LUFS, true peak, time).
struct Readout: View {
    let label: String
    let value: String
    var color: Color = Theme.text
    var big = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Caption(text: label)
            Text(value)
                .font(.system(size: big ? 20 : 14, weight: .semibold, design: .monospaced))
                .foregroundColor(color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.black.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
    }
}

/// Indeterminate or determinate progress bar in the accent color.
struct ProgressStrip: View {
    var value: Double?
    var color: Color = Theme.accent

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.bg0)
                if let value {
                    Capsule().fill(color)
                        .frame(width: max(4, geo.size.width * CGFloat(min(max(value, 0), 1))))
                } else {
                    IndeterminateBar(color: color, width: geo.size.width)
                }
            }
        }
        .frame(height: 4)
        .clipShape(Capsule())
    }
}

private struct IndeterminateBar: View {
    let color: Color
    let width: CGFloat
    @State private var phase: CGFloat = -0.3

    var body: some View {
        Capsule().fill(color)
            .frame(width: width * 0.3)
            .offset(x: phase * width)
            .onAppear {
                withAnimation(.linear(duration: 1.1).repeatForever(autoreverses: false)) { phase = 1.0 }
            }
    }
}

// MARK: - Compressor transfer curve

/// Static input → output curve of a soft-knee compressor (−60…0 dBFS on both axes).
struct CompCurveView: View {
    var threshold: Double
    var ratio: Double
    var knee: Double
    var makeup: Double = 0
    var color: Color = Theme.accent2
    private let range = 60.0

    static func output(_ x: Double, threshold t: Double, ratio: Double, knee: Double) -> Double {
        let r = max(ratio, 1), w = max(knee, 0)
        let over = x - t
        if w > 0, abs(over) * 2 <= w {
            return x + (1 / r - 1) * pow(over + w / 2, 2) / (2 * w)
        }
        return over > 0 ? t + over / r : x
    }

    var body: some View {
        Canvas { ctx, size in
            let w = size.width, h = size.height
            func px(_ db: Double) -> CGFloat { CGFloat((db + range) / range) * w }
            func py(_ db: Double) -> CGFloat { h - CGFloat((min(max(db, -range), 6) + range) / range) * h }

            ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 6), with: .color(Color.black.opacity(0.35)))
            var grid = Path()
            for db in stride(from: -48.0, through: -12.0, by: 12.0) {
                grid.move(to: CGPoint(x: px(db), y: 0)); grid.addLine(to: CGPoint(x: px(db), y: h))
                grid.move(to: CGPoint(x: 0, y: py(db))); grid.addLine(to: CGPoint(x: w, y: py(db)))
            }
            ctx.stroke(grid, with: .color(Theme.stroke), lineWidth: 0.5)

            var unity = Path()
            unity.move(to: CGPoint(x: 0, y: h)); unity.addLine(to: CGPoint(x: w, y: 0))
            ctx.stroke(unity, with: .color(Theme.text3.opacity(0.6)), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))

            var thr = Path()
            thr.move(to: CGPoint(x: px(threshold), y: 0)); thr.addLine(to: CGPoint(x: px(threshold), y: h))
            ctx.stroke(thr, with: .color(Theme.accent.opacity(0.55)), style: StrokeStyle(lineWidth: 1, dash: [2, 3]))

            var curve = Path()
            for i in 0...120 {
                let x = -range + range * Double(i) / 120
                let y = CompCurveView.output(x, threshold: threshold, ratio: ratio, knee: knee) + makeup
                let p = CGPoint(x: px(x), y: py(y))
                if i == 0 { curve.move(to: p) } else { curve.addLine(to: p) }
            }
            ctx.stroke(curve, with: .color(color), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))

            ctx.draw(Text(T("in", "вход")).font(.system(size: 8)).foregroundColor(Theme.text3),
                     at: CGPoint(x: w - 12, y: h - 7))
            ctx.draw(Text(T("out", "выход")).font(.system(size: 8)).foregroundColor(Theme.text3),
                     at: CGPoint(x: 16, y: 8))
        }
    }
}

// MARK: - Instruments

enum Instruments {
    static func abbr(_ id: String) -> String {
        switch id {
        case "vocals": return "VOX"
        case "backing": return "BV"
        case "drums": return "DR"
        case "kick": return "KK"
        case "bass": return "BS"
        case "guitar": return "GT"
        case "acoustic": return "AG"
        case "piano": return "PN"
        case "synth": return "SY"
        case "strings": return "ST"
        case "brass": return "BR"
        case "mix": return "MIX"
        default: return "FX"
        }
    }

    static let palette = ["#FF9F43", "#F87171", "#FACC15", "#4ADE80", "#4FD1C5", "#6CA0FF", "#B794F6", "#F472B6",
                          "#A3E635", "#94A3B8"]

    static func sceneIcon(_ id: String) -> String {
        switch id {
        case "dry": return "speaker.wave.1"
        case "booth": return "mic"
        case "studio_a": return "pianokeys"
        case "live_room": return "music.mic"
        case "garage": return "car"
        case "club": return "music.note.house"
        case "concert_hall": return "theatermasks"
        case "cathedral": return "building.columns"
        case "arena": return "sportscourt"
        case "open_air": return "sun.max"
        default: return "square.dashed"
        }
    }
}

/// File name without folders, for compact display.
func fileName(_ path: String) -> String { URL(fileURLWithPath: path).lastPathComponent }
