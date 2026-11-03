import Foundation
import AVFoundation

/// `AIMusicStudio --selftest`: drives the real Python engine through the whole workflow without UI
/// (generate → open in studio → change scene → preview → final render) and checks the Swift DSP helpers.
@MainActor
enum SelfTest {
    private static var failures = 0
    private static var passes = 0

    private static func check(_ name: String, _ ok: Bool, _ detail: @autoclosure () -> String = "") {
        if ok { passes += 1 } else { failures += 1 }
        let d = detail()
        print((ok ? "PASS " : "FAIL ") + name + (d.isEmpty ? "" : " — " + d))
        fflush(stdout)
    }

    static func run() {
        Task { @MainActor in
            let code = await runAll()
            exit(code)
        }
    }

    static func runAll() async -> Int32 {
        let t0 = Date()
        unitChecks()

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ams-selftest-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        print("project root: \(root.path)")
        L10n.isRussian = false
        let store = StudioStore(projectRoot: root)
        L10n.isRussian = false
        store.langCode = "en"
        store.liveMonitor = false

        await store.startEngine()
        check("engine starts", store.engineState.isReady,
              "\(store.engineState) python=\(store.pythonPath) \(store.pythonVersion) engine=\(store.engineDir?.path ?? "-")")
        guard store.engineState.isReady else { return finish(t0) }
        check("engine version", !store.engineVersion.isEmpty, store.engineVersion)
        check("info: scenes", store.scenes.count >= 10, "\(store.scenes.count)")
        check("info: mics", store.mics.count >= 8, "\(store.mics.count)")
        check("info: engines", store.engines.contains { $0.str("id") == "demo" }, store.engines.map { $0.str("id") }.joined(separator: ","))

        // generate
        store.selectEngine("demo")
        store.form.title = "Selftest Song"
        store.form.style = "synthwave, retro, dreamy pads"
        store.form.duration = 12
        store.form.randomSeed = false
        store.form.seed = 7
        await store.generate()
        check("generate (demo, 12 s)", store.genResults.count >= 1, store.genMessage)
        guard let track = store.genResults.first else { return finish(t0) }
        let mix = track.str("path")
        check("generated file exists", FileManager.default.fileExists(atPath: mix), mix)
        check("library lists the song", store.library.list("songs").contains { $0.str("path") == mix },
              "\(store.library.list("songs").count) song(s)")

        // studio session
        await store.openTrack(track)
        let channels = store.session?.channels.count ?? 0
        check("session opens with stems", channels >= 3, "\(channels) channels")
        await store.refreshDescribe()
        let geo = store.describe["channels"]?.object ?? [:]
        check("describe (geometry)", geo.count == channels, "\(geo.count) channel(s)")
        await store.loadWaveform()
        check("waveform", store.waveform.num("duration") > 10, "duration \(store.waveform.num("duration"))")

        await store.sessionOp("set_scene", ["scene": .s("live_room"), "keep_layout": true])
        check("scene → live_room", store.session?.str("scene") == "live_room", store.session?.str("scene") ?? "nil")

        if let id = store.channelIDs.first {
            let gain0 = store.session?.channel(id)?.num("gain_db") ?? 0
            store.setChannel(id, "gain_db", .n(-3.0))
            check("channel edit + undo stack", store.canUndo && store.session?.channel(id)?.num("gain_db") == -3.0)
            store.undo()
            check("undo restores value", store.session?.channel(id)?.num("gain_db") == gain0)
            check("undo keeps the earlier scene change", store.session?.str("scene") == "live_room",
                  store.session?.str("scene") ?? "nil")
            // a knob drag (many values of one channel in a row) is a single undo step
            let fader = store.chNum(id, "gain_db")
            let f0 = fader.wrappedValue
            for v in stride(from: -1.0, through: -6.0, by: -1.0) { fader.wrappedValue = v }
            store.undo()
            check("drag = one undo step", abs(fader.wrappedValue - f0) < 1e-9, "fader \(fader.wrappedValue) dB")
            store.redo()
            check("redo", abs(fader.wrappedValue + 6.0) < 1e-9)
            store.undo()
        }

        // preview
        store.previewLength = 10
        store.setLoopStart(1)
        await store.renderPreview(autoplay: false)
        let loaded = store.player.loaded?.path ?? ""
        check("preview renders", !loaded.isEmpty && FileManager.default.fileExists(atPath: loaded), loaded)
        check("preview length", abs(store.player.bufferDuration - 10) < 0.6, "\(store.player.bufferDuration) s")
        check("preview report has meters", store.previewReport["meters"]?["master"] != nil)
        check("preview loudness", store.previewLufs != nil, Fmt.lufs(store.previewLufs))
        store.meterSnapshotTime = 4
        let m = store.meter(channel: store.channelIDs.first, at: 4)
        check("channel meter snapshot", m.0 > -90 && m.0 <= 6, "peak \(m.0) rms \(m.1)")

        // final render
        await store.renderFinal()
        let out = store.lastRender.str("path")
        check("final render", !out.isEmpty && FileManager.default.fileExists(atPath: out), out)
        if !out.isEmpty, let f = try? AVAudioFile(forReading: URL(fileURLWithPath: out)) {
            let dur = Double(f.length) / f.processingFormat.sampleRate
            check("final render duration", abs(dur - 12) < 1.5, String(format: "%.2f s", dur))
        }
        let lufs = store.lastRender["report"]?["master"]?["lufs_after"]?.double
        check("final loudness near target", lufs.map { abs($0 - (store.session?["recording"]?.num("target_lufs", -14) ?? -14)) < 2.5 } ?? false,
              Fmt.lufs(lufs))

        await store.saveSession()
        check("session saved", store.sessionPath.map { FileManager.default.fileExists(atPath: $0) } ?? false, store.sessionPath ?? "nil")
        await store.refreshLibrary()
        check("library lists session and mix", !store.library.list("sessions").isEmpty && !store.library.list("renders").isEmpty,
              "\(store.library.list("sessions").count) session(s), \(store.library.list("renders").count) mix(es)")

        await v12Checks(store, root: root, mix: mix)

        // localisation round trip: engine texts and default channel names follow the language
        func cyrillic(_ t: String) -> Bool { t.unicodeScalars.contains { $0.value >= 0x0400 && $0.value <= 0x04FF } }
        let enNames = store.session?.channels.map { $0.str("name") } ?? []
        let staleBefore = store.previewStale
        L10n.isRussian = true
        store.langCode = "ru"
        await store.reloadLocalized()
        let ruScene = store.scene("live_room")?.str("name") ?? ""
        check("engine texts in Russian", cyrillic(ruScene), ruScene)
        let ruNames = store.session?.channels.map { $0.str("name") } ?? []
        check("channel names follow the language", !ruNames.isEmpty && ruNames.allSatisfy(cyrillic)
              && store.previewStale == staleBefore, ruNames.joined(separator: ", "))
        L10n.isRussian = false
        store.langCode = "en"
        await store.reloadLocalized()
        let backNames = store.session?.channels.map { $0.str("name") } ?? []
        check("channel names switch back", backNames == enNames, backNames.joined(separator: ", "))

        store.engine.stop()
        try? FileManager.default.removeItem(at: root)
        return finish(t0)
    }

