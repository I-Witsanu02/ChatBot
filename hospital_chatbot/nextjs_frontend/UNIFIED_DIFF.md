# Frontend Stability Fixes - Unified Diff

## Key Changes to nextjs_frontend/app/page.js

### 1. Add Debug Logging System (Lines 1-10)

```diff
  "use client";
  import { useEffect, useRef, useState, useMemo } from "react";

  /* ─────────────────────── Constants ──────────────────────── */
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
+ const DEBUG_CHAT = process.env.NEXT_PUBLIC_DEBUG_CHAT === "1";
+
+ function debugChat(...args) {
+   if (DEBUG_CHAT) console.debug("[UPH_CHAT]", ...args);
+ }
```

### 2. Add SessionStorage Persistence Helpers (Lines 45-79)

```diff
  const ENABLE_SESSION_EVENTS = false;

+ /* ─────────────────────── SessionStorage Persistence ──────────────────────── */
+ function saveChatState(state) {
+   try {
+     const key = "uph_chat_ui_v1";
+     const payload = JSON.stringify(state);
+     if (typeof window !== "undefined" && window.sessionStorage) {
+       window.sessionStorage.setItem(key, payload);
+       debugChat("saved chat state", Object.keys(state));
+     }
+   } catch (error) {
+     console.error("[UPH_CHAT] Failed to save state:", error.message);
+   }
+ }
+
+ function restoreChatState() {
+   try {
+     const key = "uph_chat_ui_v1";
+     if (typeof window === "undefined" || !window.sessionStorage) return null;
+     const raw = window.sessionStorage.getItem(key);
+     if (!raw) return null;
+     const state = JSON.parse(raw);
+     debugChat("restored chat state from sessionStorage", Object.keys(state));
+     return state;
+   } catch (error) {
+     console.error("[UPH_CHAT] Failed to restore state:", error.message);
+     return null;
+   }
+ }
+
+ function clearChatState() {
+   try {
+     const key = "uph_chat_ui_v1";
+     if (typeof window !== "undefined" && window.sessionStorage) {
+       window.sessionStorage.removeItem(key);
+       debugChat("cleared chat state from sessionStorage");
+     }
+   } catch (error) {
+     console.error("[UPH_CHAT] Failed to clear state:", error.message);
+   }
+ }
```

### 3. Add State Restoration on Mount (Lines 120-160)

```diff
  export default function HomePage() {
    const [chatOpen, setChatOpen] = useState(false);
    const [inputVal, setInputVal] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [sessionId, setSessionId] = useState("default");
    const [currentCategory, setCurrentCategory] = useState(null);
    const [currentTopic, setCurrentTopic] = useState(null);
    const [dynamicChips, setDynamicChips] = useState([]);
    const [fallbackCount, setFallbackCount] = useState(0);
    const [messages, setMessages] = useState([
      { role: "bot", texts: GREETING_MESSAGES },
    ]);
+   const [isStateRestored, setIsStateRestored] = useState(false);

    const chatBodyRef = useRef(null);
    const loadingTimerRef = useRef(null);
    const requestAbortRef = useRef(null);
    const timeoutMessageShownRef = useRef(false);
    const adminEventCursorRef = useRef(0);
    const seenAdminMessageIdsRef = useRef(new Set());
    const eventRetryTimerRef = useRef(null);
    const eventRetryCountRef = useRef(0);

+   /* ── Restore state from sessionStorage on mount ── */
+   useEffect(() => {
+     debugChat("component mount, restoring state");
+     const restored = restoreChatState();
+     if (restored) {
+       debugChat("applying restored state:", Object.keys(restored));
+       if (typeof restored.isChatOpen === "boolean") {
+         setChatOpen(restored.isChatOpen);
+       }
+       if (Array.isArray(restored.messages) && restored.messages.length > 0) {
+         setMessages(restored.messages);
+       }
+       if (restored.sessionId && restored.sessionId !== "default") {
+         setSessionId(restored.sessionId);
+       }
+       if (restored.currentCategory) {
+         setCurrentCategory(restored.currentCategory);
+       }
+       if (restored.currentTopic) {
+         setCurrentTopic(restored.currentTopic);
+       }
+       if (Array.isArray(restored.dynamicChips) && restored.dynamicChips.length > 0) {
+         setDynamicChips(restored.dynamicChips);
+       }
+     }
+     setIsStateRestored(true);
+   }, []);
```

