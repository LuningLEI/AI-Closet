import SwiftUI

struct HomeTabView: View {
    @EnvironmentObject private var appSettings: AppSettings

    var body: some View {
        TabView {
            TodayView()
                .tabItem { Label(appSettings.text("tab.today"), systemImage: "sun.max") }

            ClosetHomeView()
                .tabItem { Label(appSettings.text("tab.closet"), systemImage: "tshirt") }

            RecommendationsView()
                .tabItem { Label(appSettings.text("tab.recommendations"), systemImage: "sparkles") }

            MyView()
                .tabItem { Label(appSettings.text("tab.my"), systemImage: "person") }
        }
    }
}
