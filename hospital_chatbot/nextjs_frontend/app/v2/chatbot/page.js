"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
const DEBUG_CHAT = process.env.NEXT_PUBLIC_DEBUG_CHAT === "1";
const AVATAR = "https://lh3.googleusercontent.com/aida-public/AB6AXuB1GMsI3izgT-RB8q_nUaU2Y5KfNknQIiWht2TLxZ903xjbZqNb595JA1BUQSKg7eI3SNubhXH_h8sr3j8A34huPinFzPQWuhdlk6nncSQESimPshR2wXYHtbP1FbEvdivIvDW8i1EvhROM8GNW9kpQA_0eY3spwNljw8MOhFJQnj49GfonCiL83y6hrNNYG3UCRB-K0QMf_VBQVh5pcawKPJAwtFfrMzHenDzAwUOrITeJJeXcOcks_2AUGeJISWLWag7cGc9tN5c";
const LOADING_TIMEOUT_MS = 30000;
const ENABLE_SESSION_EVENTS = false;
const CHAT_STATE_KEY = "uph_chat_ui_chatbot_only";
const SESSION_KEY = "hospital_chatbot_session_id_chatbot_only";

const MAIN_THEMES = [
  "นัดหมายและตารางแพทย์",
  "วัคซีนและบริการผู้ป่วยนอก",
  "เวชระเบียน สิทธิ และค่าใช้จ่าย",
  "ตรวจสุขภาพและใบรับรองแพทย์",
  "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
];

const GREETING_MESSAGES = [
  "สวัสดีค่ะ ดิฉันน้องฟ้ามุ่ย AI - Chatbot Only ผู้ช่วยของโรงพยาบาลมหาวิทยาลัยพะเยา 🏥 มีอะไรให้ช่วยไหมคะ?",
  "ดิฉันพร้อมตอบคำถามเกี่ยวกับบริการของโรงพยาบาล เช่น นัดหมาย ตารางแพทย์ วัคซีน ตรวจสุขภาพ เวชระเบียน สิทธิการรักษา และการติดต่อหน่วยงานค่ะ",
];

function debugChat(...args) {
  if (DEBUG_CHAT) console.debug("[UPH_CHAT_CHATBOT_ONLY]", ...args);
}

function saveChatState(state) {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return;
    window.sessionStorage.setItem(CHAT_STATE_KEY, JSON.stringify(state));
  } catch (error) {
    console.error("[UPH_CHAT_CHATBOT_ONLY] Failed to save state:", error.message);
  }
}

function restoreChatState() {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    const raw = window.sessionStorage.getItem(CHAT_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    console.error("[UPH_CHAT_CHATBOT_ONLY] Failed to restore state:", error.message);
    return null;
  }
}

function resolveAttachmentUrl(rawUrl) {
  const value = String(rawUrl || "");
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `${API_BASE}${value}`;
}

function dedupeAttachments(items) {
  const seen = new Set();
  const result = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item || typeof item !== "object") continue;
    const url = resolveAttachmentUrl(item.url);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    result.push({ ...item, url });
  }
  return result;
}

