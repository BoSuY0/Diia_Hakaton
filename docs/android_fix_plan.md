# Android client change checklist

Backlog for mirroring the recent backend changes. Keep this as a reference until the Android sources land in this repo.

## 1) Stable contract status
- Add `status_effective` and `is_signed` to `ContractResponseDto` / `SessionSummaryDto`.
- Use backend status directly in `ContractsFlowViewModel` instead of recomputing from signatures/labels.

## 2) Chat reset
- Extend `ChatRequestDto` with `reset: Boolean = false`.
- Pass `reset` from `ContractsRepository.chat(...)` and toggle it in the VM when user starts a new chat.

## 3) Readiness (self vs all)
- Extend `RequirementsResponseDto` with `is_ready_self` and `is_ready_all`.
- In `buildContract`/`checkContractReady` allow ordering only when `isReadyAll == true`; surface a message when only `isReadySelf` is true.

## 4) Deep-link join
- Add `joinSession` API (+ DTOs) and use it when opening by deep-link instead of creating a new session.
- Handle HTTP 401/403/404 with user-friendly messages.

## 5) Category selection lag
- Introduce loading flags in menu VM; show shimmer/disabled state while categories/templates load.
- Cache categories/templates in the repository for the process lifetime.

## 6) Field updates / lightweight saves
- Prefer `/sessions/{id}/sync` for batching field updates with debounce.
- If single-field updates remain, extend `UpsertFieldRequest` DTO with `lightweight` and set `lightweight=true` during typing; use full validation for decisive actions.
