"use client";
import { useEffect, useRef, useState, useMemo } from "react";

/* ─────────────────────── Constants ──────────────────────── */
// Default to backend dev server when NEXT_PUBLIC_API_BASE_URL not provided.
// This avoids routing through Next's dev server (/api) which doesn't proxy to the Python backend.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
const DEBUG_CHAT = process.env.NEXT_PUBLIC_DEBUG_CHAT === "1";

function debugChat(...args) {
  if (DEBUG_CHAT) console.debug("[UPH_CHAT]", ...args);
}

const AVATAR = "https://lh3.googleusercontent.com/aida-public/AB6AXuB1GMsI3izgT-RB8q_nUaU2Y5KfNknQIiWht2TLxZ903xjbZqNb595JA1BUQSKg7eI3SNubhXH_h8sr3j8A34huPinFzPQWuhdlk6nncSQESimPshR2wXYHtbP1FbEvdivIvDW8i1EvhROM8GNW9kpQA_0eY3spwNljw8MOhFJQnj49GfonCiL83y6hrNNYG3UCRB-K0QMf_VBQVh5pcawKPJAwtFfrMzHenDzAwUOrITeJJeXcOcks_2AUGeJISWLWag7cGc9tN5c";
const HERO_BG = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRzO01Ggxf0Y4rwdFeHo38DAVm7YJGCKOuy6Q&s";

const LOGO_SLIDES = [
  { src: "https://uph.up.ac.th/images/banner_slide/uph_ita.png", alt: "UPH ITA" },
  { src: "https://uph.up.ac.th/images/banner_slide/up_dms.png", alt: "UP-DMS" },
  { src: "https://uph.up.ac.th/images/banner_slide/annual_report.png", alt: "รายงานประจำปี" },
  { src: "https://uph.up.ac.th/images/banner_slide/procurement.png", alt: "จัดซื้อจัดจ้าง" },
];

const GALLERY = [
  { src: "https://uph.up.ac.th:8084/images/content_post/202510014488.jpg", alt: "พยาบาลดูแลผู้ป่วย" },
  { src: "https://uph.up.ac.th:8084/images/content_post/202510014185.jpg", alt: "ทีมพยาบาลตรวจเวชระเบียน" },
  { src: "https://uph.up.ac.th:8084/images/content_post/202603173181.jpg", alt: "เครื่องมือห้องปฏิบัติการ" },
  { src: "https://uph.up.ac.th:8084/images/content_post/202510011668.jpg", alt: "นักเทคนิคการแพทย์" },
];

/* 5 main theme chips per PRD */
const MAIN_THEMES = [
  "นัดหมายและตารางแพทย์",
  "วัคซีนและบริการผู้ป่วยนอก",
  "เวชระเบียน สิทธิ และค่าใช้จ่าย",
  "ตรวจสุขภาพและใบรับรองแพทย์",
  "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
];

const GREETING_MESSAGES = [
  "สวัสดีค่ะ ดิฉันน้องฟ้ามุ่ย AI ผู้ช่วยของโรงพยาบาลมหาวิทยาลัยพะเยา 🏥 มีอะไรให้ช่วยไหมคะ?",
  "ดิฉันพร้อมตอบคำถามเกี่ยวกับบริการของโรงพยาบาล เช่น นัดหมาย ตารางแพทย์ วัคซีน ตรวจสุขภาพ เวชระเบียน สิทธิการรักษา และการติดต่อหน่วยงานค่ะ",
];

const FALLBACK_KEYWORDS = ["ไม่พบข้อมูล", "ขออภัย", "ไม่สามารถ", "ไม่เข้าใจ"];
const LOADING_TIMEOUT_MS = 30000;
const ENABLE_SESSION_EVENTS = false;

/* ─────────────────────── SessionStorage Persistence ──────────────────────── */
// Use sessionStorage (not localStorage) to avoid persisting sensitive hospital data across browser sessions
function saveChatState(state) {
  try {
    const key = "uph_chat_ui_v1";
    const payload = JSON.stringify(state);
    if (typeof window !== "undefined" && window.sessionStorage) {
      window.sessionStorage.setItem(key, payload);
      debugChat("saved chat state", Object.keys(state));
    }
  } catch (error) {
    console.error("[UPH_CHAT] Failed to save state:", error.message);
  }
}

function restoreChatState() {
  try {
    const key = "uph_chat_ui_v1";
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const state = JSON.parse(raw);
    debugChat("restored chat state from sessionStorage", Object.keys(state));
    return state;
  } catch (error) {
    console.error("[UPH_CHAT] Failed to restore state:", error.message);
    return null;
  }
}