function getOrCreateSessionId() {
  if (typeof window === "undefined") return "default";
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const value = `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(SESSION_KEY, value);
  return value;
}

function linkify(text) {
  const parts = String(text || "").split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, index) => {
    if (/^https?:\/\//.test(part)) {
      return (
        <a key={index} href={part} target="_blank" rel="noreferrer">
          {part.length > 50 ? `${part.slice(0, 50)}...` : part}
        </a>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

export default function ChatbotOnlyPage() {
  const [inputVal, setInputVal] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [sessionId, setSessionId] = useState("default");
  const [currentCategory, setCurrentCategory] = useState(null);
  const [currentTopic, setCurrentTopic] = useState(null);
  const [dynamicChips, setDynamicChips] = useState([]);
  const [messages, setMessages] = useState([{ role: "bot", texts: GREETING_MESSAGES }]);
  const [isStateRestored, setIsStateRestored] = useState(false);

  const chatBodyRef = useRef(null);
  const loadingTimerRef = useRef(null);
  const requestAbortRef = useRef(null);
  const timeoutMessageShownRef = useRef(false);
  const adminEventCursorRef = useRef(0);
  const seenAdminMessageIdsRef = useRef(new Set());

  useEffect(() => {
    const restored = restoreChatState();
    if (restored) {
      if (Array.isArray(restored.messages) && restored.messages.length > 0) {
        setMessages(restored.messages);
      }
      if (restored.sessionId && restored.sessionId !== "default") {
        setSessionId(restored.sessionId);
      }
      if (restored.currentCategory) {
        setCurrentCategory(restored.currentCategory);
      }
      if (restored.currentTopic) {
        setCurrentTopic(restored.currentTopic);
      }
      if (Array.isArray(restored.dynamicChips) && restored.dynamicChips.length > 0) {
        setDynamicChips(restored.dynamicChips);
      }
    }
    setIsStateRestored(true);
  }, []);

  useEffect(() => {
    setSessionId(getOrCreateSessionId());
  }, []);

  useEffect(() => {
    if (!isStateRestored) return;
    saveChatState({
      messages,
      sessionId,
      currentCategory,
      currentTopic,
      dynamicChips,
      lastActivityTime: Date.now(),
    });
  }, [messages, sessionId, currentCategory, currentTopic, dynamicChips, isStateRestored]);

  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, isSearching]);

  useEffect(() => {
    if (!ENABLE_SESSION_EVENTS) return undefined;
    if (!sessionId || sessionId === "default") return undefined;

    const stream = new EventSource(
      `${API_BASE}/chat/session-events?session_id=${encodeURIComponent(sessionId)}&after_id=${adminEventCursorRef.current}`,
    );

    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        const messageId = Number(payload.message_id || 0);
        if (!messageId || seenAdminMessageIdsRef.current.has(messageId)) return;
        seenAdminMessageIdsRef.current.add(messageId);
        adminEventCursorRef.current = Math.max(adminEventCursorRef.current, messageId);
        if (payload.response_text) {
          setMessages((prev) => [
            ...prev,
            { role: "admin", texts: [`เจ้าหน้าที่: ${payload.response_text}`], attachments: [] },
          ]);
        }
      } catch (error) {
        console.error("Session event parse error:", error);
      }
    };

    stream.onerror = () => {
      debugChat("EventSource error, closing stream but keeping chat open");
      stream.close();
    };

    return () => {
      stream.close();
    };
  }, [sessionId]);

  useEffect(() => {
    return () => {
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);
      if (requestAbortRef.current) requestAbortRef.current.abort();
    };
  }, []);

  const visibleChips = useMemo(() => {
    if (dynamicChips.length > 0) return dynamicChips;
    return MAIN_THEMES;
  }, [dynamicChips]);

  function clearLoadingTimer() {
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current);
      loadingTimerRef.current = null;
    }
  }

  function startLoadingTimer() {
    clearLoadingTimer();
    loadingTimerRef.current = setTimeout(() => {
      timeoutMessageShownRef.current = true;
      if (requestAbortRef.current) {
        requestAbortRef.current.abort();
        requestAbortRef.current = null;
      }
      setIsSearching(false);
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          texts: ["ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง หรือโทร 0 5446 6666 ต่อ 7000 ค่ะ"],
          attachments: [],
        },
      ]);
    }, LOADING_TIMEOUT_MS);
  }

  function processResponse(data) {
    const answer = data.answer || "ไม่พบคำตอบค่ะ";
    const attachments = Array.isArray(data.attachments) ? data.attachments : [];

    if (data.is_fallback_reset) {
      setCurrentCategory(null);
      setCurrentTopic(null);
      setDynamicChips(data.action_buttons || MAIN_THEMES);
      setMessages((prev) => [...prev, { role: "bot", texts: [answer], attachments: [] }]);
      return;
    }

    if (data.selected_category) {
      setCurrentCategory(data.selected_category);
    } else if (data.route !== "fallback") {
      setCurrentCategory(null);
    }

    if (data.route === "answer" && data.candidates?.length) {
      setCurrentTopic(data.candidates[0]?.question || null);
    } else {
      setCurrentTopic(null);
    }

    if (data.action_buttons?.length) {
      setDynamicChips(data.action_buttons.filter(Boolean));
    } else if (data.clarification_options?.length) {
      setDynamicChips(data.clarification_options.filter(Boolean));
    } else {
      setDynamicChips([]);
    }

    setMessages((prev) => {
      const next = [...prev, { role: "bot", texts: [answer], attachments }];
      if (data.handoff_required && data.handoff_ticket_id) {
        next.push({
          role: "system",
          texts: [`ระบบได้ส่งเรื่องให้เจ้าหน้าที่ตรวจสอบเพิ่มเติมแล้วค่ะ (เคส ${data.handoff_ticket_id})`],
          attachments: [],
        });
      }
      if (data.admin_reply) {
        next.push({ role: "admin", texts: [`เจ้าหน้าที่: ${data.admin_reply}`], attachments: [] });
      }
      return next;
    });
  }

  async function sendMessage(text, opts = {}) {
    const value = String(text || "").trim();
    if (!value) return;

    setMessages((prev) => [...prev, { role: "user", texts: [value], attachments: [] }]);
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

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      processResponse(data);
    } catch (error) {
      clearLoadingTimer();
      requestAbortRef.current = null;

      if (error.name === "AbortError") {
        if (timeoutMessageShownRef.current) return;
        setMessages((prev) => [
          ...prev,
          {
            role: "bot",
            texts: ["ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง หรือโทร 0 5446 6666 ต่อ 7000 ค่ะ"],
            attachments: [],
          },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: "bot",
            texts: ["ขออภัยค่ะ ระบบเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ชั่วคราว กรุณาลองใหม่อีกครั้งค่ะ"],
            attachments: [],
          },
        ]);
      }
    } finally {
      setIsSearching(false);
    }
  }

  async function resetConversation() {
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
      setCurrentCategory(null);
      setCurrentTopic(null);
      setDynamicChips(data.action_buttons || MAIN_THEMES);
      setMessages((prev) => [...prev, { role: "bot", texts: [data.welcome || GREETING_MESSAGES[0]] }]);
    } catch (error) {
      clearLoadingTimer();
      try {
        const response2 = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: "หน้าหลัก",
            top_k: 10,
            use_llm: true,
            session_id: sessionId,
          }),
        });

        if (response2.ok) {
          const data = await response2.json();
          setCurrentCategory(null);
          setCurrentTopic(null);
          setDynamicChips(data.action_buttons || MAIN_THEMES);
          setMessages((prev) => [...prev, { role: "bot", texts: [data.answer || GREETING_MESSAGES[0]] }]);
        } else {
          setCurrentCategory(null);
          setCurrentTopic(null);
          setDynamicChips(MAIN_THEMES);
          setMessages((prev) => [...prev, { role: "bot", texts: GREETING_MESSAGES }]);
        }
      } catch {
        setCurrentCategory(null);
        setCurrentTopic(null);
        setDynamicChips(MAIN_THEMES);
        setMessages((prev) => [...prev, { role: "bot", texts: GREETING_MESSAGES }]);
      }
    } finally {
      setIsSearching(false);
    }
  }

  function goBack() {
    if (currentTopic && currentCategory) {
      setCurrentTopic(null);
      setDynamicChips([]);
      sendMessage(`กลับไปหมวด${currentCategory}`, { forcedCategory: currentCategory });
    } else if (currentCategory) {
      resetConversation();
    }
  }

  function handleChipClick(chip) {
    sendMessage(chip);
  }

  function handleSubmit(event) {
    event.preventDefault();
    sendMessage(inputVal);
  }

  return (
  <main
    style={{
      position: "fixed",
      inset: 0,
      width: "100vw",
      height: "100vh",
      minHeight: "100vh",
      margin: 0,
      padding: 0,
      background: "#fff",
      display: "block",
      overflow: "hidden",
      zIndex: 9999,
    }}
  >
    <style>{`
      html,
      body {
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
        background: #fff !important;
      }

      body > div,
      #__next,
      [data-nextjs-scroll-focus-boundary] {
        width: 100% !important;
        height: 100% !important;
        min-height: 100vh !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #fff !important;
        overflow: hidden !important;
      }

      .chatbot-only-screen {
        position: fixed !important;
        inset: 0 !important;
        top: 0 !important;
        left: 0 !important;
        right: auto !important;
        bottom: auto !important;
        width: 100vw !important;
        height: 100vh !important;
        width: 100dvw !important;
        height: 100dvh !important;
        max-width: none !important;
        max-height: none !important;
        min-width: 100vw !important;
        min-height: 100vh !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        background: #fff !important;
        transform: none !important;
        animation: none !important;
        overflow: hidden !important;
        display: flex !important;
        flex-direction: column !important;
      }

      .chatbot-only-screen .chat-body {
        flex: 1 1 auto !important;
        min-height: 0 !important;
      }
    `}</style>

    <div
      className="chatbot-only-screen"
        style={{
          position: "fixed",
          inset: 0,
          top: 0,
          left: 0,
          right: "auto",
          bottom: "auto",
          width: "100vw",
          height: "100vh",
          maxWidth: "none",
          maxHeight: "none",
          minWidth: "100vw",
          minHeight: "100vh",
          margin: 0,
          padding: 0,
          background: "#fff",
          border: "none",
          borderRadius: 0,
          overflow: "hidden",
          boxShadow: "none",
          transform: "none",
          animation: "none",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div className="chat-header">
          <div className="header-avatar">
            <img src={AVATAR} alt="Nong Fah Mui" />
          </div>
          <div className="header-info" style={{ flex: 1 }}>
            <h3>น้องฟ้ามุ่ย AI - Chatbot Only</h3>
            <div className="header-status">
              <span className="status-dot" />
              ออนไลน์ - พร้อมช่วยเหลือค่ะ
            </div>
          </div>
          <button
            type="button"
            onClick={resetConversation}
            style={{
              background: "rgba(255,255,255,0.16)",
              border: "1px solid rgba(255,255,255,0.2)",
              color: "white",
              cursor: "pointer",
              padding: "8px 12px",
              borderRadius: "999px",
              fontWeight: 600,
            }}
          >
            เริ่มใหม่
          </button>
        </div>

        <div className="context-bar">
          <span className="material-icons-outlined" style={{ fontSize: "1rem" }}>
            home
          </span>
          <span onClick={resetConversation} style={{ cursor: "pointer" }}>
            หน้าหลัก
          </span>
          {currentCategory && (
            <>
              <span className="context-sep">›</span>
              <span onClick={() => sendMessage(currentCategory)} style={{ cursor: "pointer" }}>
                {currentCategory}
              </span>
            </>
          )}
          {currentTopic && (
            <>
              <span className="context-sep">›</span>
              <span
                style={{
                  opacity: 0.8,
                  maxWidth: 220,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {currentTopic}
              </span>
            </>
          )}
        </div>

        <div className="chat-body" ref={chatBodyRef} style={{ flex: 1 }}>
          {messages.map((message, index) => {
            const role = String(message?.role || "bot");
            const texts = Array.isArray(message?.texts)
              ? message.texts
              : ["ไม่สามารถแสดงข้อความได้"];
            const attachments = dedupeAttachments(message?.attachments);

            return (
              <div key={index} className={`msg msg-${role === "user" ? "user" : "bot"}`}>
                <div className="bubble">
                  {texts.map((text, textIndex) => (
                    <div key={textIndex} style={{ marginBottom: textIndex < texts.length - 1 ? "8px" : 0 }}>
                      {linkify(String(text || ""))}
                    </div>
                  ))}
                </div>

                {attachments.length > 0 && (
                  <div
                    className="attachment-container"
                    style={{
                      marginTop: "8px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px",
                    }}
                  >
                    {attachments.map((att, attIndex) => {
                      if (!att || typeof att !== "object") return null;
                      const attType = String(att.type || "").toLowerCase();
                      const attUrl = String(att.url || "");
                      const attLabel = String(att.label || att.filename || "ไฟล์แนบ");

                      if (attType === "image") {
                        return (
                          <div
                            key={attIndex}
                            className="attachment-card"
                            style={{
                              borderRadius: "12px",
                              overflow: "hidden",
                              border: "1px solid rgba(255,255,255,0.15)",
                              background: "rgba(255,255,255,0.05)",
                              maxWidth: "320px",
                            }}
                          >
                            <a href={attUrl} target="_blank" rel="noreferrer">
                              <img
                                src={attUrl}
                                alt={attLabel}
                                style={{
                                  width: "100%",
                                  display: "block",
                                  borderRadius: "12px 12px 0 0",
                                }}
                                onError={(event) => {
                                  debugChat("image load failed:", attUrl);
                                  event.target.style.display = "none";
                                }}
                              />
                            </a>
                            {attLabel && (
                              <div style={{ padding: "6px 10px", fontSize: "0.75rem", opacity: 0.8 }}>
                                {attLabel}
                              </div>
                            )}
                          </div>
                        );
                      }

                      return (
                        <a
                          key={attIndex}
                          href={attUrl}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: "#60a5fa", fontSize: "0.82rem" }}
                        >
                          📎 {attLabel}
                        </a>
                      );
                    })}
                  </div>
                )}

                {index === messages.length - 1 &&
                  (role === "bot" || role === "system" || role === "admin") &&
                  !isSearching &&
                  visibleChips.length > 0 && (
                    <div className="chip-container">
                      {visibleChips.map((chip, chipIndex) => {
                        const chipValue = String(chip || "").trim();
                        return chipValue ? (
                          <button
                            key={chipIndex}
                            type="button"
                            className="chip"
                            onClick={() => handleChipClick(chipValue)}
                          >
                            {chipValue}
                          </button>
                        ) : null;
                      })}
                    </div>
                  )}
              </div>
            );
          })}

          {isSearching && (
            <div className="msg msg-bot">
              <div className="typing-indicator">
                น้องฟ้ามุ่ยกำลังค้นหาข้อมูลให้ค่ะ
                <div className="typing-dots">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          )}
        </div>

        <form className="chat-footer" onSubmit={handleSubmit}>
          <button
            type="button"
            className="send-btn"
            onClick={goBack}
            disabled={!currentCategory}
            title="ย้อนกลับ"
            style={{ background: !currentCategory ? "#e2e8f0" : "var(--navy)" }}
          >
            <span className="material-icons-outlined">arrow_back</span>
          </button>

          <div className="input-wrap">
            <input
              className="chat-input"
              type="text"
              placeholder="พิมพ์คำถามที่ต้องการทราบ..."
              value={inputVal}
              onChange={(event) => setInputVal(event.target.value)}
            />
          </div>

          <button type="submit" className="send-btn" disabled={!inputVal.trim() || isSearching}>
            <span className="material-icons-outlined">send</span>
          </button>
        </form>
      </div>
    </main>
  );
}
