# POS WAI deployment notes

The intended live hostname is `https://poswai.zzaxstudio.com/`. The FastAPI
service serves the PWA and API from one HTTPS origin. Use that root URL as the
**Endpoint URL** in LINE LIFF Console after HTTPS and the app have been verified.

The user's existing Hostinger VPS runs Docker Manager and Traefik. The
`docker-compose.hostinger.yml` file connects POS WAI to its `traefik-proxy`
network, routes the hostname to port 8000, and stores SQLite on a named volume.
The Cloudflare DNS `A` record named `poswai` now points to `187.127.109.204`
with DNS-only proxy mode. Before deploying the app, merge the reviewed PR into
`main` and set the environment secrets in Hostinger Docker Manager. DNS for
`zzaxstudio.com` is authoritative at Cloudflare, so editing Hostinger DNS alone
will not activate the subdomain.

The old `render.yaml` remains an alternative deployment configuration. It is
not the target for this hostname.

Set `DATABASE_URL` to a persistent SQLite file, for example
`sqlite:////var/data/poswai.db` on a mounted persistent disk. The default
`sqlite:///./poswai.db` is for local development and will not survive an
ephemeral deployment. Set `PROMPTPAY_ID`, `LINE_LIFF_ID`,
`LINE_CHANNEL_ACCESS_TOKEN`, and `LINE_CHANNEL_SECRET` in the host's secret
settings. The current server reads these values, but the LINE Messaging API
notification and signed webhook flow have **not** been implemented.

The current UI includes sample orders, staff, and inventory. The new order API
persists submitted orders and BOM deductions with retry protection. The sample
state remains local to the browser; a fresh device does not load all records
from the server. The app does not authenticate staff or managers yet. Do not
put it into live financial operation until staff authorization, real inventory
initialization, and server-backed state loading are implemented.

QR slip validation needs a real payment verification provider. The UI blocks
QR bill closing, and the API returns HTTP 501 for QR payment. Keep QR payment
disabled until verification is implemented and enforced server-side.

For local smoke testing:

```sh
python -m py_compile line_pos_server.py
python -m uvicorn line_pos_server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/`. Service workers require localhost or HTTPS.
