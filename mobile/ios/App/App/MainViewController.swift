import Capacitor
import UIKit

/**
 The web view the app runs in, with this app's own plugins added to it.

 Capacitor registers the plugins it finds in `packageClassList` — the list
 `npx cap sync` writes from the npm packages. `TcpPrinterPlugin` lives in this
 target rather than in a package, so that list never mentions it and the page
 would find no `Capacitor.Plugins.TcpPrinter` at all: printing to the kitchen
 printer over LAN would fail on every iPhone, with the app otherwise working.
 `AppleSignInPlugin` (Sign in with Apple) lives here for the same reason.
 Registering it here is what the Android side gets for free from its
 `@CapacitorPlugin` annotation, and it survives the next `cap sync`.
 */
class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(TcpPrinterPlugin())
        bridge?.registerPluginInstance(AppleSignInPlugin())
    }
}
