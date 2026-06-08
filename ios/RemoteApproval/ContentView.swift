import SwiftUI

struct ContentView: View {
    @EnvironmentObject var store: RequestStore
    @State private var editingURL = false
    @State private var urlDraft = ""

    var body: some View {
        NavigationStack {
            Group {
                if store.pending.isEmpty {
                    emptyState
                } else {
                    List(store.pending) { req in
                        RequestCard(request: req)
                            .listRowInsets(EdgeInsets())
                            .listRowSeparator(.hidden)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 6)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Approval Queue")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    statusIndicator
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Server") { urlDraft = store.serverURL; editingURL = true }
                        .font(.footnote)
                }
            }
            .alert("Server URL", isPresented: $editingURL) {
                TextField("http://localhost:8000", text: $urlDraft)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Button("Connect") {
                    store.serverURL = urlDraft
                    store.connect()
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.shield")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("No pending approvals")
                .font(.title3.weight(.medium))
            Text("Claude Code will ask here when it needs permission to run a tool.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    var statusIndicator: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(store.isConnected ? Color.green : Color.red)
                .frame(width: 8, height: 8)
            Text(store.isConnected ? "Live" : "Disconnected")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }
}

struct RequestCard: View {
    @EnvironmentObject var store: RequestStore
    let request: ToolRequest
    @State private var deciding = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label(request.tool_name, systemImage: iconFor(request.tool_name))
                    .font(.headline)
                    .foregroundStyle(.primary)
                Spacer()
                Text(request.age)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let cwd = request.cwd {
                Text(cwd)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            ScrollView {
                Text(request.formattedInput)
                    .font(.caption.monospaced())
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(Color(uiColor: .systemGroupedBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            .frame(maxHeight: 140)

            HStack(spacing: 10) {
                Button {
                    submit("deny")
                } label: {
                    Label("Deny", systemImage: "xmark")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .disabled(deciding)

                Button {
                    submit("allow")
                } label: {
                    Label("Allow", systemImage: "checkmark")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .disabled(deciding)
            }
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    func submit(_ decision: String) {
        deciding = true
        Task {
            await store.decide(requestId: request.id, decision: decision)
        }
    }

    func iconFor(_ tool: String) -> String {
        switch tool {
        case "bash", "execute_command": return "terminal"
        case "read_file", "str_replace_editor": return "doc.text"
        case "write_file": return "doc.badge.plus"
        case "web_search", "web_fetch": return "globe"
        default: return "hammer"
        }
    }
}
