# Async Background Validation Implementation Plan

## Overview
Convert synchronous validation to async background process for faster report generation while maintaining quality through automatic fixes.

## Architecture

### Flow
1. **Report Generation** → Returns immediately with `validation_status: "pending"`
2. **Background Validation** → Runs async, updates status in DB
3. **Frontend Polling** → Checks status every 2s, shows indicator
4. **Fix Application** → If violations found, creates new version automatically
5. **User Notification** → Shows status and option to view fixed version

---

## Backend Changes

### 1. Database Schema
**File**: `backend/src/rapid_reports_ai/database/models.py`

- Add `validation_status` JSON column to `Report` model
- Structure:
  ```python
  {
    "status": "pending" | "passed" | "fixed" | "error",
    "violations_count": int,
    "started_at": ISO datetime,
    "completed_at": ISO datetime | null,
    "error": str | null
  }
  ```

### 2. Database Migration
**File**: `backend/migrations/versions/XXX_add_validation_status.py`

- Add `validation_status` column (nullable JSON, default null)

### 3. CRUD Functions
**File**: `backend/src/rapid_reports_ai/database/crud.py`

- `update_validation_status(report_id, status_dict)` - Update validation status
- `get_validation_status(report_id)` - Get current status

### 4. Background Validation Function
**File**: `backend/src/rapid_reports_ai/enhancement_utils.py`

- `async def validate_report_async(report_id, report_output, findings, scan_type, db_session)`
  - Sets status to "pending"
  - Runs validation
  - If violations: applies fixes, creates new version, updates report content
  - Sets status to "passed" or "fixed"
  - Handles errors gracefully

### 5. API Endpoints Modification

**File**: `backend/src/rapid_reports_ai/main.py`

#### `/api/chat` (Auto Reports)
- Remove synchronous validation (lines 516-548)
- Save report immediately
- Set `validation_status: {"status": "pending"}`
- Queue background task: `asyncio.create_task(validate_report_async(...))`
- Return response with `validation_status: "pending"`

#### `/api/templates/{id}/generate` (Templated Reports)
- Same changes as above

#### New Endpoint: `/api/reports/{report_id}/validation-status`
- GET endpoint
- Returns current validation status
- Used by frontend for polling

---

## Frontend Changes

### 1. ReportResponseViewer Component
**File**: `frontend/src/routes/components/ReportResponseViewer.svelte`

- Add `validationStatus` state variable
- Add `pollInterval` for status polling
- `startPollingValidation()` - Polls every 2s when report_id exists
- `stopPollingValidation()` - Cleans up on unmount
- Display validation indicator:
  - Pending: Spinner + "Validating..."
  - Passed: Green checkmark + "Validated"
  - Fixed: Green badge + "X issues fixed" + "View Fixed Version" button
  - Error: Yellow warning + "Validation failed"

### 2. AutoReportTab Component
**File**: `frontend/src/routes/components/AutoReportTab.svelte`

- Pass `reportId` to ReportResponseViewer
- Handle validation status updates
- Refresh version history when fixes applied

### 3. TemplateForm Component
**File**: `frontend/src/routes/components/TemplateForm.svelte`

- Same as AutoReportTab

### 4. API Integration
**File**: `frontend/src/routes/components/ReportResponseViewer.svelte`

- `checkValidationStatus(reportId)` - Fetches from `/api/reports/{id}/validation-status`
- `reloadFixedVersion()` - Reloads report content from latest version

---

## Edge Cases & Considerations

### 1. User Navigates Away
- Polling stops automatically (component unmounts)
- Validation continues in background
- User sees fixed version when viewing history

### 2. User Edits Report Before Validation Completes
- Validation continues but doesn't overwrite user edits
- Fixed version saved as separate version
- User can compare versions

### 3. Validation Fails
- Status set to "error"
- Original report remains unchanged
- User notified but can continue using report

### 4. Multiple Validations Queued
- Each report has its own validation task
- No interference between concurrent validations
- Each updates its own report status

### 5. Database Session Management
- Background task needs its own DB session
- Use `SessionLocal()` directly (not dependency injection)
- Properly close session after use

### 6. Version Creation
- Only create version if fixes were applied
- Original report content stays as-is
- Fixed version becomes version 2 (if version 1 exists)
- Update report.report_content to fixed version
- Mark fixed version as `is_current=True`

---

## Implementation Order

1. ✅ Database model update (add validation_status)
2. ✅ Database migration
3. ✅ CRUD functions for validation status
4. ✅ Background validation function
5. ✅ Modify /api/chat endpoint
6. ✅ Modify /api/templates/{id}/generate endpoint
7. ✅ Create /api/reports/{id}/validation-status endpoint
8. ✅ Frontend: Add polling logic
9. ✅ Frontend: Add status display
10. ✅ Frontend: Add notification handling
11. ✅ Frontend: Handle version refresh

---

## Testing Checklist

- [ ] Report generation returns immediately
- [ ] Validation runs in background
- [ ] Status updates correctly (pending → passed/fixed)
- [ ] Fixed reports create new versions
- [ ] Frontend polls and displays status
- [ ] User can view fixed version
- [ ] Version history shows both original and fixed
- [ ] Error handling works (validation fails gracefully)
- [ ] Multiple concurrent reports validate independently
- [ ] User edits don't interfere with validation

---

## Performance Considerations

- **Polling Interval**: 2 seconds (balance between responsiveness and server load)
- **Polling Timeout**: Stop after 30 seconds (validation should complete by then)
- **Background Tasks**: Use `asyncio.create_task()` (non-blocking)
- **Database**: Index `validation_status` queries if needed (JSON queries can be slow)

---

## Future Enhancements

1. WebSocket for real-time updates (instead of polling)
2. User preference to disable async validation
3. Validation retry logic
4. Validation history/audit log

