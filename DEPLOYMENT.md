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
secret settings. The initial owner account ID is 1. Log in and create named staff
accounts in the staff manager panel. Manage table QR links separately from cashier table setup. Rotate the initial PIN
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
key works. The configured key belongs to the `สาขาหลัก` branch of the Jodwai
application. An authenticated `/v2/bank-accounts` request initially returned
zero registered receiving accounts. After the owner added an account, a repeat
request returned HTTP 200 with **one registered receiving account**.
These checks do not prove a real transfer can be closed. The first EasySlip
key was accidentally entered in a VPS terminal. The owner chose to keep using
it for testing and declined rotation at this stage. Restrict access to terminal
history and revisit key rotation before accepting live payments.

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

## Online pickup, Songwai, and LINE marketing (16 October 2026)

POS WAI now has server-backed online pickup orders, a staff fulfillment queue,
menu mapping for Songwai restaurant **โคตรเนื้อ** (restaurant ID `37`), and
CRM segments (`new`, `returning`, `dormant30`). A handed-off paid order updates
the customer's completed-order count and last visit. Cancelling an order
restores its BOM inventory in the same transaction. Customer marketing consent
is stored separately from order data. Campaigns start as drafts; a manager
must explicitly submit a draft, and only opted-in, LINE-linked customers can
receive a LINE OA push. LINE HTTP acceptance is recorded separately from
delivery confirmation.

Set `SONGWAI_RESTAURANT_ID=37` and a random `SONGWAI_WEBHOOK_SECRET` of at least
32 characters on the POS WAI server. Songwai must hold the same secret and
send a JSON POST to `https://poswai.zzaxstudio.com/api/integrations/songwai/orders`
after its order is durably created. Sign the exact request body with
`HMAC-SHA256(secret, <Unix-seconds> + "." + <raw-body>)`, then send headers
`X-Songwai-Timestamp` and `X-Songwai-Signature: sha256=<hex digest>`.
The body contains `order_id`, `restaurant_id: 37`, `user_id`, `delivery_mode`
(`pickup` or `rider`), `payment_status` (`pending` or `paid`), and `items` with
Songwai `menu_id` and `qty`. POS WAI ignores partner prices and uses its own
catalog and BOM. Repeating the same `(restaurant_id, order_id)` does not
deduct stock twice. Songwai should retain failed deliveries in a durable outbox
and retry using the same order ID; do not treat a failed webhook as an accepted
POS order.

The existing Songwai restaurant's eight menu IDs are `480`–`483` and
`1490`–`1493`. A manager must first enter the real POS menu, ingredient stocks,
and BOM recipes, then map each Songwai item on the **ช่องทางขาย** tab. The public
manager screen now has **เตรียมเมนูทั้ง 8 รายการ**: it imports current Songwai
names and prices as inactive drafts and links their IDs without overwriting
any existing POS recipe. Drafts are excluded from ordering. A Songwai draft
cannot be activated until its BOM is nonempty and each ingredient has a stock
record. The owner chose to provide recipes and initial stock later.
The public POS WAI deployment still has `POSWAI_PREVIEW_ONLY=1`. Songwai's
live order route has a durable POS WAI outbox for restaurant 37 and a signed
webhook sender, but the bridge remains disabled until matching secrets are
configured. The Songwai checkout currently offers rider/postal delivery;
POS WAI's LINE LIFF flow offers customer self pickup. Do not call the
integration live or claim that either pickup flow is accepting real orders
until the menu and stock are entered and an end-to-end order is verified.
Other delivery platforms remain unconnected. The existing staff features remain incomplete for live payroll:
the overview, attendance, leave, commission, and payroll estimate APIs exist,
but shift/rate setup and full live payroll checks are outstanding.

