package com.zzaxstudio.poswai.tcpprinter;

import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Receipt and kitchen printers on the shop's network.
 *
 * Almost every LAN thermal printer takes raw ESC/POS on TCP port 9100: open a
 * socket, write the bytes, close it. That is all this does — the page draws the
 * receipt, exactly as it does for Bluetooth. One print at a time, off the main
 * thread, so a printer that is switched off never freezes the till.
 */
@CapacitorPlugin(name = "TcpPrinter")
public class TcpPrinterPlugin extends Plugin {
    private final ExecutorService line = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void send(PluginCall call) {
        String host = call.getString("host", "").trim();
        int port = call.getInt("port", 9100);
        int timeout = call.getInt("timeout", 5000);
        String data = call.getString("data", "");
        if (host.isEmpty()) {
            call.reject("no host");
            return;
        }
        final byte[] bytes;
        try {
            bytes = Base64.decode(data, Base64.DEFAULT);
        } catch (IllegalArgumentException error) {
            call.reject("bad data", error);
            return;
        }
        line.execute(() -> {
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress(host, port), timeout);
                socket.setSoTimeout(timeout);
                OutputStream out = socket.getOutputStream();
                out.write(bytes);
                out.flush();
                JSObject done = new JSObject();
                done.put("sent", bytes.length);
                call.resolve(done);
            } catch (Exception error) {
                call.reject(String.valueOf(error.getMessage()), error);
            }
        });
    }
}
