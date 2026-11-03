// swift-tools-version:5.9
// AI Music Studio — native macOS app (SwiftUI). Builds with Xcode 15+ or Command Line Tools only:
//   swift build -c release            (see build_app.sh for the .app bundle)
import PackageDescription

let package = Package(
    name: "AIMusicStudio",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "AIMusicStudio",
            path: "Sources/AIMusicStudio"
        )
    ]
)
