"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";
const navItems = ["บริการตรวจ", "นัดหมาย", "สิทธิการรักษา", "ติดต่อเรา"];
const departments = [
  { title: "General Practice", detail: "ให้บริการตรวจรักษาโรคทั่วไปและให้คำปรึกษาสุขภาพเบื้องต้นอย่างครอบคลุม" },
  { title: "Emergency Unit", detail: "ทีมฉุกเฉินพร้อมปฏิบัติการตลอด 24 ชั่วโมง เพื่อรองรับผู้ป่วยเร่งด่วน" },
  { title: "Pediatrics", detail: "ดูแลสุขภาพเด็กแบบองค์รวม ตั้งแต่วัยแรกเกิดถึงวัยรุ่น ด้วยทีมกุมารแพทย์" },
  { title: "Internal Medicine", detail: "ดูแลวินิจฉัยและรักษาโรคอายุรกรรมโดยทีมแพทย์ผู้เชี่ยวชาญเฉพาะทาง" },
];

function linkify(text) {
  const parts = String(text || "").split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, index) => {
    if (/^https?:\/\//.test(part)) {
      return <a key={index} href={part} target="_blank" rel="noreferrer">{part}</a>;
    }
    return <span key={index}>{part}</span>;
  });
}

function MessageBubble({ msg, onCopy }) {
  return (
    <div className={`message-wrap ${msg.role}`}>
      <div className={`message ${msg.role}`}>{linkify(msg.text)}</div>
    </div>
  );
}

