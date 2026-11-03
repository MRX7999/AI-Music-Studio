import AVFoundation
import Accelerate
import Combine

/// Loop player for engine previews and finished mixes. A new preview can be swapped in while playing:
/// playback continues from the same position, so knob changes are heard within a fraction of a second.
final class AudioPlayer: ObservableObject {
    @Published private(set) var isPlaying = false
    @Published private(set) var position: Double = 0          // seconds, song timeline
    @Published private(set) var loaded: URL?
    @Published private(set) var bufferStart: Double = 0       // timeline offset of the loaded audio
    @Published private(set) var bufferDuration: Double = 0
    @Published var loop = true
    @Published var volume: Double = 1 { didSet { engine.mainMixerNode.outputVolume = Float(volume) } }
    @Published private(set) var outPeak: (Double, Double) = (-90, -90)
    @Published private(set) var outHold: (Double, Double) = (-90, -90)
    @Published private(set) var lastError: String?

    private let engine = AVAudioEngine()
    private let node = AVAudioPlayerNode()
    private var buffer: AVAudioPCMBuffer?
    private var startFrame: AVAudioFramePosition = 0      // frame of the buffer where the current schedule began
    private var generation = 0
    private var timer: Timer?
    private var holdTime = (Date.distantPast, Date.distantPast)
    private var tapInstalled = false