Staff can also enter a received GrabFood, LINE MAN, ShopeeFood, TikTok Shop,
or telephone order manually with the provider's order ID. It joins the same
kitchen queue, uses POS WAI menu prices and BOM stock, and is idempotent per
provider/order ID. This is **manual intake**, not automatic partner API access.
Do not advertise an automatic integration until the provider has granted API
access, provided its webhook contract, and an authenticated end-to-end order
has been tested. The incoming Songwai webhook is likewise dormant until its
secret is configured on both services and Songwai sends persisted orders.

## LINE staff notifications and payroll inputs

Leave requests from a verified, linked LINE LIFF identity now persist manager
Flex notifications before sending. Approval or rejection persists a result
message for the staff member. A background worker retries pending LINE pushes
every minute when the Messaging API token is configured and preview mode is
off. A manager can also use **ส่ง LINE ที่ค้าง** on the staff page. LINE's retry
key is stable for each notification and recipient, so a timeout can be retried
without sending the same message twice during LINE's 24-hour retry window.
HTTP acceptance means LINE accepted the request; it does not guarantee the
recipient saw it or has added the OA.

The staff page now lets managers configure hourly rates, shift templates and
assignments, and check for staff absent more than 60 minutes after a scheduled
start. Attendance rejects a second open clock-in or a clock-out without an
open attendance. Existing monthly payroll remains a gross estimate based on
recorded hours and commission; deductions, paid leave policy, overtime
authorization, and payroll approval are not yet implemented. Test with the
restaurant's actual pay policy before using it to pay wages.

`POSWAI_STAFF_LIVE=1` allows staff login, shift setup, attendance, leave,
LINE leave notifications, and staff management while `POSWAI_PREVIEW_ONLY=1`
continues to block order, payment, inventory, and campaign writes. The
manager must sign in and link their own LINE account from the staff page
before leave requests can be delivered to that manager's chat. No real
messages are sent merely by enabling this flag.

Live check on 16 October 2026: the LINE Messaging token authenticates (bot
info HTTP 200), and the configured webhook URL is
`https://poswai.zzaxstudio.com/api/line-webhook`, but LINE reports webhook
`active=false`. The production database has one active staff record and zero
LINE-linked managers. Enable **Use webhook** in the POS WAI Messaging API
channel and link the manager's LINE account before testing leave approval in
LINE. Do not claim a real recipient notification or approval round trip until
that test succeeds.

Deployment notes: the Songwai bridge module is installed as
`/docker/songwai/lib/poswaiBridge.js` and its order route is patched on the
Hostinger VPS. The previous route is backed up at
`/docker/songwai/routes/orders.js.bak-poswai-20261016`; this Songwai checkout
is not a Git repository. POS WAI's Hostinger Compose sets
`SONGWAI_RESTAURANT_ID=37` and retains preview mode. Both services were rebuilt
on 16 October 2026. The POS WAI bridge design and rollback instructions are in
`integrations/SONGWAI.md`. Keep the shared webhook secret unset until the
real catalog/BOM/stock and authenticated order test are ready.

## Staff roles, leave allowance and database concurrency (16 October 2026)

`GET /api/permissions` publishes one role matrix that the PWA uses to hide tabs
and the staff workspace renders as a table. It is a convenience only: every
endpoint still checks the signed-in role, so hiding a tab grants nothing.
Owner and manager see all seven workspaces; a cashier sees ordering, cashier,
members and their own staff card; kitchen sees the kitchen display, stock and
their own card; service and general staff see ordering and their own card.

Each staff account now carries a yearly leave allowance in `staff_leave_quotas`
(30 sick, 3 personal, 6 vacation by default). Accounts created before this table
existed are backfilled with those defaults on start-up, which is why the staff
page no longer reports "ยังไม่ได้กำหนดโควตาวันลาในระบบ". Approved leave for the
current calendar year is deducted when the remaining days are shown. A manager
sets the name, role, PIN, hourly rate and allowance from the one staff dialog.
PINs remain eight characters or longer; a four-digit PIN is not accepted,
because the same credential opens payroll and sales data.

