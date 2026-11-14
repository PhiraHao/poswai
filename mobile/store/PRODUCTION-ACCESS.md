# สมัคร Production access รอบที่ 2 — POS WAI

สถานะจาก Play Console (ตรวจ 14 พ.ย. 2569)
- โดนตีกลับรอบแรก **รีวิวเมื่อ 5 พ.ย. 2569 04:29 น.**
- เช็กลิสต์ตอนนี้: ✅ เผยแพร่รุ่นทดสอบแบบปิด · ✅ ผู้ทดสอบ 12 ราย
  ⬜ **"ตอนนี้เลือกรับผู้ทดสอบแล้ว 12 ราย เป็นเวลา 9 วัน"** (ต้องครบ 14 วันนับจากวันตรวจ)
- 9 + 5 = 14 → **กดปุ่ม "สมัครเวอร์ชันที่ใช้งานจริง" ได้วันที่ 19 พ.ย. 2569**
- ⚠️ ตอนนี้มีพอดี **12 คนเป๊ะ** ถ้าใครถอนแอป/ออกจากแทร็กก่อน 19 พ.ย. นาฬิกาเริ่มนับใหม่หมด

## กฎเหล็กของฟอร์ม

**ตอบเป็นภาษาอังกฤษเท่านั้น** ภาษาไทยจะกดส่งไม่ผ่าน (ขึ้น "เกิดข้อผิดพลาดที่ไม่คาดคิด")
เพราะคอนโซลยัดคำตอบลง URL ตัวไทย 1 ตัว = 9 ตัวอักษรใน URL จึงยาวเกินลิมิต
ช่องละไม่เกิน ~250 ตัวอักษร · ก่อนกดส่ง ดูใต้ข้อ 3 ว่าขึ้น "เป็นเวลา 14 วัน" แล้วจริง

---

## คำตอบที่เตรียมไว้ (ก๊อปวางได้เลย)

### 1. How did you recruit testers? / คุณหาผู้ทดสอบมาอย่างไร

```
We invited 19 real shop owners and their staff from our existing LINE customer base in Chiang Mai, plus staff at two shops already running the system daily. All are people who work a till for a living, not volunteers.
```
> ไทย: ชวนเจ้าของร้านจริงกับพนักงาน 19 คนจากฐานลูกค้า LINE ที่เชียงใหม่ รวมถึงพนักงานของ 2 ร้านที่ใช้ระบบอยู่ทุกวัน ทุกคนคือคนที่ยืนหน้าเครื่องคิดเงินจริง

### 2. What feedback did you get from testers? / ได้ความคิดเห็นอะไรบ้าง

```
Testers found real defects: the receipt printed a wrong tax ID, choosing an item size did not add its price, and a bill rang up on a shift change landed in two cash drawers. They also said the app had no settings screen and read as restaurant-only.
```
> ไทย: ผู้ทดสอบเจอข้อผิดพลาดจริง — ใบเสร็จพิมพ์เลขภาษีผิด, เลือกขนาดสินค้าแล้วราคาไม่บวก, บิลที่ตกคาบเปลี่ยนกะไปอยู่ใน 2 ลิ้นชัก และบอกว่าไม่มีหน้าตั้งค่า กับดูเหมือนทำให้ร้านอาหารอย่างเดียว

### 3. What changes did you make from that feedback? / แก้อะไรไปบ้าง

```
We fixed all three defects and added a shop settings screen (legal name, address, tax ID, VAT and service charge, receipt header and footer), barcode scanning, cash shift and drawer tracking, sales reports with CSV export, and tax invoices.
```
> ไทย: แก้ครบทั้ง 3 จุด และเพิ่มหน้าตั้งค่าร้าน (ชื่อนิติบุคคล ที่อยู่ เลขภาษี VAT ค่าบริการ หัว-ท้ายใบเสร็จ), สแกนบาร์โค้ด, กะเงินสดและลิ้นชัก, รายงานยอดขายออก CSV และใบกำกับภาษี

### 4. What is the value of your app / what makes it unique? / แอปมีคุณค่าอะไร

```
POS WAI is a Thai point-of-sale that keeps selling when the internet drops: orders, cash and PromptPay payments and receipt printing all work offline and sync later. It now serves restaurants, retail shops and service shops from one app.
```
> ไทย: POS WAI คือระบบขายหน้าร้านของคนไทยที่ขายต่อได้ตอนเน็ตหลุด — รับออเดอร์ รับเงินสด/พร้อมเพย์ พิมพ์ใบเสร็จได้ออฟไลน์แล้วค่อยซิงก์ รองรับร้านอาหาร ร้านค้า และร้านบริการในแอปเดียว

### 5. Who is your target audience? / กลุ่มผู้ใช้เป้าหมาย

```
Small independent shops in Thailand: restaurants, cafes, grocery and clothing shops, salons and repair shops. Typically one owner and one to five staff, running the till on a single Android phone or tablet with a Bluetooth receipt printer.
```
> ไทย: ร้านเล็กอิสระในไทย — ร้านอาหาร คาเฟ่ ร้านของชำ ร้านเสื้อผ้า ร้านเสริมสวย ร้านซ่อม ส่วนใหญ่มีเจ้าของ 1 คนกับพนักงาน 1–5 คน ใช้มือถือหรือแท็บเล็ต Android เครื่องเดียวกับปริ้นเตอร์บลูทูธ

### 6. How have you tested / is the app ready for production? / พร้อมขึ้นจริงแค่ไหน

```
Two shops have used it for real trade through the closed test, one of them past thirty paid bills. The build has 572 automated tests covering money arithmetic, shift boundaries, stock movements and tax documents, all passing before each release.
```
> ไทย: มี 2 ร้านใช้ขายจริงระหว่างทดสอบแบบปิด ร้านหนึ่งเกิน 30 บิลแล้ว · ตัวระบบมีเทสต์อัตโนมัติ 572 ตัวครอบคลุมการคิดเงิน รอยต่อกะ การเคลื่อนไหวสต็อก และเอกสารภาษี ผ่านครบทุกครั้งก่อนปล่อยรุ่น

### 7. Anything else / how will you keep improving? / อย่างอื่นที่อยากบอก

```
Shop owners reach us on LINE and we ship fixes within days. Next we are adding iOS, in-app ordering chat and per-shop backups. We do not store ID card images on the server, and no shop can read another shop's data.
```
> ไทย: เจ้าของร้านทักมาทาง LINE แล้วเราแก้ให้ภายในไม่กี่วัน · ถัดไปจะทำ iOS แชทในออเดอร์ และสำรองข้อมูลรายร้าน · เราไม่เก็บภาพบัตรประชาชนบนเซิร์ฟเวอร์ และไม่มีร้านไหนอ่านข้อมูลร้านอื่นได้

---

## ⚠️ ถ้าชื่อหัวข้อในฟอร์มไม่ตรงกับด้านบน

ฟอร์มของ Google เปลี่ยนคำถามได้ ให้จับคู่ตามใจความ อย่าแปลไทยลงไปเด็ดขาด
ถ้ามีช่องที่ไม่มีคำตอบเตรียมไว้ ให้เขียนอังกฤษสั้น ๆ 2 ประโยค ไม่เกิน 250 ตัวอักษร