    /// v1.2: tools doctor, release pipeline (built-in backends), publish guard, splice, LRC, recorder helpers.
    private static func v12Checks(_ store: StudioStore, root: URL, mix: String) async {
        let eng = store.engine
        check("mode: release", AppMode.allCases.contains(.release))
        let doc = try? await eng.call("tools.doctor")
        check("tools.doctor", doc?["features"]?["superres"] != nil && doc?["detectors"]?["fakeprint"]?.bool == true,
              doc?["features"]?.object?.keys.sorted().joined(separator: ",") ?? "nil")

        let lp = try? await eng.call("lyrics.parse", ["lrc": "[00:01.00]hello\n[00:03.50]world"])
        check("lyrics.parse (LRC)", lp?.list("lines").count == 2 && abs((lp?["lines"]?[1]?.num("start") ?? 0) - 3.5) < 1e-6)

        let spliced = root.appendingPathComponent("splice-test.wav").path
        let sp = try? await eng.call("edit.splice", ["original": .s(mix), "edited": .s(mix), "out": .s(spliced),
                                                     "start": 3, "end": 6, "xfade": 0.2])
        check("edit.splice", FileManager.default.fileExists(atPath: spliced) && sp?.num("shift_samples", 99) == 0,
              sp.map { "shift \($0.num("shift_samples"))" } ?? "nil")

        do {
            let r = try await eng.call("release.create", ["root": .s(root.path), "source": .s(mix), "title": "Selftest Release",
                                                           "artist": "AMS", "lyrics": "[Verse]\nhello", "meta": [:]])
            let id = r.str("id")
            check("release.create", !id.isEmpty, id)
            let s = try await eng.call("release.step", ["root": .s(root.path), "id": .s(id), "step": "superres",
                                                         "options": ["backend": "builtin", "force": true, "export_sr": 48000]])
            check("release: bandwidth (built-in extension)", s["superres"]?.str("backend") == "builtin"
                  && FileManager.default.fileExists(atPath: s.str("master")), s["superres"]?.str("skipped") ?? "")
            let m = try await eng.call("release.step", ["root": .s(root.path), "id": .s(id), "step": "refmaster",
                                                         "options": ["backend": "builtin", "reference": .s(mix)]])
            let rm = m["meta"]?["refmaster"]
            check("release: reference master (built-in)", m.str("master").hasSuffix("master_ref.wav")
                  && rm?.list("eq_db").isEmpty == false && (rm?.num("true_peak_db", 0) ?? 0) <= -0.9
                  && abs((rm?.num("lufs_after") ?? 0) - (rm?.num("reference_lufs") ?? 99)) < 1.5,
                  rm.map { String(format: "%.1f LUFS, peak %.2f dBTP", $0.num("lufs_after"), $0.num("true_peak_db")) } ?? "nil")
            let c = try await eng.call("release.step", ["root": .s(root.path), "id": .s(id), "step": "cover",
                                                         "options": ["backend": "builtin"]])
            check("release: cover (built-in)", FileManager.default.fileExists(atPath: c.str("cover")), c.str("cover"))
            let d = try await eng.call("release.step", ["root": .s(root.path), "id": .s(id), "step": "detect",
                                                         "options": ["detectors": ["fakeprint"]]])
            let score = d["ai_report"]?["results"]?["fakeprint"]?["score"]?.double
            check("release: AI check (fakeprint)", score != nil, score.map { String(format: "score %.3f", $0) } ?? d.str("ai_report"))
            let pk = try await eng.call("release.step", ["root": .s(root.path), "id": .s(id), "step": "package"])
            let folder = pk["meta"]?["package"]?.str("folder") ?? ""
            check("release: distributor package", !folder.isEmpty && FileManager.default.fileExists(
                atPath: URL(fileURLWithPath: folder).appendingPathComponent("metadata.json").path), folder)
            var refused = false
            do {
                _ = try await eng.call("publish.submit", ["root": .s(root.path), "id": .s(id), "services": ["package"]])
            } catch { refused = true }
            check("publish.submit needs confirmation", refused)
        } catch {
            check("release pipeline", false, error.localizedDescription)
        }

        // tool settings payload
        var ts = ToolSettings()
        ts.tools["flashsr"] = ToolOverride(path: "~/bin/speech", template: "", enabled: false)
        ts.backends["superres"] = "builtin"
        let pl = ts.payload
        check("tool settings payload", pl["tools"]?["flashsr"]?["enabled"]?.bool == false
              && pl["tools"]?["flashsr"]?.str("path").hasPrefix("/") == true && pl["backends"]?.str("superres") == "builtin")

        // recorder: host-time trimming, latency padding, count-in
        recorderChecks(root)
    }

