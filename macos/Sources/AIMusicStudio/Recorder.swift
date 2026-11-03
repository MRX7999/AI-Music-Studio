import SwiftUI
import AppKit
import AVFoundation
import AudioToolbox
import CoreAudio
import Accelerate

// MARK: - CoreAudio input devices

struct InputDevice: Identifiable, Hashable {
    let id: AudioDeviceID
    let name: String
    let channels: Int
}

enum AudioDevices {
    private static func address(_ sel: AudioObjectPropertySelector,
                                _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }

    static func inputs() -> [InputDevice] {
        var addr = address(kAudioHardwarePropertyDevices)
        var size: UInt32 = 0
        let sys = AudioObjectID(kAudioObjectSystemObject)
        guard AudioObjectGetPropertyDataSize(sys, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
        var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(sys, &addr, 0, nil, &size, &ids) == noErr else { return [] }
        return ids.compactMap { id in
            let ch = inputChannels(id)
            return ch > 0 ? InputDevice(id: id, name: name(id), channels: ch) : nil
        }
    }

    static func defaultInput() -> AudioDeviceID? {
        var addr = address(kAudioHardwarePropertyDefaultInputDevice)
        var id = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &id) == noErr,
              id != 0 else { return nil }
        return id
    }

    static func inputChannels(_ id: AudioDeviceID) -> Int {
        var addr = address(kAudioDevicePropertyStreamConfiguration, kAudioDevicePropertyScopeInput)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
        let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
        return list.reduce(0) { $0 + Int($1.mNumberChannels) }
    }

    static func name(_ id: AudioDeviceID) -> String {
        var addr = address(kAudioObjectPropertyName)
        var size = UInt32(MemoryLayout<CFString?>.size)
        var value: Unmanaged<CFString>?
        let st = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(id, &addr, 0, nil, &size, $0) }
        guard st == noErr, let v = value else { return "Input \(id)" }
        return v.takeRetainedValue() as String
    }
}

// MARK: - Take writer (runs on the input tap thread)

/// Writes input buffers from an exact host time on, so the take starts with the backing track.
final class TakeWriter: @unchecked Sendable {
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var outFormat: AVAudioFormat?
    private var startHost: UInt64 = 0
    private var channel = 0                      // input channel index, -1 = stereo (1+2)
    private var written: AVAudioFramePosition = 0
    private var peak: Float = 0
    private var rmsAcc: Float = 0
    private var clip = false

    var frames: AVAudioFramePosition { lock.lock(); defer { lock.unlock() }; return written }
    var isArmed: Bool { lock.lock(); defer { lock.unlock() }; return file != nil }

    func arm(url: URL, sampleRate: Double, channel: Int, startHost: UInt64) throws {
        let ch: AVAudioChannelCount = channel < 0 ? 2 : 1
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: sampleRate, AVNumberOfChannelsKey: ch,
            AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let f = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        lock.lock()
        file = f
        outFormat = f.processingFormat
        self.channel = channel
        self.startHost = startHost
        written = 0
        lock.unlock()
    }

    /// Closes the file; returns the number of frames written.
    @discardableResult
    func disarm() -> AVAudioFramePosition {
        lock.lock()
        defer { lock.unlock() }
        file = nil                                   // AVAudioFile closes on release
        outFormat = nil
        return written
    }

    /// (peak dBFS, rms dBFS, clipped) since the last call.
    func takeMeter() -> (Double, Double, Bool) {
        lock.lock()
        let p = peak, r = rmsAcc, c = clip
        peak = 0; rmsAcc = 0; clip = false
        lock.unlock()
        func db(_ x: Float) -> Double { x > 1e-6 ? 20 * log10(Double(x)) : -90 }
        return (db(p), db(r), c)
    }

