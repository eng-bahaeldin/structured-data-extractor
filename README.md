# Enterprise Fault-Tolerant Structured Data Extractor

A robust, production-grade data extraction pipeline built with Python 3.11, Pydantic v2, and LLM structured outputs. The system parses messy, unstructured invoice documents (PDFs and HTML) into strictly typed records, featuring a self-correcting validation reflection loop and Dead-Letter Queue (DLQ) routing for unrecoverable inputs.

---

## 1. System Architecture & Data Flow Diagram

The diagram below details the end-to-end data processing lifecycle from raw unstructured ingestion to schema validation, reflection repair, and DLQ handling:

```mermaid
flowchart TD
    A[Unstructured Document Ingestion<br/>PDF / HTML / Raw Text] --> B[Text Parsing & Cleaning<br/>pypdf / BeautifulSoup4]
    B --> C[Stage 1: Constrained LLM Decoding<br/>Structured JSON Schema Enforcement]
    C --> D{Pydantic v2 Validation Gate}

    %% Pass Path
    D -- Validation Passed --> E[Extract Validated Object]
    E --> F[UI Render & Downstream Ingestion<br/>Side-by-Side View + Reconciliation Badge]

    %% Fail Path
    D -- ValidationError Intercepted --> G{Retry Count < Max Retries?}
    
    %% Stage 2: Reflection Loop
    G -- Yes (Attempt < 3) --> H[Stage 2: Reflection Repair Loop<br/>Format Exact Validation Error Diff]
    H --> C

    %% Stage 3: Terminal Fallback / DLQ
    G -- No (Max Retries Exceeded) --> I[Stage 3: Terminal Fallback<br/>Heuristic Repair / json-repair]
    I --> J{Repaired & Valid?}
    J -- Yes --> E
    J -- No --> K[Dead-Letter Queue - DLQ<br/>Route to dlq_records/ with Audit Trace]