Today's roster row is now the place shifts and access are set: the shift column
is a dropdown (any configured shift, or วันหยุด, which stores `day_off` and is
never auto-marked absent), and the POS column suspends or restores that person's
sign-in for the day. A manager suspension stores `suspended`, which is separate
from auto-detected `absent`, ends their open sessions, and takes them out of the
pooled commission divisor. Nobody can change their own access, and a manager
cannot touch an owner or another manager.

Every SQLite connection now opens through `connect_db()`, which enables WAL and
a ten-second busy timeout, so the kitchen display can read while the cashier
writes instead of failing on a locked database. The duplicated
`line_pos_prototype.html` copy was removed; that path now redirects to `/`, so
saved links and home-screen shortcuts land on the current app.

## Cancelling and refunding bills (16 October 2026)

Taking a bill back is split in two, because the risk is not the same.

`POST /api/orders/{order_no}/void` cancels a bill that has **not** been paid:
the usual "pressed the wrong item, customer changed their mind" case. A cashier
may do this alone while the bill is at most `POSWAI_VOID_CASHIER_MAX_AMOUNT`
(default 200 baht) and they have used fewer than
`POSWAI_VOID_CASHIER_DAILY_LIMIT` voids that day (default 3). Past either limit
the API refuses and tells them to fetch a manager. Managers and the owner have
no ceiling. Stock goes back, the kitchen ticket disappears, and the bill becomes
`void`.

`POST /api/payments/{order_no}/refund` gives money back on a bill that is
already paid. This is manager or owner only, with no cashier exception, because
it is the point where cash actually leaves the till. The bill and its
`pos_orders` row become `refunded`, stock goes back, and the commission earned
on it is reversed with mirrored negative rows, so payroll history shows both the
credit and the clawback instead of silently losing a record.

Both endpoints demand a reason of 3 to 200 characters, are idempotent on
`event_id`, write an audit row to `order_cancellations` (who, when, how much,
why), and queue a LINE message to every manager with a linked LINE account. The
daily LINE alert is deliberate: it gives the owner the oversight that asking for
a manager PIN at the counter is supposed to give, without stopping the queue.

A manager PIN typed into the till was considered and rejected: in practice the
PIN gets shared with the cashier for the shifts the manager is away, after which
the audit trail records approvals that never happened. If an approval step is
wanted later, send it through the existing LINE approval pipe (the one leave
requests use) rather than a PIN prompt on the device.

The cashier screen does not call these endpoints yet — the sales side is still
sample data behind `POSWAI_PREVIEW_ONLY=1`. Wire the buttons when live sales are
switched on; the rules above are enforced by the API either way.

## Staff dossier (16 October 2026)

The staff workspace has a fifth tab, แฟ้มประวัติ, holding one file per person:
employment facts (nickname, phone, LINE, first working day with the length of
service worked out from it, employment type and the probation review date),
payroll and emergency details (bank, account number, next of kin, a note for
allergies or conditions the kitchen should know about), the hiring document
checklist, store assets the person is holding, and a history of raises,
milestones and written warnings.

The document checklist covers the seven papers a Thai restaurant is asked for,
including the two an inspector checks the date on — the annual medical
certificate and the food handler card — plus the work permit, which counts as
optional because it only applies to foreign staff. Each row records whether the
document was handed in, when it expires and a free note (where the paper copy is
filed). Anything inside 30 days of expiry shows as ใกล้หมดอายุ and anything past
it as หมดอายุแล้ว, and `GET /api/staff/dossier-summary` rolls that up per branch
so the manager can see at a glance who still owes paperwork.

**The server stores facts about documents, not the documents.** No ID card
scans, no uploads. Copies of national ID cards are personal data under the PDPA,
and keeping them on this VPS would mean retention rules, encryption at rest and
a breach plan that this deployment does not have yet. Decide that separately
before adding uploads. For the same reason the dossier never displays a PIN —
PINs are stored only as PBKDF2 hashes and are set, never shown, from the team
overview tab.

