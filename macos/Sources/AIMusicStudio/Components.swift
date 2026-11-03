import SwiftUI
import AppKit

// MARK: - Value mapping

struct ValueScale {
    let range: ClosedRange<Double>
    var log = false
    var step: Double? = nil

    func norm(_ v: Double) -> Double {
        let lo = range.lowerBound, hi = range.upperBound
        let c = min(max(v, lo), hi)
        guard hi > lo else { return 0 }
        if log, lo > 0 { return Foundation.log(c / lo) / Foundation.log(hi / lo) }
        return (c - lo) / (hi - lo)
    }

    func value(_ n: Double) -> Double {
        let lo = range.lowerBound, hi = range.upperBound
        let c = min(max(n, 0), 1)
        var v = (log && lo > 0) ? lo * pow(hi / lo, c) : lo + c * (hi - lo)
        if let step, step > 0 { v = (v / step).rounded() * step }
        return min(max(v, lo), hi)
    }
}

private func fineDrag() -> Double { NSEvent.modifierFlags.contains(.shift) ? 0.15 : 1.0 }

// MARK: - Knob

struct ArcShape: Shape {
    var from: Double   // 0…1 of the 270° sweep
    var to: Double
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let a0 = 135 + 270 * min(from, to), a1 = 135 + 270 * max(from, to)
        let r = min(rect.width, rect.height) / 2
        p.addArc(center: CGPoint(x: rect.midX, y: rect.midY), radius: r, startAngle: .degrees(a0),
                 endAngle: .degrees(a1), clockwise: false)
        return p
    }
}

struct Knob: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    var defaultValue: Double = 0
    var label: String = ""
    var format: (Double) -> String = { String(format: "%.1f", $0) }
    var log = false
    var step: Double? = nil
    var bipolar = false
    var color: Color = Theme.accent
    var size: CGFloat = 36
    var showValue = true
    var enabled = true
    /// Double-click action; resets to `defaultValue` when nil.
    var onReset: (() -> Void)? = nil
    /// Replaces the standard "label: value · drag…" tooltip.
    var tooltip: String? = nil

    @State private var dragStart: Double?
    @State private var hover = false

    private var scale: ValueScale { ValueScale(range: range, log: log, step: step) }

    var body: some View {
        let n = scale.norm(value)
        VStack(spacing: 2) {
            ZStack {
                Circle().fill(LinearGradient(colors: [Theme.bg4, Theme.bg2], startPoint: .top, endPoint: .bottom))
                    .padding(size * 0.14)
                    .shadow(color: .black.opacity(0.5), radius: 2, y: 1)
                ArcShape(from: 0, to: 1)
                    .stroke(Theme.bg0, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .padding(2)
                ArcShape(from: bipolar ? 0.5 : 0, to: n)
                    .stroke(enabled ? color : Theme.text3, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .padding(2)
                Capsule()
                    .fill(enabled ? Theme.text : Theme.text3)
                    .frame(width: 2, height: size * 0.22)
                    .offset(y: -size * 0.2)
                    .rotationEffect(.degrees(-135 + 270 * n))
            }
            .frame(width: size, height: size)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { g in
                        guard enabled else { return }
                        if dragStart == nil { dragStart = n }
                        let delta = Double(-g.translation.height + g.translation.width * 0.25) / 160.0 * fineDrag()
                        let nv = scale.value((dragStart ?? n) + delta)
                        if nv != value { value = nv }
                    }
                    .onEnded { _ in dragStart = nil }
            )
            .onTapGesture(count: 2) {
                guard enabled else { return }
                if let onReset { onReset() } else { value = defaultValue }
            }
            if !label.isEmpty {
                Text(label).font(.system(size: 9, weight: .semibold)).foregroundColor(Theme.text2).lineLimit(1)
                    .fixedSize()
            }
            if showValue {
                Text(format(value))
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundColor(dragStart != nil || hover ? Theme.text : Theme.text3)
                    .lineLimit(1)
                    .fixedSize()
            }
        }
        .onHover { hover = $0 }
        .help(tooltip ?? (label.isEmpty ? format(value) : "\(label): \(format(value)) · "
              + T("drag · Shift = fine · double-click = reset", "тяните · Shift = точно · двойной клик = сброс")))
    }
}

// MARK: - Sliders

