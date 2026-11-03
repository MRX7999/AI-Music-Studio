import SwiftUI

/// Left column: project library (generated songs, studio sessions, finished mixes) and import actions.
struct SidebarView: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Text(T("LIBRARY", "БИБЛИОТЕКА"))
                    .font(.system(size: 10, weight: .bold))
                    .tracking(0.8)
                    .foregroundColor(Theme.text2)
                Spacer()
                IconButton(icon: "arrow.clockwise", help: T("Refresh library", "Обновить библиотеку"), size: 11) {
                    Task { await store.refreshLibrary() }
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 6)

            SearchField(text: $store.librarySearch)
                .padding(.horizontal, 10)
                .padding(.bottom, 8)

            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 10) {
                    LibraryGroup(title: T("Songs", "Песни"), icon: "music.note.list", count: store.songs.count,
                                 empty: T("Generated songs appear here.", "Здесь появятся сгенерированные песни.")) {
                        ForEach(store.songs, id: \.self) { SongRow(track: $0) }
                    }
                    LibraryGroup(title: T("Sessions", "Сессии"), icon: "square.stack.3d.up", count: store.sessions.count,
                                 empty: T("Studio sessions are saved automatically.", "Сессии студии сохраняются автоматически.")) {
                        ForEach(store.sessions, id: \.self) { SessionRow(item: $0) }
                    }
                    LibraryGroup(title: T("Mixes", "Миксы"), icon: "waveform", count: store.renders.count,
                                 empty: T("Rendered mixes appear here.", "Здесь появятся готовые миксы.")) {
                        ForEach(store.renders, id: \.self) { RenderRow(item: $0) }
                    }
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 10)
            }

            Rectangle().fill(Theme.stroke).frame(height: 1)
            SidebarFooter()
        }
        .background(Theme.bg1)
    }
}

private struct SearchField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass").font(.system(size: 11)).foregroundColor(Theme.text3)
            TextField(T("Search", "Поиск"), text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 12))
                .foregroundColor(Theme.text)
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").font(.system(size: 11)).foregroundColor(Theme.text3)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 26)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.bg0))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
    }
}

private struct LibraryGroup<Content: View>: View {
    let title: String
    let icon: String
    let count: Int
    let empty: String
    @ViewBuilder var content: () -> Content
    @State private var expanded = true

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Button { withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() } } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(Theme.text3)
                        .rotationEffect(.degrees(expanded ? 90 : 0))
                    Image(systemName: icon).font(.system(size: 10)).foregroundColor(Theme.accent)
                    Text(title).font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.text2)
                    Spacer()
                    Text("\(count)").font(Theme.monoSmall).foregroundColor(Theme.text3)
                }
                .padding(.horizontal, 4)
                .padding(.vertical, 4)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if expanded {
                if count == 0 {
                    Text(empty)
                        .font(.system(size: 10))
                        .foregroundColor(Theme.text3)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 4)
                } else {
                    VStack(alignment: .leading, spacing: 1) { content() }
                }
            }
        }
    }
}

/// Row container with hover and selection highlight.
private struct LibraryRow<Content: View>: View {
    var selected = false
    let action: () -> Void
    @ViewBuilder var content: (_ hover: Bool) -> Content
    @State private var hover = false

    var body: some View {
        content(hover)
            .padding(.horizontal, 6)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 5)
                .fill(selected ? Theme.accent.opacity(0.16) : (hover ? Theme.bg3 : Color.clear)))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(selected ? Theme.accent.opacity(0.45) : Color.clear, lineWidth: 1))
            .contentShape(Rectangle())
            .onTapGesture(perform: action)
            .onHover { hover = $0 }
    }
}

private struct SongRow: View {
    @EnvironmentObject var store: StudioStore
    let track: JSONValue

    var body: some View {
        let path = track.str("path")
        let title = track.str("title", fileName(path))
        let current = store.sourceMixPath == path
        LibraryRow(selected: current, action: { Task { await store.openTrack(track) } }) { hover in
            HStack(spacing: 7) {
                ZStack {
                    RoundedRectangle(cornerRadius: 4).fill(Theme.bg3).frame(width: 26, height: 26)
                    if hover {
                        Button { store.listen(path, title: title) } label: {
                            Image(systemName: "play.fill").font(.system(size: 10)).foregroundColor(Theme.accent)
                                .frame(width: 26, height: 26)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .help(T("Listen to the original", "Слушать оригинал"))
                    } else {
                        Image(systemName: "music.note").font(.system(size: 10)).foregroundColor(Theme.accent2)
                    }
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.system(size: 12)).foregroundColor(Theme.text).lineLimit(1)
                    HStack(spacing: 4) {
                        Text(track.str("engine")).font(.system(size: 9)).foregroundColor(Theme.text3).lineLimit(1)
                        if !(track["stems"]?.object?.isEmpty ?? true) {
                            Text(T("· stems", "· стемы")).font(.system(size: 9)).foregroundColor(Theme.green.opacity(0.85))
                        }
                    }
                }
                Spacer(minLength: 0)
                if let d = track["duration"]?.double {
                    Text(Fmt.clock(d)).font(Theme.monoSmall).foregroundColor(Theme.text3)
                }
            }
        }
        .contextMenu {
            Button(T("Open in Studio", "Открыть в студии")) { Task { await store.openTrack(track) } }
            Button(T("Open with Fresh Settings", "Открыть с чистыми настройками")) { Task { await store.openTrack(track, fresh: true) } }
            Button(T("Listen to Original", "Слушать оригинал")) { store.listen(path, title: title) }
            Divider()
            Button(T("Regenerate Part…", "Перегенерировать часть…")) { store.regenerate(track) }
            Button(T("Make a Release…", "Сделать релиз…")) {
                store.mode = .release
                Task { await store.releases.create(path: path, title: title, lyrics: track.str("lyrics")) }
            }
            Divider()
            Button(T("Show in Finder", "Показать в Finder")) { store.reveal(path) }
        }
        .help(path)
    }
}

