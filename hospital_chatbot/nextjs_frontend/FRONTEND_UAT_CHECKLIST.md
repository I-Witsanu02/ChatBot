# UPH Hospital Chatbot - Frontend UAT Checklist

This checklist ensures the frontend chat widget remains stable during extended usage and handles common error scenarios gracefully.

## Prerequisites

- Backend FastAPI running on `http://127.0.0.1:8000`
- All knowledge.jsonl and model files up to date
- Frontend code built with stability fixes

## Environment Setup

### 1. Build Frontend

```bash
cd d:\UPH_chatbot\hospital_chatbot\nextjs_frontend

# Set environment variables
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
set NEXT_PUBLIC_DEBUG_CHAT=1

# Build production bundle
npm run build
```

Expected output:
```
✓ Compiled successfully
✓ Next.js build completed
```

### 2. Start Frontend Production Server

```bash
# Continue in nextjs_frontend directory
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
set NEXT_PUBLIC_DEBUG_CHAT=1
npm run start
```

Expected output:
```
▲ Next.js 14.x.x
- Local:        http://localhost:3000
- Environments: .env.local

✓ Ready in XXs
```

### 3. Start Backend (in separate terminal)

```bash
cd d:\UPH_chatbot\hospital_chatbot
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

## Test Cases

### **Test 1: Chat Widget Opens and Closes**

**Steps:**
1. Open browser to `http://localhost:3000`
2. Click the floating chat button (🤖 icon)
3. Verify chat window opens smoothly
4. Click the X button in top-right corner
5. Verify chat closes
6. Click chat button again
7. Verify chat opens again

**Expected Result:** ✅ Chat opens/closes only on user action

---

### **Test 2: Chat State Persists After Page Reload**

**Steps:**
1. Open chat
2. Type and send: "สวัสดี"
3. Wait for bot response
4. Refresh page (F5 or Ctrl+R)
5. Wait for page to load completely

**Expected Result:** ✅
- Chat is still open
- Previous messages are restored
- No blank page or errors
- Console shows: `[UPH_CHAT] restored chat state from sessionStorage`

---

### **Test 3: Chat Sends Messages (30-second timeout test)**

**Steps:**
1. Open chat
2. Type: "ตารางแพทย์"
3. Click send or press Enter
4. Wait for response (should complete within 30 seconds)

**Expected Result:** ✅
- Loading indicator appears ("น้องฟ้ามุ่ยกำลังค้นหาข้อมูลให้ค่ะ")
- Bot responds with category chips
- Chat remains open during loading
- Input field is disabled while loading

---

### **Test 4: Category Navigation (Drill Down)**

**Steps:**
1. Open chat
2. Ask: "ตารางแพทย์"
3. Wait for category chips to appear
4. Click: "ตารางแพทย์และเวลาทำการ"
5. Wait for response
6. Click: "ตารางแพทย์ออกตรวจ"
7. Wait for response
8. Click back arrow (←) button
9. Verify breadcrumb shows: "หน้าหลัก › ตารางแพทย์และเวลาทำการ"

**Expected Result:** ✅
- Navigation is smooth
- Breadcrumbs update correctly
- Back button works
- Chat never closes during navigation

---

### **Test 5: Image/Schedule Display**

**Steps:**
1. Open chat
2. Ask: "มีรูปตารางแพทย์ไหม"
3. Wait for response with image attachments

**Expected Result:** ✅
- Images load and display
- If image fails to load, image is hidden gracefully (no broken image)
- Chat remains fully functional
- No console errors about missing images

---

### **Test 6: Extended Open Duration (20 minutes)**

**Steps:**
1. Open chat
2. Ask initial question: "สวัสดี"
3. Leave chat window open for 20 minutes
4. Check every 5 minutes that chat is still open
5. Periodically send messages: "วัคซีน", "นัดหมาย", "เวชระเบียน"

**Expected Result:** ✅
- Chat remains open the entire time
- No auto-close or reset
- No blank page appears
- Messages are preserved
- User can send messages at any time
- Console shows only debug logs, no errors

---

### **Test 7: Backend Goes Offline**

**Steps:**
1. Open chat
2. Send message: "สวัสดี"
3. While waiting for response, **stop the backend** (Ctrl+C)
4. Wait for timeout (30 seconds)

**Expected Result:** ✅
- Chat **remains open**
- Friendly error message appears:
  ```
  ขออภัยค่ะ ระบบเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ชั่วคราว กรุณาลองใหม่อีกครั้งค่ะ
  ```
- Chat input field remains enabled
- User can try again

**Steps (continued - backend recovery):**
5. Start backend again
6. Type new message: "ยังมีหรือเปล่า"
7. Click send

**Expected Result:** ✅
- After backend restarts, chat can send messages normally
- No need to refresh page
- Chat is still open with previous messages

---

### **Test 8: Network Timeout**

**Steps:**
1. Open browser DevTools (F12)
2. Go to Network tab
3. Set throttling to: **Offline** or **Very Slow 3G**
4. Open chat
5. Try to send message: "ตารางแพทย์"
6. Wait 30+ seconds (until timeout)