function clearChatState() {
  try {
    const key = "uph_chat_ui_v1";
    if (typeof window !== "undefined" && window.sessionStorage) {
      window.sessionStorage.removeItem(key);
      debugChat("cleared chat state from sessionStorage");
    }
  } catch (error) {
    console.error("[UPH_CHAT] Failed to clear state:", error.message);
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
    if (!url) continue;
    if (seen.has(url)) continue;
    seen.add(url);
    result.push({ ...item, url });
  }
  return result;
}

/* ─────────────────────── Utilities ──────────────────────── */
function getOrCreateSessionId() {
  if (typeof window === "undefined") return "default";
  const key = "hospital_chatbot_session_id";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const value = `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(key, value);
  return value;
}

function linkify(text) {
  const parts = String(text || "").split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, i) => {
    if (/^https?:\/\//.test(part)) {
      return <a key={i} href={part} target="_blank" rel="noreferrer">{part.length > 50 ? part.slice(0, 50) + "…" : part}</a>;
    }
    return <span key={i}>{part}</span>;
  });
}

function isFallbackAnswer(text) {
  const t = String(text || "").toLowerCase();
  return FALLBACK_KEYWORDS.some(k => t.includes(k));
}

/* ─────────────────────── Component ──────────────────────── */
export default function HomePage() {
  /* ── State ── */
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
  const [isStateRestored, setIsStateRestored] = useState(false);

  const chatBodyRef = useRef(null);
  const loadingTimerRef = useRef(null);
  const requestAbortRef = useRef(null);
  const timeoutMessageShownRef = useRef(false);
  const adminEventCursorRef = useRef(0);
  const seenAdminMessageIdsRef = useRef(new Set());
  const eventRetryTimerRef = useRef(null);
  const eventRetryCountRef = useRef(0);

  /* ── Restore state from sessionStorage on mount ── */
  useEffect(() => {
    debugChat("component mount, restoring state");
    const restored = restoreChatState();
    if (restored) {
      debugChat("applying restored state:", Object.keys(restored));
      if (typeof restored.isChatOpen === "boolean") {
        setChatOpen(restored.isChatOpen);
      }
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

  /* ── Init session ── */
  useEffect(() => { setSessionId(getOrCreateSessionId()); }, []);

  /* ── Persist chat state to sessionStorage whenever key state changes ── */
  useEffect(() => {
    if (!isStateRestored) return;
    saveChatState({
      isChatOpen: chatOpen,
      messages: messages,
      sessionId: sessionId,
      currentCategory: currentCategory,
      currentTopic: currentTopic,
      dynamicChips: dynamicChips,
      lastActivityTime: Date.now(),
    });
  }, [chatOpen, messages, sessionId, currentCategory, currentTopic, dynamicChips, isStateRestored]);

  useEffect(() => {
    if (!ENABLE_SESSION_EVENTS) return undefined;
    if (!sessionId || sessionId === "default") return undefined;
    const stream = new EventSource(`${API_BASE}/chat/session-events?session_id=${encodeURIComponent(sessionId)}&after_id=${adminEventCursorRef.current}`);

    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        const messageId = Number(payload.message_id || 0);
        if (!messageId || seenAdminMessageIdsRef.current.has(messageId)) return;
        seenAdminMessageIdsRef.current.add(messageId);
        adminEventCursorRef.current = Math.max(adminEventCursorRef.current, messageId);
        if (payload.response_text) {
          debugChat("received admin message via EventSource");
          setMessages(prev => [...prev, { role: "admin", texts: [`เจ้าหน้าที่: ${payload.response_text}`] }]);
        }
      } catch (error) {
        console.error("Session event parse error:", error);
      }
    };

    stream.onerror = () => {
      // IMPORTANT: Never close the chat on EventSource error.
      // Only log and close the stream. Chat must remain open.
      debugChat("EventSource error, closing stream but keeping chat open");
      stream.close();
      // Do NOT call setChatOpen(false) or setMessages([])
    };

    return () => {
      stream.close();
    };
  }, [sessionId]);

  /* ── Global error listeners (log only, never close chat) ── */
  useEffect(() => {
    function handleError(event) {
      debugChat("window error", event.error?.message || event.message);
      // Never close the chat on error
    }

    function handleUnhandledRejection(event) {
      debugChat("unhandled promise rejection", event.reason?.message || String(event.reason));
      // Never close the chat on error
    }

    if (typeof window !== "undefined") {
      window.addEventListener("error", handleError);
      window.addEventListener("unhandledrejection", handleUnhandledRejection);

      return () => {
        window.removeEventListener("error", handleError);
        window.removeEventListener("unhandledrejection", handleUnhandledRejection);
      };
    }
  }, []);

  /* ── Auto-scroll ── */
  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, isSearching, chatOpen]);

  /* ── Chips to show ── */
  const visibleChips = useMemo(() => {
    if (dynamicChips.length > 0) return dynamicChips;
    return MAIN_THEMES;
  }, [dynamicChips]);

  /* ── Clear loading safety net ── */
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
      setMessages(prev => [
        ...prev,
        { role: "bot", texts: ["ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง หรือโทร 0 5446 6666 ต่อ 7000 ค่ะ"], attachments: [] },
      ]);
    }, LOADING_TIMEOUT_MS);
  }

  /* ── Explicit close handler (only X button should call this) ── */
  function closeChat(reason = "user_close") {
    debugChat("closeChat triggered by:", reason);
    setChatOpen(false);
    // Note: state is auto-persisted by useEffect, no need to manually save
  }

  /* ── Process backend response ── */
  function processResponse(data) {
    const answer = data.answer || "ไม่พบคำตอบค่ะ";
    const attachments = Array.isArray(data.attachments) ? data.attachments : [];

    // Handle auto-reset from backend
    if (data.is_fallback_reset) {
      setCurrentCategory(null);
      setCurrentTopic(null);
      setDynamicChips(data.action_buttons || MAIN_THEMES);
      setMessages(prev => [
        ...prev,
        { role: "bot", texts: [answer], attachments: [] },
      ]);
      return;
    }

    // Update context from response
    if (data.selected_category) {
      setCurrentCategory(data.selected_category);
    } else if (data.route === "fallback") {
      // Don't clear category on single fallback unless it's a reset
    } else {
      setCurrentCategory(null);
    }

    if (data.route === "answer" && data.candidates?.length) {
      setCurrentTopic(data.candidates[0]?.question || null);
    } else {
      setCurrentTopic(null);
    }

    // Update dynamic chips
    if (data.action_buttons?.length) {
      setDynamicChips(data.action_buttons.filter(Boolean));
    } else if (data.clarification_options?.length) {
      setDynamicChips(data.clarification_options.filter(Boolean));
    } else {
      setDynamicChips([]);
    }

    // Add messages
    setMessages(prev => {
      const next = [...prev, { role: "bot", texts: [answer], attachments }];
      if (data.handoff_required && data.handoff_ticket_id) {
        next.push({ role: "system", texts: [`ระบบได้ส่งเรื่องให้เจ้าหน้าที่ตรวจสอบเพิ่มเติมแล้วค่ะ (เคส ${data.handoff_ticket_id})`], attachments: [] });
      }
      if (data.admin_reply) {
        next.push({ role: "admin", texts: [`เจ้าหน้าที่: ${data.admin_reply}`], attachments: [] });
      }
      return next;
    });
  }

  /* ── Send message ── */
  async function sendMessage(text, opts = {}) {
    const value = String(text || "").trim();
    if (!value) return;

    debugChat("sendMessage start", value.slice(0, 50));
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

      if (!response.ok) {
        debugChat("fetch returned non-200 status:", response.status);
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      debugChat("sendMessage success");
      processResponse(data);
    } catch (error) {
      clearLoadingTimer();
      requestAbortRef.current = null;

      if (error.name === "AbortError") {
        if (timeoutMessageShownRef.current) {
          debugChat("sendMessage timeout, message already shown");
          return;
        }
        debugChat("sendMessage timeout");
        setMessages(prev => [
          ...prev,
          { role: "bot", texts: ["ขออภัยค่ะ การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง หรือโทร 0 5446 6666 ต่อ 7000 ค่ะ"], attachments: [] },
        ]);
      } else {
        debugChat("sendMessage error:", error.message);
        // Provide friendly message for backend unavailability
        setMessages(prev => [
          ...prev,
          { role: "bot", texts: ["ขออภัยค่ะ ระบบเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ชั่วคราว กรุณาลองใหม่อีกครั้งค่ะ"], attachments: [] },
        ]);
      }
      // IMPORTANT: Never close the chat on error. Chat must remain open.
    } finally {
      setIsSearching(false);
    }
  }

  async function resetConversation() {
    debugChat("resetConversation start");
    setIsSearching(true);
    startLoadingTimer();

    try {
      // Try explicit backend reset endpoint first (ensures server-side session cleared)
      const response = await fetch(`${API_BASE}/chat/reset-session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      clearLoadingTimer();
      if (!response.ok) throw new Error("Reset failed");
      const data = await response.json();
      debugChat("resetConversation success");
      setCurrentCategory(null);
      setCurrentTopic(null);
      setDynamicChips(data.action_buttons || MAIN_THEMES);
      setFallbackCount(0);
      setMessages(prev => [...prev, { role: "bot", texts: [data.welcome || GREETING_MESSAGES[0]] }]);
    } catch (error) {
      clearLoadingTimer();
      debugChat("resetConversation error (fallback to legacy):", error.message);
      // Fallback to legacy reset via /chat endpoint
      try {
        const response2 = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: "หน้าหลัก", top_k: 10, use_llm: true, session_id: sessionId }),
        });
        if (response2.ok) {
          const data = await response2.json();
          setCurrentCategory(null);
          setCurrentTopic(null);
          setDynamicChips(data.action_buttons || MAIN_THEMES);
          setFallbackCount(0);
          setMessages(prev => [...prev, { role: "bot", texts: [data.answer || GREETING_MESSAGES[0]] }]);
        } else {
          setCurrentCategory(null);
          setCurrentTopic(null);
          setDynamicChips(MAIN_THEMES);
          setFallbackCount(0);
          setMessages(prev => [...prev, { role: "bot", texts: GREETING_MESSAGES }]);
        }
      } catch (err) {
        setCurrentCategory(null);
        setCurrentTopic(null);
        setDynamicChips(MAIN_THEMES);
        setFallbackCount(0);
        setMessages(prev => [...prev, { role: "bot", texts: GREETING_MESSAGES }]);
      }
    } finally {
      setIsSearching(false);
    }
  }

  /* ── Navigation ── */
  function goBack() {
    if (currentTopic && currentCategory) {
      setCurrentTopic(null);
      setDynamicChips([]);
      sendMessage(`กลับไปหมวด${currentCategory}`, { forcedCategory: currentCategory });
    } else if (currentCategory) {
      goHome();
    }
  }

  function goHome() {
    resetConversation();
  }

  function handleChipClick(chip) {
    sendMessage(chip);
  }

  function handleSubmit(e) {
    e.preventDefault();
    sendMessage(inputVal);
  }

  /* ═══════════════════════ RENDER ═══════════════════════ */
  return (
    <>
      {/* ════ NAVBAR ════ */}
      <nav className="navbar">
        <div className="nav-top">
          <div style={{ display: "flex", gap: "1.5rem", alignItems: "center" }}>
            <a href="tel:054466666" className="emergency-btn">
              <span className="material-icons-outlined" style={{ fontSize: "1rem" }}>phone</span>
              ติดต่อโรงพยาบาล 0 5446 6666 ต่อ 7000
            </a>
            <div style={{ display: "flex", gap: "1.5rem", fontSize: ".82rem" }}>
              <a href="https://uph.up.ac.th" target="_blank" rel="noreferrer">บทความสาระน่ารู้</a>
              <a href="https://uph.up.ac.th" target="_blank" rel="noreferrer">ตารางออกตรวจแพทย์</a>
              <a href="https://uph.up.ac.th" target="_blank" rel="noreferrer">จุดเด่นที่โดดเด่น</a>
            </div>
          </div>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
            <div className="search-wrap">
              <input type="text" placeholder="Search" />
              <span className="material-icons-outlined mi">search</span>
            </div>
          </div>
        </div>
        <div className="nav-bottom">
          <a className="navbar-brand" href="https://uph.up.ac.th" target="_blank" rel="noreferrer">
            <img src="https://uph.up.ac.th/images/banner_slide/uph_ita.png" alt="UPH Logo" />
            <div className="brand-text">
              <strong>โรงพยาบาลมหาวิทยาลัยพะเยา</strong>
              <span>University of Phayao Hospital</span>
            </div>
          </a>
          <ul className="navbar-links">
            <li><a href="#">หน้าแรก</a></li>
            <li><a href="#">เกี่ยวกับเรา</a></li>
            <li><a href="#">บริการ</a></li>
            <li><a href="#">ข่าวสาร</a></li>
            <li><a href="#">ติดต่อเรา</a></li>
          </ul>
        </div>
      </nav>

      {/* ════ HERO ════ */}
      <section className="hero">
        <img className="hero-img" src={HERO_BG} alt="Hospital Building" />
        <div className="hero-overlay" />
        <div className="hero-container">
          <h1 className="hero-headline">HOSPITAL<br />YOU CAN<br />TOUCH</h1>
          <h1 className="hero-headline-right">WELL-<br />BEING<br />FOR ALL</h1>
        </div>
      </section>

      {/* ════ LOGO BANNER ════ */}
      <div className="logo-bar">
        <div className="logo-bar-inner">
          {LOGO_SLIDES.map((l, i) => (
            <div key={i} className="logo-card">
              <img src={l.src} alt={l.alt} />
            </div>
          ))}
        </div>
      </div>

      {/* ════ DOCTOR SECTION ════ */}
      <div className="section" style={{ background: "#fff" }}>
        <div className="section-header">
          <h2 className="section-title">ตารางแพทย์ออกตรวจ</h2>
        </div>
        <div className="gallery-grid">
          {GALLERY.map((g, i) => (
            <div key={i} className="gallery-card">
              <img src={g.src} alt={g.alt} />
            </div>
          ))}
        </div>
        <div className="pagination">
          <div className="page-dot" />
          <div className="page-dot" />
          <div className="page-dot active" />
          <div className="page-dot" />
        </div>
      </div>

      {/* ════ FOOTER ════ */}
      <footer className="footer">
        <div className="footer-inner">
          <div>
            <div className="footer-logo">
              <img src="https://uph.up.ac.th/images/banner_slide/uph_ita.png" alt="UPH" />
              <div className="footer-logo-text">
                <strong>โรงพยาบาล มหาวิทยาลัยพะเยา</strong>
                <span>ศูนย์การแพทย์และโรงพยาบาล</span>
              </div>
            </div>
            <ul className="footer-info">
              <li>
                <span className="material-icons-outlined mi">location_on</span>
                โรงพยาบาลมหาวิทยาลัยพะเยา คณะแพทยศาสตร์ 103 ม.2 ต.แม่กา อ.เมือง จ.พะเยา 56000
              </li>
              <li>
                <span className="material-icons-outlined mi">phone</span>
                0 5446 6666 ต่อ 7000
              </li>
              <li>
                <span className="material-icons-outlined mi">email</span>
                uph@up.ac.th
              </li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>บริการทางการแพทย์</h4>
            <ul>
              <li><a href="#">ตารางออกตรวจแพทย์</a></li>
              <li><a href="#">นัดหมายตรวจล่วงหน้า</a></li>
              <li><a href="#">เอกสารตรวจรักษา</a></li>
              <li><a href="#">สิทธิความสะดวก</a></li>
              <li><a href="#">จัดซื้อจัดจ้าง</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>ติดต่อเรา</h4>
            <ul>
              <li><a href="#">สำนักงานผู้อำนวยการ</a></li>
              <li><a href="#">แผนกผู้ป่วยนอก</a></li>
              <li><a href="#">แผนกอุบัติเหตุ</a></li>
              <li><a href="#">แจ้งเรื่องร้องเรียน</a></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <p>© 2025 UPH. All Rights Reserved</p>
          <div style={{ display: "flex", gap: "2rem" }}>
            <a href="#" style={{ color: "inherit" }}>Terms & Conditions</a>
            <a href="#" style={{ color: "inherit" }}>Privacy Policy</a>
          </div>
        </div>
      </footer>

      {/* ═══════════════════════ CHAT WIDGET ═══════════════════════ */}
      {/* FAB Button */}
      {!chatOpen && (
        <button className="chat-fab" onClick={() => setChatOpen(true)} aria-label="Open Chat">
          <span className="material-icons-outlined" style={{ fontSize: "2rem" }}>smart_toy</span>
        </button>
      )}

      {/* Chat Window */}
      {chatOpen && (
        <div className="chat-container">
          {/* Header */}
          <div className="chat-header">
            <div className="header-avatar">
              <img src={AVATAR} alt="Nong Fah Mui" />
            </div>
            <div className="header-info" style={{ flex: 1 }}>
              <h3>น้องฟ้ามุ่ย AI</h3>
              <div className="header-status">
                <span className="status-dot" />
                ออนไลน์ - พร้อมช่วยเหลือค่ะ
              </div>
            </div>
            <button
              onClick={() => closeChat("user_close")}
              style={{ background: "none", border: "none", color: "white", cursor: "pointer", padding: "4px" }}
              aria-label="Close Chat"
            >
              <span className="material-icons-outlined">close</span>
            </button>
          </div>

          {/* Context / Breadcrumb Bar */}
          <div className="context-bar">
            <span className="material-icons-outlined" style={{ fontSize: "1rem" }}>home</span>
            <span onClick={goHome} style={{ cursor: "pointer" }}>หน้าหลัก</span>
            {currentCategory && (
              <>
                <span className="context-sep">›</span>
                <span onClick={() => sendMessage(currentCategory)} style={{ cursor: "pointer" }}>{currentCategory}</span>
              </>
            )}
            {currentTopic && (
              <>
                <span className="context-sep">›</span>
                <span style={{ opacity: 0.8, maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {currentTopic}
                </span>
              </>
            )}
          </div>

          {/* Chat Body */}
          <div className="chat-body" ref={chatBodyRef}>
            {messages.map((m, i) => {
              // Defensive rendering: ensure message structure is valid
              const role = String(m?.role || "bot");
              const texts = Array.isArray(m?.texts) ? m.texts : ["ไม่สามารถแสดงข้อความได้"];
              const attachments = dedupeAttachments(m?.attachments);

              return (
                <div key={i} className={`msg msg-${role === "user" ? "user" : "bot"}`}>
                  <div className="bubble">
                    {texts.map((t, j) => {
                      const textValue = String(t || "");
                      return (
                        <div key={j} style={{ marginBottom: j < texts.length - 1 ? "8px" : 0 }}>
                          {linkify(textValue)}
                        </div>
                      );
                    })}
                  </div>

                  {/* Attachment image cards */}
                  {attachments.length > 0 && (
                    <div className="attachment-container" style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "8px" }}>
                      {attachments.map((att, k) => {
                        if (!att || typeof att !== "object") return null;
                        const attType = String(att.type || "").toLowerCase();
                        const attUrl = String(att.url || "");
                        const attLabel = String(att.label || att.filename || "ไฟล์แนบ");

                        return attType === "image" ? (
                          <div key={k} className="attachment-card" style={{
                            borderRadius: "12px",
                            overflow: "hidden",
                            border: "1px solid rgba(255,255,255,0.15)",
                            background: "rgba(255,255,255,0.05)",
                            maxWidth: "280px",
                          }}>
                            <a href={attUrl} target="_blank" rel="noreferrer">
                              <img
                                src={attUrl}
                                alt={attLabel}
                                style={{ width: "100%", display: "block", borderRadius: "12px 12px 0 0" }}
                                onError={(e) => {
                                  debugChat("image load failed:", attUrl);
                                  e.target.style.display = "none";
                                }}
                              />
                            </a>
                            {attLabel && (
                              <div style={{ padding: "6px 10px", fontSize: "0.75rem", opacity: 0.8 }}>
                                {attLabel}
                              </div>
                            )}
                          </div>
                        ) : (
                          <a key={k} href={attUrl} target="_blank" rel="noreferrer"
                            style={{ color: "#60a5fa", fontSize: "0.82rem" }}>
                            📎 {attLabel}
                          </a>
                        );
                      })}
                    </div>
                  )}

                  {/* Chips — only after the latest bot message or when clarifying */}
                  {i === messages.length - 1 && (role === "bot" || role === "system" || role === "admin") && !isSearching && visibleChips.length > 0 && (
                    <div className="chip-container">
                      {visibleChips.map((chip, k) => {
                        const chipValue = String(chip || "").trim();
                        return chipValue ? (
                          <button key={k} className="chip" onClick={() => handleChipClick(chipValue)}>
                            {chipValue}
                          </button>
                        ) : null;
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Typing indicator */}
            {isSearching && (
              <div className="msg msg-bot">
                <div className="typing-indicator">
                  น้องฟ้ามุ่ยกำลังค้นหาข้อมูลให้ค่ะ
                  <div className="typing-dots">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer / Input */}
          <form className="chat-footer" onSubmit={handleSubmit}>
            {/* Nav buttons inside footer or just above */}
            <button type="button" className="send-btn" onClick={goBack} disabled={!currentCategory} title="ย้อนกลับ" style={{ background: !currentCategory ? "#e2e8f0" : "var(--navy)" }}>
              <span className="material-icons-outlined">arrow_back</span>
            </button>

            <div className="input-wrap">
              <input
                className="chat-input"
                type="text"
                placeholder="พิมพ์คำถามที่ต้องการทราบ..."
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
              />
            </div>

            <button type="submit" className="send-btn" disabled={!inputVal.trim() || isSearching}>
              <span className="material-icons-outlined">send</span>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
