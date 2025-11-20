# Project Analysis Report

## 1. Executive Summary
The project is a functional MVP of a contract generation chatbot. It uses a file-based storage system (JSON) and an LLM-driven agent.
**Status**: Stable. Critical race conditions and validation bugs have been resolved.
**Key Risks**: Code duplication in tool logic, lack of authentication, and potential brittleness in DOCX filling.

## 2. Detailed Findings

### 2.1. Code Duplication
-   **Category Logic**: `FindCategoryByQueryTool` (in `src/agent/tools/categories.py`) duplicates the session update logic found in `SetCategoryTool`. It manually resets the session state, clears fields, etc. This violates DRY and risks inconsistency if one tool is updated but the other isn't.
-   **Fallback Logic**: `GetCategoryEntitiesTool` contains fallback logic to find a category by template ID. This seems to be a workaround for legacy data structures and adds unnecessary complexity.

### 2.2. Architecture & State Management
-   **Tool Router**: `src/app/tool_router.py` is a good abstraction, but it contains hidden logic (regex parsing for `find_category_by_query`) that should be explicit in the tool or a dedicated intent parser.
-   **State Gating**: `server.py` implements `_filter_tools_for_session` to restrict tools based on session state. This is good for safety but couples the server tightly to the agent's internal logic.
-   **Session Store**: `src/sessions/store.py` handles serialization well, including the new `.lock` mechanism.

### 2.3. Validation & Data Integrity
-   **Centralized Validation**: The move to `src/validators` is a big improvement. `UpsertFieldTool` now correctly uses `normalize_rnokpp`.
-   **PII Handling**: PII sanitization is robust. `server.py` masks inputs before they reach the LLM, and `UpsertFieldTool` unmasks them using context tags. This ensures the LLM never sees raw sensitive data.

### 2.4. Security
-   **Authentication**: **MISSING**. The API relies solely on `session_id`. Anyone with the ID can read/write data. This is acceptable for a demo/MVP but critical for production.
-   **Authorization**: No role-based access control (RBAC).

## 3. Recommendations

### High Priority (Refactoring)
1.  **Deduplicate Category Logic (COMPLETED)**: Extract the "set category" logic into a shared service function (e.g., in `src/sessions/actions.py` or `src/categories/service.py`) and call it from both `SetCategoryTool` and `FindCategoryByQueryTool`.
2.  **Clean up Tool Router (COMPLETED)**: Move the regex parsing logic from `dispatch_tool` into `FindCategoryByQueryTool` itself (it can handle "field=value" hints if designed to).

### Medium Priority (Enhancements)
1.  **Enhance Validators (COMPLETED)**: Ensure `UpsertFieldTool` uses `src/validators/core.py` registry for *all* field types (IBAN, Date, etc.), not just RNOKPP.
2.  **Docx Filler (COMPLETED)**: Replace hardcoded regex replacements in `fill_docx_template` with a more configuration-driven approach (e.g., defining aliases in the template metadata).

### Low Priority (Future Work)
1.  **Authentication**: Implement JWT or API Key auth.
2.  **Database**: Migrate from JSON files to SQLite or PostgreSQL for better concurrency and querying capabilities.