    func process(_ buf: AVAudioPCMBuffer, _ when: AVAudioTime) {
        guard let data = buf.floatChannelData, buf.frameLength > 0 else { return }
        let n = Int(buf.frameLength)
        let chs = Int(buf.format.channelCount)
        lock.lock()
        defer { lock.unlock() }
        let src = channel < 0 ? 0 : min(channel, chs - 1)
        var m: Float = 0, r: Float = 0
        vDSP_maxmgv(data[src], 1, &m, vDSP_Length(n))
        vDSP_rmsqv(data[src], 1, &r, vDSP_Length(n))
        if channel < 0, chs > 1 {
            var m2: Float = 0
            vDSP_maxmgv(data[1], 1, &m2, vDSP_Length(n))
            m = max(m, m2)
        }
        peak = max(peak, m)
        rmsAcc = max(rmsAcc, r)
        if m >= 0.999 { clip = true }

        guard let file, let fmt = outFormat else { return }
        var skip = 0
        if written == 0 {
            guard when.isHostTimeValid else { return }
            let sr = buf.format.sampleRate
            let bufStart = AVAudioTime.seconds(forHostTime: when.hostTime)
            let start = AVAudioTime.seconds(forHostTime: startHost)
            if bufStart + Double(n) / sr <= start { return }       // still before the downbeat
            skip = max(0, Int(((start - bufStart) * sr).rounded()))
        }
        let count = n - skip
        guard count > 0, let out = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(count)),
              let dst = out.floatChannelData else { return }
        out.frameLength = AVAudioFrameCount(count)
        if fmt.channelCount == 2 {
            let right = chs > 1 ? 1 : 0
            memcpy(dst[0], data[0] + skip, count * MemoryLayout<Float>.size)
            memcpy(dst[1], data[right] + skip, count * MemoryLayout<Float>.size)
        } else {
            memcpy(dst[0], data[src] + skip, count * MemoryLayout<Float>.size)
        }
        do {
            try file.write(from: out)
            written += AVAudioFramePosition(count)
        } catch {
            NSLog("AIMusicStudio: take write failed: \(error)")
        }
    }
}

// MARK: - Recorder

@MainActor
final class Recorder: ObservableObject {
    enum State: Equatable { case idle, countIn, recording, processing }

    struct Take: Identifiable, Equatable {
        let id = UUID()
        let path: String
        var name: String
        let duration: Double
        var inSession: Bool
        var rvcPath: String?
    }

    unowned let studio: StudioStore

    @Published var permission: AVAuthorizationStatus = AVCaptureDevice.authorizationStatus(for: .audio)
    @Published var devices: [InputDevice] = []
    @Published var deviceID: AudioDeviceID = 0
    @Published var inputChannel = 0
    @Published var level: (peak: Double, rms: Double) = (-90, -90)
    @Published var peakHold: Double = -90
    @Published var clipped = false
    @Published var state: State = .idle
    @Published var elapsed: Double = 0
    @Published var engineRunning = false
    @Published var status = ""
    @Published var latencyMs: Double = 0
    @Published var sampleRate: Double = 0
    @Published var monitorAvailable = true
    @Published var takes: [Take] = []
    @Published var takeName = ""
    @Published var startAt: Double = 0

    // Persisted settings (UserDefaults "rec.*").
    @Published var monitor: Bool { didSet { save("monitor", monitor); applyGains() } }
    @Published var monitorGain: Double { didSet { save("monitorGain", monitorGain); applyGains() } }
    @Published var backing: Bool { didSet { save("backing", backing) } }
    @Published var backingGain: Double { didSet { save("backingGain", backingGain); applyGains() } }
    @Published var countInBars: Int { didSet { save("countInBars", countInBars) } }
    @Published var bpm: Double { didSet { save("bpm", bpm) } }
    @Published var clickGain: Double { didSet { save("clickGain", clickGain); applyGains() } }
    @Published var offsetMs: Double { didSet { save("offsetMs", offsetMs) } }
    @Published var rvcEnabled: Bool { didSet { save("rvc", rvcEnabled) } }
    @Published var rvcModel: String { didSet { save("rvcModel", rvcModel) } }
    @Published var rvcIndex: String { didSet { save("rvcIndex", rvcIndex) } }
    @Published var rvcPitch: Double { didSet { save("rvcPitch", rvcPitch) } }
    @Published var rvcF0: String { didSet { save("rvcF0", rvcF0) } }

    private var engine: AVAudioEngine?
    private var monitorMixer: AVAudioMixerNode?
    private var backingNode: AVAudioPlayerNode?
    private var clickNode: AVAudioPlayerNode?
    private var backingFile: AVAudioFile?
    private let writer = TakeWriter()
    private var meterTimer: Timer?
    private var downbeatHost: UInt64 = 0
    private var rawURL: URL?
    private var recStartPos: Double = 0
    private var deviceObserver: NSObjectProtocol?

    init(studio: StudioStore) {
        self.studio = studio
        let d = UserDefaults.standard
        func v<T>(_ k: String, _ fallback: T) -> T { d.object(forKey: "rec." + k) as? T ?? fallback }
        monitor = v("monitor", false)
        monitorGain = v("monitorGain", 0.8)
        backing = v("backing", true)
        backingGain = v("backingGain", 0.8)
        countInBars = v("countInBars", 1)
        bpm = v("bpm", 120.0)
        clickGain = v("clickGain", 0.5)
        offsetMs = v("offsetMs", 0.0)
        rvcEnabled = v("rvc", false)
        rvcModel = v("rvcModel", "")
        rvcIndex = v("rvcIndex", "")
        rvcPitch = v("rvcPitch", 0.0)
        rvcF0 = v("rvcF0", "rmvpe")
    }

