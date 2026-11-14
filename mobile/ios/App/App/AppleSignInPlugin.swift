import AuthenticationServices
import Capacitor
import CryptoKit
import Foundation

/**
 Sign in with Apple, with the phone's own sheet — the iPhone half of the
 Apple sign-in in `app-bridge.js` (`app.appleSignIn`).

 App Review 4.8 asks an iPhone app that offers LINE or Google to offer Apple
 beside them. LINE and Google sign in through a browser tab; Apple does not
 need one, because the system shows its sheet over the app.

 The server issues a nonce with the state row, exactly as for LINE and Google.
 Apple is handed its SHA-256 (Apple's own recommendation, so the raw nonce never
 leaves the server and the app), and the identity token Apple signs carries that
 hash, which the server checks. The name comes back on the first sign-in only and
 is never in the token, so it is returned beside it for the server to keep.
 */
@objc(AppleSignInPlugin)
public class AppleSignInPlugin: CAPPlugin, CAPBridgedPlugin, ASAuthorizationControllerDelegate,
    ASAuthorizationControllerPresentationContextProviding {
    public let identifier = "AppleSignInPlugin"
    public let jsName = "AppleSignIn"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "authorize", returnType: CAPPluginReturnPromise)
    ]

    /// The call waiting on Apple's sheet. One sheet at a time.
    private var pending: CAPPluginCall?

    @objc func authorize(_ call: CAPPluginCall) {
        guard let nonce = call.getString("nonce"), !nonce.isEmpty else {
            call.reject("no nonce")
            return
        }
        guard pending == nil else {
            call.reject("a sign-in is already open")
            return
        }
        pending = call
        let request = ASAuthorizationAppleIDProvider().createRequest()
        request.requestedScopes = [.fullName, .email]
        request.nonce = SHA256.hash(data: Data(nonce.utf8)).map { String(format: "%02x", $0) }.joined()
        DispatchQueue.main.async {
            let controller = ASAuthorizationController(authorizationRequests: [request])
            controller.delegate = self
            controller.presentationContextProvider = self
            controller.performRequests()
        }
    }

    public func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }

    public func authorizationController(controller: ASAuthorizationController,
                                        didCompleteWithAuthorization authorization: ASAuthorization) {
        guard let call = pending else { return }
        pending = nil
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let tokenData = credential.identityToken,
              let token = String(data: tokenData, encoding: .utf8) else {
            call.reject("Apple returned no identity token")
            return
        }
        call.resolve([
            "identityToken": token,
            "user": credential.user,
            "email": credential.email ?? "",
            "givenName": credential.fullName?.givenName ?? "",
            "familyName": credential.fullName?.familyName ?? "",
        ])
    }

    public func authorizationController(controller: ASAuthorizationController,
                                        didCompleteWithError error: Error) {
        guard let call = pending else { return }
        pending = nil
        // The page tells a closed sheet apart from a failure by this code.
        let canceled = (error as? ASAuthorizationError)?.code == .canceled
        call.reject(canceled ? "canceled" : error.localizedDescription, canceled ? "canceled" : nil, error)
    }
}