A dossier holds pay, bank and health details, so it opens only for the person
themselves (read-only) or a manager or owner of the same branch, who may edit it.
The endpoints are `GET/PATCH /api/staff/{id}/dossier`,
`PUT /api/staff/{id}/documents/{doc_type}`, `POST/PATCH /api/staff/{id}/assets`
and `POST /api/staff/{id}/timeline`.

## The front door (16 October 2026)

Opening the site no longer drops a visitor straight into the ordering screen.
Until someone signs in, a landing page covers the workspace with one action,
เข้าสู่ระบบพนักงาน, and a line telling customers to scan the QR on their table.
A phone that arrives with `table_token` in the URL skips all of it and lands on
the menu for that table, which is the only way a customer should reach ordering
anyway — the API refuses an order without a staff session or a signed table
token. While `POSWAI_PREVIEW_ONLY=1`, the landing also offers
"ดูตัวอย่างระบบโดยไม่เข้าสู่ระบบ" so the owner can still demo the app; that
choice lives in sessionStorage and is forgotten when the tab closes or the
person signs out.

## Preview mode switched off (16 October 2026)

At the owner's request POS WAI now runs as the official site:
`POSWAI_PREVIEW_ONLY=0`. Sales, payments, menu and stock edits are accepted,
and the PWA shows the real menu from the database instead of the built-in
sample menu (live-data.js never mixes the two). The database had no menu
items at the switch, so the ordering screen is empty until a manager adds the
real menu from the stock workspace. The home page no longer offers a demo: its
trial and demo buttons open the shop's LINE OA instead. To go back to a
read-only showcase, set `POSWAI_PREVIEW_ONLY` to `"1"` and recreate the
container; nothing else needs to change.

## หลายร้านและสมาชิก (16 ตุลาคม 2569)

- ร้านแต่ละร้านมีไฟล์ฐานข้อมูลของตัวเองใน `shops/<รหัสร้าน>.db` ข้างไฟล์ร้านหลัก
  ทะเบียนร้านอยู่ที่ `shops.db` ร้านเดิมยังเป็นร้าน `main` ที่ไฟล์เดิมไม่ย้าย
- เปิดร้านใหม่จากหน้าแรก ปุ่ม "ทดลองใช้ฟรี" สร้างร้าน เจ้าของร้าน และ PIN ในขั้นตอนเดียว
  จำกัด 3 ร้านต่อชั่วโมงและ 10 ร้านต่อวันต่อหนึ่งหมายเลขเครือข่าย เพดานร้านทั้งระบบตั้งที่ `POSWAI_MAX_SHOPS` (ค่าเริ่มต้น 500)
- เข้าสู่ระบบต้องใส่รหัสร้านด้วย ลิงก์ของร้านคือ `/?shop=<รหัสร้าน>` QR โต๊ะผูกกับร้านนั้น ใช้ข้ามร้านไม่ได้
- `/?shop=demo` คือร้านตัวอย่าง อ่านอย่างเดียว ใช้ข้อมูลตัวอย่างในหน้าเว็บ ไม่แตะข้อมูลร้านจริง
- สมาชิกร้าน ลูกค้าสมัครเองผ่าน LINE หรือพนักงานสมัครให้ที่หน้าร้านด้วยชื่อและเบอร์โทร
  ทุก 10 บาทได้ 1 แต้ม แคชเชียร์ขึ้นไปบันทึกแต้มและหักแต้มได้ในแท็บสมาชิก
- เจ้าของร้านตั้งชื่อร้านและเลขพร้อมเพย์ของร้านตัวเองได้ที่แท็บสต็อก หัวข้อ "ตั้งค่าร้าน"

## ค่าบริการรายเดือนของร้าน (17 ตุลาคม 2569)

