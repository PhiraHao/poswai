# POS WAI — แอปสำหรับ iPhone, iPad และ Android

แอปนี้คือ **เปลือก** ที่เปิดเว็บ POS WAI ตัวจริง สิ่งที่มันเพิ่มให้คือสิ่งที่
เว็บทำเองไม่ได้: **Bluetooth** จึงพิมพ์ใบเสร็จออกเครื่องพิมพ์ในร้านได้
จากเครื่องที่ถืออยู่เลย ไม่ต้องมีคอมในร้าน ไม่ต้องลงแอปตัวที่สอง

เพราะเป็นเปลือก **แก้เว็บแล้วแอปได้ของใหม่ทันที ไม่ต้องส่งสโตร์ใหม่** —
ส่งสโตร์อีกทีเฉพาะตอนเปลี่ยนไอคอน ชื่อ สิทธิ์ หรือปลั๊กอิน

## สร้างแอป

```
cd app
```

```
npm install
```

```
npx cap add android
```

```
npx cap add ios
```

```
npm run sync
```

เปิดด้วย `npm run android` (Android Studio) หรือ `npm run ios` (Xcode บนแมค)

## สิทธิ์ที่ต้องใส่ในโปรเจกต์เนทีฟ

**iOS — `ios/App/App/Info.plist`**

```
<key>NSBluetoothAlwaysUsageDescription</key>
<string>ใช้เชื่อมกับเครื่องพิมพ์ใบเสร็จของร้าน</string>
```

**Android — `android/app/src/main/AndroidManifest.xml`**

```
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" android:usesPermissionFlags="neverForLocation" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30" />
```

## ของที่ยังต้องเตรียมเอง

- ไอคอนกับหน้าจอเปิดแอป (`resources/icon.png` 1024×1024 แล้วใช้ `@capacitor/assets`)
- **บัญชีนักพัฒนา Apple** ปีละ ~3,500 บาท (Android มีอยู่แล้วจากหวัดดี)
- iOS ต้อง build บนเครื่องแมคเท่านั้น

## ทำไมต้องเป็นแอป ทั้งที่มีเว็บอยู่แล้ว

เว็บบน iPhone แตะ Bluetooth ไม่ได้เลย Apple ไม่รองรับ Web Bluetooth และ
ประกาศชัดว่าจะไม่ทำ ส่วนเครื่องพิมพ์ 58 มม. ที่ร้านเล็กใช้กันก็ไม่มี AirPrint
ทางเดียวที่ไอโฟนจะพิมพ์ออกเครื่องพิมพ์ของร้านได้คือผ่านแอปที่ลงในเครื่อง

ในแอปนี้ หน้าแคชเชียร์จะมีกล่อง **“เครื่องพิมพ์ของเครื่องนี้”** เพิ่มขึ้นมา
กดเชื่อมครั้งเดียวแล้วปุ่มพิมพ์ใบแจ้งหนี้กับปิดบิลจะพิมพ์ออกทันที

ส่วนคิวงานพิมพ์ (`PRINTING.md`) ยังอยู่และยังมีประโยชน์ สำหรับร้านที่อยาก
ให้พนักงานหลายคนสั่งพิมพ์ไปออกที่เครื่องพิมพ์ตัวเดียวที่เครื่องอื่นถืออยู่
