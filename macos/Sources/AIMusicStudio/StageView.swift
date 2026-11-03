import SwiftUI

/// Stage mode: scene presets, the top-down room plan with draggable musicians and listener.
struct StageView: View {
    @EnvironmentObject var store: StudioStore
    @State private var fitRoom = false

    var body: some View {
        if store.session == nil {
            EmptySessionView()
        } else {
            VStack(spacing: 10) {
                SceneStrip()
                StageToolbar(fitRoom: $fitRoom)
                StagePlan(fitRoom: fitRoom)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                SceneInfoBar()
            }
            .padding(12)
        }
    }
}

// MARK: - Scene presets

struct SceneStrip: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let current = store.session?.str("scene") ?? ""
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(store.scenes.map { $0.str("id") }, id: \.self) { id in
                    if let sc = store.scene(id) {
                        SceneCard(scene: sc, selected: id == current) { store.setScene(id) }
                    }
                }
            }
            .padding(.vertical, 1)
        }
        .frame(height: 74)
    }
}

private struct SceneCard: View {
    let scene: JSONValue
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: Instruments.sceneIcon(scene.str("id")))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(selected ? Theme.accent : Theme.text2)
                    Text(SceneCard.title(scene.str("name")))
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Theme.text)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }
                Text(subtitle)
                    .font(Theme.monoSmall)
                    .foregroundColor(Theme.text3)
                    .lineLimit(1)
                Text(scene.str("description"))
                    .font(.system(size: 9))
                    .foregroundColor(Theme.text3)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            .padding(8)
            .frame(width: 168, height: 70, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: 8).fill(selected ? Theme.bg3 : (hover ? Theme.bg2.opacity(0.9) : Theme.bg2)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Theme.accent : Theme.stroke, lineWidth: selected ? 1.5 : 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(scene.str("name") + "\n" + scene.str("description"))
    }

    /// Card title: the name without its explanatory tail ("Studio A — medium room" → "Studio A",
    /// "Garage / rehearsal space" → "Garage");
    /// the full name is in the tooltip and in the stage header.
    static func title(_ name: String) -> String {
        var t = name
        for sep in [" — ", " (", ", ", " / "] {
            if let r = t.range(of: sep), r.lowerBound > t.startIndex { t = String(t[..<r.lowerBound]) }
        }
        return t
    }

    private var subtitle: String {
        let rt = scene.num("rt60")
        let size = String(format: "%.0f×%.0f ", scene.num("width"), scene.num("depth")) + Fmt.Unit.m
        return rt > 0 ? "RT60 " + Fmt.sec(rt) + " · " + size : T("anechoic", "без эха") + " · " + size
    }
}

// MARK: - Toolbar and info

private struct StageToolbar: View {
    @EnvironmentObject var store: StudioStore
    @Binding var fitRoom: Bool

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                Text(store.sessionTitle)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(Theme.text)
                    .lineLimit(1)
                Text(store.describe["scene"]?.str("name") ?? store.name(in: store.scenes, store.session?.str("scene") ?? ""))
                    .font(Theme.small)
                    .foregroundColor(Theme.text3)
            }
            Spacer()
            IconButton(icon: fitRoom ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right",
                       help: fitRoom ? T("Zoom to the stage", "Приблизить к сцене") : T("Show the whole room", "Показать всю комнату"),
                       active: fitRoom) { fitRoom.toggle() }
            Button { store.resetLayout() } label: {
                Label(T("Reset layout", "Сбросить расстановку"), systemImage: "arrow.counterclockwise")
            }
            .buttonStyle(StudioButtonStyle(compact: true))
            .help(T("Put every musician back to the default stage position", "Вернуть всех музыкантов на позиции по умолчанию"))
            Button { store.resetListener() } label: {
                Label(T("Reset listener", "Сбросить слушателя"), systemImage: "headphones")
            }
            .buttonStyle(StudioButtonStyle(compact: true))
            Button { store.addChannels() } label: {
                Label(T("Add tracks…", "Добавить дорожки…"), systemImage: "plus")
            }
            .buttonStyle(StudioButtonStyle(compact: true))
        }
    }
}