function getOrCreateSessionId() {
  if (typeof window === "undefined") return "default";
  const key = "hospital_chatbot_session_id";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const value = `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(key, value);
  return value;
}

function dedupe(items) {
  const seen = new Set();
  const out = [];
  for (const item of items || []) {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

function findCategoryNode(tree, category) {
  return (tree || []).find((node) => node?.label === category) || null;
}

function buildTopicSections(tree, category) {
  const node = findCategoryNode(tree, category);
  if (!node || !Array.isArray(node.children)) return [];
  const sections = [];
  const directTopics = [];
  for (const child of node.children) {
    if (child?.type === "topic") directTopics.push(child.label);
    if (child?.type === "subcategory") {
      sections.push({
        label: child.label,
        topics: (child.children || []).map((item) => item.label).filter(Boolean),
      });
    }
  }
  if (directTopics.length) sections.unshift({ label: "หัวข้อหลัก", topics: directTopics });
  return sections;
}

export default function HomePage() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [input, setInput] = useState("");
  const [guideItems, setGuideItems] = useState([]);
  const [guideExamples, setGuideExamples] = useState({});
  const [topicTree, setTopicTree] = useState([]);
  const [dynamicReplies, setDynamicReplies] = useState([]);
  const [sessionId, setSessionId] = useState("default");
  const [currentCategory, setCurrentCategory] = useState(null);
  const [currentTopic, setCurrentTopic] = useState(null);
  const [messages, setMessages] = useState([
    { role: "bot", text: "สวัสดีครับ/ค่ะ ระบบผู้ช่วย AI โรงพยาบาลมหาวิทยาลัยพะเยาพร้อมให้ข้อมูลบริการเบื้องต้น" },
  ]);
  const chatBodyRef = useRef(null);

  useEffect(() => {
    setSessionId(getOrCreateSessionId());
  }, []);

  const defaultQuickReplies = useMemo(
    () => [
      "การจัดการนัดหมาย",
      "คลินิกทันตกรรม",
      "ศูนย์ไตเทียม",
      "สูตินรีเวช",
      "ประเมินค่าใช้จ่ายทั่วไป",
      "วัคซีน",
      "สวัสดิการวัคซีนนักศึกษา",
      "ธนาคารเลือดและบริจาคเลือด",
      "กลุ่มงานบุคคล",
      "ตารางแพทย์และเวลาทำการ",
      "ตรวจสุขภาพรายบุคคล",
      "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย",
      "การขอเอกสารทางการแพทย์",
    ],
    []
  );

  const categoryButtons = useMemo(() => {
    if (topicTree.length) return topicTree.map((node) => node.label);
    if (guideItems.length) return guideItems;
    return defaultQuickReplies;
  }, [topicTree, guideItems, defaultQuickReplies]);

  const topicSections = useMemo(() => {
    if (dynamicReplies.length) {
      return [{ label: "หัวข้อแนะนำ", topics: dedupe(dynamicReplies) }];
    }
    if (currentCategory && topicTree.length) {
      return buildTopicSections(topicTree, currentCategory);
    }
    if (currentCategory && Array.isArray(guideExamples[currentCategory])) {
      return [{ label: "หัวข้อในหมวด", topics: dedupe(guideExamples[currentCategory]) }];
    }
    return [];
  }, [dynamicReplies, currentCategory, topicTree, guideExamples]);

  useEffect(() => {
    const loadGuide = async () => {
      try {
        const [guideRes, treeRes] = await Promise.all([
          fetch(`${API_BASE}/guide`),
          fetch(`${API_BASE}/guide/tree`),
        ]);
        const data = await guideRes.json();
        const treeData = treeRes.ok ? await treeRes.json() : {};
        if (data?.welcome_message) {
          setMessages([{ role: "bot", text: data.welcome_message }]);
        }
        if (Array.isArray(data?.supported_topics)) {
          setGuideItems(data.supported_topics);
        }
        if (data?.topic_examples && typeof data.topic_examples === "object") {
          setGuideExamples(data.topic_examples);
        }
        if (Array.isArray(treeData?.topic_tree)) {
          setTopicTree(treeData.topic_tree);
        }
      } catch (e) {
        console.error(e);
      }
    };
    loadGuide();
  }, []);

  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, isSearching, isChatOpen]);

  useEffect(() => {
    if (!sessionId || sessionId === "default") return;
    const source = new EventSource(`${API_BASE}/chat/session-events?session_id=${encodeURIComponent(sessionId)}`);
    source.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data);
        setMessages((prev) => {
          if (prev.some((m) => m.messageId === item.message_id)) return prev;
          return [...prev, { role: "admin", text: `เจ้าหน้าที่ (${item.responder || "admin"}): ${item.response_text}`, ticketId: item.ticket_id, messageId: item.message_id }];
        });
      } catch (error) {
        console.error(error);
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [sessionId]);

  const copyMessage = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      console.error(error);
    }
  };

  const updateContextFromResponse = (data) => {
    if (data?.selected_category) {
      setCurrentCategory(data.selected_category);
    }
    if (data?.route === "answer" && Array.isArray(data?.candidates) && data.candidates.length) {
      setCurrentTopic(data.candidates[0]?.question || null);
    } else if (data?.route !== "answer") {
      setCurrentTopic(null);
    }
    if (Array.isArray(data?.action_buttons) && data.action_buttons.length) {
      setDynamicReplies(dedupe(data.action_buttons));
      return;
    }
    if (Array.isArray(data?.clarification_options) && data.clarification_options.length) {
      setDynamicReplies(dedupe(data.clarification_options));
      return;
    }
    if (data?.selected_category && guideExamples[data.selected_category]?.length) {
      setDynamicReplies(dedupe(guideExamples[data.selected_category]));
      return;
    }
    setDynamicReplies([]);
  };

  const sendMessage = async (text, { forcedCategory = null } = {}) => {
    const value = String(text || "").trim();
    if (!value) return;
    setIsChatOpen(true);
    setMessages((prev) => [...prev, { role: "user", text: value }]);
    setInput("");
    setIsSearching(true);
    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: value,
          top_k: 10,
          use_llm: true,
          session_id: sessionId,
          preferred_category: forcedCategory || currentCategory || undefined,
        }),
      });
      if (!response.ok) throw new Error("Request failed");
      const data = await response.json();
      setMessages((prev) => {
        const next = [...prev, { role: "bot", text: data.answer || "ไม่พบคำตอบ" }];
        if (data?.handoff_required && data?.handoff_ticket_id) {
          next.push({ role: "system", text: `ระบบได้ส่งคำถามนี้ให้เจ้าหน้าที่ตรวจสอบเพิ่มเติมแล้ว (เคส ${data.handoff_ticket_id})` });
        }
        if (data?.admin_reply) {
          next.push({ role: "admin", text: `เจ้าหน้าที่: ${data.admin_reply}`, ticketId: data.handoff_ticket_id || `inline-${Date.now()}` });
        }
        return next;
      });
      updateContextFromResponse(data);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: "ขออภัยครับ/ค่ะ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้ง หรือโทร 054-466666" },
      ]);
    } finally {
      setIsSearching(false);
    }
  };

  const selectCategory = (category) => {
    setCurrentCategory(category);
    setCurrentTopic(null);
    setDynamicReplies(dedupe(guideExamples[category] || []));
    sendMessage(category, { forcedCategory: category });
  };

  const goBack = () => {
    if (currentTopic && currentCategory) {
      setCurrentTopic(null);
      setDynamicReplies(dedupe(guideExamples[currentCategory] || []));
      sendMessage(`กลับไปหมวด${currentCategory}`, { forcedCategory: currentCategory });
      return;
    }
    if (currentCategory) {
      setCurrentCategory(null);
      setCurrentTopic(null);
      setDynamicReplies([]);
      sendMessage("กลับหน้าหลัก");
      return;
    }
    setDynamicReplies([]);
  };

  const goHome = () => {
    setCurrentCategory(null);
    setCurrentTopic(null);
    setDynamicReplies([]);
    sendMessage("กลับหน้าหลัก");
  };

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand">UP Hospital</div>
        <nav>
          {navItems.map((item) => (
            <a key={item} href="#" className="nav-link">{item}</a>
          ))}
        </nav>
        <button className="hotline">ฉุกเฉิน 054 466 666</button>
      </header>

      <section className="hero">
        <div className="hero-overlay" />
        <img className="hero-image" src="https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=1900&q=80" alt="Hospital Interior" />
        <div className="hero-content">
          <span className="badge">MEDICAL EXCELLENCE</span>
          <h1>Medical Excellence<br /><span>&amp; Human Connection</span></h1>
          <p>สัมผัสประสบการณ์การดูแลสุขภาพระดับพรีเมียมด้วยเทคโนโลยีที่ทันสมัย และความใส่ใจที่สะท้อนหัวใจของการแพทย์มหาวิทยาลัยพะเยา</p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => selectCategory("การจัดการนัดหมาย")}>นัดหมายแพทย์</button>
            <button className="btn-ghost" onClick={() => selectCategory("ตรวจสุขภาพรายบุคคล")}>ดูแพ็กเกจสุขภาพ</button>
          </div>
          <div className="guide-inline">
            {categoryButtons.map((item) => <button key={item} type="button" className="guide-chip button-chip" onClick={() => selectCategory(item)}>{item}</button>)}
          </div>
        </div>
        <div className="alert-card">
          <div className="alert-title">สายด่วนฉุกเฉิน</div>
          <div className="alert-subtitle">พร้อมดูแลคุณตลอด 24 ชั่วโมง</div>
          <div className="alert-chip">ห้องฉุกเฉิน (ER)</div>
          <div className="alert-number">1669</div>
          <div className="alert-number secondary">054-466666 ต่อ 7235</div>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <div>
            <h2>Core Departments</h2>
            <p>ศูนย์ความเชี่ยวชาญเฉพาะทาง เพื่อการดูแลที่แม่นยำและปลอดภัย</p>
          </div>
          <a href="#">ดูบริการทั้งหมด</a>
        </div>
        <div className="department-grid">
          {departments.map((department) => (
            <article key={department.title} className="department-card">
              <div className="card-icon">+</div>
              <h3>{department.title}</h3>
              <p>{department.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <button className="fab" onClick={() => setIsChatOpen(true)} aria-label="Open AI Assistant"><span>🤖</span></button>

      <aside className={`chatbox ${isChatOpen ? "open" : ""}`}>
        <div className="chat-head">
          <div>
            <strong>ผู้ช่วย AI รพ.มหาวิทยาลัยพะเยา</strong>
            <small>THE INTELLIGENT CONCIERGE</small>
          </div>
          <div className="chat-head-actions">
            <button onClick={() => setIsChatOpen(false)} aria-label="Close">×</button>
          </div>
        </div>

        <div className="context-bar">
          <div className="context-title">บริบทปัจจุบัน</div>
          <div className="context-path">
            <span className={`context-pill ${!currentCategory ? "active" : ""}`}>หน้าหลัก</span>
            {currentCategory ? <span className="context-sep">›</span> : null}
            {currentCategory ? <span className={`context-pill ${currentCategory ? "active" : ""}`}>{currentCategory}</span> : null}
            {currentTopic ? <span className="context-sep">›</span> : null}
            {currentTopic ? <span className="context-pill active">{currentTopic}</span> : null}
          </div>
        </div>

        <div className="tree-panel">
          <div className="tree-group">
            <div className="tree-label">หมวดหลัก</div>
            <div className="quick-replies compact">
              {categoryButtons.map((item) => (
                <button key={item} className={item === currentCategory ? "active" : ""} onClick={() => selectCategory(item)}>{item}</button>
              ))}
            </div>
          </div>

          {currentCategory ? (
            <div className="tree-group">
              <div className="tree-label">หัวข้อในหมวด {currentCategory}</div>
              {topicSections.length ? topicSections.map((section) => (
                <div key={section.label} className="tree-subsection">
                  <div className="tree-subtitle">{section.label}</div>
                  <div className="quick-replies compact secondary-group">
                    {section.topics.map((item) => (
                      <button key={item} className={item === currentTopic ? "active" : ""} onClick={() => sendMessage(item, { forcedCategory: currentCategory })}>{item}</button>
                    ))}
                  </div>
                </div>
              )) : <span className="tree-empty">เลือกหมวดแล้ว ระบบจะแสดงหัวข้อย่อยที่เกี่ยวข้องที่นี่</span>}
            </div>
          ) : null}
        </div>

        <div className="chat-body" ref={chatBodyRef}>
          {messages.map((msg, index) => (
            <MessageBubble key={`${msg.role}-${index}`} msg={msg} onCopy={copyMessage} />
          ))}
          {isSearching ? <div className="typing">กำลังค้นหาคำตอบที่เหมาะสม...</div> : null}
        </div>

        <form className="chat-input" onSubmit={(event) => { event.preventDefault(); sendMessage(input, { forcedCategory: currentCategory }); }}>
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="พิมพ์คำถามของคุณ... เช่น เลื่อนนัด, ราคาเท่าไหร่, ติดต่อที่ไหน" />
          <button type="submit">ส่ง</button>
        </form>
      </aside>
    </main>
  );
}