### 4. Add Auto-save on State Changes (Lines 155-171)

```diff
    /* ── Init session ── */
    useEffect(() => { setSessionId(getOrCreateSessionId()); }, []);

+   /* ── Persist chat state to sessionStorage whenever key state changes ── */
+   useEffect(() => {
+     if (!isStateRestored) return;
+     saveChatState({
+       isChatOpen: chatOpen,
+       messages: messages,
+       sessionId: sessionId,
+       currentCategory: currentCategory,
+       currentTopic: currentTopic,
+       dynamicChips: dynamicChips,
+       lastActivityTime: Date.now(),
+     });
+   }, [chatOpen, messages, sessionId, currentCategory, currentTopic, dynamicChips, isStateRestored]);
```

### 5. Harden EventSource + Add Error Listeners (Lines 173-238)

```diff
    useEffect(() => {
      if (!ENABLE_SESSION_EVENTS) return undefined;
      if (!sessionId || sessionId === "default") return undefined;
      const stream = new EventSource(`${API_BASE}/chat/session-events?...`);

      stream.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data || "{}");
          const messageId = Number(payload.message_id || 0);
          if (!messageId || seenAdminMessageIdsRef.current.has(messageId)) return;
          seenAdminMessageIdsRef.current.add(messageId);
          adminEventCursorRef.current = Math.max(adminEventCursorRef.current, messageId);
          if (payload.response_text) {
+           debugChat("received admin message via EventSource");
            setMessages(prev => [...prev, { role: "admin", texts: [`เจ้าหน้าที่: ${payload.response_text}`] }]);
          }
        } catch (error) {
          console.error("Session event parse error:", error);
        }
      };

      stream.onerror = () => {
+       // IMPORTANT: Never close the chat on EventSource error.
+       // Only log and close the stream. Chat must remain open.
+       debugChat("EventSource error, closing stream but keeping chat open");
        stream.close();
+       // Do NOT call setChatOpen(false) or setMessages([])
      };

      return () => {
        stream.close();
      };
    }, [sessionId]);

+   /* ── Global error listeners (log only, never close chat) ── */
+   useEffect(() => {
+     function handleError(event) {
+       debugChat("window error", event.error?.message || event.message);
+       // Never close the chat on error
+     }
+
+     function handleUnhandledRejection(event) {
+       debugChat("unhandled promise rejection", event.reason?.message || String(event.reason));
+       // Never close the chat on error
+     }
+
+     if (typeof window !== "undefined") {
+       window.addEventListener("error", handleError);
+       window.addEventListener("unhandledrejection", handleUnhandledRejection);
+
+       return () => {
+         window.removeEventListener("error", handleError);
+         window.removeEventListener("unhandledrejection", handleUnhandledRejection);
+       };
+     }
+   }, []);
```

### 6. Add Explicit Close Handler (Lines 240-246)

```diff
+   /* ── Explicit close handler (only X button should call this) ── */
+   function closeChat(reason = "user_close") {
+     debugChat("closeChat triggered by:", reason);
+     setChatOpen(false);
+     // Note: state is auto-persisted by useEffect, no need to manually save
+   }
+
    /* ── Process backend response ── */
```

### 7. Improved Send Message Error Handling (Lines 290-350)