struct StudioSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    var log = false
    var step: Double? = nil
    var defaultValue: Double? = nil
    var bipolar = false
    var color: Color = Theme.accent
    var enabled = true

    @State private var dragging = false

    var body: some View {
        let scale = ValueScale(range: range, log: log, step: step)
        GeometryReader { geo in
            let w = geo.size.width
            let n = scale.norm(value)
            let origin = bipolar ? 0.5 : (defaultValue.map { range.contains($0) && range.lowerBound < 0 && range.upperBound > 0 ? scale.norm(0) : 0 } ?? 0)
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.bg0).frame(height: 4)
                Capsule().fill(enabled ? color.opacity(0.9) : Theme.text3)
                    .frame(width: max(2, abs(n - origin) * w), height: 4)
                    .offset(x: min(n, origin) * w)
                Circle()
                    .fill(dragging ? Theme.text : Color(hex: "#C9CED8"))
                    .frame(width: 12, height: 12)
                    .shadow(color: .black.opacity(0.6), radius: 1.5, y: 1)
                    .offset(x: n * (w - 12))
            }
            .frame(height: geo.size.height)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        guard enabled else { return }
                        dragging = true
                        let nv = scale.value(Double((g.location.x - 6) / max(w - 12, 1)))
                        if nv != value { value = nv }
                    }
                    .onEnded { _ in dragging = false }
            )
            .simultaneousGesture(TapGesture(count: 2).onEnded { if let d = defaultValue, enabled { value = d } })
        }
        .frame(height: 16)
    }
}

/// Editable numeric readout: click to type (accepts "2.5k", "−12", "1,5").
struct ValueField: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    let format: (Double) -> String
    var enabled = true
    @State private var editing = false
    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        ZStack(alignment: .trailing) {
            if editing {
                TextField("", text: $text)
                    .textFieldStyle(.plain)
                    .font(Theme.mono)
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .onSubmit { commit() }
                    .onExitCommand { editing = false }
                    .onAppear { focused = true }
                    .onChange(of: focused) { _, f in if !f { commit() } }
            } else {
                Text(format(value))
                    .font(Theme.mono)
                    .foregroundColor(enabled ? Theme.text : Theme.text3)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
        .padding(.horizontal, 6)
        .frame(height: 20)
        .frame(maxWidth: .infinity, alignment: .trailing)
        .background(RoundedRectangle(cornerRadius: 4).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(editing ? Theme.accent : Theme.stroke, lineWidth: 1))
        .contentShape(Rectangle())
        .onTapGesture {
            guard enabled, !editing else { return }
            text = String(format: abs(value) >= 100 ? "%.0f" : "%.2f", value)
            editing = true
        }
    }

    private func commit() {
        guard editing else { return }
        editing = false
        var t = text.lowercased().replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: "−", with: "-")
        let kilo = t.contains("k") || t.contains("к")
        t = t.filter { "0123456789.-+".contains($0) }
        guard var v = Double(t) else { return }
        if kilo { v *= 1000 }
        value = min(max(v, range.lowerBound), range.upperBound)
    }
}

struct ParamRow: View {
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var log = false
    var step: Double? = nil
    var defaultValue: Double? = nil
    var bipolar = false
    var format: (Double) -> String = { String(format: "%.2f", $0) }
    var help: String? = nil
    var enabled = true
    var labelWidth: CGFloat = 112

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .font(Theme.label)
                .foregroundColor(enabled ? Theme.text2 : Theme.text3)
                .frame(width: labelWidth, alignment: .leading)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            StudioSlider(value: $value, range: range, log: log, step: step, defaultValue: defaultValue,
                         bipolar: bipolar, enabled: enabled)
            ValueField(value: $value, range: range, format: format, enabled: enabled)
                .frame(width: 78)
        }
        .help(help ?? label)
    }
}

struct ToggleRow: View {
    let label: String
    @Binding var isOn: Bool
    var help: String? = nil
    var body: some View {
        HStack {
            Text(label).font(Theme.label).foregroundColor(Theme.text2)
            Spacer()
            Toggle("", isOn: $isOn).toggleStyle(.switch).controlSize(.mini).labelsHidden()
        }
        .help(help ?? label)
    }
}

struct PickerRow<T: Hashable>: View {
    let label: String
    @Binding var selection: T
    let options: [(T, String)]
    var help: String? = nil
    var labelWidth: CGFloat = 112

    var body: some View {
        HStack(spacing: 8) {
            Text(label).font(Theme.label).foregroundColor(Theme.text2)
                .frame(width: labelWidth, alignment: .leading).lineLimit(1)
            Picker("", selection: $selection) {
                ForEach(Array(options.enumerated()), id: \.offset) { _, o in
                    Text(o.1).tag(o.0)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .controlSize(.small)
        }
        .help(help ?? label)
    }
}

// MARK: - Buttons / chips

struct Chip: View {
    let title: String
    var isOn: Bool
    var color: Color = Theme.accent
    var width: CGFloat? = nil
    var help: String = ""
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 10, weight: .bold))
                .foregroundColor(isOn ? .black.opacity(0.85) : Theme.text2)
                .frame(width: width, height: 18)
                .padding(.horizontal, width == nil ? 7 : 0)
                .background(RoundedRectangle(cornerRadius: 4).fill(isOn ? color : (hover ? Theme.bg4 : Theme.bg3)))
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(isOn ? Color.clear : Theme.strokeStrong, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help.isEmpty ? title : help)
    }
}

