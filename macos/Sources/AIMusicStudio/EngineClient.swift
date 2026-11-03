import Foundation

struct EngineError: LocalizedError {
    let type: String
    let message: String
    var errorDescription: String? { message }
    var isCancelled: Bool { type == "Cancelled" }
}

/// Runs `python -m studio.engine_server` and talks JSON lines over stdin/stdout.
/// Secrets never go on the command line: API keys are sent with `config.set` after start.
final class EngineClient: @unchecked Sendable {
    struct Launch {
        var python: String
        var engineDir: String
        var language: String
    }

    typealias Completion = (Result<JSONValue, Error>) -> Void
    typealias Progress = @MainActor (Double, String) -> Void

    private let queue = DispatchQueue(label: "studio.engine.client")
    private var process: Process?
    private var input: FileHandle?
    private var buffer = Data()
    private var errBuffer = Data()
    private var nextId = 1
    private var pending: [Int: Completion] = [:]
    private var progress: [Int: Progress] = [:]
    private var readyWaiter: Completion?
    private(set) var stderrTail: [String] = []

    /// Called on the main actor when the engine process exits on its own.
    var onExit: (@MainActor (Int32, String) -> Void)?

    var isRunning: Bool { queue.sync { process?.isRunning == true } }

    // MARK: lifecycle

    func start(_ launch: Launch, timeout: Double = 45) async throws -> JSONValue {
        stop()
        return try await withCheckedThrowingContinuation { (cont: CheckedContinuation<JSONValue, Error>) in
            // strong for the duration of the launch; the pipe and timer handlers below hold `self` weakly
            queue.async { [self] in
                let p = Process()
                p.executableURL = URL(fileURLWithPath: launch.python)
                p.arguments = ["-u", "-m", "studio.engine_server"]
                p.currentDirectoryURL = URL(fileURLWithPath: launch.engineDir)
                var env = ProcessInfo.processInfo.environment
                env["PYTHONPATH"] = launch.engineDir
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                env["AMS_LANG"] = launch.language
                // keep .pyc files out of the signed app bundle
                env["PYTHONPYCACHEPREFIX"] = AppPaths.cacheDir.appendingPathComponent("pycache").path
                // GUI apps start with a minimal PATH; ffmpeg usually lives in Homebrew
                let extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
                let path = (env["PATH"] ?? "").split(separator: ":").map(String.init)
                env["PATH"] = (path + extra.filter { !path.contains($0) }).joined(separator: ":")
                p.environment = env
                let inPipe = Pipe(), outPipe = Pipe(), errPipe = Pipe()
                p.standardInput = inPipe
                p.standardOutput = outPipe
                p.standardError = errPipe
                outPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
                    let d = h.availableData
                    if d.isEmpty { h.readabilityHandler = nil; return }
                    self?.queue.async { self?.consume(d) }
                }
                errPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
                    let d = h.availableData
                    if d.isEmpty { h.readabilityHandler = nil; return }
                    self?.queue.async { self?.consumeErr(d) }
                }
                p.terminationHandler = { [weak self] proc in
                    self?.queue.async { self?.terminated(proc) }
                }
                self.buffer = Data()
                self.errBuffer = Data()
                self.stderrTail = []
                self.readyWaiter = { cont.resume(with: $0) }
                do {
                    try p.run()
                } catch {
                    self.readyWaiter = nil
                    cont.resume(throwing: EngineError(type: "LaunchFailed",
                                                      message: T("Cannot start Python: ", "Не удалось запустить Python: ") + error.localizedDescription))
                    return
                }
                self.process = p
                self.input = inPipe.fileHandleForWriting
                self.queue.asyncAfter(deadline: .now() + timeout) { [weak self] in
                    guard let self, let w = self.readyWaiter else { return }
                    self.readyWaiter = nil
                    w(.failure(EngineError(type: "Timeout", message: T("The engine did not start in time.", "Движок не запустился вовремя.")
                                           + "\n" + self.stderrTail.suffix(8).joined(separator: "\n"))))
                    self.process?.terminate()
                }
            }
        }
    }

    func stop() {
        queue.sync {
            guard let p = process else { return }
            process = nil
            if p.isRunning {
                if let input, let data = "{\"id\":0,\"method\":\"shutdown\"}\n".data(using: .utf8) {
                    try? input.write(contentsOf: data)
                    try? input.close()
                }
                let deadline = Date().addingTimeInterval(1.5)
                while p.isRunning && Date() < deadline { usleep(20_000) }
                if p.isRunning { p.terminate() }
            }
            input = nil
            failAll(EngineError(type: "Stopped", message: T("Engine stopped", "Движок остановлен")))
        }
    }

    // MARK: calls

    func call(_ method: String, _ params: [String: JSONValue] = [:], progress: Progress? = nil) async throws -> JSONValue {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<JSONValue, Error>) in
            send(method, params, progress: progress) { cont.resume(with: $0) }
        }
    }

    func send(_ method: String, _ params: [String: JSONValue], progress: Progress? = nil, completion: @escaping Completion) {
        queue.async {
            guard let input = self.input, self.process?.isRunning == true else {
                completion(.failure(EngineError(type: "NotRunning", message: T("The engine is not running.", "Движок не запущен."))))
                return
            }
            let id = self.nextId
            self.nextId += 1
            self.pending[id] = completion
            if let progress { self.progress[id] = progress }
            let obj: [String: Any] = ["id": id, "method": method, "params": JSONValue.object(params).any]
            do {
                var data = try JSONSerialization.data(withJSONObject: obj, options: [])
                data.append(0x0A)
                try input.write(contentsOf: data)
            } catch {
                self.pending.removeValue(forKey: id)
                self.progress.removeValue(forKey: id)
                completion(.failure(error))
            }
        }
    }

    // MARK: transport (engine queue)

    private func consume(_ d: Data) {
        buffer.append(d)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer.subdata(in: buffer.startIndex..<nl)
            buffer.removeSubrange(buffer.startIndex...nl)
            guard !line.isEmpty, let msg = try? JSONValue.parse(line) else { continue }
            handle(msg)
        }
    }

    private func consumeErr(_ d: Data) {
        errBuffer.append(d)
        while let nl = errBuffer.firstIndex(of: 0x0A) {
            let line = String(decoding: errBuffer.subdata(in: errBuffer.startIndex..<nl), as: UTF8.self)
            errBuffer.removeSubrange(errBuffer.startIndex...nl)
            if line.contains("nice(5) failed") { continue }
            stderrTail.append(line)
            if stderrTail.count > 200 { stderrTail.removeFirst(stderrTail.count - 200) }
        }
    }

    private func handle(_ msg: JSONValue) {
        if let ev = msg["event"]?.string {
            if ev == "ready", let w = readyWaiter {
                readyWaiter = nil
                w(.success(msg))
            } else if ev == "progress", let id = msg["id"]?.int, let h = progress[id] {
                let frac = msg.num("frac"), text = msg.str("msg")
                Task { @MainActor in h(frac, text) }
            }
            return
        }
        guard let id = msg["id"]?.int, let done = pending.removeValue(forKey: id) else { return }
        progress.removeValue(forKey: id)
        if let err = msg["error"] {
            done(.failure(EngineError(type: err.str("type", "Error"), message: err.str("message", "Engine error"))))
        } else {
            done(.success(msg["result"] ?? .null))
        }
    }

    private func terminated(_ p: Process) {
        let status = p.terminationStatus
        let tail = stderrTail.suffix(12).joined(separator: "\n")
        let wasCurrent = process === p
        if wasCurrent {
            process = nil
            input = nil
        }
        if let w = readyWaiter {
            readyWaiter = nil
            w(.failure(EngineError(type: "Exited", message: T("The engine exited during start (code \(status)).",
                                                               "Движок завершился при запуске (код \(status)).") + "\n" + tail)))
        }
        failAll(EngineError(type: "Exited", message: T("The engine exited (code \(status)).", "Движок завершился (код \(status)).")))
        if wasCurrent, let onExit {
            Task { @MainActor in onExit(status, tail) }
        }
    }

    private func failAll(_ e: Error) {
        let all = pending
        pending.removeAll()
        progress.removeAll()
        for (_, c) in all { c(.failure(e)) }
    }
}