**Expected Result:** ✅
- After timeout, friendly error message:
  ```
  ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งหรือโทร 054-466666 ค่ะ
  ```
- Chat **remains open**
- User can try again
- No duplicate timeout messages

Remove throttling, then try again:
6. Remove network throttling
7. Try message again: "สวัสดี"

**Expected Result:** ✅ Message sends successfully

---

### **Test 9: Multiple Categories in Sequence**

**Steps:**
1. Open chat
2. Send: "นัดหมายและตารางแพทย์"
3. Wait for chips, click one
4. Wait for response
5. Use back button to go back
6. Click different chip
7. Repeat 3-4 times with different categories:
   - "วัคซีน"
   - "เวชระเบียน"
   - "สิทธิการรักษา"

**Expected Result:** ✅
- Smooth navigation between categories
- Breadcrumbs track correctly
- Chat never closes
- No state corruption (messages don't duplicate/disappear)
- Input field always available

---

### **Test 10: HMR (Hot Module Reload) - Dev Mode Only**

**Steps (using `npm run dev` instead of `npm run start`):**
1. Open chat with `npm run dev`
2. Send a message
3. Leave chat window open
4. Edit code in page.js (add a space, save)
5. Wait for HMR to reload
6. Observe chat widget

**Expected Result:** ✅
- Chat widget either:
  - Stays open with messages preserved, OR
  - Restores state from sessionStorage
- Chat is not closed after reload
- No console errors

---

### **Test 11: Console Debugging Enabled**

**Steps:**
1. Open DevTools (F12)
2. Go to Console tab
3. Open chat and send message
4. Check for log messages starting with `[UPH_CHAT]`

**Expected Log Output:**
```
[UPH_CHAT] component mount, restoring state
[UPH_CHAT] sendMessage start ตารางแพทย์
[UPH_CHAT] sendMessage success
[UPH_CHAT] closeChat triggered by: user_close
```

**Expected Result:** ✅
- Debug logs appear when `NEXT_PUBLIC_DEBUG_CHAT=1`
- No `undefined` or cryptic error messages
- All chat actions are traced

---

### **Test 12: Error Boundary**

**Steps (Development Only):**
1. Open chat
2. Open DevTools Console
3. Manually throw error:
   ```javascript
   throw new Error("Test error boundary")
   ```
4. Observe page behavior

**Expected Result:** ✅
- Error boundary catches error
- Friendly Thai message displayed:
  ```
  ⚠️ เกิดข้อผิดพลาด
  ขออภัยค่ะ หน้าเว็บเกิดข้อผิดพลาดชั่วคราว กรุณากดโหลดใหม่อีกครั้ง
  ```
- Reload button is clickable
- Page is not blank

---

## Backend Regression Test (Ensure Backend Unchanged)

After frontend UAT passes, run backend regression:

```bash
cd d:\UPH_chatbot\hospital_chatbot
python test_focused_runtime_regression.py http://127.0.0.1:8000
```

**Expected Result:** ✅
- 24/24 PASS
- No regressions introduced by frontend changes

---

## Logs to Check

### Browser Console (F12 → Console tab)

Should contain only:
- `[UPH_CHAT]` debug messages (when NEXT_PUBLIC_DEBUG_CHAT=1)
- No `Uncaught Error` or `Uncaught TypeError`
- No 404 errors for assets/images

### Terminal Output (Backend)

Should show:
- `GET /health/ollama HTTP 200`
- `POST /chat HTTP 200`
- No 5xx errors
- No connection resets

---

## Acceptance Criteria

✅ All tests 1-12 pass
✅ Backend regression: 24/24 PASS
✅ Console has no uncaught errors
✅ Chat widget can remain open indefinitely
✅ Chat state persists across page reloads
✅ Backend offline → friendly error message (no auto-close)
✅ Images load without crashing widget
✅ Navigation is smooth
✅ All messages in Thai display correctly

---

## Troubleshooting

### Chat closes by itself
- Check for `setChatOpen(false)` in page.js (should only be in closeChat function)
- Check browser console for errors
- Enable `NEXT_PUBLIC_DEBUG_CHAT=1` and review logs

### Messages don't restore after reload
- Check browser DevTools → Application → Session Storage
- Verify `uph_chat_ui_v1` key exists with data
- Check browser privacy settings aren't blocking sessionStorage

### Images don't load
- Check `/assets/schedule/*.png` is accessible via backend
- Check browser console Network tab for 404 errors
- Verify `NEXT_PUBLIC_API_BASE_URL` is correct

### Backend timeout but chat should stay open
- Review sendMessage() error handling
- Verify no `setChatOpen(false)` in catch block
- Check `clearLoadingTimer()` is working

---

## Sign-off

- **Tester Name:** ___________________
- **Test Date:** ___________________
- **Status:** ☐ PASS  ☐ FAIL
- **Notes:** ___________________
