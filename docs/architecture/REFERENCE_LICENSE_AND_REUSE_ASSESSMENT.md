# Reference License & Reuse Assessment — Legal & Architectural Boundaries

**Document ID:** `REFERENCE_LICENSE_AND_REUSE_ASSESSMENT`  
**Governing Workstream:** Ground-Truth Legal & Licensing Review  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **ACTIVE & AUDITED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Legal Cautionary Statement

> [!CAUTION]
> This assessment provides technical and architectural analysis of software licenses governing the 7 external reference codebases located in `D:\AI-Employee-Platform-Research`. It evaluates the legal risks of code reuse, bundling, and derivation in the context of a proprietary multi-tenant commercial SaaS platform. It does not constitute formal legal counsel, but establishes mandatory engineering boundaries to prevent copyright infringement, license breach, and proprietary IP contamination.

---

## 2. Reference Codebase License Inventory & Analysis

| Repository | Inspected Path | Verified Commit | Stated License | Commercial SaaS Compatibility | Copy / Import Permitted? | Architectural Status |
| :--- | :--- | :---: | :--- | :---: | :---: | :--- |
| **`langgraph`** | `D:\AI-Employee-Platform-Research\langgraph` | `4c52e12` | **MIT License**<br>(LangChain, Inc.) | **YES** (Permissive) | YES (with attribution) | Architectural concepts (Pregel, checkpointing) extracted; native implementation adopted. |
| **`memento-skills`** | `D:\AI-Employee-Platform-Research\memento-skills` | `ee9b9a4` | **Apache 2.0**<br>(Memento-Teams) | **YES** (Permissive) | YES (with NOTICE & attribution) | 6-Gate verification pipeline and Dream Daemon offline evolution extracted. |
| **`microsoft-agent-framework`** | `D:\AI-Employee-Platform-Research\microsoft-agent-framework` | `67ba500` | **MIT License**<br>(Microsoft Corporation) | **YES** (Permissive) | YES (with attribution) | Telegram UTF-16 code unit chunking and agent contracts extracted. |
| **`openai-agents-python`**| `D:\AI-Employee-Platform-Research\openai-agents-python` | `0dc4cf1` | **MIT License**<br>(OpenAI) | **YES** (Permissive) | YES (with attribution) | Declarative `Handoff` pattern and `input_filter` context sanitization extracted. |
| **`ragleap-core`** | `D:\AI-Employee-Platform-Research\ragleap-core` | `b9bb6fb` | **MIT License**<br>(RagLeap) | **YES** (Permissive) | YES (with attribution) | Immutable `Scope`, `SecretStr`, and HMAC audit chaining extracted. |
| **`dify`** | `D:\AI-Employee-Platform-Research\dify` | `89cdc0c7` | **Modified Apache 2.0**<br>(LangGenius, Inc.) | **STRICT PROHIBITION**<br>(Clause 1.a) | **STRICTLY PROHIBITED (0% Code)** | Concepts (DB pool preservation, thoughts) extracted; **ZERO code copied or imported**. |
| **`n8n`** | `D:\AI-Employee-Platform-Research\n8n` | `9a489b65` | **Sustainable Use License (SUL 1.0) / Enterprise** | **STRICT PROHIBITION**<br>(Commercial SaaS) | **STRICTLY PROHIBITED (0% Code)** | Concept (`WaitTracker`) extracted; **ZERO code copied or imported**. |

---

## 3. Deep-Dive Forensic License Assessments

### 3.1 Dify — Modified Apache 2.0 (High Risk)
- **Verified Source File:** `D:\AI-Employee-Platform-Research\dify\LICENSE`
- **Textual Evidence:**
  > "1. Dify may be utilized commercially... Should the conditions below be met, a commercial license must be obtained from the producer:  
  > a. **Multi-tenant service:** Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment.  
  > - *Tenant Definition:* Within the context of Dify, one tenant corresponds to one workspace. The workspace provides a separated area for each tenant's data and configurations."
