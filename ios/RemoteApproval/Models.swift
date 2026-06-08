import Foundation

struct ToolRequest: Identifiable, Codable, Equatable {
    let id: String
    let tool_name: String
    let tool_input: [String: AnyCodable]
    let session_id: String?
    let cwd: String?
    let created_at: Double
    var status: String

    var formattedInput: String {
        let dict = tool_input.mapValues { $0.value }
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: .prettyPrinted),
           let str = String(data: data, encoding: .utf8) {
            return str
        }
        return "\(tool_input)"
    }

    var age: String {
        let date = Date(timeIntervalSince1970: created_at)
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// Allows decoding heterogeneous JSON values
struct AnyCodable: Codable, Equatable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let int = try? container.decode(Int.self)       { value = int; return }
        if let double = try? container.decode(Double.self) { value = double; return }
        if let bool = try? container.decode(Bool.self)     { value = bool; return }
        if let str = try? container.decode(String.self)    { value = str; return }
        if let arr = try? container.decode([AnyCodable].self) { value = arr.map { $0.value }; return }
        if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }; return
        }
        value = NSNull()
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let v as Int:    try container.encode(v)
        case let v as Double: try container.encode(v)
        case let v as Bool:   try container.encode(v)
        case let v as String: try container.encode(v)
        default: try container.encodeNil()
        }
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        "\(lhs.value)" == "\(rhs.value)"
    }
}

struct SSEMessage: Codable {
    let event: String
    let data: ToolRequest?
    let request_id: String?
    let decision: String?
}
