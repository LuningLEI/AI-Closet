import SwiftUI

struct AuthRootView: View {
    @StateObject private var authStore = AuthStore()

    var body: some View {
        Group {
            if authStore.isAuthenticated {
                RootContentView()
            } else {
                AuthView()
            }
        }
        .environmentObject(authStore)
        .task {
            await authStore.refreshStoredSessionIfNeeded()
        }
    }
}

struct AuthView: View {
    @EnvironmentObject private var authStore: AuthStore
    @EnvironmentObject private var appSettings: AppSettings
    @State private var email = ""
    @State private var password = ""
    @State private var mode: AuthMode = .signIn

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 24) {
                Spacer()

                VStack(alignment: .leading, spacing: 8) {
                    Text("AI Closet")
                        .font(.largeTitle.bold())
                    Text(mode.title(appSettings))
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(.secondary)
                }

                VStack(spacing: 14) {
                    TextField(appSettings.text("auth.email"), text: $email)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.emailAddress)
                        .textContentType(.emailAddress)
                        .authFieldStyle()

                    SecureField(appSettings.text("auth.password"), text: $password)
                        .textContentType(mode == .signIn ? .password : .newPassword)
                        .authFieldStyle()
                }

                if let errorMessage = authStore.errorMessage {
                    Text(errorMessage)
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.red)
                }

                Button {
                    Task {
                        if mode == .signIn {
                            await authStore.signIn(email: email, password: password)
                        } else {
                            await authStore.signUp(email: email, password: password)
                        }
                    }
                } label: {
                    if authStore.isLoading {
                        ProgressView()
                            .tint(.white)
                            .frame(maxWidth: .infinity)
                    } else {
                        Text(mode.primaryAction(appSettings))
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(email.isEmpty || password.count < 6 || authStore.isLoading)

                Button(mode.secondaryAction(appSettings)) {
                    authStore.errorMessage = nil
                    mode = mode == .signIn ? .signUp : .signIn
                }
                .frame(maxWidth: .infinity)

                Spacer()
            }
            .padding(24)
        }
    }
}

private enum AuthMode {
    case signIn
    case signUp

    func title(_ appSettings: AppSettings) -> String {
        self == .signIn ? appSettings.text("auth.subtitle.sign_in") : appSettings.text("auth.subtitle.sign_up")
    }

    func primaryAction(_ appSettings: AppSettings) -> String {
        self == .signIn ? appSettings.text("auth.action.sign_in") : appSettings.text("auth.action.create_account")
    }

    func secondaryAction(_ appSettings: AppSettings) -> String {
        self == .signIn ? appSettings.text("auth.toggle.sign_up") : appSettings.text("auth.toggle.sign_in")
    }
}

private extension View {
    func authFieldStyle() -> some View {
        self
            .padding(14)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
    }
}
