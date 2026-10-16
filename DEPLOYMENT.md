# POS WAI deployment notes

The intended live hostname is `https://poswai.zzaxstudio.com/`. The FastAPI
service serves the PWA and API from one HTTPS origin. Use that root URL as the
**Endpoint URL** in LINE LIFF Console after HTTPS and the app have been verified.

The user's existing Hostinger VPS runs Docker Manager and Traefik. The
`docker-compose.hostinger.yml` file uses its own Compose network, lets Traefik
route the hostname to port 8000, and stores SQLite on a named volume.
It currently builds the PR branch and sets `POSWAI_PREVIEW_ONLY=1`. This mode
shows the interface but rejects API writes. Keep it enabled while the
production gaps below are unresolved. After the PR is merged, change the
build ref to `main`; do not disable preview mode until authentication and
payment verification are complete.
On the Hostinger VPS, Docker's Git build context needs a full 40-character
commit SHA when pinned to a commit. After editing the Compose YAML, rebuild
the `poswai` image and recreate only that service; applying new environment
values alone can leave the old source files in the existing image. Verify the
served `service-worker.js` cache version and `/api/config` after deployment.
The Cloudflare DNS `A` record named `poswai` now points to `187.127.109.204`
with DNS-only proxy mode. Before production deployment, merge the reviewed PR
into `main` and set the environment secrets in Hostinger Docker Manager. DNS for
`zzaxstudio.com` is authoritative at Cloudflare, so editing Hostinger DNS alone
will not activate the subdomain.

The old `render.yaml` remains an alternative deployment configuration. It is
not the target for this hostname.

Set `DATABASE_URL` to a persistent SQLite file, for example
`sqlite:////var/data/poswai.db` on a mounted persistent disk. The default
`sqlite:///./poswai.db` is for local development and will not survive an
ephemeral deployment. Set `PROMPTPAY_ID` and the LINE settings below in the
host's secret settings. Never place LINE tokens in frontend files or Git.

### LINE leave and approval setup

1. Create a LINE Login channel and LIFF app with `openid` scope. Set its LIFF
   Endpoint URL to `https://poswai.zzaxstudio.com/`. Set `LINE_LIFF_ID` to the
   LIFF ID and `LINE_LOGIN_CHANNEL_ID` to the numeric LINE Login channel ID.
   The dedicated POS WAI LINE Login channel under ZZAX Studio is `2012039182`;
   its LIFF ID is `2012039182-4hwigCrL` and its endpoint is the HTTPS root above.
   The Docker Compose defaults include these public IDs. The LINE Login channel
   is still in Developing mode; publish it after the public app and privacy
   details have been checked.
2. Use a Messaging API channel under the **same LINE provider**. Set
   `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_CHANNEL_SECRET` from this channel.
   The dedicated POS WAI Official Account is `@151jbyje` and its Messaging
   API channel ID is `2012039195` under ZZAX Studio.
   The POS WAI long-lived access token has been issued and both LINE secrets
   are now stored in the Hostinger Docker Manager environment for `poswai`.
   The container was recreated with these values on 16 October 2026, while
   `POSWAI_PREVIEW_ONLY=1` remains enabled. Do not copy the values into Git.
   Register `https://poswai.zzaxstudio.com/api/line-webhook` as the Messaging
   API Webhook URL after deploying the new backend and enable webhooks only
   when LINE's Verify succeeds. The current public preview rejects writes.
   Managers must add the Official Account
   as a friend to receive approval messages.
3. Create staff accounts through the manager-only staff API. Each staff member
   signs in to POS and clicks **เชื่อมบัญชีพนักงานกับ LINE**. This verifies a
   fresh LINE ID token and binds that LINE user to their own staff account.
   Managers must also bind their LINE account before they can receive and
   approve Flex messages. One LINE account cannot bind to two staff accounts.
4. A leave request verifies the LIFF ID token against the LINE Login channel
   and requires the selected staff ID to match the bound LINE account. It is
   stored even if the Flex push fails; the response reports `delivery_failed`
   or `no_bound_manager` so an administrator can follow up. The LINE webhook
   verifies `x-line-signature` against the **raw request bytes**, then accepts
   postbacks only from active managers bound to that LINE user and branch.
   Approval updates every shift in the requested date range and locks POS PIN
   for those dates. Repeated postbacks cannot change a reviewed decision.

If LINE settings are absent, leave requests fail closed. Test the full flow
with real LINE accounts and an HTTPS deployment before enabling it for staff.

The server now requires staff PIN sessions for protected actions and signed QR
table tokens for guest orders and service calls. Set
`POSWAI_BOOTSTRAP_MANAGER_PIN` (at least eight characters) and
`POSWAI_TABLE_QR_SECRET` (at least 32 random characters) only in the host's
secret settings. The bootstrap manager ID is 1. Log in and create named staff
accounts and signed table links in the manager panel. Rotate the bootstrap PIN
after setup. In live mode, the menu, open orders, and inventory load from the
server; sample records are cleared. Create the real catalog and stock levels
before accepting orders. Menu IDs may be text; BOM entries use
`[{"ingId":"RICE","qty":1}]`. Every ingredient in a BOM must have sufficient
stock or the order is rejected.
The Hostinger environment now contains a manager PIN of at least eight
characters and a generated table QR signing secret. The app was recreated
after saving both values. The manager's first login and a signed table link
still need an end-to-end test when preview mode is lifted in staging.

EasySlip v2 verification is wired to the cashier's QR close flow. Set
`EASYSLIP_API_KEY` in the host and register the restaurant's receiving account
in EasySlip. The provider response must confirm the amount, receiving account,
and unused slip reference before the server closes all bills on a table in one
transaction. Never expose the API key in HTML or chat. Cash close is restricted
to cashiers. Other electronic payment buttons remain disabled until their
processors are integrated. The slip flow must be verified against a real bank
transfer in the staging branch before disabling preview mode.
The restaurant selected a phone-number PromptPay destination. Its number and
an EasySlip API key have now been entered in the Hostinger Docker
Manager environment. On 16 October 2026, the public `/api/config` confirmed a
10-digit PromptPay destination. An authenticated EasySlip `/v2/info` call from
the running container returned HTTP 200, an active branch, and 48 remaining
verification requests at the time of testing. This confirms the configured
key works; it does not confirm the receiving account is registered or prove a
real transfer can be closed. The first EasySlip key was accidentally entered
in a VPS terminal. The owner chose to keep using it for testing and declined
rotation at this stage. Restrict access to terminal history and revisit key
rotation before accepting live payments.

Keep `POSWAI_PREVIEW_ONLY=1` until the remaining live workflows are implemented
and verified. The legacy kitchen status, CRM, purchasing, some inventory
actions, shift/payroll panels, split bills, and digital receipts still have
browser-only demonstration behavior. They must be connected to protected APIs
or removed from the live workflow before the store relies on them. Payroll is
an estimate and does not include tax, Social Security, or deductions. The
production cutover also needs the actual LINE channel credentials, LIFF ID,
PromptPay receiving number, EasySlip key, bootstrap manager PIN, signed-table
secret, real menu/BOM data, and end-to-end checks on the HTTPS hostname.

For local smoke testing:

```sh
python -m py_compile line_pos_server.py
python -m uvicorn line_pos_server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/`. Service workers require localhost or HTTPS.
