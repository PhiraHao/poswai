# POS WAI บน App Store (iPhone)

ทุกอย่างที่เตรียมไว้แล้ว และขั้นตอนที่ต้องทำบนเครื่อง Mac

---

## เตรียมไว้ให้แล้ว (ทำบนวินโดวส์ได้ ทำเสร็จแล้ว)

| อะไร | ที่อยู่ | สถานะ |
|---|---|---|
| โปรเจกต์ Xcode | `mobile/ios/App/App.xcodeproj` | ✅ |
| Bundle ID | `com.zzaxstudio.poswai` (ตัวเดียวกับ Android) | ✅ |
| เวอร์ชัน | 1.0.1 (build 1) | ✅ |
| iOS ต่ำสุด | 15.0 | ✅ |
| ไอคอนแอป | `Assets.xcassets/AppIcon.appiconset` 1024×1024 ไม่มีพื้นโปร่ง | ✅ โลโก้ใหม่ |
| หน้าเปิดแอป | `Assets.xcassets/Splash.imageset` มาสคอต + โลโก้ | ✅ โลโก้ใหม่ |
| ไฟล์เว็บในแอป | `ios/App/App/public` (sync ด้วย `npx cap copy ios`) | ✅ ตรงกับ www |
| ข้อความขอสิทธิ์ (ภาษาไทย) | `Info.plist` — กล้อง, Bluetooth, เครือข่ายในร้าน | ✅ |
| พิมพ์ผ่าน LAN/ครัว | `ios/App/App/TcpPrinterPlugin.swift` + `MainViewController.swift` | ✅ คอมไพล์ผ่านและทดสอบจริงบนซิมูเลเตอร์แล้ว |
| เครื่องเป้าหมาย | iPhone อย่างเดียว (`TARGETED_DEVICE_FAMILY = 1`) | ✅ ตัด iPad ออกแล้ว |
| พิมพ์ผ่าน Bluetooth | ปลั๊กอิน `@capacitor-community/bluetooth-le` | ✅ รองรับ iOS อยู่แล้ว |

สร้างไอคอน/หน้าเปิดใหม่เมื่อโลโก้เปลี่ยน: `python mobile/make-icons.py` (เขียนทั้ง Android และ iOS)

---

## สิ่งที่ขาด และต้องมีจริง ๆ

1. **เครื่อง Mac** — Xcode ลงได้เฉพาะ macOS ไม่มีทางลัด (เช่า Mac ชั่วโมงละไม่กี่สิบบาทก็ได้ เช่น MacStadium, MacinCloud)
2. **Apple Developer Program** — **99 USD/ปี (~3,500 บาท)** จ่ายแล้วถึงจะส่งขึ้น App Store ได้
   (ต่างจาก Google Play ที่จ่ายครั้งเดียว 25 USD) — **ยังไม่ได้จ่าย ต้องให้เจ้าของตัดสินใจก่อน**
3. **iPhone จริง 1 เครื่อง** สำหรับทดสอบเครื่องพิมพ์ (ซิมูเลเตอร์ต่อ Bluetooth/LAN printer ไม่ได้)

---

## ขั้นตอนบน Mac

ลงก่อน: **Xcode** (จาก App Store) และ **Node.js** (`brew install node` หรือ nodejs.org)
ไม่ต้องลง CocoaPods — โปรเจกต์นี้ใช้ Swift Package Manager (`ios/App/CapApp-SPM`) แล้ว

```bash
git clone -b codex/pwa-api-offline-deploy https://github.com/PhiraHao/poswai.git
```
```bash
cd poswai/mobile
```
```bash
npm install
```
```bash
npm run build
```
```bash
npx cap sync ios
```
```bash
npx cap open ios
```

ใน Xcode:
1. เลือก target **App** → แท็บ **Signing & Capabilities**
   - ติ๊ก *Automatically manage signing*
   - Team = บัญชี Apple Developer ที่จ่ายแล้ว
2. (ไม่ต้องทำแล้ว) เรื่องไฟล์ปลั๊กอินและการตัด iPad ทำเสร็จในโปรเจกต์แล้ว
3. เสียบ iPhone จริง → กด Run → **ทดสอบ 3 อย่างนี้ก่อน**
   - พิมพ์ใบเสร็จผ่าน Bluetooth
   - พิมพ์ใบครัวผ่าน LAN (ครั้งแรก iOS จะถามขอสิทธิ์ "ค้นหาอุปกรณ์ในเครือข่าย" → ต้องกดอนุญาต)
   - สแกนบาร์โค้ดด้วยกล้อง
4. **Product → Archive** → *Distribute App* → *App Store Connect* → *Upload*

---

## ที่ต้องกรอกใน App Store Connect

ใช้ข้อความชุดเดียวกับ Play Store ได้เลย (อยู่ใน `PLAY-STORE.md`) ที่ต่างมีดังนี้

- **ชื่อแอป (≤30):** POS WAI - ระบบขายหน้าร้าน
- **Subtitle (≤30):** ขายหน้าร้าน ส่งครัว รับเงิน
- **หมวด:** Business (รอง: Food & Drink)
- **คำสำคัญ (≤100 ตัวอักษร รวมคอมมา):** POS,ขายหน้าร้าน,ร้านอาหาร,ใบเสร็จ,คาเฟ่,เครื่องคิดเงิน,สั่งอาหาร,พร้อมเพย์
- **URL นโยบายความเป็นส่วนตัว:** https://poswai.zzaxstudio.com/privacy.html
- **URL สนับสนุน:** https://poswai.zzaxstudio.com
- **ลิขสิทธิ์:** ZZAX Studio
- **อายุ:** 17+ หรือ 18+ (ให้ตรงกับที่แจ้ง Play ว่า 18 ปีขึ้นไป)

