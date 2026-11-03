import SwiftUI

/// One filter of a channel or master EQ, in the same terms as studio/dsp.py `biquad()`.
struct EQBand: Equatable {
    enum Kind { case highpass, lowpass, lowshelf, highshelf, peak }
    var kind: Kind
    var freq: Double
    var gain: Double
    var q: Double
}

enum Biquad {
    /// RBJ cookbook coefficients, identical to dsp.biquad(): (b0, b1, b2, a1, a2), normalized by a0.
    static func coefficients(_ band: EQBand, sr: Double) -> (Double, Double, Double, Double, Double) {
        let f = min(max(band.freq, 5), sr * 0.49)
        let w0 = 2 * Double.pi * f / sr
        let cw = cos(w0), sw = sin(w0)
        let q = max(band.q, 0.05)
        let alpha = sw / (2 * q)
        let A = pow(10, band.gain / 40)
        var b0 = 1.0, b1 = 0.0, b2 = 0.0, a0 = 1.0, a1 = 0.0, a2 = 0.0
        switch band.kind {
        case .peak:
            b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A
            a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A
        case .lowshelf:
            let sa = 2 * sqrt(A) * alpha
            b0 = A * ((A + 1) - (A - 1) * cw + sa)
            b1 = 2 * A * ((A - 1) - (A + 1) * cw)
            b2 = A * ((A + 1) - (A - 1) * cw - sa)
            a0 = (A + 1) + (A - 1) * cw + sa
            a1 = -2 * ((A - 1) + (A + 1) * cw)
            a2 = (A + 1) + (A - 1) * cw - sa
        case .highshelf:
            let sa = 2 * sqrt(A) * alpha
            b0 = A * ((A + 1) + (A - 1) * cw + sa)
            b1 = -2 * A * ((A - 1) + (A + 1) * cw)
            b2 = A * ((A + 1) + (A - 1) * cw - sa)
            a0 = (A + 1) - (A - 1) * cw + sa
            a1 = 2 * ((A - 1) - (A + 1) * cw)
            a2 = (A + 1) - (A - 1) * cw - sa
        case .highpass:
            b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2
            a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha
        case .lowpass:
            b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2
            a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha
        }
        return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)
    }

    /// Magnitude of the whole chain at `freq`, dB.
    static func magnitudeDB(_ bands: [EQBand], freq: Double, sr: Double) -> Double {
        let w = 2 * Double.pi * freq / sr
        let c1 = cos(w), s1 = sin(w), c2 = cos(2 * w), s2 = sin(2 * w)
        var total = 0.0
        for band in bands {
            let (b0, b1, b2, a1, a2) = coefficients(band, sr: sr)
            let nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2)
            let dr = 1 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2)
            total += 10 * log10(max(nr * nr + ni * ni, 1e-30) / max(dr * dr + di * di, 1e-30))
        }
        return total
    }

    /// Bands of a channel strip — mirrors render.channel_eq_bands().
    static func channelBands(_ ch: JSONValue) -> [EQBand] {
        var out: [EQBand] = []
        let hpf = ch.num("hpf_hz", 30), lpf = ch.num("lpf_hz", 20000)
        if hpf > 20 { out.append(EQBand(kind: .highpass, freq: hpf, gain: 0, q: 0.707)) }
        if lpf > 20 && lpf < 19000 { out.append(EQBand(kind: .lowpass, freq: lpf, gain: 0, q: 0.707)) }
        if ch.flag("eq_on", true) {
            let lo = ch.num("eq_low_db"), lm = ch.num("eq_lowmid_db"), mid = ch.num("eq_mid_db"), hi = ch.num("eq_high_db")
            if abs(lo) > 0.05 { out.append(EQBand(kind: .lowshelf, freq: ch.num("eq_low_freq", 100), gain: lo, q: 0.7)) }
            if abs(lm) > 0.05 {
                out.append(EQBand(kind: .peak, freq: ch.num("eq_lowmid_freq", 400), gain: lm, q: max(ch.num("eq_lowmid_q", 1), 0.1)))
            }
            if abs(mid) > 0.05 {
                out.append(EQBand(kind: .peak, freq: ch.num("eq_mid_freq", 1000), gain: mid, q: max(ch.num("eq_mid_q", 1), 0.1)))
            }
            if abs(hi) > 0.05 { out.append(EQBand(kind: .highshelf, freq: ch.num("eq_high_freq", 10000), gain: hi, q: 0.7)) }
        }
        return out
    }

    /// Master EQ — mirrors the master section of render.render_session().
    static func masterBands(_ rec: JSONValue) -> [EQBand] {
        guard rec.flag("master_eq_on", true) else { return [] }
        var out: [EQBand] = []
        let hpf = rec.num("master_hpf_hz", 0)
        if hpf >= 15 { out.append(EQBand(kind: .highpass, freq: hpf, gain: 0, q: 0.707)) }
        let lo = rec.num("master_low_db"), mid = rec.num("master_mid_db"), hi = rec.num("master_high_db")
        if abs(lo) > 0.05 { out.append(EQBand(kind: .lowshelf, freq: rec.num("master_low_freq", 100), gain: lo, q: 0.7)) }
        if abs(mid) > 0.05 {
            out.append(EQBand(kind: .peak, freq: rec.num("master_mid_freq", 1000), gain: mid, q: max(rec.num("master_mid_q", 0.8), 0.1)))
        }
        if abs(hi) > 0.05 { out.append(EQBand(kind: .highshelf, freq: rec.num("master_high_freq", 10000), gain: hi, q: 0.7)) }
        return out
    }
}

