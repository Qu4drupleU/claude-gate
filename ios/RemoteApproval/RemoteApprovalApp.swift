import SwiftUI

@main
struct RemoteApprovalApp: App {
    @StateObject private var store = RequestStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
