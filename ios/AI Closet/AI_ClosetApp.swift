import SwiftUI

@main
struct AI_ClosetApp: App {
    @StateObject private var appSettings = AppSettings()

    var body: some Scene {
        WindowGroup {
            AuthRootView()
                .environmentObject(appSettings)
                .environment(\.locale, appSettings.locale)
        }
    }
}
