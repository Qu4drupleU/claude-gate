import Foundation
import UserNotifications

@MainActor
class RequestStore: ObservableObject {
    @Published var pending: [ToolRequest] = []
    @Published var history: [(request: ToolRequest, decision: String)] = []
    @Published var isConnected = false
    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") }
    }

    private var sseTask: Task<Void, Never>?

    init() {
        self.serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        connect()
    }

    func connect() {
        sseTask?.cancel()
        isConnected = false
        pending = []

        sseTask = Task {
            await streamEvents()
        }
    }

    private func streamEvents() async {
        guard let url = URL(string: "\(serverURL)/events") else { return }
        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        do {
            let (bytes, _) = try await URLSession.shared.bytes(for: request)
            isConnected = true

            var buffer = ""
            for try await byte in bytes {
                guard let char = String(bytes: [byte], encoding: .utf8) else { continue }
                buffer += char

                if buffer.hasSuffix("\n\n") {
                    let lines = buffer
                        .components(separatedBy: "\n")
                        .filter { $0.hasPrefix("data: ") }
                        .map { String($0.dropFirst(6)) }

                    for line in lines {
                        handleSSELine(line)
                    }
                    buffer = ""
                }
            }
        } catch {
            isConnected = false
            // Reconnect after 3 seconds
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if !Task.isCancelled { await streamEvents() }
        }
    }

    private func handleSSELine(_ json: String) {
        guard let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let event = obj["event"] as? String ?? ""

        if event == "new_request",
           let reqData = try? JSONSerialization.data(withJSONObject: obj["data"] as Any),
           let req = try? JSONDecoder().decode(ToolRequest.self, from: reqData) {
            pending.insert(req, at: 0)
            sendNotification(for: req)
        }

        if event == "decision",
           let requestId = obj["request_id"] as? String,
           let decision = obj["decision"] as? String {
            if let idx = pending.firstIndex(where: { $0.id == requestId }) {
                let req = pending.remove(at: idx)
                history.insert((req, decision), at: 0)
                if history.count > 50 { history.removeLast() }
            }
        }
    }

    func decide(requestId: String, decision: String) async {
        guard let url = URL(string: "\(serverURL)/decision/\(requestId)") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["decision": decision])

        _ = try? await URLSession.shared.data(for: req)
    }

    private func sendNotification(for req: ToolRequest) {
        let content = UNMutableNotificationContent()
        content.title = "Claude wants to: \(req.tool_name)"
        content.body = req.formattedInput.prefix(150).description
        content.sound = .default
        content.userInfo = ["request_id": req.id]

        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 0.1, repeats: false)
        let request = UNNotificationRequest(identifier: req.id, content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }
}
