import Capacitor
import Foundation
import Network

/**
 Receipt and kitchen printers on the shop's network — the iPhone half.

 The Android half is `mobile/plugins/tcp-printer`; this is the same plugin for
 iOS, written straight into the app target because it is a few lines and only
 this app uses it. Both answer to `TcpPrinter.send`, so `app-printer.js` does
 not care which phone it is running on.

 Almost every LAN thermal printer takes raw ESC/POS on TCP port 9100: open a
 socket, write the bytes, close it. The page draws the receipt, exactly as it
 does for Bluetooth. One print at a time, off the main thread, so a printer
 that is switched off never freezes the till.

 The first print of the day may raise iOS's "find devices on your local
 network" prompt. Until the shop says yes, the connection fails; the message
 that comes back tells them to check the printer and the Wi-Fi, which is the
 right thing to look at either way.
 */
@objc(TcpPrinterPlugin)
public class TcpPrinterPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "TcpPrinterPlugin"
    public let jsName = "TcpPrinter"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "send", returnType: CAPPluginReturnPromise)
    ]

    /// One print at a time, like the Android side's single-thread executor.
    private let line = DispatchQueue(label: "com.zzaxstudio.poswai.tcpprinter")

    @objc func send(_ call: CAPPluginCall) {
        let host = (call.getString("host") ?? "").trimmingCharacters(in: .whitespaces)
        let port = call.getInt("port") ?? 9100
        let timeout = call.getInt("timeout") ?? 5000
        guard !host.isEmpty, (1...65535).contains(port), let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
            call.reject("no host")
            return
        }
        guard let bytes = Data(base64Encoded: call.getString("data") ?? "") else {
            call.reject("bad data")
            return
        }

        line.async {
            let connection = NWConnection(host: NWEndpoint.Host(host), port: endpointPort, using: .tcp)
            let waiting = DispatchSemaphore(value: 0)
            // Whoever gets there first answers the page; the rest is ignored.
            let answered = NSLock()
            var done = false
            let finish: (String?) -> Void = { failure in
                answered.lock()
                defer { answered.unlock() }
                if done { return }
                done = true
                if let failure = failure {
                    call.reject(failure)
                } else {
                    call.resolve(["sent": bytes.count])
                }
                connection.cancel()
                waiting.signal()
            }

            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    /* `.finalMessage` is what makes this the Android side's
                       write-flush-close: the bytes go out and a FIN follows
                       them, so the printer has the whole receipt before the
                       socket shuts. Cancelling straight after a plain send
                       can reset the connection with the tail still in flight
                       and tear a receipt in half. */
                    connection.send(content: bytes, contentContext: .finalMessage, isComplete: true,
                                    completion: .contentProcessed { error in
                        finish(error.map { String(describing: $0) })
                    })
                case .failed(let error):
                    finish(String(describing: error))
                case .cancelled:
                    finish("cancelled")
                case .waiting(let error):
                    // Unreachable host, or local network access not granted yet.
                    finish(String(describing: error))
                default:
                    break
                }
            }
            // Not `line`: that one is about to block on the semaphore below,
            // and the connection's own callbacks are what will release it.
            connection.start(queue: DispatchQueue.global(qos: .userInitiated))

            if waiting.wait(timeout: .now() + .milliseconds(timeout)) == .timedOut {
                finish("timed out")
            }
        }
    }
}