struct IconButton: View {
    let icon: String
    var help: String = ""
    var active = false
    var size: CGFloat = 13
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: size, weight: .medium))
                .foregroundColor(active ? Theme.accent : (hover ? Theme.text : Theme.text2))
                .frame(width: size + 15, height: size + 13)
                .background(RoundedRectangle(cornerRadius: 6).fill(hover ? Theme.bg3 : Color.clear))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help)
    }
}

// MARK: - Sections

struct SectionCard<Content: View>: View {
    let title: String
    var icon: String? = nil
    var trailing: AnyView? = nil
    var collapsible = true
    @ViewBuilder var content: () -> Content
    @State private var expanded = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                if collapsible {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundColor(Theme.text3)
                        .rotationEffect(.degrees(expanded ? 90 : 0))
                }
                if let icon {
                    Image(systemName: icon).font(.system(size: 11)).foregroundColor(Theme.accent)
                }
                Text(title.uppercased())
                    .font(.system(size: 10, weight: .bold))
                    .tracking(0.8)
                    .foregroundColor(Theme.text2)
                Spacer()
                if let trailing { trailing }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
            .onTapGesture { if collapsible { withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() } } }
            if expanded {
                VStack(alignment: .leading, spacing: 8) { content() }
                    .padding(.horizontal, 10)
                    .padding(.bottom, 10)
            }
        }
        .panel(Theme.bg2, radius: 8)
    }
}

struct InfoLine: View {
    let label: String
    let value: String
    var color: Color = Theme.text
    var body: some View {
        HStack {
            Text(label).font(Theme.label).foregroundColor(Theme.text3)
            Spacer()
            Text(value).font(Theme.mono).foregroundColor(color).lineLimit(1)
        }
    }
}

struct Badge: View {
    let text: String
    var color: Color = Theme.accent2
    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .bold))
            .foregroundColor(color)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 3).fill(color.opacity(0.15)))
    }
}

// MARK: - Meters and faders

/// dB → 0…1 for meters (−60…+6 dBFS, linear in dB).
func meterNorm(_ db: Double) -> Double { min(max((db + 60) / 66, 0), 1) }

struct LevelMeter: View {
    var peak: Double
    var rms: Double
    var hold: Double? = nil
    var width: CGFloat = 6

    var body: some View {
        Canvas { ctx, size in
            let h = size.height, w = size.width
            ctx.fill(Path(roundedRect: CGRect(x: 0, y: 0, width: w, height: h), cornerRadius: 2), with: .color(Theme.bg0))
            let grad = Gradient(stops: [
                .init(color: Theme.green, location: 0),
                .init(color: Theme.green, location: 0.70),
                .init(color: Theme.yellow, location: 0.84),
                .init(color: Theme.red, location: 0.92),
                .init(color: Theme.red, location: 1),
            ])
            let shading = GraphicsContext.Shading.linearGradient(grad, startPoint: CGPoint(x: 0, y: h), endPoint: CGPoint(x: 0, y: 0))
            let ph = h * meterNorm(peak), rh = h * meterNorm(rms)
            var dim = ctx
            dim.opacity = 0.45
            dim.fill(Path(CGRect(x: 0, y: h - ph, width: w, height: ph)), with: shading)
            ctx.fill(Path(CGRect(x: 0, y: h - rh, width: w, height: rh)), with: shading)
            if let hold, hold > -60 {
                let y = h - h * meterNorm(hold)
                ctx.fill(Path(CGRect(x: 0, y: max(0, y - 1), width: w, height: 2)), with: .color(hold > -1 ? Theme.red : Theme.text))
            }
            // segment gaps
            var y: CGFloat = 3
            while y < h {
                ctx.fill(Path(CGRect(x: 0, y: y, width: w, height: 1)), with: .color(Theme.bg0.opacity(0.7)))
                y += 3
            }
        }
        .frame(width: width)
    }
}

/// Mixer fader with a console-style law (more travel around 0 dB).
struct VerticalFader: View {
    @Binding var value: Double
    var range: ClosedRange<Double> = -60...12
    var defaultValue: Double = 0
    var color: Color = Theme.accent

    @State private var dragStart: Double?
    private static let law: [(Double, Double)] = [(-60, 0), (-40, 0.1), (-30, 0.2), (-20, 0.35), (-10, 0.55),
                                                  (-5, 0.67), (0, 0.78), (6, 0.89), (12, 1.0)]