    private func save(_ key: String, _ value: Any) { UserDefaults.standard.set(value, forKey: "rec." + key) }

    // MARK: lifecycle

    func open() async {
        permission = AVCaptureDevice.authorizationStatus(for: .audio)
        if permission == .notDetermined {
            let ok = await AVCaptureDevice.requestAccess(for: .audio)
            permission = ok ? .authorized : .denied
        }
        refreshDevices()
        if let b = studio.session?["meta"]?["bpm"]?.double, b > 30 { bpm = b }
        startAt = studio.loopStart
        if permission == .authorized { start() }
    }

    func close() {
        if state == .recording || state == .countIn { stop(save: false) }
        teardown()
    }

    func refreshDevices() {
        devices = AudioDevices.inputs()
        if deviceID == 0 || !devices.contains(where: { $0.id == deviceID }) {
            deviceID = AudioDevices.defaultInput() ?? devices.first?.id ?? 0
        }
        let chs = devices.first(where: { $0.id == deviceID })?.channels ?? 1
        if inputChannel >= chs { inputChannel = 0 }
    }

    func selectDevice(_ id: AudioDeviceID) {
        guard id != deviceID || !engineRunning else { return }
        deviceID = id
        inputChannel = 0
        if permission == .authorized { start() }
    }

    var currentChannels: Int { devices.first(where: { $0.id == deviceID })?.channels ?? 1 }

    private func teardown() {
        meterTimer?.invalidate()
        meterTimer = nil
        if let e = engine {
            e.inputNode.removeTap(onBus: 0)
            e.stop()
        }
        engine = nil
        monitorMixer = nil
        backingNode = nil
        clickNode = nil
        backingFile = nil
        engineRunning = false
    }

