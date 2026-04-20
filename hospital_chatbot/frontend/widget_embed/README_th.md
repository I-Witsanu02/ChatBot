# การฝัง mockup chat widget บนเว็บโรงพยาบาล

1. นำไฟล์ `chat-widget-loader.js` ไปวางบน static path ของเว็บ เช่น `/chatbot/widget_embed/chat-widget-loader.js`
2. ใส่ snippet จาก `embed_snippet.html` ก่อนปิด `</body>`
3. เปลี่ยน `window.UPH_CHATBOT_URL` ให้ชี้ไปยังหน้า demo/staging ของ chatbot
4. อย่าให้ widget เรียก Ollama ตรง ให้เรียก backend ของ chatbot เท่านั้น
