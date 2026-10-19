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
| พิมพ์ผ่าน LAN/ครัว | `ios/App/App/TcpPrinterPlugin.swift` | ✅ เขียนแล้ว **ยังไม่เคยคอมไพล์** |
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

```bash
# 1. ดึงโค้ดและลงของ
git clone <repo> && cd poswai/mobile
npm install
sudo gem install cocoapods      # ถ้ายังไม่มี
npx cap sync ios

# 2. เปิดโปรเจกต์
npx cap open ios
```

ใน Xcode:
1. เลือก target **App** → แท็บ **Signing & Capabilities**
   - ติ๊ก *Automatically manage signing*
   - Team = บัญชี Apple Developer ที่จ่ายแล้ว
2. ตรวจว่าไฟล์ **TcpPrinterPlugin.swift** อยู่ใน *Build Phases → Compile Sources*
   (ใส่ไว้ในโปรเจกต์ให้แล้ว ถ้าไม่เห็นให้ลากไฟล์เข้าไปแล้วติ๊ก target App)
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
  **แนะนำให้ตั้งเป็น iPhone อย่างเดียวก่อน** (Xcode → General → Supported Destinations เอา iPad ออก)
  จะได้ไม่ต้องทำภาพ iPad และไม่ต้องทดสอบ iPad

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

## สรุปสั้น ๆ

โค้ดฝั่ง iPhone พร้อมแล้ว เหลือแค่ 3 อย่างที่ผู้ช่วยทำแทนไม่ได้
1. จ่ายค่า Apple Developer 99 USD/ปี
2. หา Mac มา build + เสียบ iPhone ทดสอบเครื่องพิมพ์
3. ถ่ายภาพหน้าจอจาก iPhone