    /// Builds the graph: input → monitor mixer (muted unless monitoring), backing player, click player.
    func start() {
        teardown()
        let e = AVAudioEngine()
        let input = e.inputNode
        if deviceID != 0, let au = input.audioUnit {
            var id = deviceID
            let st = AudioUnitSetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &id,
                                          UInt32(MemoryLayout<AudioDeviceID>.size))
            if st != noErr { status = T("Could not select the input (\(st)), using the default", "Не удалось выбрать вход (\(st)), беру системный") }
        }
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0, fmt.channelCount > 0 else {
            status = T("The input has no audio channels", "У входа нет аудиоканалов")
            return
        }
        sampleRate = fmt.sampleRate
        let mon = AVAudioMixerNode()
        let back = AVAudioPlayerNode()
        let click = AVAudioPlayerNode()
        e.attach(mon); e.attach(back); e.attach(click)
        e.connect(mon, to: e.mainMixerNode, format: nil)
        if let src = studio.sourceMixPath, let f = try? AVAudioFile(forReading: URL(fileURLWithPath: src)) {
            backingFile = f
            e.connect(back, to: e.mainMixerNode, format: f.processingFormat)
        } else {
            e.connect(back, to: e.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 2))
        }
        e.connect(click, to: e.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1))
        e.connect(input, to: mon, format: fmt)
        let w = writer
        input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { buf, when in w.process(buf, when) }
        monitorMixer = mon; backingNode = back; clickNode = click
        engine = e
        applyGains()
        e.prepare()
        do {
            try e.start()
            monitorAvailable = true
        } catch {
            // Different input and output devices at different rates: keep recording, drop live monitoring.
            input.removeTap(onBus: 0)
            e.disconnectNodeInput(mon)
            input.installTap(onBus: 0, bufferSize: 1024, format: fmt) { buf, when in w.process(buf, when) }
            do {
                try e.start()
                monitorAvailable = false
                status = T("Monitoring is off: the input and output run at different sample rates",
                           "Мониторинг выключен: вход и выход работают на разных частотах")
            } catch {
                status = T("Audio input failed: \(error.localizedDescription)", "Не удалось запустить вход: \(error.localizedDescription)")
                teardown()
                return
            }
        }
        engineRunning = true
        latencyMs = (input.presentationLatency + e.outputNode.presentationLatency) * 1000
        meterTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    private func applyGains() {
        monitorMixer?.outputVolume = monitor && monitorAvailable ? Float(monitorGain) : 0
        backingNode?.volume = Float(backingGain)
        clickNode?.volume = Float(clickGain)
    }

    private func tick() {
        let (p, r, c) = writer.takeMeter()
        let fall = 24.0 / 30
        level = (max(p, level.peak - fall), max(r, level.rms - fall))
        if p > peakHold { peakHold = p }
        if c { clipped = true }
        switch state {
        case .countIn:
            if mach_absolute_time() >= downbeatHost { state = .recording }
        case .recording:
            elapsed = Double(writer.frames) / max(sampleRate, 1)
        default: break
        }
    }

    func resetPeak() {
        peakHold = -90
        clipped = false
    }

    // MARK: record

    var takesFolder: URL {
        let base: URL
        if let sp = studio.sessionPath {
            base = URL(fileURLWithPath: sp).deletingLastPathComponent()
        } else {
            base = studio.projectRoot.appendingPathComponent("takes-unsaved")
        }
        return base.appendingPathComponent("takes")
    }

    func record() async {
        guard engineRunning, let e = engine, state == .idle else { return }
        if studio.sessionPath == nil { await studio.saveSession() }
        studio.player.pause()
        let folder = takesFolder
        do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) } catch {
            studio.fail(error); return
        }
        let raw = folder.appendingPathComponent(".raw-\(UUID().uuidString.prefix(8)).wav")
        let beat = 60.0 / max(bpm, 30)
        let countIn = Double(countInBars * 4) * beat
        let lead = 0.2
        let now = mach_absolute_time()
        let clickHost = now + AVAudioTime.hostTime(forSeconds: lead)
        downbeatHost = now + AVAudioTime.hostTime(forSeconds: lead + countIn)
        recStartPos = max(0, startAt)
        do {
            try writer.arm(url: raw, sampleRate: sampleRate, channel: inputChannel >= currentChannels ? 0 : inputChannel,
                           startHost: downbeatHost)
        } catch { studio.fail(error); return }
        rawURL = raw
        schedulePlayback(clickHost: clickHost, beat: beat)
        latencyMs = (e.inputNode.presentationLatency + e.outputNode.presentationLatency) * 1000
        elapsed = 0
        state = countIn > 0 ? .countIn : .recording
        status = ""
    }

    /// Count-in clicks and the backing track, both locked to host time (synchronous on purpose).
    private func schedulePlayback(clickHost: UInt64, beat: Double) {
        if countInBars > 0, let click = clickNode, let buf = Recorder.clickBuffer(beats: countInBars * 4, beat: beat) {
            click.stop()
            click.scheduleBuffer(buf, at: nil, options: [], completionHandler: nil)
            click.play(at: AVAudioTime(hostTime: clickHost))
        }
        if backing, let f = backingFile, let node = backingNode {
            let sr = f.processingFormat.sampleRate
            let first = AVAudioFramePosition(recStartPos * sr)
            if first < f.length {
                node.stop()
                node.scheduleSegment(f, startingFrame: first, frameCount: AVAudioFrameCount(f.length - first), at: nil,
                                     completionHandler: nil)
                node.play(at: AVAudioTime(hostTime: downbeatHost))
            }
        }
    }

    func stop(save: Bool = true) {
        guard state == .recording || state == .countIn else { return }
        let frames = writer.disarm()
        backingNode?.stop()
        clickNode?.stop()
        guard let raw = rawURL else { state = .idle; return }
        rawURL = nil
        guard save, frames > Int64(sampleRate * 0.3) else {
            try? FileManager.default.removeItem(at: raw)
            state = .idle
            if save { status = T("The take was too short and was discarded", "Дубль слишком короткий, удалён") }
            return
        }
        state = .processing
        let pad = recStartPos - (latencyMs + offsetMs) / 1000
        let dst = nextTakeURL()
        let name = takeName.isEmpty ? dst.deletingPathExtension().lastPathComponent : takeName
        Task {
            do {
                let dur = try await Task.detached(priority: .userInitiated) {
                    try Recorder.finalizeTake(raw: raw, dst: dst, padSeconds: pad)
                }.value
                try? FileManager.default.removeItem(at: raw)
                var take = Take(path: dst.path, name: name, duration: dur, inSession: false, rvcPath: nil)
                takes.insert(take, at: 0)
                if rvcEnabled, !rvcModel.isEmpty {
                    if let out = await convert(take) { take.rvcPath = out }
                }
                await addToSession(take, useRVC: take.rvcPath != nil)
                takeName = ""
            } catch {
                studio.fail(error)
            }
            state = .idle
        }
    }

    private func nextTakeURL() -> URL {
        let fm = FileManager.default
        var i = 1
        while fm.fileExists(atPath: takesFolder.appendingPathComponent("vocals-take-\(i).wav").path) { i += 1 }
        return takesFolder.appendingPathComponent("vocals-take-\(i).wav")
    }

    // MARK: session / RVC

    func addToSession(_ take: Take, useRVC: Bool) async {
        let path = useRVC ? (take.rvcPath ?? take.path) : take.path
        let name = useRVC ? "\(take.name) (RVC)" : take.name
        await studio.sessionOp("add_channel", ["source": .s(path), "name": .s(name), "instrument": "vocals"])
        if let i = takes.firstIndex(where: { $0.id == take.id }) { takes[i].inSession = true }
        studio.show(T("Added to the session: \(name)", "Добавлено в сессию: \(name)"))
    }

    /// Runs the take through RVC; returns the converted file.
    func convert(_ take: Take) async -> String? {
        guard !rvcModel.isEmpty else {
            status = T("Choose an RVC model (.pth) first", "Сначала выберите модель RVC (.pth)")
            return nil
        }
        status = T("RVC: converting…", "RVC: конвертирую…")
        let out = URL(fileURLWithPath: take.path).deletingPathExtension().path + " — RVC.wav"
        var p: [String: JSONValue] = ["path": .s(take.path), "out": .s(out), "model": .s(rvcModel),
                                      "pitch": .n(Int(rvcPitch)), "f0": .s(rvcF0), "_group": "rvc"]
        if !rvcIndex.isEmpty { p["index"] = .s(rvcIndex) }
        do {
            let r = try await studio.engine.call("voice.convert", p) { [weak self] _, m in
                if !m.isEmpty { self?.status = m }
            }
            let path = r.str("output", out)
            if let i = takes.firstIndex(where: { $0.id == take.id }) { takes[i].rvcPath = path }
            status = T("RVC done", "RVC готово")
            return path
        } catch {
            status = error.localizedDescription
            return nil
        }
    }

    func chooseFile(index: Bool) {
        let p = NSOpenPanel()
        p.allowsOtherFileTypes = true
        p.message = index ? T("Choose the RVC .index file", "Выберите файл .index для RVC")
                          : T("Choose the RVC voice model (.pth)", "Выберите голосовую модель RVC (.pth)")
        guard p.runModal() == .OK, let u = p.url else { return }
        if index { rvcIndex = u.path } else { rvcModel = u.path }
    }

    func discard(_ take: Take) {
        try? FileManager.default.removeItem(atPath: take.path)
        if let r = take.rvcPath { try? FileManager.default.removeItem(atPath: r) }
        takes.removeAll { $0.id == take.id }
    }

    // MARK: offline helpers (also used by the self-test)

    /// Writes `dst` = `padSeconds` of silence + raw take (or the raw take minus -padSeconds when negative).
    /// Returns the duration of the result in seconds.
    nonisolated static func finalizeTake(raw: URL, dst: URL, padSeconds: Double) throws -> Double {
        let src = try AVAudioFile(forReading: raw, commonFormat: .pcmFormatFloat32, interleaved: false)
        let fmt = src.processingFormat
        let sr = fmt.sampleRate
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: sr, AVNumberOfChannelsKey: fmt.channelCount,
            AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        try? FileManager.default.removeItem(at: dst)
        let out = try AVAudioFile(forWriting: dst, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        let chunk: AVAudioFrameCount = 65536
        guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: chunk) else { throw CocoaError(.fileWriteUnknown) }
        var padFrames = AVAudioFramePosition((max(0, padSeconds) * sr).rounded())
        while padFrames > 0 {
            let n = AVAudioFrameCount(min(AVAudioFramePosition(chunk), padFrames))
            buf.frameLength = n
            for c in 0..<Int(fmt.channelCount) { memset(buf.floatChannelData![c], 0, Int(n) * MemoryLayout<Float>.size) }
            try out.write(from: buf)
            padFrames -= AVAudioFramePosition(n)
        }
        let trim = AVAudioFramePosition((max(0, -padSeconds) * sr).rounded())
        if trim >= src.length { return Double(out.length) / sr }
        src.framePosition = trim
        while src.framePosition < src.length {
            try src.read(into: buf, frameCount: chunk)
            if buf.frameLength == 0 { break }
            try out.write(from: buf)
        }
        return Double(out.length) / sr
    }

    /// Count-in: short decaying sine blips, accented downbeat (48 kHz mono).
    nonisolated static func clickBuffer(beats: Int, beat: Double) -> AVAudioPCMBuffer? {
        let sr = 48000.0
        let beatFrames = Int(beat * sr)
        guard beats > 0, beatFrames > 0,
              let fmt = AVAudioFormat(standardFormatWithSampleRate: sr, channels: 1),
              let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(beats * beatFrames)),
              let d = buf.floatChannelData?[0] else { return nil }
        buf.frameLength = AVAudioFrameCount(beats * beatFrames)
        memset(d, 0, beats * beatFrames * MemoryLayout<Float>.size)
        let len = min(Int(0.035 * sr), beatFrames)
        for b in 0..<beats {
            let f = b % 4 == 0 ? 1760.0 : 1175.0
            let amp: Float = b % 4 == 0 ? 0.9 : 0.6
            for i in 0..<len {
                let t = Double(i) / sr
                d[b * beatFrames + i] = amp * Float(sin(2 * .pi * f * t) * exp(-t * 90))
            }
        }
        return buf
    }
}