/// A draggable point on the EQ graph.
struct EQHandle: Identifiable {
    let id: String
    let label: String
    let color: Color
    let freq: Binding<Double>
    let gain: Binding<Double>?          // nil → filter (HPF/LPF): drag changes frequency only
    let freqRange: ClosedRange<Double>
    var gainRange: ClosedRange<Double> = -18...18
    var enabled = true
}

struct EQCurveView: View {
    let bands: [EQBand]
    let handles: [EQHandle]
    var sampleRate: Double = 48000
    var dbRange: Double = 18
    var showLabels = true
    var interactive = true

    @State private var active: String?

    private let fMin = 20.0, fMax = 20000.0

    private func x(_ f: Double, _ w: CGFloat) -> CGFloat {
        CGFloat(log(max(f, fMin) / fMin) / log(fMax / fMin)) * w
    }
    private func freq(_ x: CGFloat, _ w: CGFloat) -> Double {
        fMin * pow(fMax / fMin, Double(min(max(x / max(w, 1), 0), 1)))
    }
    private func y(_ db: Double, _ h: CGFloat) -> CGFloat {
        h / 2 - CGFloat(min(max(db, -dbRange * 1.4), dbRange * 1.4) / dbRange) * (h / 2 - 6)
    }
    private func db(_ y: CGFloat, _ h: CGFloat) -> Double {
        Double((h / 2 - y) / (h / 2 - 6)) * dbRange
    }

