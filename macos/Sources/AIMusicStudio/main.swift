import AppKit
import Foundation

// Entry point. Flags (all optional):
//   --python <path>         Python interpreter for the engine (same as AMS_PYTHON)
//   --engine <dir>          folder that contains studio/engine_server.py (same as AMS_ENGINE_DIR)
//   --project <dir>         project folder for this launch (not saved to the settings)
//   --selftest              run the engine workflow + DSP checks without UI, exit code 0/1
//   --screenshots <dir>     render README screenshots of the real UI into <dir>
//   --smoke <sec> [report]  start the app normally, write a JSON report after <sec> seconds and quit

let arguments = Array(CommandLine.arguments.dropFirst())

func argument(after flag: String) -> String? {
    guard let i = arguments.firstIndex(of: flag), i + 1 < arguments.count else { return nil }
    let v = arguments[i + 1]
    return v.hasPrefix("--") ? nil : v
}

if let py = argument(after: "--python") { setenv("AMS_PYTHON", (py as NSString).expandingTildeInPath, 1) }
if let dir = argument(after: "--engine") { setenv("AMS_ENGINE_DIR", (dir as NSString).expandingTildeInPath, 1) }
if let dir = argument(after: "--project") {
    let path = (dir as NSString).expandingTildeInPath
    try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
    LaunchOptions.projectRoot = path
}

if arguments.contains("--selftest") {
    MainActor.assumeIsolated { SelfTest.run() }
    RunLoop.main.run()
} else if arguments.contains("--screenshots") {
    let dir = argument(after: "--screenshots") ?? "/tmp/ams-screenshots"
    _ = NSApplication.shared
    MainActor.assumeIsolated { Screenshots.run(outDir: dir) }
    NSApplication.shared.run()
} else {
    if arguments.contains("--smoke") {
        LaunchOptions.smokeSeconds = Double(argument(after: "--smoke") ?? "") ?? 8
        if let i = arguments.firstIndex(of: "--smoke"), i + 2 < arguments.count, !arguments[i + 2].hasPrefix("--") {
            LaunchOptions.smokeReport = arguments[i + 2]
        }
    }
    MainActor.assumeIsolated { AIMusicStudioApp.main() }
}
