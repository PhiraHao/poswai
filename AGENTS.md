# AGENTS.md — Instructions for OpenAI Codex (POS WAI Project)

## Project Overview
**POS WAI** is an Offline-First, Mobile-First Restaurant & Cafe POS system integrated with **LINE Front-end Framework (LINE LIFF)** and **LINE Messaging API**.
- **Frontend (`index.html` / `line_pos_prototype.html`)**: Single-page progressive web app (PWA) with 7 modules:
  1. Customer QR Self-Ordering, Multi-language (`TH` / `EN` / `CN`), Service Call via QR, Quick Menu Edit & 86 List (Sold Out), Drag-and-Drop Menu Reordering, Per-Item Custom Modifiers/Add-ons (Coffee Sweetness vs Spicy Food vs Tom Yum vs Somtum), Step-by-Step Combo Builder, and Smart Cart Auto-Promotions.
  2. Station-Routed Kitchen Display System (KDS: Hot Kitchen, Cold Kitchen, Bar) with Course Hold/Fire control.
  3. Cashier POS with Shift/Cash Drawer Management (Z-Report), Dynamic Table Builder (Add/Remove/Move/Merge/Reserve tables), Split Bill (Equal & By Item), VAT 7% & Full Tax Invoice, Dynamic EMVCo PromptPay QR Generator (CRC-16), Slip Verification, and Web Bluetooth / RawBT / Wi-Fi ESC/POS Receipt Printing.
  4. Real-time Inventory & Hybrid BOM Recipe Deduction, Single-Store vs Multi-Branch stock transfer, Waste Log, FIFO Expiry Alerts, and Purchase Order (PO) generation via LINE.
  5. CRM Tier Membership (Silver/Gold/Platinum), Points & Vouchers, and Delivery Hub Webhook integration (GrabFood, LINE MAN, ShopeeFood, TikTok Shop).
  6. Staff Attendance & LINE LIFF Leave Request (with real medical certificate image upload), Manager LINE Flex Message Approval, Auto-Absence Detection (>60 mins), Temporary POS PIN Lockout for staff on leave/absent, and Pooled Equal vs Individual Commission Engine (automatically excluding on-leave/absent staff from `pool_divisor`).
  7. Executive BI & Predictive Analytics Dashboard (DoD/WoW Comparative Benchmarking, Channel & Payment Split, 4-Group BCG Menu Engineering Matrix, 7-Day Peak Hour Heatmap, KDS Speed Bottleneck, Predictive Staffing Roster, Food Cost/Wastage %, and Customer Retention/LTV).
- **Backend (`line_pos_server.py`)**: Python FastAPI server with a 5-module Relational Database Schema (`branches`, `staffs`, `shift_templates`, `staff_shifts`, `attendances`, `leave_requests`, `pos_orders`, `commission_rules`, `commission_records`), EMVCo PromptPay QR generator, and TCP Port 9100 Wi-Fi ESC/POS thermal printer bridge.

## Tasks for Codex
When asked to prepare or deploy this repository:
1. **Register PWA Service Worker**: Ensure `index.html` and `line_pos_prototype.html` register `/service-worker.js` and link `/manifest.json` so the POS continues working seamlessly when the restaurant's internet drops.
2. **Connect Frontend Actions to FastAPI Endpoints**: Wire frontend actions (`submitOrderFromCustomer`, `confirmPaymentAndPrint`, `submitLineLeaveRequest`, `reviewLeaveRequest`, `recordAttendance`, and `flushOfflineSyncQueue`) to call the FastAPI endpoints in `line_pos_server.py` with automatic fallback to `localStorage` (`offlineSyncQueue`) when offline.
3. **Production Database & Environment Config**: Read environment variables (`DATABASE_URL`, `PROMPTPAY_ID`, `LINE_LIFF_ID`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`) in `line_pos_server.py` while keeping SQLite as the zero-config default.
4. **Verify & Test**: Run `python3 -m py_compile line_pos_server.py` and start `uvicorn line_pos_server:app --host 0.0.0.0 --port 8000` to verify all endpoints return HTTP 200.