private struct SceneInfoBar: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let room = store.describe["room"]
        let size = store.roomSize
        let tech = store.session?["recording"]?.str("room_technique") ?? ""
        HStack(spacing: 8) {
            InfoChip(icon: "cube", label: T("Room", "Комната"),
                     value: String(format: "%.1f × %.1f × %.1f ", size.0, size.1, size.2) + Fmt.Unit.m)
            InfoChip(icon: "waveform.path.ecg", label: "RT60", value: Fmt.sec(room?.num("rt60") ?? 0))
            InfoChip(icon: "circle.dashed", label: T("Critical distance", "Критическое расстояние"),
                     value: Fmt.meters(store.describe.num("critical_distance_m")))
            InfoChip(icon: "ruler", label: T("Reference", "Опорное"), value: Fmt.meters(store.describe.num("ref_distance_m")))
            InfoChip(icon: "mic.and.signal.meter", label: T("Room pair", "Пара комнатных"),
                     value: store.name(in: store.techniques, tech))
            Spacer(minLength: 0)
        }
    }
}

private struct InfoChip: View {
    let icon: String
    let label: String
    let value: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 10)).foregroundColor(Theme.accent2)
            VStack(alignment: .leading, spacing: 0) {
                Text(label).font(.system(size: 9, weight: .medium)).foregroundColor(Theme.text3).lineLimit(1)
                Text(value).font(Theme.mono).foregroundColor(Theme.text).lineLimit(1)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .panel(Theme.bg2, radius: 6)
    }
}

// MARK: - Plan geometry

struct PlanViewport: Equatable {
    var x0: Double, y0: Double, x1: Double, y1: Double
}

struct PlanLayout {
    let vp: PlanViewport
    let scale: CGFloat
    let origin: CGPoint

    init(size: CGSize, vp: PlanViewport, pad: CGFloat = 30) {
        self.vp = vp
        let vw = max(vp.x1 - vp.x0, 0.5), vh = max(vp.y1 - vp.y0, 0.5)
        let s = min((size.width - 2 * pad) / CGFloat(vw), (size.height - 2 * pad) / CGFloat(vh))
        scale = max(s, 0.5)
        origin = CGPoint(x: (size.width - CGFloat(vw) * scale) / 2, y: (size.height - CGFloat(vh) * scale) / 2)
    }

    func point(_ x: Double, _ y: Double) -> CGPoint {
        CGPoint(x: origin.x + CGFloat(x - vp.x0) * scale, y: origin.y + CGFloat(y - vp.y0) * scale)
    }

    func meters(_ p: CGPoint) -> (Double, Double) {
        (vp.x0 + Double((p.x - origin.x) / scale), vp.y0 + Double((p.y - origin.y) / scale))
    }

    func rect(_ x0: Double, _ y0: Double, _ x1: Double, _ y1: Double) -> CGRect {
        let a = point(x0, y0), b = point(x1, y1)
        return CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y))
    }

    var gridStep: Double {
        for s in [0.25, 0.5, 1, 2, 5, 10, 20, 50] where CGFloat(s) * scale >= 26 { return s }
        return 100
    }
}

/// Everything the plan Canvas draws, computed once per body evaluation.
private struct PlanDrawing {
    struct Line { let x: Double; let y: Double; let color: Color; let beyond: Bool; let selected: Bool; let distance: Double }
    struct Mic { let x: Double; let y: Double; let axis: Double }

    let layout: PlanLayout
    let roomW: Double, roomD: Double
    let stage: [Double]
    let listener: (Double, Double)
    let critical: Double
    let pair: [Mic]
    let lines: [Line]
    let stageLabel: String
    let criticalLabel: String

