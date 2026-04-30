"use client";

/**
 * Error Boundary for UPH Hospital Chatbot
 * 
 * This component catches React rendering errors and displays a friendly fallback message
 * instead of showing a blank page. It prevents a single error from breaking the entire UI.
 */

export default function Error({ error, reset }) {
  console.error("[UPH_CHAT] Error caught by boundary:", error);

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      backgroundColor: "#f1f5f9",
      fontFamily: "Kanit, sans-serif",
      padding: "2rem",
      textAlign: "center",
    }}>
      <div style={{
        backgroundColor: "white",
        padding: "3rem",
        borderRadius: "12px",
        boxShadow: "0 4px 6px rgba(0, 0, 0, 0.1)",
        maxWidth: "500px",
      }}>
        <h1 style={{
          fontSize: "1.5rem",
          color: "#1e3a8a",
          marginBottom: "1rem",
        }}>
          ⚠️ เกิดข้อผิดพลาด
        </h1>
        <p style={{
          fontSize: "1rem",
          color: "#475569",
          marginBottom: "2rem",
          lineHeight: "1.6",
        }}>
          ขออภัยค่ะ หน้าเว็บเกิดข้อผิดพลาดชั่วคราว กรุณากดโหลดใหม่อีกครั้ง
        </p>
        <button
          onClick={() => window.location.reload()}
          style={{
            backgroundColor: "#1e3a8a",
            color: "white",
            padding: "0.75rem 2rem",
            fontSize: "1rem",
            border: "none",
            borderRadius: "8px",
            cursor: "pointer",
            fontFamily: "Kanit, sans-serif",
            fontWeight: "600",
            transition: "background-color 0.2s",
          }}
          onMouseEnter={(e) => e.target.style.backgroundColor = "#1e40af"}
          onMouseLeave={(e) => e.target.style.backgroundColor = "#1e3a8a"}
        >
          🔄 โหลดหน้าใหม่
        </button>
        {process.env.NODE_ENV === "development" && (
          <details style={{
            marginTop: "2rem",
            textAlign: "left",
            fontSize: "0.875rem",
            color: "#666",
            backgroundColor: "#f5f5f5",
            padding: "1rem",
            borderRadius: "8px",
          }}>
            <summary style={{ cursor: "pointer", fontWeight: "600" }}>
              📋 รายละเอียดข้อผิดพลาด (Development only)
            </summary>
            <pre style={{
              marginTop: "1rem",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: "0.75rem",
            }}>
              {error.message}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}