- **Analysis & Legal Risk:**
  The AI-Employee-Platform is fundamentally an enterprise multi-tenant platform where each tenant business possesses isolated agents, channels, and data. Utilizing Dify source code, modules, or derivative components to operate a multi-tenant service without purchasing an enterprise commercial license from LangGenius directly breaches Clause 1.a.
- **Mandatory Architectural Rule:**
  **Zero code carryover.** No Python files, database models, or API controllers from `dify` may be copied, modified, or bundled. Only high-level architectural patterns (such as closing database sessions prior to LLM streaming in `fc_agent_runner.py`) are extracted and cleanly implemented in native Python 3.14 / SQLAlchemy 2.0.

### 3.2 n8n — Sustainable Use License 1.0 & Enterprise License (High Risk)
- **Verified Source Files:** `D:\AI-Employee-Platform-Research\n8n\LICENSE.md` and `LICENSE_EE.md`
- **Textual Evidence:**
  > "Source code files that contain '.ee.' in their filename or '.ee' in their dirname are NOT licensed under the Sustainable Use License... you must hold a valid n8n Enterprise license... Content outside... is available under the 'Sustainable Use License' as defined below."
- **Analysis & Legal Risk:**
  n8n's SUL 1.0 explicitly restricts offering n8n workflow execution as a hosted commercial service to third parties. Furthermore, n8n is built on Node.js/TypeScript, which does not fit directly into our Python backend stack.
- **Mandatory Architectural Rule:**
  **Zero code carryover.** n8n is inspected purely as an architectural reference for execution suspension (`WaitTracker`) and webhook wait-and-resume semantics. All workflow execution nodes in AI-Employee-Platform are implemented natively using Python Pregel state graphs.

### 3.3 Memento-Skills — Apache License 2.0 (Permissive with Attribution)
- **Verified Source File:** `D:\AI-Employee-Platform-Research\memento-skills\LICENSE`
- **Analysis:**
  Standard Apache 2.0 allows commercial use, modification, and distribution, subject to:
  1. Retaining original copyright and license notices.
  2. Providing a copy of the Apache 2.0 license.
  3. Stating significant changes in modified files.
  4. Retaining any `NOTICE` file.
  5. Adhering to trademark and patent grant terms (Section 3 and 6).
- **Architectural Adoption:**
  The 6-Gate verification engine and Dream Daemon offline evolution patterns are adopted. Because our platform implements these natively using Pydantic v2 and FastAPI, direct file copying is unnecessary, but full attribution is maintained in platform documentation.

### 3.4 Permissive MIT References (LangGraph, Microsoft Agent Framework, OpenAI Agents SDK, RagLeap Core)
- **Verified Source Files:** `LICENSE` files in each respective repository.
- **Analysis:**
  All four codebases use the standard MIT License, which grants unrestricted rights to use, copy, modify, merge, publish, and distribute, subject only to including the copyright notice and warranty disclaimer in substantial portions.
- **Architectural Adoption:**
  While legally permissible to copy or vendor, we enforce **Clean-Room Native Architecture**: patterns are adapted to fit our strict multi-tenant Pydantic v2 / SQLAlchemy models rather than pulling heavy, unnecessary external framework dependencies that could bloat the backend or constrain platform evolution.

---

## 4. Summary of Architecture Decision ADR-08 (Clean-Room Boundary)

As formalized in `ARCHITECTURAL_DECISION_RECORDS.md` (ADR-08):
1. **Zero External Core Dependency:** The core execution runtime (`packages/engine/`), capability evolution engine (`packages/self_development/`), and supervisory daemon (`packages/godfather/`) are 100% proprietary, clean-room implementations.
2. **Zero Commercial License Liabilities:** Neither Dify nor n8n licenses are violated because zero lines of code from either project exist in the platform.
3. **Attribution Integrity:** All architectural principles adopted from open-source literature and permissive references are formally cataloged in `SOURCE_AND_EVIDENCE_REGISTER.md`.