    private static func recorderChecks(_ root: URL) {
        let sr = 48000.0
        let raw = root.appendingPathComponent("raw-take.wav")
        let w = TakeWriter()
        let t0 = mach_absolute_time()
        let start = t0 + AVAudioTime.hostTime(forSeconds: 0.05)        // downbeat 50 ms into the first buffer
        guard let fmt = AVAudioFormat(standardFormatWithSampleRate: sr, channels: 2),
              (try? w.arm(url: raw, sampleRate: sr, channel: 1, startHost: start)) != nil else {
            check("recorder: writer arms", false); return
        }
        let n = 4800
        for b in 0..<10 {
            guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(n)) else { continue }
            buf.frameLength = AVAudioFrameCount(n)
            for i in 0..<n {
                buf.floatChannelData![0][i] = 0.1
                buf.floatChannelData![1][i] = Float(b * n + i) / 1_000_000      // channel 2 = frame index ramp
            }
            let host = t0 + AVAudioTime.hostTime(forSeconds: Double(b * n) / sr)
            w.process(buf, AVAudioTime(hostTime: host))
        }
        let frames = w.disarm()
        check("recorder: starts at the downbeat", abs(Int(frames) - (10 * n - 2400)) <= 1, "\(frames) frames")
        if let f = try? AVAudioFile(forReading: raw), let b = AVAudioPCMBuffer(pcmFormat: f.processingFormat, frameCapacity: 8) {
            try? f.read(into: b, frameCount: 8)
            let first = Double(b.floatChannelData![0][0]) * 1_000_000
            check("recorder: picks input channel 2, mono", f.processingFormat.channelCount == 1 && abs(first - 2400) <= 1.5,
                  String(format: "first sample = frame %.0f", first))
        }
        let padded = root.appendingPathComponent("take-padded.wav")
        let d1 = (try? Recorder.finalizeTake(raw: raw, dst: padded, padSeconds: 0.5)) ?? 0
        check("recorder: pads to the song position", abs(d1 - (Double(frames) / sr + 0.5)) < 1e-3, String(format: "%.3f s", d1))
        let trimmed = root.appendingPathComponent("take-trimmed.wav")
        let d2 = (try? Recorder.finalizeTake(raw: raw, dst: trimmed, padSeconds: -0.1)) ?? 0
        check("recorder: latency trim from the head", abs(d2 - (Double(frames) / sr - 0.1)) < 1e-3, String(format: "%.3f s", d2))
        let click = Recorder.clickBuffer(beats: 4, beat: 0.5)
        check("recorder: count-in clicks", click.map { Int($0.frameLength) == 4 * 24000 } ?? false)
        check("recorder: input devices enumerate", true, "\(AudioDevices.inputs().count) input device(s)")
    }

    private static func finish(_ t0: Date) -> Int32 {
        print(String(format: "\n%d passed, %d failed in %.1f s", passes, failures, Date().timeIntervalSince(t0)))
        print(failures == 0 ? "SELFTEST OK" : "SELFTEST FAILED")
        fflush(stdout)
        return failures == 0 ? 0 : 1
    }

    /// Pure Swift checks: biquad curves, fader law, JSON round trip.
    private static func unitChecks() {
        let sr = 48000.0
        let peak = Biquad.magnitudeDB([EQBand(kind: .peak, freq: 1000, gain: 6, q: 1)], freq: 1000, sr: sr)
        check("biquad peak gain", abs(peak - 6) < 0.05, String(format: "%.3f dB", peak))
        let hp = Biquad.magnitudeDB([EQBand(kind: .highpass, freq: 100, gain: 0, q: 0.7071)], freq: 100, sr: sr)
        check("biquad HPF −3 dB at cutoff", abs(hp + 3.01) < 0.1, String(format: "%.3f dB", hp))
        let shelf = Biquad.magnitudeDB([EQBand(kind: .highshelf, freq: 8000, gain: 4, q: 0.7071)], freq: 20000, sr: sr)
        check("biquad high shelf plateau", abs(shelf - 4) < 0.5, String(format: "%.3f dB", shelf))

        var worst = 0.0
        for db in stride(from: -60.0, through: 12.0, by: 0.5) {
            worst = max(worst, abs(VerticalFader.db(VerticalFader.pos(db)) - db))
        }
        check("fader law round trip", worst < 1e-9, "max error \(worst)")

        let v: JSONValue = ["a": 1, "b": [true, nil, "x", 2.5], "c": ["d": "е"]]
        let back = (try? v.data()).flatMap { try? JSONValue.parse($0) }
        check("JSON round trip", back == v)
        check("JSON bool stays bool", back?["b"]?[0] == .bool(true))
    }
}