    func draw(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let L = layout
        let room = L.rect(0, 0, roomW, roomD)

        // floor
        ctx.fill(Path(roundedRect: room, cornerRadius: 3), with: .linearGradient(
            Gradient(colors: [Color(hex: "#1C1F27"), Color(hex: "#171A21")]),
            startPoint: CGPoint(x: room.minX, y: room.minY), endPoint: CGPoint(x: room.maxX, y: room.maxY)))

        // grid inside the room
        var g = ctx
        g.clip(to: Path(room))
        let step = L.gridStep
        var minor = Path(), major = Path()
        var i = 0
        var x = 0.0
        while x <= roomW + 1e-6 {
            let px = L.point(x, 0).x
            var p = (i % 5 == 0) ? major : minor
            p.move(to: CGPoint(x: px, y: room.minY)); p.addLine(to: CGPoint(x: px, y: room.maxY))
            if i % 5 == 0 { major = p } else { minor = p }
            x += step; i += 1
        }
        i = 0
        var y = 0.0
        while y <= roomD + 1e-6 {
            let py = L.point(0, y).y
            var p = (i % 5 == 0) ? major : minor
            p.move(to: CGPoint(x: room.minX, y: py)); p.addLine(to: CGPoint(x: room.maxX, y: py))
            if i % 5 == 0 { major = p } else { minor = p }
            y += step; i += 1
        }
        g.stroke(minor, with: .color(Color.white.opacity(0.035)), lineWidth: 0.5)
        g.stroke(major, with: .color(Color.white.opacity(0.08)), lineWidth: 0.8)

        // walls
        ctx.stroke(Path(roundedRect: room, cornerRadius: 3), with: .color(Theme.strokeStrong), lineWidth: 2)

        // stage
        if stage.count == 4 {
            let sr = L.rect(stage[0], stage[1], stage[2], stage[3])
            ctx.fill(Path(roundedRect: sr, cornerRadius: 6), with: .color(Theme.accent.opacity(0.06)))
            ctx.stroke(Path(roundedRect: sr, cornerRadius: 6), with: .color(Theme.accent.opacity(0.45)),
                       style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
            ctx.draw(Text(stageLabel).font(.system(size: 9, weight: .bold)).foregroundColor(Theme.accent.opacity(0.7)),
                     at: CGPoint(x: sr.minX + 6, y: sr.minY + 8), anchor: .leading)
        }

        // critical distance around the listener
        let lp = L.point(listener.0, listener.1)
        if critical > 0 {
            let r = CGFloat(critical) * L.scale
            let circle = Path(ellipseIn: CGRect(x: lp.x - r, y: lp.y - r, width: 2 * r, height: 2 * r))
            ctx.fill(circle, with: .color(Theme.accent2.opacity(0.04)))
            ctx.stroke(circle, with: .color(Theme.accent2.opacity(0.5)), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            ctx.draw(Text(criticalLabel).font(.system(size: 9)).foregroundColor(Theme.accent2.opacity(0.8)),
                     at: CGPoint(x: lp.x, y: lp.y - r - 7))
        }

        // direct paths musician → listener
        for ln in lines {
            let p = L.point(ln.x, ln.y)
            var path = Path()
            path.move(to: p); path.addLine(to: lp)
            let style = ln.beyond ? StrokeStyle(lineWidth: ln.selected ? 1.6 : 1, dash: [3, 4])
                                  : StrokeStyle(lineWidth: ln.selected ? 1.8 : 1)
            ctx.stroke(path, with: .color(ln.color.opacity(ln.selected ? 0.8 : 0.32)), style: style)
            if ln.selected {
                let mid = CGPoint(x: (p.x + lp.x) / 2, y: (p.y + lp.y) / 2)
                let label = Text(Fmt.meters(ln.distance)).font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundColor(Theme.text)
                let bg = CGRect(x: mid.x - 24, y: mid.y - 9, width: 48, height: 18)
                ctx.fill(Path(roundedRect: bg, cornerRadius: 4), with: .color(Color.black.opacity(0.65)))
                ctx.draw(label, at: mid)
            }
        }

        // room microphones
        for m in pair {
            let p = L.point(m.x, m.y)
            let a = m.axis * .pi / 180
            var tick = Path()
            tick.move(to: p); tick.addLine(to: CGPoint(x: p.x + CGFloat(sin(a)) * 11, y: p.y - CGFloat(cos(a)) * 11))
            ctx.stroke(tick, with: .color(Theme.accent2), lineWidth: 1.5)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 3.5, y: p.y - 3.5, width: 7, height: 7)), with: .color(Theme.accent2))
        }