// MARK: - Record sheet

struct RecordView: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rec: Recorder

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if rec.permission != .authorized {
                permissionBox
            } else {
                HStack(alignment: .top, spacing: 14) {
                    inputColumn.frame(width: 300)
                    takeColumn.frame(maxWidth: .infinity)
                }
                transport
                takesList
            }
            HStack {
                Text(rec.status).font(.system(size: 10)).foregroundColor(Theme.text2).lineLimit(2)
                Spacer()
                Button(T("Close", "Закрыть")) {
                    rec.close()
                    store.showRecorder = false
                }
                .buttonStyle(StudioButtonStyle())
                .keyboardShortcut(.cancelAction)
                .disabled(rec.state == .processing)
            }
        }
        .padding(18)
        .frame(width: 800)
        .background(Theme.bg1)
        .preferredColorScheme(.dark)
        .task { await rec.open() }
        .onDisappear { rec.close() }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "mic.fill").foregroundColor(Theme.red)
            Text(T("Record Vocals", "Запись вокала")).font(Theme.title).foregroundColor(Theme.text)
            Text("· \(store.sessionTitle)").font(.system(size: 12)).foregroundColor(Theme.text3).lineLimit(1)
            Spacer()
            if rec.engineRunning {
                Badge(text: "\(Int(rec.sampleRate)) Hz · \(T("latency", "задержка")) \(Int(rec.latencyMs.rounded())) ms",
                      color: Theme.blue)
            }
        }
    }

    private var permissionBox: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(T("AI Music Studio needs access to the microphone to record takes.",
                   "AI Music Studio нужен доступ к микрофону, чтобы записывать дубли."))
                .font(.system(size: 12)).foregroundColor(Theme.text)
            Text(T("Allow it in System Settings → Privacy & Security → Microphone, then reopen this window.",
                   "Разрешите в Системных настройках → Конфиденциальность и безопасность → Микрофон и откройте окно снова."))
                .font(.system(size: 11)).foregroundColor(Theme.text2)
            Button(T("Open Privacy Settings", "Открыть настройки конфиденциальности")) {
                if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
                    NSWorkspace.shared.open(u)
                }
            }
            .buttonStyle(StudioButtonStyle(prominent: true))
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.bg2))
    }

    private var inputColumn: some View {
        SectionCard(title: T("Input", "Вход"), icon: "mic", collapsible: false) {
            VStack(alignment: .leading, spacing: 8) {
                PickerRow(label: T("Device", "Устройство"),
                          selection: Binding(get: { rec.deviceID }, set: { rec.selectDevice($0) }),
                          options: rec.devices.map { ($0.id, "\($0.name) (\($0.channels))") }, labelWidth: 80)
                PickerRow(label: T("Channel", "Канал"), selection: $rec.inputChannel,
                          options: (0..<max(1, rec.currentChannels)).map { ($0, "\(T("Input", "Вход")) \($0 + 1)") }
                              + (rec.currentChannels > 1 ? [(-1, T("Stereo 1+2", "Стерео 1+2"))] : []),
                          labelWidth: 80)
                HStack(alignment: .bottom, spacing: 10) {
                    LevelMeter(peak: rec.level.peak, rms: rec.level.rms, hold: rec.peakHold, width: 16)
                        .frame(width: 16, height: 110)
                    VStack(alignment: .leading, spacing: 6) {
                        Readout(label: T("Peak", "Пик"), value: rec.peakHold > -89 ? String(format: "%.1f dB", rec.peakHold) : "—",
                                color: rec.clipped ? Theme.red : Theme.text)
                        if rec.clipped {
                            Text(T("CLIP — lower the input gain", "ПЕРЕГРУЗ — уменьшите усиление входа"))
                                .font(.system(size: 9, weight: .bold)).foregroundColor(Theme.red)
                        } else {
                            Text(T("Aim for peaks around −10…−6 dB", "Цельтесь в пики около −10…−6 дБ"))
                                .font(.system(size: 9)).foregroundColor(Theme.text3)
                        }
                        Button(T("Reset Peak", "Сбросить пик")) { rec.resetPeak() }.buttonStyle(StudioButtonStyle(compact: true))
                    }
                    Spacer()
                }
                ToggleRow(label: T("Monitor input in headphones", "Слышать себя в наушниках"), isOn: $rec.monitor,
                          help: T("Use headphones: with speakers the backing leaks into the mic.",
                                  "Используйте наушники: с колонками фонограмма попадёт в микрофон."))
                    .disabled(!rec.monitorAvailable)
                if rec.monitor {
                    ParamRow(label: T("Monitor", "Мониторинг"), value: $rec.monitorGain, range: 0...1, step: 0.01, defaultValue: 0.8,
                             format: { "\(Int($0 * 100))%" }, labelWidth: 80)
                }
                ParamRow(label: T("Offset", "Сдвиг"), value: $rec.offsetMs, range: -200...200, step: 1, defaultValue: 0,
                         bipolar: true, format: { String(format: "%+.0f ms", $0) },
                         help: T("Extra latency compensation if the take lands late (+) or early (−).",
                                 "Доп. компенсация, если дубль ложится позже (+) или раньше (−)."), labelWidth: 80)
            }
        }
    }

    private var takeColumn: some View {
        SectionCard(title: T("Take", "Дубль"), icon: "record.circle", collapsible: false) {
            VStack(alignment: .leading, spacing: 8) {
                TextRow(label: T("Name", "Название"), text: $rec.takeName,
                        placeholder: T("vocals-take-N", "vocals-take-N"), labelWidth: 100)
                HStack(spacing: 6) {
                    ParamRow(label: T("Start at", "Начать с"), value: $rec.startAt, range: 0...max(1, store.songDuration), step: 0.1,
                             defaultValue: 0, format: { Fmt.clock($0) }, labelWidth: 100)
                    Button(T("Loop", "Цикл")) { rec.startAt = store.loopStart }.buttonStyle(StudioButtonStyle(compact: true))
                    Button("0:00") { rec.startAt = 0 }.buttonStyle(StudioButtonStyle(compact: true))
                }
                ToggleRow(label: T("Play the song while recording", "Играть песню во время записи"), isOn: $rec.backing)
                if rec.backing {
                    ParamRow(label: T("Song level", "Громкость песни"), value: $rec.backingGain, range: 0...1, step: 0.01,
                             defaultValue: 0.8, format: { "\(Int($0 * 100))%" }, labelWidth: 100)
                }
                PickerRow(label: T("Count-in", "Отсчёт"), selection: $rec.countInBars,
                          options: [(0, T("Off", "Нет")), (1, T("1 bar", "1 такт")), (2, T("2 bars", "2 такта"))], labelWidth: 100)
                if rec.countInBars > 0 {
                    ParamRow(label: "BPM", value: $rec.bpm, range: 40...220, step: 1, defaultValue: 120,
                             format: { "\(Int($0))" }, labelWidth: 100)
                    ParamRow(label: T("Click level", "Громкость клика"), value: $rec.clickGain, range: 0...1, step: 0.01,
                             defaultValue: 0.5, format: { "\(Int($0 * 100))%" }, labelWidth: 100)
                }
                Divider().background(Theme.stroke)
                ToggleRow(label: T("Convert the take with RVC", "Обработать дубль через RVC"), isOn: $rec.rvcEnabled,
                          help: T("Voice conversion with a local RVC model (mlx-rvc on Apple Silicon). Set up in Settings → AI Models.",
                                  "Смена тембра локальной моделью RVC (mlx-rvc на Apple Silicon). Настройка: Настройки → AI-модели."))
                if rec.rvcEnabled {
                    HStack(spacing: 6) {
                        Text(rec.rvcModel.isEmpty ? T("no model", "модель не выбрана") : URL(fileURLWithPath: rec.rvcModel).lastPathComponent)
                            .font(.system(size: 10)).foregroundColor(rec.rvcModel.isEmpty ? Theme.yellow : Theme.text2)
                            .lineLimit(1).truncationMode(.middle)
                        Spacer()
                        Button(T("Model .pth…", "Модель .pth…")) { rec.chooseFile(index: false) }
                            .buttonStyle(StudioButtonStyle(compact: true))
                        Button(T("Index…", "Индекс…")) { rec.chooseFile(index: true) }
                            .buttonStyle(StudioButtonStyle(compact: true))
                        if !rec.rvcIndex.isEmpty {
                            IconButton(icon: "xmark.circle", help: T("Clear index", "Убрать индекс"), size: 10) { rec.rvcIndex = "" }
                        }
                    }
                    ParamRow(label: T("Pitch", "Тон"), value: $rec.rvcPitch, range: -24...24, step: 1, defaultValue: 0, bipolar: true,
                             format: { String(format: "%+.0f st", $0) }, labelWidth: 100)
                    PickerRow(label: "F0", selection: $rec.rvcF0,
                              options: [("rmvpe", "RMVPE"), ("harvest", "Harvest"), ("pm", "PM")], labelWidth: 100)
                }
            }
        }
    }

    private var transport: some View {
        HStack(spacing: 12) {
            Button {
                if rec.state == .idle { Task { await rec.record() } } else { rec.stop() }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: rec.state == .idle ? "record.circle.fill" : "stop.fill").font(.system(size: 16))
                    Text(stateTitle).font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 16).frame(height: 34)
                .background(RoundedRectangle(cornerRadius: 8).fill(rec.state == .idle ? Theme.red : Theme.bg4))
            }
            .buttonStyle(.plain)
            .disabled(!rec.engineRunning || rec.state == .processing)
            Text(Fmt.clock(rec.elapsed)).font(.system(size: 22, weight: .medium, design: .monospaced))
                .foregroundColor(rec.state == .recording ? Theme.red : Theme.text2)
            if rec.state == .countIn {
                Text(T("count-in…", "отсчёт…")).font(.system(size: 11)).foregroundColor(Theme.yellow)
            }
            if rec.state == .processing { ProgressView().controlSize(.small) }
            Spacer()
            Text(T("The take is placed at the song position you started from, latency compensated.",
                   "Дубль ставится в ту позицию песни, с которой начали, с компенсацией задержки."))
                .font(.system(size: 9)).foregroundColor(Theme.text3).multilineTextAlignment(.trailing)
                .frame(width: 260, alignment: .trailing)
        }
    }

    private var stateTitle: String {
        switch rec.state {
        case .idle: return T("Record", "Запись")
        case .countIn, .recording: return T("Stop", "Стоп")
        case .processing: return T("Saving…", "Сохраняю…")
        }
    }

    @ViewBuilder private var takesList: some View {
        if !rec.takes.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Caption(text: T("Takes", "Дубли"))
                ScrollView {
                    VStack(spacing: 4) {
                        ForEach(rec.takes) { t in TakeRow(rec: rec, take: t) }
                    }
                }
                .frame(maxHeight: 150)
            }
        }
    }
}