    static func pos(_ db: Double) -> Double {
        let d = min(max(db, law.first!.0), law.last!.0)
        for i in 1..<law.count where d <= law[i].0 {
            let (a, pa) = law[i - 1], (b, pb) = law[i]
            return pa + (d - a) / (b - a) * (pb - pa)
        }
        return 1
    }

    static func db(_ pos: Double) -> Double {
        let p = min(max(pos, 0), 1)
        for i in 1..<law.count where p <= law[i].1 {
            let (a, pa) = law[i - 1], (b, pb) = law[i]
            return a + (p - pa) / (pb - pa) * (b - a)
        }
        return law.last!.0
    }

    var body: some View {
        GeometryReader { geo in
            let h = geo.size.height - 24
            let p = VerticalFader.pos(value)
            ZStack(alignment: .top) {
                // scale
                ForEach([12.0, 6, 0, -6, -12, -20, -30, -40, -60], id: \.self) { m in
                    let y = 12 + h * (1 - VerticalFader.pos(m))
                    HStack(spacing: 2) {
                        Text(m > 0 ? "+\(Int(m))" : "\(Int(m))")
                            .font(.system(size: 7, weight: .medium, design: .monospaced))
                            .foregroundColor(m == 0 ? Theme.text2 : Theme.text3)
                            .frame(width: 16, alignment: .trailing)
                        Rectangle().fill(m == 0 ? Theme.text3 : Theme.stroke).frame(width: 5, height: 1)
                        Spacer()
                    }
                    .offset(y: y - 5)
                }
                // groove
                RoundedRectangle(cornerRadius: 2)
                    .fill(Theme.bg0)
                    .frame(width: 4, height: h)
                    .offset(x: 6, y: 12)
                // cap
                ZStack {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(LinearGradient(colors: [Color(hex: "#4A505E"), Color(hex: "#2B2F39")], startPoint: .top, endPoint: .bottom))
                    Rectangle().fill(color).frame(height: 2)
                }
                .frame(width: 26, height: 22)
                .shadow(color: .black.opacity(0.6), radius: 2, y: 1)
                .offset(x: 6, y: 1 + h * (1 - p))
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { g in
                        if dragStart == nil { dragStart = p }
                        let np = (dragStart ?? p) - Double(g.translation.height / max(h, 1)) * fineDrag()
                        let v = (VerticalFader.db(np) * 10).rounded() / 10
                        if v != value { value = min(max(v, range.lowerBound), range.upperBound) }
                    }
                    .onEnded { _ in dragStart = nil }
            )
            .onTapGesture(count: 2) { value = defaultValue }
        }
        .help(T("Fader: drag · Shift = fine · double-click = 0 dB", "Фейдер: тяните · Shift = точно · двойной клик = 0 дБ"))
    }
}

// MARK: - Polar pattern

struct PolarPatternView: View {
    var a: Double            // 1 = omni, 0.5 = cardioid, 0 = figure-8
    var color: Color = Theme.accent2

    var body: some View {
        Canvas { ctx, size in
            let c = CGPoint(x: size.width / 2, y: size.height / 2)
            let r = min(size.width, size.height) / 2 - 2
            for k in [0.33, 0.66, 1.0] {
                ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r * k, y: c.y - r * k, width: 2 * r * k, height: 2 * r * k)),
                           with: .color(Theme.stroke), lineWidth: 1)
            }
            var front = Path(), back = Path()
            for i in 0...180 {
                let th = Double(i) / 180 * 2 * .pi
                let g = a + (1 - a) * cos(th)
                let pt = CGPoint(x: c.x + CGFloat(abs(g) * sin(th)) * r, y: c.y - CGFloat(abs(g) * cos(th)) * r)
                if g >= 0 {
                    if front.isEmpty { front.move(to: pt) } else { front.addLine(to: pt) }
                } else {
                    if back.isEmpty { back.move(to: pt) } else { back.addLine(to: pt) }
                }
            }
            ctx.fill(front, with: .color(color.opacity(0.18)))
            ctx.stroke(front, with: .color(color), lineWidth: 1.5)
            ctx.stroke(back, with: .color(Theme.red.opacity(0.8)), style: StrokeStyle(lineWidth: 1.2, dash: [3, 2]))
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 2, y: c.y - 2, width: 4, height: 4)), with: .color(Theme.text2))
        }
    }
}


// MARK: - Flow layout

/// Places children left to right and wraps to a new line when the row is full (tag clouds, chips).
struct FlowLayout: Layout {
    var spacing: CGFloat = 4
    var lineSpacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > maxWidth {
                y += lineHeight + lineSpacing
                x = 0
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                y += lineHeight + lineSpacing
                x = bounds.minX
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