        // dimensions
        let top = L.point(roomW / 2, 0), left = L.point(0, roomD / 2)
        if top.y > 14 {
            ctx.draw(Text(Fmt.meters(roomW)).font(Theme.monoSmall).foregroundColor(Theme.text3),
                     at: CGPoint(x: top.x, y: top.y - 9))
        }
        if left.x > 14 {
            // depth runs vertically: the label is rotated along the left wall
            var side = ctx
            side.translateBy(x: left.x - 9, y: left.y)
            side.rotate(by: .degrees(-90))
            side.draw(Text(Fmt.meters(roomD)).font(Theme.monoSmall).foregroundColor(Theme.text3), at: .zero)
        }

        // scale bar
        let barW = CGFloat(step) * L.scale
        let base = CGPoint(x: 14, y: size.height - 14)
        var bar = Path()
        bar.move(to: CGPoint(x: base.x, y: base.y - 4)); bar.addLine(to: base)
        bar.addLine(to: CGPoint(x: base.x + barW, y: base.y)); bar.addLine(to: CGPoint(x: base.x + barW, y: base.y - 4))
        ctx.stroke(bar, with: .color(Theme.text2), lineWidth: 1)
        let stepText = String(format: step < 1 ? "%.2g " : "%.0f ", step) + Fmt.Unit.m
        ctx.draw(Text(stepText).font(Theme.monoSmall).foregroundColor(Theme.text2),
                 at: CGPoint(x: base.x + barW + 6, y: base.y - 3), anchor: .leading)

        // how to use the plan, bottom right
        ctx.draw(Text(T("Drag musicians and the headphones · double-click the headphones to reset",
                        "Перетаскивайте музыкантов и наушники · двойной клик по наушникам — сброс"))
                    .font(.system(size: 10)).foregroundColor(Theme.text3),
                 at: CGPoint(x: size.width - 14, y: base.y - 3), anchor: .trailing)
    }
}

// MARK: - Plan view

struct StagePlan: View {
    @EnvironmentObject var store: StudioStore
    var fitRoom: Bool
    @State private var frozen: PlanViewport?