private struct TakeRow: View {
    @EnvironmentObject var store: StudioStore
    @ObservedObject var rec: Recorder
    let take: Recorder.Take

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: take.inSession ? "checkmark.circle.fill" : "waveform")
                .foregroundColor(take.inSession ? Theme.green : Theme.accent2)
            Text(take.name).font(.system(size: 11)).foregroundColor(Theme.text).lineLimit(1)
            Text(Fmt.clock(take.duration)).font(Theme.monoSmall).foregroundColor(Theme.text3)
            if take.rvcPath != nil { Badge(text: "RVC", color: Theme.purple) }
            Spacer()
            Button(T("Play", "Слушать")) { store.listen(take.rvcPath ?? take.path, title: take.name) }
                .buttonStyle(StudioButtonStyle(compact: true))
            if take.rvcPath == nil {
                Button("RVC") { Task { _ = await rec.convert(take) } }
                    .buttonStyle(StudioButtonStyle(compact: true))
                    .disabled(rec.rvcModel.isEmpty)
            }
            Button(T("Add to Session", "В сессию")) { Task { await rec.addToSession(take, useRVC: take.rvcPath != nil) } }
                .buttonStyle(StudioButtonStyle(compact: true))
            IconButton(icon: "folder", help: T("Show in Finder", "Показать в Finder"), size: 10) { store.reveal(take.path) }
            if !take.inSession {
                IconButton(icon: "trash", help: T("Delete this take", "Удалить дубль"), size: 10) { rec.discard(take) }
            }
        }
        .padding(.horizontal, 8).frame(height: 28)
        .background(RoundedRectangle(cornerRadius: 5).fill(Theme.bg2))
    }
}
