GitHub Repository README.md Requirements
Your repository must include a clear, professional README.md containing:

System Architecture & Data Flow Diagram: A Mermaid.js sequence or flowchart diagram mapping: Document Ingestion Text Extraction Constrained LLM Decoding Pydantic Validation Gate (Pass UI / Downstream) OR (Fail Reflection Loop / DLQ).
Installation & Setup Guide: Detailed instructions using uv or poetry with Python 3.11+.
Schema Specification: A clear summary of your Pydantic data contract, listing fields, types, and custom cross-field validation rules.
Execution Commands: Exact CLI commands to run the web application and execute the test harness (pytest -v).
AI Audit Log Summary: An overview section documenting the initial AI generation, highlighting prompt revisions, syntax corrections, and
