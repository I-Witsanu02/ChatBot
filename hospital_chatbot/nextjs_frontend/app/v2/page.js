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

/* เปลี่ยนเฉพาะข้อมูลภาพ/พื้นหลังหน้าเว็บ */
const UPH_LOGO = "https://uph.up.ac.th/assets/images/logo/logo-uph.png";
const HERO_BG = "https://uph.up.ac.th/images/slide/20260306-3.jpg";

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

const UPH_DOCTOR_SCHEDULE = [
  {
    src: "https://uph.up.ac.th:8084/images/content_post/202510018808.jpg",
    alt: "คลินิกกุมารเวชกรรม",
  },
  {
    src: "https://uph.up.ac.th:8084/images/content_post/202603173181.jpg",
    alt: "คลินิกจักษุวิทยา",
  },
  {
    src: "https://uph.up.ac.th:8084/images/content_post/202510014185.jpg",
    alt: "คลินิกเวชศาสตร์ป้องกันและครอบครัว",
  },
  {
    src: "https://uph.up.ac.th:8084/images/content_post/202510018923.jpg",
    alt: "รังสีวินิจฉัย",
  },
  {
    src: "https://uph.up.ac.th:8084/images/content_post/202510011958.jpg",
    alt: "คลินิก โสต ศอ นาสิก",
  },
];

const UPH_NEWS = [
  {
    img: "https://uph.up.ac.th:8084/images/content_post/202605061310.jpg",
    date: "05/05/2026",
    title:
      "โรงพยาบาลมหาวิทยาลัยพะเยา รับการตรวจเยี่ยมเตรียมความพร้อมรับรองมาตรฐานการรับบริจาคโลหิต และการผลิตส่วนประกอบโลหิต",
    link: "https://www.facebook.com/share/p/1agy4xi4VA/",
  },
  {
    img: "https://uph.up.ac.th:8084/images/content_post/202605064828.jpg",
    date: "05/05/2026",
    title:
      "โรงพยาบาลมหาวิทยาลัยพะเยา ให้การต้อนรับคณะตรวจประเมินหน่วยบริการปฐมภูมิจังหวัดพะเยา",
    link: "https://www.facebook.com/share/p/1CZ52MxNoy/",
  },
  {
    img: "https://uph.up.ac.th:8084/images/content_post/202605067750.jpg",
    date: "28/04/2026",
    title:
      "โรงพยาบาลมหาวิทยาลัยพะเยา จัดโครงการจัดการความรู้ความสมบูรณ์ของเวชระเบียน",
    link: "https://www.facebook.com/share/p/1ChYeiNchK/",
  },
];