### ภาพหน้าจอที่ App Store บังคับ
- **iPhone 6.9 นิ้ว** (1320×2868 หรือ 1290×2796) — อย่างน้อย 3 ภาพ **บังคับ**
- iPhone 6.5 นิ้ว (1242×2688) — บังคับถ้ารองรับเครื่องรุ่นเก่า
- iPad 13 นิ้ว — บังคับเฉพาะถ้าเปิดขายบน iPad ด้วย
  **ตั้งเป็น iPhone อย่างเดียวแล้ว** (Supported Destinations เหลือ iPhone) จึงไม่ต้องทำภาพ iPad

ภาพชุด Android ใช้ไม่ได้ เพราะขนาดไม่ตรง ต้องถ่ายใหม่จาก iPhone จริงหรือซิมูเลเตอร์

### App Privacy (ตอบให้ตรงกับ Data safety ของ Play)
เก็บและผูกกับตัวตนผู้ใช้ ไม่ใช้ติดตามโฆษณา:
- Contact Info → Name, Email Address, Phone Number
- Identifiers → User ID
- Purchases → Purchase History
- User Content → Photos

ไม่เก็บ: ตำแหน่ง, รายชื่อติดต่อ, ข้อความ, สุขภาพ, ข้อมูลการเงิน (บัตร/บัญชี), ข้อมูลโฆษณา
ทุกข้อเลือก "Used for App Functionality" (รหัสผู้ใช้/อีเมล เพิ่ม "Account Management")

### ข้อมูลให้ผู้ตรวจ (App Review Information)
ใช้ชุดเดียวกับ Play:
```
Shop code: zzaxstudio
Staff ID: 1
PIN: 88889999
Open the app, tap Sign in, choose the Staff tab, then enter the three values above.
This is the shop owner account, so every screen is available.
Nothing in the app requires a purchase.
```

---

## กับดักที่คาดว่าจะเจอตอนส่งตรวจ

1. **ค่าบริการรายเดือน 399 บาท** — กฎ App Store เข้มกว่า Play ด้วยซ้ำ (ข้อ 3.1.1)
   ตอนนี้แอปเป็นแบบ consumption-only อยู่แล้ว (ซื้ออะไรในแอปไม่ได้ ต่ออายุที่เว็บ)
   แต่ **หน้าแรกในแอปยังมีตารางราคา 399 บาท/เดือน** — Apple ทักเรื่องนี้บ่อยกว่า Google
   ถ้าโดนตีกลับ ให้ซ่อนตารางราคาเมื่ออยู่ในแอป (คลาส `poswai-app`) แล้วส่งใหม่
2. **สิทธิ์เครือข่ายในร้าน** — ถ้าผู้ตรวจกดไม่อนุญาต แล้วลองพิมพ์ LAN จะเจอ error
   ควรเขียนใน Review Notes ว่าเครื่องพิมพ์ LAN ต้องมีเครื่องพิมพ์จริงถึงจะทดสอบได้
3. **Bluetooth** — Apple อาจถามว่าใช้ทำอะไร ตอบว่าส่งใบเสร็จไปเครื่องพิมพ์ความร้อนของร้าน
4. **แอปที่ต้องล็อกอิน** — ต้องให้บัญชีทดสอบเสมอ (ใส่ไว้ด้านบนแล้ว)

---

## บั๊กที่เจอตอนคอมไพล์ครั้งแรก (แก้แล้ว)

ปลั๊กอินคอมไพล์ผ่านตั้งแต่ครั้งแรกโดยไม่มี error — แต่ **แอปจะพิมพ์ LAN ไม่ได้เลย**
เพราะ Capacitor 8 ลงทะเบียนเฉพาะปลั๊กอินที่อยู่ใน `packageClassList` (ซึ่ง `cap sync`
เขียนจาก npm package เท่านั้น) ส่วน `TcpPrinterPlugin` อยู่ใน target ของแอปเอง
จึงไม่เคยถูกลงทะเบียน — `window.Capacitor.Plugins.TcpPrinter` เป็น undefined

แก้ด้วย `MainViewController` (subclass ของ `CAPBridgeViewController`) ที่เรียก
`registerPluginInstance(TcpPrinterPlugin())` แล้วให้ `SceneDelegate` ใช้คลาสนี้แทน
(`SceneDelegate` สร้างหน้าจอเองด้วยโค้ด ไม่ได้อ่าน Main.storyboard) การแก้นี้อยู่รอด
`npx cap sync ios` รอบถัดไป

อีกจุด: ตอนส่งไบต์ใช้ `contentContext: .finalMessage` เพื่อปิดซ็อกเก็ตแบบ FIN
เหมือนฝั่ง Android (write → flush → close) ของเดิม cancel ทันทีหลังส่ง ซึ่งอาจ RST
ทิ้งท้ายใบเสร็จได้

ยืนยันแล้วบนซิมูเลเตอร์: `TcpPrinter` ขึ้นในรายการปลั๊กอิน, ส่ง 20,480 ไบต์ถึงปลายทาง
ครบถ้วน (CRC ตรง), และตอนไม่มีเครื่องพิมพ์ได้ error `Connection refused` ซึ่ง `app-printer.js`
แปลเป็นข้อความไทยที่ถูกต้อง

---

## สรุปสั้น ๆ

โค้ดฝั่ง iPhone พร้อมแล้ว build ผ่านทั้ง Debug และ Release เหลือแค่ 3 อย่างที่ผู้ช่วยทำแทนไม่ได้
1. จ่ายค่า Apple Developer 99 USD/ปี
2. เซ็น Signing ด้วยบัญชีจริง + เสียบ iPhone ทดสอบเครื่องพิมพ์ แล้ว Archive/Upload
3. ถ่ายภาพหน้าจอจาก iPhone
