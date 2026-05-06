# Model Card: UPH Hospital Chatbot

## Model Details

### Model Identifier
- **Project Name**: UPH Hospital Chatbot (UP FahMui ChatBot)
- **Model Type**: Retrieval-Augmented Generation (RAG) System
- **Backend Framework**: FastAPI + Ollama
- **Frontend Framework**: Next.js
- **Language**: Thai (ไทย)
- **Knowledge Cutoff**: Based on hospital knowledge base (data/knowledge.jsonl)

### Model Architecture
This is a **knowledge-base-first RAG system**, not a general-purpose LLM:

1. **Retrieval Layer**
   - Vector search over hospital knowledge base
   - Knowledge source: `data/knowledge.jsonl` / `data/knowledge.csv`
   - Reranking for relevance

2. **Reasoning Layer**
   - LLM-based intent detection and response formatting
   - Policy checking for safe responses
   - NO knowledge generation—only formatting and rewriting

3. **Application Layer**
   - Hospital scheduling and menu routing
   - Hospital contact information
   - Service information and certificates

---

## Intended Use

### Primary Use Cases
✅ **Recommended**
- Information about hospital services and contact details
- Doctor schedule queries (ตารางแพทย์)
- Vaccination appointment and information (วัคซีน)
- Annual health check programs (ตรวจสุขภาพประจำปี)
- Health certificates and documentation
- Hospital contact numbers and extensions
- Service availability and operating hours

### Limitations & Restrictions
❌ **NOT Recommended**
- **Medical Diagnosis**: Do NOT use for diagnosing diseases
- **Treatment Advice**: Do NOT provide treatment recommendations
- **Patient Data**: Do NOT use with real patient information
- **Medical Research**: Do NOT use as a medical research source
- **Emergency Care**: Do NOT use for emergencies—always call hospital directly
- **Prescription Information**: Not suitable for detailed drug interactions
- **Liability**: Chatbot responses do not constitute medical advice

---

## Knowledge Base

### Primary Data Source
- **Excel File**: `data/AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx`
- **Format**: Q&A pairs in Thai, organized by department/service
- **Last Updated**: As per version in filename (01.04.69 = April 1, 2569 Thai calendar)

### Runtime Knowledge Files
- `data/knowledge.jsonl`: Structured Q&A data with metadata
- `data/knowledge.csv`: CSV export of knowledge base
- `data/ตารางออกตรวจแพทย์/`: Doctor schedule images
- `data/ตรวจสุขภาพประจำปี/`: Health check program images

### Update Process
1. Update Excel source file
2. Export to `knowledge.jsonl` / `knowledge.csv`
3. Rebuild vector index
4. Restart backend service

---

## Model Behavior & Safety

### Response Policy
- Responses are **retrieved from knowledge base**, not generated
- If information is not in knowledge base → return "cannot answer"
- **No hallucination**: Never invent hospital facts
- **No diagnosis**: Decline medical diagnosis requests
- **No treatment advice**: Redirect to real doctor

### Typo & Intent Handling
- Thai text preprocessing (diacritic normalization)
- Short query understanding (e.g., "นัดหมาย" → appointment scheduling)
- Intent categorization for menu routing

### Safe Fallback
```
User: "ฉันเจ็บท้อง"  (I have stomach pain)
Bot: "ขออภัย ฉันไม่สามารถวินิจฉัยโรคได้ โปรดติดต่อแพทย์จริง"
     "Sorry, I cannot diagnose disease. Please consult a real doctor."
```

---

## Technical Specifications

### Input/Output
- **Input**: Thai text queries (user messages)
- **Output**: Thai text responses with optional attachments
- **Max Response Time**: ~3 seconds (including retrieval + ranking + generation)
- **Confidence Scoring**: Available for retrieval results

### Deployment Requirements
- **Python**: 3.9+
- **Node.js**: 18+ (frontend)
- **Memory**: 4GB+ (recommended 8GB)
- **GPU**: Optional (faster inference with CUDA)
- **Database**: Chroma vector DB (included)

### Performance Characteristics
- **Latency**: ~1-3 seconds per query (includes network)
- **Throughput**: ~10-20 concurrent users
- **Availability**: Depends on backend uptime and vector DB
- **Accuracy**: Depends on knowledge base quality and relevance of documents

---

## Evaluation & Testing

### Test Suite
- `test_focused_runtime_regression.py`: Focused regression test suite
- Coverage: ~150 critical queries across all hospital services
- Test categories:
  - Scheduling (appointment, reschedule)
  - Doctor information
  - Service details
  - Certificate programs
  - Safety/fallback behavior

### Evaluation Metrics
- **Retrieval Accuracy**: % of queries returning correct knowledge items
- **Intent Recognition**: % of queries correctly categorized
- **Response Relevance**: Manual QA score (1-5)
- **Safe Fallback**: % of out-of-scope queries declined properly

### Known Issues & Limitations
1. **Long Thai sentences**: May struggle with very long or complex Thai text
2. **Ambiguous queries**: Short queries (< 5 words) require contextual clues
3. **New services**: Not available until knowledge base is updated
4. **Multi-turn context**: Limited conversation history support
5. **Real-time info**: Doctor availability is point-in-time snapshot

---

## Data & Privacy

### Data Handling
- Knowledge base contains **NO patient data**
- Chat logs: Not collected by default
- Analytics: Optional (separate database if enabled)
- API Keys: Use `.env` file (never commit)

### Security Recommendations
1. Use HTTPS in production
2. Implement rate limiting on `/chat` endpoint
3. Monitor for abuse or unusual query patterns
4. Regularly backup knowledge base
5. Restrict API access to hospital network

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2569-04-01 | Initial release with 150+ Q&A pairs |
| 1.1 | Current | Enhanced Thai tokenization & intent routing |

---

## Contact & Support

For questions about:
- **System Issues**: Contact IT department
- **Knowledge Base Updates**: Contact Hospital Communications Team
- **Chatbot Logic Issues**: Refer to README.md and code comments in `backend/`

---

## License & Attribution

This chatbot is proprietary to Phayao University Hospital (UPH).
All hospital data, schedules, and service information are confidential.

---

## Compliance

- ✅ GDPR-ready: No personal data stored
- ✅ Thai language support: Full UTF-8 compliance
- ✅ Accessibility: Keyboard navigation support
- ⚠️ Medical Compliance: NOT a medical device—informational only