const UPH_SERVICES = [
  {
    title: "Checkup",
    subtitle: "คลินิกตรวจสุขภาพ",
    img: "https://uph.up.ac.th/assets/images/department/checkup_1.jpg",
  },
  {
    title: "Hemodialysis Center",
    subtitle: "ศูนย์ไตเทียม 1",
    img: "https://uph.up.ac.th/images/multidisciplinary/2.jpg",
  },
  {
    title: "Thalassemia Unit",
    subtitle: "หน่วยธาลัสซีเมีย",
    img: "https://uph.up.ac.th/images/multidisciplinary/3.jpg",
  },
  {
    title: "Blood Bank",
    subtitle: "ธนาคารเลือด",
    img: "https://uph.up.ac.th/assets/images/department/blood_bank.jpg",
  },
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
      {/* ════ UPH REAL-LIKE WEBSITE BACKGROUND ════ */}
      <div className="uph-page">
        {/* Topbar */}
        <div className="uph-topbar">
          <div className="uph-topbar-inner">
            <div className="uph-top-left">
              <a href="tel:054466666">
                <span className="material-icons-outlined">phone</span>
                เบอร์โทรศัพท์
              </a>
              <a href="mailto:uph@up.ac.th">
                <span className="material-icons-outlined">mail</span>
                uph@up.ac.th
              </a>
              <a
                href="https://docs.google.com/forms/d/e/1FAIpQLSe6_Ksm9chzaPpH25LZ2kHsWeBY6Sc15NuD5hye4ZUTAnIuFA/viewform?pli=1"
                target="_blank"
                rel="noreferrer"
              >
                สายตรงผู้อำนวยการ
              </a>
              <a href="http://uph.up.ac.th/appeal" target="_blank" rel="noreferrer">
                แจ้งเรื่องร้องเรียน
              </a>
            </div>

            <div className="uph-top-right">
              <a href="https://www.facebook.com/UPHospital" target="_blank" rel="noreferrer">
                f
              </a>
              <a href="https://line.me/ti/p/@medup" target="_blank" rel="noreferrer">
                L
              </a>
              <a href="https://www.tiktok.com/@uph.up" target="_blank" rel="noreferrer">
                ♪
              </a>
              <div className="uph-search">
                <input placeholder="Search" />
                <span className="material-icons-outlined">search</span>
              </div>
            </div>
          </div>
        </div>

        {/* Header */}
        <header className="uph-header">
          <div className="uph-header-inner">
            <a className="uph-logo-wrap" href="https://uph.up.ac.th/landing" target="_blank" rel="noreferrer">
              <img src={UPH_LOGO} alt="UPH Logo" />
            </a>

            <nav className="uph-nav">
              <div className="uph-nav-item">
                <a href="http://uph.up.ac.th/profile" target="_blank" rel="noreferrer">
                  เกี่ยวกับโรงพยาบาล
                </a>
                <span>⌄</span>
              </div>
              <div className="uph-nav-item">
                <a href="http://uph.up.ac.th/sdg.list?type=1" target="_blank" rel="noreferrer">
                  ข่าวและกิจกรรม
                </a>
                <span>⌄</span>
              </div>
              <div className="uph-nav-item">
                <a href="http://uph.up.ac.th/doctor_schedule" target="_blank" rel="noreferrer">
                  บริการทางการแพทย์
                </a>
                <span>⌄</span>
              </div>
              <div className="uph-nav-item">
                <a href="http://uph.up.ac.th/contact_us" target="_blank" rel="noreferrer">
                  ติดต่อเรา
                </a>
              </div>
            </nav>

            <a
              className="uph-staff-btn"
              href="http://uph.up.ac.th/officer_service"
              target="_blank"
              rel="noreferrer"
            >
              <span className="material-icons-outlined">person</span>
              สำหรับเจ้าหน้าที่
            </a>
          </div>
        </header>

        {/* Hero */}
        <section className="uph-hero">
          <button className="uph-hero-arrow left">‹</button>
          <button className="uph-hero-arrow right">›</button>
        </section>

        {/* Banner shortcut */}
        <section className="uph-banner-shortcut">
          <div className="uph-banner-row">
            {LOGO_SLIDES.map((item, index) => (
              <a className="uph-banner-card" href="#" key={index}>
                <img src={item.src} alt={item.alt} />
              </a>
            ))}
          </div>
        </section>

        {/* Doctor schedule */}
        <section className="uph-section uph-doctor-section">
          <h2>ตารางแพทย์ออกตรวจ</h2>

          <div className="uph-slider-row">
            <button className="uph-small-arrow">‹</button>

            <div className="uph-doctor-grid">
              {UPH_DOCTOR_SCHEDULE.map((item, index) => (
                <a
                  href={item.src}
                  target="_blank"
                  rel="noreferrer"
                  className="uph-doctor-card"
                  key={index}
                >
                  <img src={item.src} alt={item.alt} />
                </a>
              ))}
            </div>

            <button className="uph-small-arrow">›</button>
          </div>
        </section>

        {/* News */}
        <section className="uph-section uph-news-section">
          <h2>ข่าวสาร</h2>
          <p>โรงพยาบาลมหาวิทยาลัยพะเยา</p>

          <div className="uph-news-grid">
            {UPH_NEWS.map((item, index) => (
              <a
                href={item.link}
                target="_blank"
                rel="noreferrer"
                className="uph-news-card"
                key={index}
              >
                <div className="uph-news-img-wrap">
                  <img src={item.img} alt={item.title} />
                </div>

                <div className="uph-news-body">
                  <div className="uph-news-pill">ข่าว กิจกรรม</div>
                  <div className="uph-news-date">{item.date} | UPH</div>
                  <h3>{item.title}</h3>

                  <div className="uph-sdg-mini">
                    <img src="https://uph.up.ac.th/images/sdg/3.png" alt="SDG 3" />
                    <img src="https://uph.up.ac.th/images/sdg/11.png" alt="SDG 11" />
                  </div>

                  <div className="uph-read-more">อ่านเพิ่มเติม⌄</div>
                </div>
              </a>
            ))}
          </div>
        </section>

        {/* SDGs */}
        <section className="uph-section uph-sdg-section">
          <h3>SDGs : Sustainable Development Goals</h3>

          <div className="uph-sdg-row">
            <img
              className="uph-sdg-logo"
              src="https://uph.up.ac.th/images/sdg/logo.jpg"
              alt="Sustainable Development Goals"
            />

            <div className="uph-sdg-icons">
              {Array.from({ length: 17 }, (_, i) => (
                <a
                  key={i}
                  href={`http://uph.up.ac.th/sdg.list?sdg=${i + 1}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    src={`https://uph.up.ac.th/images/sdg/${i + 1}.png`}
                    alt={`SDG ${i + 1}`}
                  />
                </a>
              ))}
            </div>
          </div>
        </section>

        {/* Special services */}
        <section className="uph-special-service">
          <h2>บริการคลินิกเฉพาะทางพิเศษ</h2>
          <p>Special Medical Services</p>

          <div className="uph-service-grid">
            {UPH_SERVICES.map((item, index) => (
              <a href="#" className="uph-service-card" key={index}>
                <img src={item.img} alt={item.title} />
                <h3>{item.title}</h3>
                <span>{item.subtitle}</span>
              </a>
            ))}
          </div>
        </section>

        {/* Footer */}
        <footer className="uph-footer">
          <div className="uph-footer-inner">
            <div className="uph-footer-about">
              <img src={UPH_LOGO} alt="UPH Logo" />
              <p>
                โรงพยาบาลมหาวิทยาลัยพะเยา คณะแพทยศาสตร์ 19/1 หมู่ 2 ถ.พหลโยธิน
                ต.แม่กา อ.เมืองพะเยา จ.พะเยา 56000
              </p>
              <p>โทร 0 5446 6666 ต่อ 7000</p>
              <p>ห้องฉุกเฉิน 0 5446 6758</p>
              <p>uph@up.ac.th</p>
            </div>

            <div className="uph-footer-links">
              <h3>บริการทางการแพทย์</h3>
              <a href="http://uph.up.ac.th/medical_specialist/0" target="_blank" rel="noreferrer">
                แพทย์ผู้เชี่ยวชาญ
              </a>
              <a href="http://uph.up.ac.th/doctor_schedule" target="_blank" rel="noreferrer">
                ตารางเวลาออกตรวจแพทย์
              </a>
              <a href="http://uph.up.ac.th/building_plan" target="_blank" rel="noreferrer">
                แผนผังอาคาร
              </a>
              <a href="http://uph.up.ac.th/service_guideline" target="_blank" rel="noreferrer">
                คู่มือการให้บริการ
              </a>
              <a href="http://uph.up.ac.th/patient_service" target="_blank" rel="noreferrer">
                สิทธิการรักษา
              </a>
            </div>

            <div className="uph-quick-contact">
              <h3>Quick Contacts</h3>
              <p>
                โรงพยาบาลมหาวิทยาลัยพะเยา 19/1 หมู่ 2 ถ.พหลโยธิน ต.แม่กา
                อ.เมืองพะเยา จ.พะเยา 56000
              </p>
              <a href="tel:054466666">0 5446 6666 ต่อ 7000</a>
              <a href="http://uph.up.ac.th/contact_us" target="_blank" rel="noreferrer">
                Get Directions →
              </a>
            </div>
          </div>

          <div className="uph-footer-bottom">
            <span>© 2024 UPH, All Rights Reserved.</span>
            <div>
              <a href="#">Terms & Conditions</a>
              <a href="#">Privacy Policy</a>
            </div>
          </div>
        </footer>
      </div>

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

      <style jsx global>{`
        @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600;700&family=Sarabun:wght@300;400;500;600;700&display=swap');
        @import url('https://fonts.googleapis.com/icon?family=Material+Icons+Outlined');

        :root {
          --primary: #7e22ce;
          --primary-dark: #6b21a8;
          --accent: #0d9488;
          --navy: #1e1b4b;
          --navy-light: #312e81;
          --surface: #ffffff;
          --surface-alt: #f8fafc;
          --surface-muted: #f1f5f9;
          --text: #0f172a;
          --text-secondary: #475569;
          --border: #e2e8f0;
          --shadow-sm: 0 1px 3px rgba(0,0,0,.08);
          --shadow-md: 0 4px 12px rgba(0,0,0,.1);
          --shadow-lg: 0 8px 30px rgba(0,0,0,.12);
          --radius: 12px;
          --font-th: 'Kanit', 'Sarabun', sans-serif;
          --font-en: 'Outfit', 'Inter', sans-serif;
        }

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html { scroll-behavior: smooth; }
        body {
          font-family: var(--font-th);
          background: var(--surface);
          color: var(--text);
          line-height: 1.6;
          -webkit-font-smoothing: antialiased;
        }
        a { color: inherit; text-decoration: none; }
        img { max-width: 100%; display: block; }
        button { font-family: inherit; }

        /* ═══════════════════════════════════════════════════════════════
           UPH Website Background — เปลี่ยนเฉพาะหน้าเว็บด้านหลัง
           ═══════════════════════════════════════════════════════════════ */
        .uph-page {
          background: #ffffff;
          color: #1c2947;
          min-height: 100vh;
        }

        .uph-topbar {
          height: 38px;
          background: #1c3767;
          color: #dfe9ff;
          font-size: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          position: sticky;
          top: 0;
          z-index: 40;
        }

        .uph-topbar-inner {
          width: min(1180px, 94%);
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
        }

        .uph-top-left,
        .uph-top-right {
          display: flex;
          align-items: center;
          gap: 18px;
        }

        .uph-topbar a {
          color: #dfe9ff;
          text-decoration: none;
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }

        .uph-topbar .material-icons-outlined { font-size: 15px; }

        .uph-top-right > a {
          width: 19px;
          height: 19px;
          background: #21b7a8;
          color: #ffffff;
          border-radius: 50%;
          align-items: center;
          justify-content: center;
          font-size: 10px;
        }

        .uph-search {
          display: flex;
          align-items: center;
          gap: 6px;
          height: 24px;
          padding: 0 8px;
          border-radius: 3px;
          background: rgba(0, 0, 0, 0.18);
        }

        .uph-search input {
          width: 115px;
          border: 0;
          outline: 0;
          background: transparent;
          color: white;
          font-size: 12px;
        }

        .uph-search input::placeholder { color: #b8c4d8; }

        .uph-header {
          height: 74px;
          background: rgba(255, 255, 255, 0.97);
          box-shadow: 0 4px 18px rgba(20, 30, 60, 0.08);
          position: sticky;
          top: 38px;
          z-index: 39;
        }

        .uph-header-inner {
          width: min(1180px, 94%);
          height: 74px;
          margin: 0 auto;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .uph-logo-wrap img {
          height: 54px;
          width: auto;
          object-fit: contain;
        }

        .uph-nav {
          display: flex;
          align-items: center;
          gap: 30px;
          font-size: 15px;
        }

        .uph-nav-item {
          display: flex;
          align-items: center;
          gap: 5px;
          color: #1c2947;
        }

        .uph-nav-item a {
          color: #1c2947;
          text-decoration: none;
        }

        .uph-nav-item:hover a,
        .uph-nav-item:hover span { color: #21b7a8; }

        .uph-staff-btn {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          padding: 12px 22px;
          background: #25b9a9;
          color: white;
          border-radius: 999px;
          text-decoration: none;
          box-shadow: 0 10px 22px rgba(37, 185, 169, 0.25);
          font-size: 14px;
        }

        .uph-staff-btn .material-icons-outlined { font-size: 18px; }

        .uph-hero {
          height: 356px;
          background-image: url("https://uph.up.ac.th/images/slide/20260306-3.jpg");
          background-size: cover;
          background-position: center;
          position: relative;
        }

        .uph-hero-arrow {
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          width: 42px;
          height: 42px;
          border-radius: 50%;
          border: 0;
          background: rgba(255, 255, 255, 0.78);
          color: #34405f;
          font-size: 35px;
          line-height: 1;
          box-shadow: 0 7px 18px rgba(15, 23, 42, 0.12);
          cursor: pointer;
        }

        .uph-hero-arrow.left { left: 30px; }
        .uph-hero-arrow.right { right: 30px; }

        .uph-banner-shortcut {
          background: #f8fafc;
          padding: 30px 0;
        }

        .uph-banner-row {
          width: min(980px, 94%);
          margin: 0 auto;
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
        }

        .uph-banner-card {
          background: white;
          border: 1px solid #eef0f4;
          border-radius: 12px;
          padding: 14px;
          box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
          transition: transform 0.25s, box-shadow 0.25s;
        }

        .uph-banner-card:hover {
          transform: translateY(-7px);
          box-shadow: 0 18px 35px rgba(15, 23, 42, 0.14);
        }

        .uph-banner-card img {
          width: 100%;
          height: 60px;
          object-fit: contain;
          display: block;
        }

        .uph-section {
          padding: 38px 0 26px;
          text-align: center;
          background: white;
        }

        .uph-section h2,
        .uph-special-service h2 {
          font-size: 30px;
          line-height: 1.25;
          color: #1d2c4d;
          margin: 0;
          font-weight: 700;
        }

        .uph-section > p,
        .uph-special-service > p {
          margin: 5px 0 22px;
          color: #64748b;
          font-size: 13px;
        }

        .uph-slider-row {
          width: min(1080px, 94%);
          margin: 24px auto 0;
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .uph-small-arrow {
          width: 34px;
          height: 34px;
          border: 1px solid #d9dee8;
          background: white;
          border-radius: 50%;
          font-size: 26px;
          color: #64748b;
          cursor: pointer;
        }

        .uph-doctor-grid {
          flex: 1;
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 18px;
        }

        .uph-doctor-card {
          display: block;
          overflow: hidden;
          border-radius: 10px;
          background: white;
          box-shadow: 0 8px 22px rgba(15, 23, 42, 0.12);
          transition: transform 0.25s;
        }

        .uph-doctor-card:hover { transform: translateY(-7px); }

        .uph-doctor-card img {
          width: 100%;
          height: 174px;
          object-fit: cover;
          display: block;
        }

        .uph-news-section { padding-top: 24px; }

        .uph-news-grid {
          width: min(960px, 94%);
          margin: 0 auto;
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 24px;
        }

        .uph-news-card {
          background: white;
          text-align: left;
          border-radius: 9px;
          overflow: hidden;
          color: #1d2c4d;
          text-decoration: none;
          box-shadow: 0 9px 25px rgba(15, 23, 42, 0.1);
          transition: transform 0.25s;
        }

        .uph-news-card:hover { transform: translateY(-7px); }

        .uph-news-img-wrap {
          height: 156px;
          overflow: hidden;
        }

        .uph-news-card img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .uph-news-card:hover .uph-news-img-wrap img {
          transform: scale(1.08);
          transition: transform 0.4s;
        }

        .uph-news-body { padding: 14px 18px 18px; }

        .uph-news-pill {
          display: inline-block;
          background: #24b8a8;
          color: white;
          border-radius: 99px;
          padding: 3px 14px;
          font-size: 12px;
          margin-bottom: 8px;
        }

        .uph-news-date {
          color: #7b8497;
          font-size: 12px;
          margin-bottom: 8px;
        }

        .uph-news-body h3 {
          font-size: 15px;
          line-height: 1.45;
          height: 66px;
          overflow: hidden;
          margin: 0 0 10px;
        }

        .uph-sdg-mini {
          display: flex;
          gap: 5px;
          margin: 10px 0 16px;
        }

        .uph-sdg-mini img {
          width: 24px;
          height: 24px;
        }

        .uph-read-more {
          text-align: center;
          font-size: 12px;
          color: #273856;
        }

        .uph-sdg-section { padding-top: 18px; }

        .uph-sdg-section h3 {
          font-size: 16px;
          font-weight: 500;
          margin: 0 0 14px;
        }

        .uph-sdg-row {
          width: min(980px, 94%);
          margin: 0 auto;
          display: grid;
          grid-template-columns: 180px 1fr;
          gap: 10px;
          align-items: center;
        }

        .uph-sdg-logo {
          width: 180px;
          height: 100px;
          object-fit: contain;
          background: #f7f7f7;
        }

        .uph-sdg-icons {
          display: grid;
          grid-template-columns: repeat(9, 1fr);
          gap: 5px;
        }

        .uph-sdg-icons img {
          width: 100%;
          aspect-ratio: 1 / 1;
          object-fit: contain;
          display: block;
          transition: transform 0.2s;
        }

        .uph-sdg-icons img:hover { transform: scale(1.14); }

        .uph-special-service {
          padding: 48px 0 58px;
          text-align: center;
          background:
            radial-gradient(circle at 10% 20%, rgba(34, 183, 170, 0.12), transparent 32%),
            radial-gradient(circle at 80% 10%, rgba(91, 72, 167, 0.1), transparent 28%),
            #edfdfb;
        }

        .uph-service-grid {
          width: min(980px, 94%);
          margin: 28px auto 0;
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 22px;
        }

        .uph-service-card {
          background: white;
          min-height: 132px;
          border-radius: 10px;
          padding: 18px 12px;
          color: #1d2c4d;
          text-decoration: none;
          box-shadow: 0 12px 30px rgba(15, 23, 42, 0.09);
          transition: transform 0.25s;
        }

        .uph-service-card:hover { transform: translateY(-7px); }

        .uph-service-card img {
          width: 42px;
          height: 42px;
          border-radius: 10px;
          object-fit: cover;
          margin: 0 auto 10px;
        }

        .uph-service-card h3 {
          font-size: 13px;
          margin: 0 0 3px;
        }

        .uph-service-card span {
          font-size: 12px;
          color: #526073;
        }

        .uph-footer {
          background: #122447;
          color: white;
          padding: 62px 0 26px;
        }

        .uph-footer-inner {
          width: min(1080px, 94%);
          margin: 0 auto;
          display: grid;
          grid-template-columns: 1.45fr 1fr 1fr;
          gap: 70px;
        }

        .uph-footer a {
          color: #d8e1f0;
          text-decoration: none;
        }

        .uph-footer p,
        .uph-footer a {
          font-size: 13px;
          line-height: 1.8;
        }

        .uph-footer-about img {
          width: 165px;
          background: white;
          border-radius: 6px;
          padding: 8px;
          margin-bottom: 18px;
        }

        .uph-footer-links {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .uph-footer h3 {
          margin: 0 0 14px;
          font-size: 16px;
        }

        .uph-quick-contact {
          background: white;
          color: #1d2c4d;
          border-radius: 10px;
          padding: 24px;
          box-shadow: 0 18px 42px rgba(0, 0, 0, 0.18);
        }

        .uph-quick-contact p,
        .uph-quick-contact a,
        .uph-quick-contact h3 { color: #1d2c4d; }

        .uph-quick-contact a {
          display: block;
          margin-top: 8px;
        }

        .uph-footer-bottom {
          width: min(1080px, 94%);
          margin: 40px auto 0;
          padding-top: 18px;
          border-top: 1px solid rgba(255, 255, 255, 0.08);
          display: flex;
          justify-content: space-between;
          font-size: 12px;
          color: #aebad0;
        }

        .uph-footer-bottom div {
          display: flex;
          gap: 22px;
        }

        .uph-footer-bottom a {
          font-size: 12px;
          color: #aebad0;
        }

        /* ═══════════════════════════════════════════════════════════════
           CHAT WIDGET — คง class และโครงเดิมไว้
           ═══════════════════════════════════════════════════════════════ */
        .chat-fab {
          position: fixed;
          bottom: 24px;
          right: 24px;
          width: 64px;
          height: 64px;
          border-radius: 50%;
          background: linear-gradient(135deg, var(--primary), var(--primary-dark));
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: var(--shadow-lg);
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          z-index: 1000;
          border: none;
        }
        .chat-fab:hover { transform: scale(1.1) rotate(5deg); box-shadow: 0 12px 40px rgba(126, 34, 206, 0.4); }

        .chat-container {
          position: fixed;
          bottom: 100px;
          right: 24px;
          width: 420px;
          height: 640px;
          max-width: calc(100vw - 48px);
          max-height: calc(100vh - 140px);
          background: var(--surface);
          border-radius: 20px;
          box-shadow: var(--shadow-lg);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          z-index: 1000;
          border: 1px solid var(--border);
          animation: slideUp 0.4s ease-out;
        }

        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        .chat-header {
          padding: 20px;
          background: linear-gradient(135deg, var(--navy), var(--navy-light));
          color: white;
          display: flex;
          align-items: center;
          gap: 12px;
          border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        .header-avatar {
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: white;
          padding: 2px;
          box-shadow: 0 4px 10px rgba(0,0,0,0.2);
          flex-shrink: 0;
        }
        .header-avatar img { width: 100%; height: 100%; object-fit: cover; border-radius: 10px; }
        .header-info h3 { font-size: 1.1rem; font-weight: 600; margin-bottom: 2px; color: #fff; }
        .header-status { font-size: 0.75rem; color: #a5b4fc; display: flex; align-items: center; gap: 4px; }
        .status-dot { width: 8px; height: 8px; background: #4ade80; border-radius: 50%; box-shadow: 0 0 8px #4ade80; }

        .context-bar {
          padding: 8px 16px;
          background: var(--navy-light);
          color: #e0e7ff;
          font-size: 0.75rem;
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 500;
        }
        .context-sep { opacity: 0.4; }

        .chat-body {
          flex: 1;
          padding: 20px;
          overflow-y: auto;
          background: var(--surface-alt);
          display: flex;
          flex-direction: column;
          gap: 16px;
          scroll-behavior: smooth;
        }

        .msg { display: flex; flex-direction: column; max-width: 85%; animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }

        .msg-bot { align-self: flex-start; }
        .msg-user { align-self: flex-end; }

        .bubble {
          padding: 12px 16px;
          border-radius: 16px;
          font-size: 0.95rem;
          line-height: 1.5;
          position: relative;
          box-shadow: var(--shadow-sm);
          word-break: break-word;
          white-space: pre-wrap;
        }
        .msg-bot .bubble {
          background: var(--surface);
          color: var(--text);
          border-bottom-left-radius: 4px;
          border: 1px solid var(--border);
        }
        .msg-user .bubble {
          background: linear-gradient(135deg, var(--primary), var(--primary-dark));
          color: white;
          border-bottom-right-radius: 4px;
        }

        .bubble a {
          color: inherit;
          text-decoration: underline;
          text-underline-offset: 2px;
        }

        .chip-container {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 8px;
        }
        .chip {
          padding: 8px 14px;
          background: white;
          border: 1.5px solid var(--primary);
          color: var(--primary);
          border-radius: 50px;
          font-size: 0.85rem;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: var(--shadow-sm);
          font-family: var(--font-th);
        }
        .chip:hover {
          background: var(--primary);
          color: white;
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(126, 34, 206, 0.2);
        }

        .chat-footer {
          padding: 16px;
          background: var(--surface);
          border-top: 1px solid var(--border);
          display: flex;
          gap: 10px;
          align-items: center;
        }
        .input-wrap {
          flex: 1;
          background: var(--surface-muted);
          border-radius: 24px;
          padding: 4px 16px;
          display: flex;
          align-items: center;
          border: 1px solid transparent;
          transition: all 0.2s;
        }
        .input-wrap:focus-within {
          background: white;
          border-color: var(--primary);
          box-shadow: 0 0 0 3px rgba(126, 34, 206, 0.1);
        }
        .chat-input {
          width: 100%;
          border: none;
          background: transparent;
          padding: 8px 0;
          font-size: 0.95rem;
          outline: none;
          color: var(--text);
          font-family: var(--font-th);
        }
        .send-btn {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          background: var(--primary);
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          cursor: pointer;
          transition: all 0.2s;
          flex-shrink: 0;
        }
        .send-btn:hover:not(:disabled) { background: var(--primary-dark); transform: scale(1.05); }
        .send-btn:disabled { background: var(--border); cursor: not-allowed; }

        .typing-indicator {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 10px 14px;
          background: var(--surface);
          border-radius: 16px;
          font-size: 0.8rem;
          color: var(--text-secondary);
          border-bottom-left-radius: 4px;
          border: 1px solid var(--border);
        }
        .typing-dots { display: inline-flex; gap: 3px; }
        .typing-dots span {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: var(--text-secondary);
          animation: typingBounce 1s infinite;
        }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes typingBounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-4px); opacity: 1; }
        }

        @media (max-width: 900px) {
          .uph-topbar { display: none; }
          .uph-header { top: 0; }
          .uph-nav { display: none; }
          .uph-staff-btn { padding: 10px 14px; font-size: 12px; }
          .uph-hero { height: 210px; }
          .uph-banner-row,
          .uph-news-grid,
          .uph-service-grid,
          .uph-footer-inner { grid-template-columns: 1fr; }
          .uph-slider-row { align-items: stretch; }
          .uph-doctor-grid { display: flex; overflow-x: auto; }
          .uph-doctor-card { min-width: 170px; }
          .uph-sdg-row { grid-template-columns: 1fr; }
          .uph-sdg-logo { margin: 0 auto; }
          .uph-sdg-icons { grid-template-columns: repeat(6, 1fr); }
          .uph-footer-bottom { flex-direction: column; gap: 10px; }
        }

        @media (max-width: 600px) {
          .chat-container {
            bottom: 0;
            right: 0;
            width: 100%;
            height: 100%;
            max-width: none;
            max-height: none;
            border-radius: 0;
          }
          .chat-fab { bottom: 16px; right: 16px; width: 56px; height: 56px; }
        }
      `}</style>
    </>
  );
}