    var body: some View {
        GeometryReader { geo in
            let vp = frozen ?? viewport()
            let layout = PlanLayout(size: geo.size, vp: vp)
            let drawing = makeDrawing(layout)
            ZStack(alignment: .topLeading) {
                Canvas { ctx, size in drawing.draw(&ctx, size) }
                    .contentShape(Rectangle())
                    .onTapGesture { store.selectedChannel = nil }
                ForEach(store.channelIDs, id: \.self) { id in
                    if let ch = store.session?.channel(id) {
                        MusicianDot(channel: ch, selected: store.selectedChannel == id, dimmed: isDimmed(ch),
                                    center: layout.point(ch.num("x"), ch.num("y")),
                                    onSelect: { store.selectedChannel = id },
                                    onDrag: { p in
                                        if frozen == nil { frozen = vp }
                                        let m = layout.meters(p)
                                        store.move(id, x: (m.0 * 20).rounded() / 20, y: (m.1 * 20).rounded() / 20)
                                    },
                                    onEnd: { frozen = nil })
                    }
                }
                ListenerGlyph(center: layout.point(listener.0, listener.1),
                              onDrag: { p in
                                  if frozen == nil { frozen = vp }
                                  let m = layout.meters(p)
                                  store.move(nil, x: (m.0 * 20).rounded() / 20, y: (m.1 * 20).rounded() / 20)
                              },
                              onEnd: { frozen = nil },
                              onReset: { store.resetListener() })
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .coordinateSpace(name: "plan")
            .clipped()
        }
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.stroke, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var listener: (Double, Double) { store.listenerPosition }

    private func isDimmed(_ ch: JSONValue) -> Bool {
        if ch.flag("mute") { return true }
        let anySolo = store.session?.channels.contains { $0.flag("solo") } ?? false
        return anySolo && !ch.flag("solo")
    }

    /// Visible part of the room in meters: the whole room, or the stage + listener region in big rooms.
    private func viewport() -> PlanViewport {
        let (w, d, _) = store.roomSize
        let full = PlanViewport(x0: 0, y0: 0, x1: w, y1: d)
        if fitRoom { return full }
        var xs: [Double] = [], ys: [Double] = []
        let st = store.describe["room"]?["stage"]?.doubles ?? []
        if st.count == 4 { xs += [st[0], st[2]]; ys += [st[1], st[3]] }
        let l = listener
        xs.append(l.0); ys.append(l.1)
        for ch in store.session?.channels ?? [] { xs.append(ch.num("x")); ys.append(ch.num("y")) }
        guard let x0 = xs.min(), let x1 = xs.max(), let y0 = ys.min(), let y1 = ys.max() else { return full }
        let pad = max(1.2, 0.15 * max(x1 - x0, y1 - y0))
        let vp = PlanViewport(x0: max(0, x0 - pad), y0: max(0, y0 - pad), x1: min(w, x1 + pad), y1: min(d, y1 + pad))
        if (vp.x1 - vp.x0) * (vp.y1 - vp.y0) > 0.55 * w * d { return full }
        return vp
    }

    private func makeDrawing(_ layout: PlanLayout) -> PlanDrawing {
        let (w, d, _) = store.roomSize
        let chans = store.describe["channels"]
        let lines: [PlanDrawing.Line] = (store.session?.channels ?? []).map { ch in
            let id = ch.str("id")
            let info = chans?[id]
            return PlanDrawing.Line(x: ch.num("x"), y: ch.num("y"), color: store.color(of: ch),
                                    beyond: info?.flag("beyond_critical") ?? false,
                                    selected: store.selectedChannel == id,
                                    distance: info?.num("distance_m") ?? 0)
        }
        let pair = store.describe.list("pair").map { PlanDrawing.Mic(x: $0.num("x"), y: $0.num("y"), axis: $0.num("axis_deg")) }
        let crit = store.describe.num("critical_distance_m")
        return PlanDrawing(layout: layout, roomW: w, roomD: d, stage: store.describe["room"]?["stage"]?.doubles ?? [],
                           listener: listener, critical: crit, pair: pair, lines: lines,
                           stageLabel: T("STAGE", "СЦЕНА"),
                           criticalLabel: T("critical distance ", "критическое расстояние ") + Fmt.meters(crit))
    }
}

/// A musician on the plan: colored disc with the instrument abbreviation and the channel name.
private struct MusicianDot: View {
    let channel: JSONValue
    let selected: Bool
    let dimmed: Bool
    let center: CGPoint
    let onSelect: () -> Void
    let onDrag: (CGPoint) -> Void
    let onEnd: () -> Void
    @State private var grab: CGSize?
    @State private var hover = false

    var body: some View {
        let color = Color(hex: channel.str("color", "#cba6f7"))
        ZStack {
            Circle().fill(color.opacity(dimmed ? 0.28 : 0.92))
            Circle().stroke(selected ? Color.white : Color.black.opacity(0.45), lineWidth: selected ? 2.5 : 1)
            Text(Instruments.abbr(channel.str("instrument")))
                .font(.system(size: 10, weight: .heavy))
                .foregroundColor(Color.black.opacity(dimmed ? 0.5 : 0.82))
        }
        .frame(width: 36, height: 36)
        .shadow(color: color.opacity(selected ? 0.75 : 0.3), radius: selected ? 10 : 4)
        .scaleEffect(hover && !selected ? 1.06 : 1)
        .overlay(alignment: .topTrailing) { flags }
        .overlay(alignment: .top) {
            Text(channel.str("name"))
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(dimmed ? Theme.text3 : Theme.text)
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(Capsule().fill(Color.black.opacity(0.6)))
                .offset(y: 40)
        }
        .contentShape(Circle())
        .onHover { hover = $0 }
        .onTapGesture { onSelect() }
        .gesture(
            DragGesture(minimumDistance: 1, coordinateSpace: .named("plan"))
                .onChanged { g in
                    if grab == nil {
                        grab = CGSize(width: center.x - g.startLocation.x, height: center.y - g.startLocation.y)
                        onSelect()
                    }
                    let o = grab ?? .zero
                    onDrag(CGPoint(x: g.location.x + o.width, y: g.location.y + o.height))
                }
                .onEnded { _ in
                    grab = nil
                    onEnd()
                }
        )
        .help(channel.str("name") + " — " + T("drag to move, click to edit", "перетащите, чтобы переместить; клик — настройки"))
        .position(center)
    }

    @ViewBuilder private var flags: some View {
        HStack(spacing: 1) {
            if channel.flag("solo") { flag("S", Theme.yellow) }
            if channel.flag("mute") { flag("M", Theme.red) }
        }
        .offset(x: 6, y: -4)
    }

    private func flag(_ t: String, _ c: Color) -> some View {
        Text(t)
            .font(.system(size: 8, weight: .heavy))
            .foregroundColor(.black)
            .frame(width: 12, height: 12)
            .background(RoundedRectangle(cornerRadius: 3).fill(c))
    }
}

/// The listener (and the room microphone pair): drag to move, double-click to reset.
private struct ListenerGlyph: View {
    let center: CGPoint
    let onDrag: (CGPoint) -> Void
    let onEnd: () -> Void
    let onReset: () -> Void
    @State private var grab: CGSize?

    var body: some View {
        ZStack {
            Circle().fill(Theme.bg3)
            Circle().stroke(Theme.accent2, lineWidth: 1.5)
            Image(systemName: "headphones")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(Theme.accent2)
        }
        .frame(width: 32, height: 32)
        .shadow(color: Theme.accent2.opacity(0.35), radius: 6)
        .overlay(alignment: .top) {
            Text(T("Listener", "Слушатель"))
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(Theme.accent2)
                .fixedSize()
                .offset(y: 36)
        }
        .contentShape(Circle())
        .onTapGesture(count: 2) { onReset() }
        .gesture(
            DragGesture(minimumDistance: 1, coordinateSpace: .named("plan"))
                .onChanged { g in
                    if grab == nil { grab = CGSize(width: center.x - g.startLocation.x, height: center.y - g.startLocation.y) }
                    let o = grab ?? .zero
                    onDrag(CGPoint(x: g.location.x + o.width, y: g.location.y + o.height))
                }
                .onEnded { _ in
                    grab = nil
                    onEnd()
                }
        )
        .help(T("Listener and room microphones — drag to move, double-click to reset",
                "Слушатель и комнатные микрофоны — перетащите; двойной клик — сброс"))
        .position(center)
    }
}

// MARK: - Empty state

struct EmptySessionView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "music.mic")
                .font(.system(size: 44, weight: .light))
                .foregroundColor(Theme.accent)
            VStack(spacing: 6) {
                Text(T("No session open", "Сессия не открыта"))
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(Theme.text)
                Text(T("Generate a song or import audio. The studio splits it into stems, puts the musicians on a stage and lets you record them in a virtual room.",
                       "Сгенерируйте песню или импортируйте аудио. Студия разделит его на стемы, расставит музыкантов на сцене и даст «записать» их в виртуальной комнате."))
                    .font(.system(size: 12))
                    .foregroundColor(Theme.text2)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 460)
            }
            HStack(spacing: 10) {
                Button { store.mode = .generate } label: {
                    Label(T("Generate a song", "Сгенерировать песню"), systemImage: "wand.and.stars")
                }
                .buttonStyle(StudioButtonStyle(prominent: true))
                Button { store.importAudio(method: store.stemMethod) } label: {
                    Label(T("Import audio…", "Импорт аудио…"), systemImage: "square.and.arrow.down")
                }
                .buttonStyle(StudioButtonStyle())
                Button { store.newSessionFromStems() } label: {
                    Label(T("Session from stems…", "Сессия из стемов…"), systemImage: "square.stack.3d.up")
                }
                .buttonStyle(StudioButtonStyle())
            }
            .disabled(!store.engineState.isReady)
            RecentSongs()
                .frame(maxWidth: 520)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct RecentSongs: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        let songs = Array(store.library.list("songs").prefix(5))
        if !songs.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Caption(text: T("Recent songs", "Недавние песни"))
                ForEach(songs, id: \.self) { song in
                    HStack(spacing: 8) {
                        Image(systemName: "music.note").foregroundColor(Theme.accent2).font(.system(size: 11))
                        Text(song.str("title")).font(.system(size: 12)).foregroundColor(Theme.text).lineLimit(1)
                        Spacer()
                        Text(Fmt.clock(song.num("duration"))).font(Theme.monoSmall).foregroundColor(Theme.text3)
                        Button(T("Open", "Открыть")) { Task { await store.openTrack(song) } }
                            .buttonStyle(StudioButtonStyle(compact: true))
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .panel(Theme.bg2, radius: 6)
                }
            }
        }
    }
}