ร้านที่เปิดเองจากหน้าแรกทดลองใช้ฟรี 30 วัน จากนั้นจ่ายค่าบริการเดือนละ 399 บาท
ให้ ZZAX Studio วันหมดอายุคือ `trial_ends_at` ในทะเบียนร้าน (`shops.db`) ทุกครั้งที่
ชำระเงินสำเร็จวันนี้จะถูกเลื่อนออกไปอีก 1 เดือน กติกาทั้งหมดอยู่ใน `poswai_billing.py`
และตาราง `shop_payments` ในทะเบียนร้าน

- **แจ้งเตือนในแอป** เหลือ 7 วันหรือน้อยกว่าขึ้นแถบสีเหลือง เลยกำหนดขึ้นแถบสีแดง
  แถบนี้มาจาก `/api/billing` (ต้องเข้าสู่ระบบ) และ `/api/config` ที่บอกสถานะแบบย่อ
  เฉพาะเจ้าของร้านและผู้จัดการเท่านั้นที่กดปุ่มชำระเงินได้
- **เลยกำหนดแล้ว** `/api/orders`, `/api/online/orders`, `/api/online/manual-orders`
  และ webhook ของส่งไว ตอบ HTTP 402 พร้อมข้อความว่าต้องทำอะไร **ส่วนอื่นเปิดปกติ**
  ทั้งดูเมนู บิลเก่า รายงาน สต็อก พนักงาน และการปิดบิลที่เปิดค้างไว้ก่อนหน้า
  **ไม่มีการลบข้อมูลร้านในทุกกรณี**
- **ช่องทางชำระ** พร้อมเพย์ของ ZZAX Studio + อัปโหลดสลิป ตรวจด้วย EasySlip
  (`POST /api/billing/pay`) ยอดต้องตรงกับ 399 × จำนวนเดือน สลิปหนึ่งใบใช้ได้ครั้งเดียว
  และยิงซ้ำด้วย `event_id` เดิมจะไม่ต่ออายุซ้ำ จ่ายก่อนครบกำหนดจะบวกต่อจากวันเดิม
  จ่ายช้าจะเริ่มนับจากวันนี้ (ค้างหลายเดือนจ่ายเดือนเดียวก็กลับมาใช้งานได้)
- **หน้าทีมงาน** `/admin` เปิดด้วยกุญแจใน `POSWAI_ADMIN_KEY` อย่างเดียว ไม่ใช่บัญชี
  พนักงานร้าน ดูรายชื่อร้านทุกร้าน สถานะการจ่าย และกดยืนยันการโอนที่ตรวจเองด้วยมือได้
  (`POST /api/admin/shops/{slug}/payments`) หน้านี้แตะเฉพาะทะเบียนร้าน ไม่เห็นข้อมูลขายของร้าน

ตัวแปรสภาพแวดล้อมใหม่ ตั้งใน Hostinger Docker Manager (ห้ามใส่ลง Git):

| ตัวแปร | ความหมาย |
| --- | --- |
| `POSWAI_SERVICE_PROMPTPAY_ID` | เลขพร้อมเพย์ของ ZZAX Studio ที่รับค่าบริการ (10/13/15 หลัก) คนละตัวกับ `PROMPTPAY_ID` ของร้าน |
| `POSWAI_SERVICE_EASYSLIP_API_KEY` | คีย์ EasySlip ที่ผูกกับบัญชีรับเงินของ ZZAX Studio ถ้าไม่ตั้ง ปุ่มชำระจะบอกให้ส่งสลิปให้ทีมงานยืนยันแทน |
| `POSWAI_ADMIN_KEY` | กุญแจเปิดหน้า `/admin` ต้องยาวอย่างน้อย 24 ตัว สุ่มใหม่ ห้ามใช้ซ้ำกับรหัสอื่น |
| `POSWAI_MONTHLY_PRICE` | ราคาต่อเดือน ค่าเริ่มต้น 399 (ตรงกับราคาที่ประกาศในหน้าแรก) |