    init() {
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: nil)
    }

    var hasAudio: Bool { buffer != nil }

    // MARK: loading

    /// Loads a file. `timelineStart` is where the file begins on the song timeline (preview start).
    /// When `keepPosition` is set and audio is playing, playback resumes at the same timeline position.
    /// `region` (start, length) in seconds reads only that part of the file (A/B with the original mix).
    func load(_ url: URL, timelineStart: Double = 0, keepPosition: Bool = true, autoplay: Bool = false,
              region: (Double, Double)? = nil) throws {
        let file = try AVAudioFile(forReading: url)
        let format = file.processingFormat
        let sr = format.sampleRate
        var first: AVAudioFramePosition = 0
        var count = file.length
        if let region {
            first = min(max(AVAudioFramePosition(region.0 * sr), 0), file.length)
            count = min(AVAudioFramePosition(region.1 * sr), file.length - first)
            file.framePosition = first
        }
        let frames = AVAudioFrameCount(max(count, 0))
        guard frames > 0, let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else {
            throw NSError(domain: "AudioPlayer", code: 1, userInfo: [NSLocalizedDescriptionKey: "empty audio file"])
        }
        try file.read(into: buf, frameCount: frames)
        let wasPlaying = isPlaying
        let oldPos = position
        stopNode()
        engine.disconnectNodeOutput(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        buffer = buf
        loaded = url
        bufferStart = timelineStart
        bufferDuration = Double(buf.frameLength) / format.sampleRate
        var rel = keepPosition ? oldPos - timelineStart : 0
        if rel < 0 || rel >= bufferDuration { rel = 0 }
        position = timelineStart + rel
        if wasPlaying || autoplay {
            play(fromRelative: rel)
        }
    }

    func unload() {
        stop()
        buffer = nil
        loaded = nil
        bufferDuration = 0
    }

    // MARK: transport

    func toggle() { isPlaying ? pause() : play(fromRelative: max(0, position - bufferStart)) }

    func play(fromRelative rel: Double? = nil) {
        guard let buf = buffer else { return }
        let sr = buf.format.sampleRate
        var r = rel ?? max(0, position - bufferStart)
        if r >= bufferDuration - 0.01 { r = 0 }
        do {
            if !engine.isRunning {
                installTap()
                engine.prepare()
                try engine.start()
            }
        } catch {
            lastError = error.localizedDescription
            return
        }
        stopNode()
        generation += 1
        let gen = generation
        startFrame = AVAudioFramePosition(r * sr)
        let first = startFrame > 0 ? slice(buf, from: AVAudioFrameCount(startFrame)) : buf
        if loop {
            if let first, startFrame > 0 {
                node.scheduleBuffer(first, at: nil, options: [], completionHandler: nil)
                node.scheduleBuffer(buf, at: nil, options: [.loops], completionHandler: nil)
            } else {
                node.scheduleBuffer(buf, at: nil, options: [.loops], completionHandler: nil)
            }
        } else if let first {
            node.scheduleBuffer(first, at: nil, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self, self.generation == gen else { return }
                    self.isPlaying = false
                    self.position = self.bufferStart + self.bufferDuration
                    self.stopTimer()
                }
            }
        }
        node.play()
        isPlaying = true
        startTimer()
    }

    func pause() {
        updatePosition()
        stopNode()
        isPlaying = false
        stopTimer()
    }

    func stop() {
        stopNode()
        isPlaying = false
        stopTimer()
        position = bufferStart
        outPeak = (-90, -90)
    }

    /// Seek on the song timeline. Outside the loaded audio the position is clamped to it.
    func seek(_ t: Double) {
        let rel = min(max(t - bufferStart, 0), max(bufferDuration - 0.01, 0))
        position = bufferStart + rel
        if isPlaying { play(fromRelative: rel) }
    }

    // MARK: internals

    private func stopNode() {
        generation += 1
        if node.engine != nil { node.stop() }
    }

    private func slice(_ buf: AVAudioPCMBuffer, from frame: AVAudioFrameCount) -> AVAudioPCMBuffer? {
        guard frame < buf.frameLength,
              let out = AVAudioPCMBuffer(pcmFormat: buf.format, frameCapacity: buf.frameLength - frame) else { return nil }
        out.frameLength = buf.frameLength - frame
        let chans = Int(buf.format.channelCount)
        if let src = buf.floatChannelData, let dst = out.floatChannelData {
            for c in 0..<chans {
                dst[c].update(from: src[c].advanced(by: Int(frame)), count: Int(out.frameLength))
            }
        }
        return out
    }

    private func updatePosition() {
        guard isPlaying, let buf = buffer, let t = node.lastRenderTime, let pt = node.playerTime(forNodeTime: t) else { return }
        let sr = buf.format.sampleRate
        let played = Double(pt.sampleTime) / pt.sampleRate
        let len = Double(buf.frameLength) / sr
        var rel = Double(startFrame) / sr + max(played, 0)
        if loop, len > 0 { rel = rel.truncatingRemainder(dividingBy: len) } else { rel = min(rel, len) }
        position = bufferStart + rel
    }

    private func startTimer() {
        stopTimer()
        let t = Timer(timeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in self?.updatePosition() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func installTap() {
        guard !tapInstalled else { return }
        tapInstalled = true
        let mixer = engine.mainMixerNode
        let fmt = mixer.outputFormat(forBus: 0)
        mixer.installTap(onBus: 0, bufferSize: 2048, format: fmt) { [weak self] buf, _ in
            guard let data = buf.floatChannelData else { return }
            let n = vDSP_Length(buf.frameLength)
            var peaks: [Double] = []
            for c in 0..<min(Int(buf.format.channelCount), 2) {
                var m: Float = 0
                vDSP_maxmgv(data[c], 1, &m, n)
                peaks.append(m > 1e-6 ? 20 * log10(Double(m)) : -90)
            }
            if peaks.count == 1 { peaks.append(peaks[0]) }
            DispatchQueue.main.async { self?.pushMeter(peaks[0], peaks[1]) }
        }
    }

    private func pushMeter(_ l: Double, _ r: Double) {
        guard isPlaying else { outPeak = (-90, -90); return }
        // fast attack, ~20 dB/s fall
        let fall = 20.0 / 21.5
        outPeak = (max(l, outPeak.0 - fall), max(r, outPeak.1 - fall))
        let now = Date()
        if l >= outHold.0 || now.timeIntervalSince(holdTime.0) > 1.5 { outHold.0 = l; holdTime.0 = now }
        if r >= outHold.1 || now.timeIntervalSince(holdTime.1) > 1.5 { outHold.1 = r; holdTime.1 = now }
    }
}