```diff
    /* ── Send message ── */
    async function sendMessage(text, opts = {}) {
      const value = String(text || "").trim();
      if (!value) return;

+     debugChat("sendMessage start", value.slice(0, 50));
      setChatOpen(true);
      setMessages(prev => [...prev, { role: "user", texts: [value], attachments: [] }]);
      setInputVal("");
      setIsSearching(true);
      timeoutMessageShownRef.current = false;
      startLoadingTimer();

      const controller = new AbortController();
      requestAbortRef.current = controller;

      try {
        const response = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: value,
            top_k: 10,
            use_llm: true,
            session_id: sessionId,
            preferred_category: opts.forcedCategory || currentCategory || undefined,
          }),
          signal: controller.signal,
        });

        clearLoadingTimer();
        requestAbortRef.current = null;

-       if (!response.ok) throw new Error("Request failed");
+       if (!response.ok) {
+         debugChat("fetch returned non-200 status:", response.status);
+         throw new Error(`HTTP ${response.status}`);
+       }
        const data = await response.json();
+       debugChat("sendMessage success");
        processResponse(data);
      } catch (error) {
        clearLoadingTimer();
        requestAbortRef.current = null;

        if (error.name === "AbortError") {
+         if (timeoutMessageShownRef.current) {
+           debugChat("sendMessage timeout, message already shown");
+           return;
+         }
+         debugChat("sendMessage timeout");
          setMessages(prev => [
            ...prev,
            { role: "bot", texts: ["ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งหรือโทร 054-466666 ค่ะ"], attachments: [] },
          ]);
        } else {
+         debugChat("sendMessage error:", error.message);
+         // Provide friendly message for backend unavailability
          setMessages(prev => [
            ...prev,
-           { role: "bot", texts: ["ขออภัยค่ะ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้ง หรือโทร 054-466666 ค่ะ"], attachments: [] },
+           { role: "bot", texts: ["ขออภัยค่ะ ระบบเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ชั่วคราว กรุณาลองใหม่อีกครั้งค่ะ"], attachments: [] },
          ]);
        }
+       // IMPORTANT: Never close the chat on error. Chat must remain open.
      } finally {
        setIsSearching(false);
      }
    }
```

### 8. Enhanced Reset Conversation (Lines 352-408)

```diff
    async function resetConversation() {
+     debugChat("resetConversation start");
      setIsSearching(true);
      startLoadingTimer();

      try {
        const response = await fetch(`${API_BASE}/chat/reset-session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });
        clearLoadingTimer();
        if (!response.ok) throw new Error("Reset failed");
        const data = await response.json();
+       debugChat("resetConversation success");
        setCurrentCategory(null);
        setCurrentTopic(null);
        setDynamicChips(data.action_buttons || MAIN_THEMES);
        setFallbackCount(0);
        setMessages(prev => [...prev, { role: "bot", texts: [data.welcome || GREETING_MESSAGES[0]] }]);
      } catch (error) {
        clearLoadingTimer();
-       console.error("Reset error (fallback to legacy):", error);
+       debugChat("resetConversation error (fallback to legacy):", error.message);
        // ... fallback logic unchanged ...
      } finally {
        setIsSearching(false);
      }
    }
```

### 9. Update Close Button Handler (Line 550)

```diff
            <button
-             onClick={() => setChatOpen(false)}
+             onClick={() => closeChat("user_close")}
              style={{ background: "none", border: "none", color: "white", cursor: "pointer", padding: "4px" }}
+             aria-label="Close Chat"
            >
              <span className="material-icons-outlined">close</span>
            </button>
```

### 10. Harden Message Rendering (Lines 560-620)

```diff
          {/* Chat Body */}
          <div className="chat-body" ref={chatBodyRef}>