### ตั้งค่าจริงบน VPS แล้ว 17 ตุลาคม 2569

ค่าทั้งสามตัวตั้งไว้แล้วที่ `/docker/poswai` โดยใช้ `0895185188` รับค่าบริการ และใช้
คีย์ EasySlip ตัวเดียวกับที่ร้านหลักใช้อยู่ กุญแจผู้ดูแลสุ่มมา 48 ตัว เก็บที่
`/docker/poswai/admin-key.txt` (สิทธิ์ 600) เปิดดูด้วย `cat /docker/poswai/admin-key.txt`

**กับดักสำคัญ: ปุ่ม "ปรับใช้" ใน Docker Manager เขียนทับไฟล์ `.env` ด้วยสำเนาของตัวเอง**
ค่าทั้งสามตัวจะหายทุกครั้งที่กดปุ่มนั้น ซึ่งรวมถึงทุกครั้งที่ deploy ตามขั้นตอนข้างบน
จึงเก็บต้นฉบับไว้ที่ `/docker/poswai/billing.env` (สิทธิ์ 600) พร้อมสคริปต์กู้คืน

ลำดับ deploy ที่ถูกต้องจึงเป็น

```
cd /docker/poswai
docker compose build poswai
./apply-billing-env.sh
```

`apply-billing-env.sh` เติมค่าที่หายกลับเข้า `.env` แล้วสร้างคอนเทนเนอร์ใหม่ให้เอง
ใช้แทน `docker compose up -d --force-recreate poswai` ได้เลย ตรวจว่าค่าเข้าแล้วด้วย

```
docker compose exec poswai sh -c 'echo ${#POSWAI_ADMIN_KEY}'
```

ได้ 48 แปลว่าใช้ได้ ถ้าได้ 0 แปลว่าค่าหาย ให้รัน `./apply-billing-env.sh` อีกครั้ง
ดูจากนอกเซิร์ฟเวอร์ก็ได้ `curl -s -o /dev/null -w "%{http_code}" https://poswai.zzaxstudio.com/api/admin/shops`
ต้องได้ 401 (กุญแจไม่ถูก) ถ้าได้ 503 แปลว่ายังไม่ได้ตั้งกุญแจ

บัญชีรับเงินของ ZZAX Studio ต้องลงทะเบียนในสาขา EasySlip ของคีย์ที่ใช้ ไม่งั้น
`matchedAccount` จะไม่ผ่านและระบบจะปฏิเสธสลิปทุกใบ ควรใช้คีย์ EasySlip คนละตัวกับ
ของร้าน เพราะโควตาการตรวจสลิปนับรวมกัน ยังไม่ได้ทดสอบกับการโอนจริง ให้ทดสอบโอนจริง
หนึ่งครั้งก่อนบอกร้านว่าชำระเงินผ่านระบบได้

## หน้าแอดมินครบชุด (17 ตุลาคม 2569)

`/admin` ทำได้ครบ 7 อย่างแล้ว ทุก endpoint ยังผ่าน `require_admin_key` และเห็นเฉพาะ
ทะเบียนร้านกับการชำระเงิน ไม่แตะยอดขายหรือข้อมูลลูกค้าของร้าน

1. **ประวัติการชำระ** กดปุ่ม "รายละเอียด" ในแถวร้าน จะกางการ์ดประวัติ ยืนยันรับเงิน
   แถมวันฟรี และสถานะร้านในที่เดียว
2. **ระงับ / ปิดถาวร / เปิดกลับ** `POST /api/admin/shops/{slug}/status` รับ
   `active` `suspended` `closed` ต้องมีเหตุผลเมื่อหยุดใช้งาน ร้านที่ถูกหยุดจะเห็น
   **หน้าบอกเหตุผลและวิธีติดต่อ** ไม่ใช่เด้งไปร้าน main เงียบ ๆ แบบเดิม
   (ทั้งหน้าเว็บ `/?shop=` API และการเข้าสู่ระบบ ตอบ HTTP 403 พร้อมข้อความเดียวกัน)
   `POSWAI_SUPPORT_CONTACT` คือช่องทางติดต่อที่ต่อท้ายข้อความนั้น
