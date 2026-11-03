import Foundation

/// Loosely typed JSON used for engine payloads. Sessions travel as JSON objects, so fields the app
/// does not know about (newer engine versions) are preserved on the round trip.
enum JSONValue: Equatable, Hashable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    // MARK: Foundation bridge (JSONSerialization is fast and keeps bools distinct from numbers)

    init(any: Any?) {
        guard let any else { self = .null; return }
        switch any {
        case is NSNull:
            self = .null
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() {
                self = .bool(n.boolValue)
            } else {
                self = .number(n.doubleValue)
            }
        case let s as String:
            self = .string(s)
        case let a as [Any]:
            self = .array(a.map { JSONValue(any: $0) })
        case let d as [String: Any]:
            self = .object(d.mapValues { JSONValue(any: $0) })
        default:
            self = .null
        }
    }

    var any: Any {
        switch self {
        case .null: return NSNull()
        case .bool(let b): return NSNumber(value: b)
        case .number(let d):
            if !d.isFinite { return NSNull() }
            if d == d.rounded(), abs(d) < 1e15 { return NSNumber(value: Int64(d)) }
            return NSNumber(value: d)
        case .string(let s): return s
        case .array(let a): return a.map { $0.any }
        case .object(let o): return o.mapValues { $0.any }
        }
    }

    static func parse(_ data: Data) throws -> JSONValue {
        JSONValue(any: try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]))
    }

    static func parse(file url: URL) throws -> JSONValue {
        try parse(try Data(contentsOf: url))
    }

    func data(pretty: Bool = false) throws -> Data {
        var opts: JSONSerialization.WritingOptions = [.fragmentsAllowed]
        if pretty { opts.insert(.prettyPrinted); opts.insert(.sortedKeys) }
        return try JSONSerialization.data(withJSONObject: any, options: opts)
    }

    // MARK: Accessors

    var double: Double? {
        switch self {
        case .number(let d): return d
        case .bool(let b): return b ? 1 : 0
        case .string(let s): return Double(s)
        default: return nil
        }
    }
    var int: Int? { double.map { Int($0) } }
    var bool: Bool? {
        switch self {
        case .bool(let b): return b
        case .number(let d): return d != 0
        default: return nil
        }
    }
    var string: String? {
        switch self {
        case .string(let s): return s
        case .number(let d): return d == d.rounded() ? String(Int64(d)) : String(d)
        default: return nil
        }
    }
    var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
    var isNull: Bool { if case .null = self { return true }; return false }

    subscript(key: String) -> JSONValue? {
        get { object?[key] }
        set {
            guard case .object(var o) = self else { return }
            o[key] = newValue
            self = .object(o)
        }
    }

    subscript(index: Int) -> JSONValue? {
        guard let a = array, a.indices.contains(index) else { return nil }
        return a[index]
    }

    func str(_ key: String, _ fallback: String = "") -> String { self[key]?.string ?? fallback }
    func num(_ key: String, _ fallback: Double = 0) -> Double { self[key]?.double ?? fallback }
    func flag(_ key: String, _ fallback: Bool = false) -> Bool { self[key]?.bool ?? fallback }
    func list(_ key: String) -> [JSONValue] { self[key]?.array ?? [] }
    var doubles: [Double] { (array ?? []).compactMap { $0.double } }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
                     ExpressibleByBooleanLiteral, ExpressibleByNilLiteral, ExpressibleByArrayLiteral,
                     ExpressibleByDictionaryLiteral {
    init(stringLiteral value: String) { self = .string(value) }
    init(integerLiteral value: Int) { self = .number(Double(value)) }
    init(floatLiteral value: Double) { self = .number(value) }
    init(booleanLiteral value: Bool) { self = .bool(value) }
    init(nilLiteral: ()) { self = .null }
    init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    init(dictionaryLiteral elements: (String, JSONValue)...) {
        var o: [String: JSONValue] = [:]
        for (k, v) in elements { o[k] = v }
        self = .object(o)
    }
}

extension JSONValue {
    static func s(_ v: String) -> JSONValue { .string(v) }
    static func n(_ v: Double) -> JSONValue { .number(v) }
    static func n(_ v: Int) -> JSONValue { .number(Double(v)) }
    static func b(_ v: Bool) -> JSONValue { .bool(v) }
    static func opt(_ v: String?) -> JSONValue { v.map { .string($0) } ?? .null }
}

// MARK: Session helpers (channels are an array of objects with an "id")

extension JSONValue {
    var channels: [JSONValue] { list("channels") }

    func channel(_ id: String) -> JSONValue? { channels.first { $0.str("id") == id } }

    mutating func updateChannel(_ id: String, _ f: (inout JSONValue) -> Void) {
        guard var chans = self["channels"]?.array, let i = chans.firstIndex(where: { $0.str("id") == id }) else { return }
        var c = chans[i]
        f(&c)
        chans[i] = c
        self["channels"] = .array(chans)
    }

    mutating func updateObject(_ key: String, _ f: (inout JSONValue) -> Void) {
        var o = self[key] ?? .object([:])
        if o.object == nil { o = .object([:]) }
        f(&o)
        self[key] = o
    }
}