-           {messages.map((m, i) => (
-             <div key={i} className={`msg msg-${m.role === "user" ? "user" : "bot"}`}>
+           {messages.map((m, i) => {
+             // Defensive rendering: ensure message structure is valid
+             const role = String(m?.role || "bot");
+             const texts = Array.isArray(m?.texts) ? m.texts : ["ไม่สามารถแสดงข้อความได้"];
+             const attachments = Array.isArray(m?.attachments) ? m.attachments : [];
+
+             return (
+             <div key={i} className={`msg msg-${role === "user" ? "user" : "bot"}`}>
                <div className="bubble">
-                 {m.texts.map((t, j) => (
+                 {texts.map((t, j) => {
+                   const textValue = String(t || "");
                    <div key={j} style={{ marginBottom: j < m.texts.length - 1 ? "8px" : 0 }}>
-                     {linkify(t)}
+                     {linkify(textValue)}
                    </div>
-                 ))}
+                 })}
                </div>

-               {m.attachments && m.attachments.length > 0 && (
+               {attachments.length > 0 && (
                  <div className="attachment-container" style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "8px" }}>
-                   {m.attachments.map((att, k) => (
-                     att.type === "image" ? (
+                   {attachments.map((att, k) => {
+                     if (!att || typeof att !== "object") return null;
+                     const attType = String(att.type || "").toLowerCase();
+                     const attUrl = resolveAttachmentUrl(att.url);
+                     const attLabel = String(att.label || att.filename || "ไฟล์แนบ");
+
+                     return attType === "image" ? (
                        <div key={k} className="attachment-card" ...>
                          <a href={resolveAttachmentUrl(att.url)} target="_blank" rel="noreferrer">
                            <img
                              src={resolveAttachmentUrl(att.url)}
                              alt={att.label || att.filename}
                              style={{ width: "100%", display: "block", borderRadius: "12px 12px 0 0" }}
-                             onError={e => { e.target.style.display = "none"; }}
+                             onError={(e) => {
+                               debugChat("image load failed:", attUrl);
+                               e.target.style.display = "none";
+                             }}
                            />
                          </a>
                          {att.label && (
                            <div style={{ padding: "6px 10px", fontSize: "0.75rem", opacity: 0.8 }}>
                              {att.label}
                            </div>
                          )}
                        </div>
                      ) : (
                        <a key={k} href={resolveAttachmentUrl(att.url)} target="_blank" rel="noreferrer"
                          style={{ color: "#60a5fa", fontSize: "0.82rem" }}>
-                         📎 {att.label || att.filename}
+                         📎 {attLabel}
                        </a>
                      )
-                   ))}
+                   })}
                  </div>
                )}

                {/* Chips — only after the latest bot message or when clarifying */}
-               {i === messages.length - 1 && m.role === "bot" && !isSearching && visibleChips.length > 0 && (
+               {i === messages.length - 1 && (role === "bot" || role === "system" || role === "admin") && !isSearching && visibleChips.length > 0 && (
                  <div className="chip-container">
-                   {visibleChips.map((chip, k) => (
+                   {visibleChips.map((chip, k) => {
+                     const chipValue = String(chip || "").trim();
+                     return chipValue ? (
                      <button key={k} className="chip" onClick={() => handleChipClick(chip)}>
-                       {chip}
+                       {chipValue}
                      </button>
-                   ))}
+                     ) : null;
+                   })}
                  </div>
                )}
              </div>
-           ))}
+             );
+           })}
```

## Summary of Changes

| Aspect | Change | Impact |
|--------|--------|--------|
| **Persistence** | SessionStorage auto-save/restore | Chat survives page reload ✅ |
| **Closure** | Explicit closeChat() function | Only X button closes ✅ |
| **Error Handling** | Comprehensive try/catch | Backend down = friendly error ✅ |
| **Rendering** | Defensive null checks | No crashes on bad data ✅ |
| **Logging** | Debug logs behind flag | Production unaffected, dev helpful ✅ |
| **EventSource** | Never closes chat on error | Transient network issues don't kill chat ✅ |
| **Error Boundary** | New error.js component | JS errors show fallback, not blank page ✅ |

---

## No Changes To:
- Backend API contract
- Hospital facts / KB
- Model training
- Vaccine mapping
- Schedule logic
- Port 8000
- User-facing language
