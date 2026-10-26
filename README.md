# Enterprise Fault-Tolerant Structured Data Extractor

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Pydantic-v2-green.svg)](https://docs.pydantic.dev/latest/)
[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://structured-data-extractor.streamlit.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-grade, fault-tolerant unstructured document extraction pipeline built with **Python 3.11**, **Pydantic v2**, and **LLM structured outputs**. The system parses messy invoices (PDF, HTML, raw OCR) into strictly typed JSON schemas using a 3-stage pipeline: **Constrained Decoding**, **Reflection Self-Healing Loop**, and **Dead-Letter Queue (DLQ) Fallback**.

🔗 **Live Deployment:** [https://structured-data-extractor.streamlit.app/](https://structured-data-extractor.streamlit.app/)

---

## Table of Contents
- [1. System Architecture & Data Flow Diagram](#1-system-architecture--data-flow-diagram)
- [2. Installation & Setup Guide](#2-installation--setup-guide)
- [3. Schema Specification](#3-schema-specification)
- [4. Execution Commands](#4-execution-commands)
- [5. Interactive Test Cases & Usage](#5-interactive-test-cases--usage)
- [6. Project Directory Structure](#6-project-directory-structure)
- [7. AI Audit Log Summary](#7-ai-audit-log-summary)

---

## 1. System Architecture & Data Flow Diagram

The diagram below maps the end-to-end data lifecycle from document ingestion through the Pydantic v2 validation gate, automated reflection recovery, and Dead-Letter Queue routing:

```mermaid
flowchart TD
    A[Unstructured Document Ingestion<br/>PDF / HTML / Raw Text] --> B[Text Extraction & Cleaning<br/>pypdf / BeautifulSoup4]
    B --> C[Stage 1: Constrained LLM Decoding<br/>OpenAI / Gemini Structured JSON Mode]
    C --> D{Pydantic v2 Validation Gate<br/>Type Assertions & Cross-Field Rules}

    %% Pass Path
    D -- Validation Passed --> E[Extract Validated Object<br/>status: SUCCESS]
    E --> F[UI Render & Downstream Ingestion<br/>Side-by-Side View + Reconciliation Badge]

    %% Fail Path
    D -- ValidationError Intercepted --> G{Retry Count < Max Retries?}

    %% Stage 2: Reflection Repair Loop
    G -- Yes (Attempt < 3) --> H[Stage 2: Reflection Repair Loop<br/>Inject ValidationError Diff + Previous JSON]
    H --> C

    %% Stage 3: Terminal Fallback & DLQ
    G -- No (3 Failed Attempts) --> I[Stage 3: Terminal Fallback<br/>Heuristic Repair / json-repair]
    I --> J{Repaired & Valid?}
    J -- Yes --> K[Validated Object<br/>status: REPAIRED_VIA_REFLECTION]
    K --> F
    J -- No --> L[Dead-Letter Queue - DLQ<br/>status: DLQ_FAILED<br/>Persist to dlq_records/ with Full Error Trace]