private struct SessionRow: View {
    @EnvironmentObject var store: StudioStore
    let item: JSONValue

    var body: some View {
        let path = item.str("path")
        let sceneName = store.name(in: store.scenes, item.str("scene"))
        LibraryRow(selected: store.sessionPath == path, action: { Task { await store.openSession(path) } }) { _ in
            HStack(spacing: 7) {
                ZStack {
                    RoundedRectangle(cornerRadius: 4).fill(Theme.bg3).frame(width: 26, height: 26)
                    Image(systemName: Instruments.sceneIcon(item.str("scene")))
                        .font(.system(size: 10))
                        .foregroundColor(Theme.purple)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.str("name", fileName(path))).font(.system(size: 12)).foregroundColor(Theme.text).lineLimit(1)
                    Text(T("\(sceneName) · \(Int(item.num("channels"))) ch",
                           "\(sceneName) · каналов: \(Int(item.num("channels")))"))
                        .font(.system(size: 9))
                        .foregroundColor(Theme.text3)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        }
        .contextMenu {
            Button(T("Open Session", "Открыть сессию")) { Task { await store.openSession(path) } }
            Divider()
            Button(T("Show in Finder", "Показать в Finder")) { store.reveal(path) }
        }
        .help(path)
    }
}

private struct RenderRow: View {
    @EnvironmentObject var store: StudioStore
    let item: JSONValue

    var body: some View {
        let path = item.str("path")
        let name = item.str("name", fileName(path))
        LibraryRow(action: { store.listen(path, title: name) }) { _ in
            HStack(spacing: 7) {
                RenderIcon(player: store.player, path: path)
                VStack(alignment: .leading, spacing: 1) {
                    Text(name).font(.system(size: 12)).foregroundColor(Theme.text).lineLimit(1)
                    HStack(spacing: 4) {
                        Text(item.str("format").uppercased()).font(.system(size: 9, weight: .semibold)).foregroundColor(Theme.text2)
                        Text(Fmt.lufs(item["lufs"]?.double)).font(.system(size: 9)).foregroundColor(Theme.text3)
                        if !item.str("scene").isEmpty {
                            Text("· " + item.str("scene")).font(.system(size: 9)).foregroundColor(Theme.text3).lineLimit(1)
                        }
                    }
                }
                Spacer(minLength: 0)
                if let d = item["duration_s"]?.double {
                    Text(Fmt.clock(d)).font(Theme.monoSmall).foregroundColor(Theme.text3)
                }
            }
        }
        .contextMenu {
            Button(T("Play", "Воспроизвести")) { store.listen(path, title: name) }
            Divider()
            Button(T("Show in Finder", "Показать в Finder")) { store.reveal(path) }
        }
        .help(path)
    }
}

/// Observes the player separately so only this icon redraws during playback.
private struct RenderIcon: View {
    @ObservedObject var player: AudioPlayer
    let path: String

    var body: some View {
        let playing = player.isPlaying && player.loaded?.path == path
        ZStack {
            RoundedRectangle(cornerRadius: 4).fill(playing ? Theme.green.opacity(0.2) : Theme.bg3).frame(width: 26, height: 26)
            Image(systemName: playing ? "speaker.wave.2.fill" : "waveform")
                .font(.system(size: 10))
                .foregroundColor(Theme.green)
        }
    }
}

private struct SidebarFooter: View {
    @EnvironmentObject var store: StudioStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                FooterButton(icon: "square.and.arrow.down", title: T("Import", "Импорт"),
                             help: T("Import a song: the engine splits it into stems (⌘O)", "Импорт песни: движок разделит её на стемы (⌘O)")) {
                    store.importAudio(method: store.stemMethod)
                }
                FooterButton(icon: "square.stack.3d.down.right", title: T("Stems", "Стемы"),
                             help: T("New session from a folder of stems (⇧⌘N)", "Новая сессия из папки со стемами (⇧⌘N)")) {
                    store.newSessionFromStems()
                }
                FooterButton(icon: "folder", title: T("Folder", "Папка"),
                             help: T("Choose the project folder", "Выбрать папку проекта")) {
                    store.chooseProjectRoot()
                }
            }
            Button { store.reveal(store.projectRoot.path) } label: {
                HStack(spacing: 5) {
                    Image(systemName: "externaldrive").font(.system(size: 9))
                    Text(abbreviated(store.projectRoot.path))
                        .font(.system(size: 9))
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .foregroundColor(Theme.text3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(T("Project folder — click to show in Finder", "Папка проекта — нажмите, чтобы показать в Finder"))
        }
        .padding(10)
    }

    private func abbreviated(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home) ? "~" + String(path.dropFirst(home.count)) : path
    }
}

private struct FooterButton: View {
    let icon: String
    let title: String
    let help: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: icon).font(.system(size: 13))
                Text(title).font(.system(size: 9, weight: .medium)).lineLimit(1)
            }
            .foregroundColor(hover ? Theme.text : Theme.text2)
            .frame(maxWidth: .infinity)
            .frame(height: 42)
            .background(RoundedRectangle(cornerRadius: 6).fill(hover ? Theme.bg3 : Theme.bg2))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.stroke, lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
        .onHover { hover = $0 }
    }
}