    private func handlePoint(_ hd: EQHandle, _ size: CGSize) -> CGPoint {
        let f = hd.freq.wrappedValue
        let g: Double
        if let gain = hd.gain { g = gain.wrappedValue } else { g = Biquad.magnitudeDB(bands, freq: f, sr: sampleRate) }
        return CGPoint(x: x(f, size.width), y: y(g, size.height))
    }

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            ZStack {
                Canvas { ctx, sz in draw(&ctx, sz) }
                if interactive {
                    ForEach(handles) { hd in
                        let p = handlePoint(hd, size)
                        ZStack {
                            Circle().fill(hd.enabled ? hd.color : Theme.text3)
                                .frame(width: active == hd.id ? 14 : 11, height: active == hd.id ? 14 : 11)
                            Circle().stroke(Color.black.opacity(0.6), lineWidth: 1)
                                .frame(width: active == hd.id ? 14 : 11, height: active == hd.id ? 14 : 11)
                            if showLabels {
                                Text(hd.label)
                                    .font(.system(size: 8, weight: .bold))
                                    .foregroundColor(Theme.text)
                                    .offset(y: -13)
                            }
                        }
                        .position(p)
                        .allowsHitTesting(false)
                    }
                }
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        guard interactive else { return }
                        if active == nil {
                            var best: (String, CGFloat)?
                            for hd in handles {
                                let p = handlePoint(hd, size)
                                let d = hypot(p.x - g.startLocation.x, p.y - g.startLocation.y)
                                if d < 18, d < (best?.1 ?? .infinity) { best = (hd.id, d) }
                            }
                            active = best?.0 ?? ""
                        }
                        guard let id = active, let hd = handles.first(where: { $0.id == id }) else { return }
                        let f = min(max(freq(g.location.x, size.width), hd.freqRange.lowerBound), hd.freqRange.upperBound)
                        let rf = f >= 1000 ? (f / 10).rounded() * 10 : f.rounded()
                        if rf != hd.freq.wrappedValue { hd.freq.wrappedValue = rf }
                        if let gain = hd.gain {
                            let v = (min(max(db(g.location.y, size.height), hd.gainRange.lowerBound), hd.gainRange.upperBound) * 10).rounded() / 10
                            if v != gain.wrappedValue { gain.wrappedValue = v }
                        }
                    }
                    .onEnded { _ in active = nil }
            )
        }
        .help(T("Drag the points: left/right = frequency, up/down = gain", "Тяните точки: влево/вправо — частота, вверх/вниз — усиление"))
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let w = size.width, h = size.height
        ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 6), with: .color(Theme.bg0))
        // grid
        for f in [50.0, 100, 200, 500, 1000, 2000, 5000, 10000] {
            let gx = x(f, w)
            ctx.stroke(Path { p in p.move(to: CGPoint(x: gx, y: 0)); p.addLine(to: CGPoint(x: gx, y: h)) },
                       with: .color(Theme.stroke), lineWidth: 1)
            if showLabels {
                let label = f >= 1000 ? "\(Int(f / 1000))k" : "\(Int(f))"
                ctx.draw(Text(label).font(.system(size: 8, design: .monospaced)).foregroundColor(Theme.text3),
                         at: CGPoint(x: gx + 2, y: h - 7), anchor: .leading)
            }
        }
        for d in stride(from: -dbRange, through: dbRange, by: dbRange / 3) {
            let gy = y(d, h)
            ctx.stroke(Path { p in p.move(to: CGPoint(x: 0, y: gy)); p.addLine(to: CGPoint(x: w, y: gy)) },
                       with: .color(abs(d) < 0.01 ? Theme.strokeStrong : Theme.stroke), lineWidth: 1)
            if showLabels && abs(d) > 0.01 {
                // the top line gets its label below it, the others above
                ctx.draw(Text(String(format: "%+.0f", d)).font(.system(size: 8, design: .monospaced)).foregroundColor(Theme.text3),
                         at: CGPoint(x: 3, y: d > dbRange - 0.01 ? gy + 7 : gy - 6), anchor: .leading)
            }
        }
        // curve
        let n = max(Int(w / 2), 60)
        var line = Path(), fill = Path()
        let zero = y(0, h)
        fill.move(to: CGPoint(x: 0, y: zero))
        for i in 0...n {
            let px = CGFloat(i) / CGFloat(n) * w
            let py = y(Biquad.magnitudeDB(bands, freq: freq(px, w), sr: sampleRate), h)
            if i == 0 { line.move(to: CGPoint(x: px, y: py)) } else { line.addLine(to: CGPoint(x: px, y: py)) }
            fill.addLine(to: CGPoint(x: px, y: py))
        }
        fill.addLine(to: CGPoint(x: w, y: zero))
        fill.closeSubpath()
        ctx.fill(fill, with: .color(Theme.accent2.opacity(0.14)))
        ctx.stroke(line, with: .color(Theme.accent2), lineWidth: 1.8)
    }
}