// MARK: - Locating Python and the engine

enum AppPaths {
    static var appSupport: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("AI Music Studio", isDirectory: true)
    }
    static var cacheDir: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Caches")
        return base.appendingPathComponent("AI Music Studio", isDirectory: true)
    }
    static var managedVenv: URL { appSupport.appendingPathComponent("venv", isDirectory: true) }
    static var managedPython: URL { managedVenv.appendingPathComponent("bin/python3") }

    /// ~/Music/AI Music Studio, or ~/AI Music Studio when the Music folder is not writable.
    static func defaultProjectRoot() -> URL {
        let home = URL(fileURLWithPath: NSHomeDirectory())
        let music = home.appendingPathComponent("Music/AI Music Studio", isDirectory: true)
        let fm = FileManager.default
        if (try? fm.createDirectory(at: music, withIntermediateDirectories: true)) != nil, fm.isWritableFile(atPath: music.path) {
            return music
        }
        return home.appendingPathComponent("AI Music Studio", isDirectory: true)
    }
}

struct PythonCandidate: Identifiable, Hashable {
    var id: String { path }
    let path: String
    let version: String
    let hasDeps: Bool
    let missing: [String]
}

enum EngineLocator {
    static func isEngineDir(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.appendingPathComponent("studio/engine_server.py").path)
    }

    /// Settings override → app bundle → walk up from the executable / working directory (dev checkout).
    static func engineDir(override: String?) -> URL? {
        if let o = override, !o.isEmpty {
            let u = URL(fileURLWithPath: (o as NSString).expandingTildeInPath)
            if isEngineDir(u) { return u }
        }
        // an explicit AMS_ENGINE_DIR (or --engine) beats the copy bundled inside the app
        if let env = ProcessInfo.processInfo.environment["AMS_ENGINE_DIR"], !env.isEmpty {
            let u = URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
            if isEngineDir(u) { return u }
        }
        if let res = Bundle.main.resourceURL?.appendingPathComponent("engine"), isEngineDir(res) { return res }
        var starts = [URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent(),
                      URL(fileURLWithPath: FileManager.default.currentDirectoryPath)]
        if let exe = Bundle.main.executableURL { starts.append(exe.deletingLastPathComponent()) }
        for start in starts {
            var u = start
            for _ in 0..<8 {
                if isEngineDir(u) { return u }
                u.deleteLastPathComponent()
            }
        }
        return nil
    }

    static func pythonCandidates(engineDir: URL?) -> [String] {
        var c: [String] = []
        if let env = ProcessInfo.processInfo.environment["AMS_PYTHON"] { c.append(env) }
        c.append(AppPaths.managedPython.path)
        if let e = engineDir {
            c.append(e.appendingPathComponent(".venv/bin/python3").path)
            c.append(e.deletingLastPathComponent().appendingPathComponent(".venv/bin/python3").path)
        }
        let fm = FileManager.default
        let pyenv = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".pyenv/versions")
        if let vs = try? fm.contentsOfDirectory(atPath: pyenv.path) {
            for v in vs.sorted(by: { $0.compare($1, options: .numeric) == .orderedDescending }) {
                c.append(pyenv.appendingPathComponent(v).appendingPathComponent("bin/python3").path)
            }
        }
        for prefix in ["/opt/homebrew/bin", "/usr/local/bin"] {
            for v in ["3.13", "3.12", "3.11", "3.10", "3.9"] { c.append("\(prefix)/python\(v)") }
            c.append("\(prefix)/python3")
        }
        let fw = "/Library/Frameworks/Python.framework/Versions"
        if let vs = try? fm.contentsOfDirectory(atPath: fw) {
            for v in vs.sorted(by: { $0.compare($1, options: .numeric) == .orderedDescending }) where v != "Current" {
                c.append("\(fw)/\(v)/bin/python3")
            }
        }
        // the CLT python directly: /usr/bin/python3 would pop up an installer dialog when CLT is missing
        c.append("/Library/Developer/CommandLineTools/usr/bin/python3")
        c.append("/Applications/Xcode.app/Contents/Developer/usr/bin/python3")
        var seen = Set<String>()
        return c.filter { p in
            let real = URL(fileURLWithPath: p).resolvingSymlinksInPath().path
            guard fm.isExecutableFile(atPath: p), !seen.contains(real) else { return false }
            seen.insert(real)
            return true
        }
    }

    /// Runs the interpreter with a tiny probe script (no network, ~0.3 s).
    static func probe(_ python: String) -> PythonCandidate? {
        let script = """
        import sys, importlib.util as u
        need = ["numpy", "scipy", "soundfile", "requests"]
        miss = [m for m in need if u.find_spec(m) is None]
        print(sys.version.split()[0]); print(",".join(miss))
        """
        guard let out = run(python, ["-c", script], timeout: 20) else { return nil }
        let lines = out.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        guard let ver = lines.first, ver.first?.isNumber == true else { return nil }
        let parts = ver.split(separator: ".").compactMap { Int($0) }
        guard parts.count >= 2, parts[0] == 3, parts[1] >= 9 else { return nil }
        let missing = lines.count > 1 ? lines[1].split(separator: ",").map(String.init).filter { !$0.isEmpty } : []
        return PythonCandidate(path: python, version: ver, hasDeps: missing.isEmpty, missing: missing)
    }

    static func detect(engineDir: URL?, override: String?) -> (best: PythonCandidate?, all: [PythonCandidate]) {
        var list: [PythonCandidate] = []
        if let o = override, !o.isEmpty, let p = probe((o as NSString).expandingTildeInPath) {
            list.append(p)
            if p.hasDeps { return (p, list) }
        }
        for path in pythonCandidates(engineDir: engineDir) {
            guard let p = probe(path) else { continue }
            list.append(p)
            if p.hasDeps { return (p, list) }
        }
        return (nil, list)
    }

    @discardableResult
    static func run(_ exe: String, _ args: [String], timeout: Double, env: [String: String]? = nil,
                    onLine: ((String) -> Void)? = nil) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = args
        if let env { p.environment = env }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        var collected = Data()
        let lock = NSLock()
        pipe.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil; return }
            lock.lock(); collected.append(d); lock.unlock()
            if let onLine {
                for line in String(decoding: d, as: UTF8.self).split(separator: "\n") { onLine(String(line)) }
            }
        }
        do { try p.run() } catch { return nil }
        let deadline = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < deadline { usleep(30_000) }
        if p.isRunning { p.terminate(); return nil }
        p.waitUntilExit()
        usleep(50_000)
        pipe.fileHandleForReading.readabilityHandler = nil
        lock.lock(); let d = collected; lock.unlock()
        return p.terminationStatus == 0 ? String(decoding: d, as: UTF8.self) : nil
    }
}