3. **ขยายเวลาให้ฟรี** `POST /api/admin/shops/{slug}/grants` ช่องทาง `grant`
   ยอดเงินเป็นศูนย์ ต้องมีเหตุผล 1–365 วัน **ไม่ถูกนับในยอดรายได้ทุกจุด**
   (รายได้รายเดือน ยอดรวมของร้าน และ CSV แยกคอลัมน์ "แถมฟรี" ไว้ต่างหาก)
4. **ค้นหาและกรอง** ชื่อร้าน รหัสร้าน เจ้าของ เบอร์โทร และกรองตามสถานะ ทำในหน้าเว็บ
5. **เตือนทาง LINE** `POST /api/admin/reminders` ส่งให้ทุกร้านที่ใกล้ครบกำหนดและ
   เลยกำหนด ผู้รับคือเจ้าของ/ผู้จัดการที่ผูก LINE ไว้ในฐานข้อมูลของร้านนั้น
   **ข้อความถูกใส่คิว outbox ของฐานข้อมูลร้านหลัก** เพราะตัวส่งเบื้องหลังอ่านจากที่นั่น
   ที่เดียว ร้านที่ยังไม่ผูก LINE จะคืนเบอร์โทรพร้อมข้อความให้กดคัดลอกไปส่งเอง
   ร้านเดียวพังไม่ทำให้ทั้งชุดล้ม และกดซ้ำในวันครบกำหนดเดิมไม่ส่งซ้ำ
6. **รายได้รายเดือน + CSV** `/api/admin/revenue` และ
   `/api/admin/export/shops.csv` `/api/admin/export/payments.csv`
   ไฟล์ CSV มี BOM UTF-8 ให้ Excel ไทยอ่านออก เดือนคิดตามเวลาไทยไม่ใช่ UTC
7. **ปิดถาวรแทนการลบ** ร้านที่ปิดถาวรหายจากรายการหลัก ไม่ถูกนับว่าค้างชำระ
   เข้าใช้งานไม่ได้ แต่ `shops/<slug>.db` ยังอยู่ครบและเปิดกลับได้ทุกเมื่อ
   ติ๊ก "แสดงร้านที่ปิดถาวร" เพื่อดูและเปิดกลับ **ไม่มีโค้ดส่วนใดลบไฟล์ฐานข้อมูลร้าน**
   ยังไม่มีปุ่มดาวน์โหลดข้อมูลขายของร้านก่อนปิด เพราะขัดกับข้อห้ามไม่ให้หน้าแอดมิน
   เข้าถึงข้อมูลขายของร้าน ถ้าต้องการสำรอง ให้ก๊อปไฟล์ `shops/<slug>.db` จากเซิร์ฟเวอร์

ทะเบียนร้านเพิ่มคอลัมน์ `status_reason` กับ `status_changed_at` และ `status`
รับค่า `closed` เพิ่ม ฐานข้อมูลเดิมจะถูกอัปเกรดให้เองตอนเปิดใช้ครั้งแรก (ข้อมูลไม่หาย)

ตัวแปรใหม่ที่ต้องเพิ่มใน `/docker/poswai/billing.env` ด้วย ไม่งั้นหายตอน deploy รอบหน้า:

| ตัวแปร | ความหมาย |
| --- | --- |
| `POSWAI_SUPPORT_CONTACT` | ช่องทางติดต่อที่แสดงให้ร้านที่ถูกระงับหรือปิด เช่น `LINE @151jbyje` ไม่ตั้งก็ได้ ข้อความจะบอกแค่ให้ติดต่อ ZZAX Studio |
