# Admin Approval Gate for Radflow Sign-ups

Spec for gating new user authentication on manual admin approval, with signup-context capture to support triage.

## Background and motivation

Radflow currently has open sign-up. Eleven users exist in production; five are zero-activity (signed up, never generated a report). Continuing open sign-up risks inbound users we do not want to onboard (spam, non-target clinical roles, curious tyre-kickers) while consuming API spend for skill-sheet generation and analyser traffic before we know if they are a real user.

This spec introduces a manual approval gate: sign-ups create a pending user, the admin receives a structured notification email, one click approves or rejects. No admin dashboard is built in v1 — the approval email itself is the admin UI.

## Design principles

- **Email is the admin UI.** Approvals happen from the inbox with a single click. No auth session required on the approve/reject endpoints — the HMAC token in the URL is the authorisation.
- **Two independent gates.** `is_verified` (email confirmed) and `is_approved` (admin approved) serve different purposes and must both be satisfied at login. Do not overload one with the other.
- **Grandfather existing users.** All 11 current users are set to `is_approved=TRUE` in the migration. No disruption to existing workflows.
- **Capture triage context at signup.** Role, institution, and "why Radflow?" are collected at sign-up so the approval email carries enough signal for a 2-second decision.
- **YAGNI on admin tooling.** No admin dashboard, no `is_admin` column, no bulk operations. Add when volume justifies it.

## Scope

### In scope

1. Alembic migration adding `is_approved`, `signup_reason`, `role`, `institution` columns to `users`.
2. Updated `/api/auth/register` handler: persists new fields, creates user with `is_approved=FALSE`, sends admin notification email.
3. Updated `/api/auth/login` handler: adds `is_approved` gate before `is_verified` gate.
4. New endpoints `GET /api/admin/approve` and `GET /api/admin/reject` — HMAC-authenticated, idempotent where applicable, return simple HTML confirmation pages.
5. Frontend register page: three new form controls and updated success message.
6. Frontend login page: new error-path handling for pending-approval state.
7. Backend unit tests covering the migration, register, login gates, and admin endpoints.

### Out of scope (deliberately)

- Admin dashboard UI.
- `is_admin` column or session-authenticated admin surface.
- Bulk approval.
- Rate limiting changes on `/register` (existing behaviour preserved).
- Email template visual design beyond plain-text structure.
- Retroactive audit of existing grandfathered users.
- Migration rollback beyond standard Alembic `downgrade`.

## Database changes

One Alembic migration, upgrading `users`:

```sql
ALTER TABLE users ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN signup_reason TEXT;
ALTER TABLE users ADD COLUMN role VARCHAR(32);
ALTER TABLE users ADD COLUMN institution VARCHAR(200);

-- Grandfather all existing users (any row visible in this transaction pre-dates the migration)
UPDATE users SET is_approved = TRUE;
```

### Column details

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `is_approved` | `BOOLEAN NOT NULL DEFAULT FALSE` | No | Admin approval gate. New sign-ups default `FALSE`; migration backfills existing rows to `TRUE`. |
| `signup_reason` | `TEXT` | Yes | Free text answer to "Why do you want to use Radflow?" Required at API layer (min 10, max 1000 chars), nullable at DB layer to permit grandfathered rows. |
| `role` | `VARCHAR(32)` | Yes | One of `consultant_radiologist`, `registrar`, `medical_student`, `other_healthcare_professional`, `other`. Required at API layer. Nullable at DB layer for grandfathered rows. |
| `institution` | `VARCHAR(200)` | Yes | Optional free text (e.g. "Guy's and St Thomas'"). |

No indexes added at current scale.

### Downgrade

Standard Alembic `downgrade` drops the four columns. Data in `signup_reason`, `role`, `institution` is lost on downgrade — acceptable given v1 rollout and small volume.

## Sign-up flow

### Frontend — `frontend/src/routes/register/+page.svelte`

Add three controls above the existing password field:

1. **Role** — required dropdown with five options:
   - Consultant radiologist
   - Registrar
   - Medical student
   - Other healthcare professional
   - Other
2. **Institution** — optional text input, max 200 chars, placeholder: `e.g. Guy's and St Thomas'`.
3. **Why do you want to use Radflow?** — required textarea, 4 rows, 10–1000 chars, placeholder: `What made you try Radflow? What are you hoping to use it for?`

Client-side validation: role required, reason required with min 10 chars. Error messages inline beneath the field.

On successful POST, replace the existing "check your email to verify your account" success banner with:

> **Thanks — your account is pending admin approval.**
> We'll email you when it's approved. Once approved you'll also receive a verification email to confirm your address.

The existing form hides on success (unchanged behaviour).

### Backend — `POST /api/auth/register`

Request schema gains three fields:

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: Literal[
        "consultant_radiologist",
        "registrar",
        "medical_student",
        "other_healthcare_professional",
        "other",
    ]
    institution: str | None = Field(default=None, max_length=200)
    signup_reason: str = Field(min_length=10, max_length=1000)
```

Handler behaviour:

1. Existing email-uniqueness check.
2. Existing password hashing.
3. Create user with `is_active=TRUE`, `is_verified=FALSE`, `is_approved=FALSE`, plus the three new fields.
4. Existing magic-link verification email to the user (unchanged — still sends, still sets `is_verified=TRUE` on click).
5. **New:** Admin notification email to `hass.ahmad.95@gmail.com` (env-driven: `ADMIN_NOTIFICATION_EMAIL`) containing user details and approve/reject links.
6. Return the existing success response.

The two emails are sent in sequence within the same request handler. If the admin email fails, the request still succeeds (user is created; admin just doesn't get notified — user is surfaced by missing approval over time). Log the failure.

### Admin notification email

Plain-text body, example:

```
A new user signed up for Radflow:

Name:        George Shaw
Email:       georgewshaw@hotmail.co.uk
Role:        Registrar
Institution: Guy's and St Thomas'
Signed up:   2026-04-21 14:03 UTC

Why Radflow?
"Want to speed up on-call CT reporting during overnights"

Approve:  https://radflow.app/api/admin/approve?uid=<UUID>&token=<HMAC>
Reject:   https://radflow.app/api/admin/reject?uid=<UUID>&token=<HMAC>
```

Rendered via the existing Resend pipeline, fallback to SMTP (same as magic-link email). Subject: `[Radflow] New sign-up: George Shaw (Registrar)`.

## Login flow change

`POST /api/auth/login` currently gates on `is_active` then `is_verified`. Add `is_approved` as a third gate, ordered to report the most actionable blocker first:

```python
# existing
if not user.is_active:
    raise HTTPException(403, detail="Account disabled")

# NEW — before is_verified check
if not user.is_approved:
    raise HTTPException(403, detail="Account pending admin approval")

# existing
if not user.is_verified:
    raise HTTPException(403, detail="Email not verified")
```

The approval check comes before the verification check because a user who hasn't been approved doesn't need to be told to verify their email first — that would confuse them into thinking clicking the verify link unblocks login.

## Admin endpoints

Two endpoints, both unauthenticated (HMAC-in-URL is the auth), both `GET` (so they work from any email client without JavaScript):

### `GET /api/admin/approve?uid=<uuid>&token=<hmac>`

1. Constant-time compare `token == HMAC_SHA256(secret=JWT_SECRET_KEY, msg=f"{uid}:approve")`.
2. If mismatch → return `403` HTML page: `Invalid or expired approval link`.
3. If match → load user. If not found, return `404` page.
4. If already approved → return `200` idempotent success page: `✅ User already approved`.
5. Otherwise set `is_approved=TRUE`, commit, return `200` page: `✅ User <email> approved`.

### `GET /api/admin/reject?uid=<uuid>&token=<hmac>`

1. Same HMAC check, with message `f"{uid}:reject"` (distinct from approve token — approve link cannot be used to reject and vice versa).
2. If match → hard-delete user row. Existing ON DELETE CASCADE on child tables (`reports`, `templates`, `report_feedback`, `ephemeral_skill_sheets`, `report_versions`, `password_reset_tokens`, `report_audits`) handles cleanup.
3. Return `200` page: `✅ User <email> rejected and removed`.
4. If user already deleted → `200` idempotent page: `User already removed`.

### Token construction

```python
def sign_admin_action(user_id: UUID, action: Literal["approve", "reject"]) -> str:
    msg = f"{user_id}:{action}".encode()
    return hmac.new(JWT_SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
```

Tokens do not expire. Rationale: the approve link is harmless once approval is set (idempotent); the reject link becomes useless once the user is deleted (`404` idempotent). The link is only valuable during the window between signup and admin action. No token rotation or cleanup needed.

### Idempotency and race handling

Approve and reject are idempotent within their own semantics (re-approving is a no-op, re-rejecting hits the `already removed` path). Cross-action race (admin clicks approve, then reject) works as expected: user becomes approved, then is deleted. Cross-action race in the reverse order (reject, then approve): first click succeeds, second click returns `404` because the user no longer exists — acceptable behaviour.

## Error handling

| Scenario | Behaviour |
|---|---|
| Admin email send fails during register | User is still created; failure logged; admin alerted by missing approval over time. No user-facing error. |
| Verification email send fails during register | Existing behaviour preserved — register returns error, user is not created. |
| HMAC mismatch on approve/reject | `403` HTML page; logged as potential tampering attempt. |
| User UUID not found on approve/reject | `404` HTML page. |
| Frontend submits register with invalid role value | Existing Pydantic 422 error surfaced inline. |
| Login attempted with `is_approved=FALSE` | `403` with actionable detail; frontend shows blue info banner (distinct from red error). |
| Pre-existing pending users (none today, but possible future state) | Admin can approve them via email link at any time. No expiry. |

## Testing

Backend tests (pytest, following existing patterns under `backend/tests/`):

| Test | File | Purpose |
|---|---|---|
| `test_migration_adds_columns_and_grandfathers` | `tests/test_migrations.py` | Runs upgrade on a snapshot DB containing mock users; verifies columns added and existing rows have `is_approved=TRUE`. |
| `test_register_creates_unapproved_user_with_new_fields` | `tests/test_auth.py` | Posts valid register payload; verifies DB row has `is_approved=FALSE` and the three new fields populated. |
| `test_register_rejects_invalid_role` | `tests/test_auth.py` | Posts invalid role; expects 422. |
| `test_register_rejects_short_reason` | `tests/test_auth.py` | Posts 5-char reason; expects 422. |
| `test_register_sends_admin_notification` | `tests/test_auth.py` | Mocks email sender; verifies admin email fired with correct fields and valid HMAC in URLs. |
| `test_login_blocks_pending_approval` | `tests/test_auth.py` | Valid credentials, `is_approved=FALSE`; expects 403 with `"Account pending admin approval"`. |
| `test_login_still_blocks_unverified_after_approval` | `tests/test_auth.py` | `is_approved=TRUE`, `is_verified=FALSE`; expects 403 with `"Email not verified"`. |
| `test_login_succeeds_when_both_flags_true` | `tests/test_auth.py` | Happy path; expects 200 with token. |
| `test_admin_approve_valid_token_flips_flag` | `tests/test_admin.py` | Valid HMAC; expects 200 and `is_approved=TRUE` in DB. |
| `test_admin_approve_invalid_token_rejected` | `tests/test_admin.py` | Bad HMAC; expects 403. |
| `test_admin_approve_idempotent` | `tests/test_admin.py` | Calling twice returns success both times. |
| `test_admin_reject_deletes_user` | `tests/test_admin.py` | Valid HMAC; expects user row gone, cascade effective. |
| `test_admin_reject_idempotent_on_missing_user` | `tests/test_admin.py` | Second call returns 200 with "already removed" copy. |
| `test_admin_approve_token_cannot_reject` | `tests/test_admin.py` | Token signed for `approve` action does not validate against reject endpoint. |

Frontend testing: manual smoke test covering register form validation, success banner copy, and login error-path banner. No unit tests in v1 (the existing frontend does not have a unit test harness; adding one is outside the scope of this spec).

## Files touched

Backend:
- `backend/alembic/versions/<hash>_add_approval_gate_columns.py` (new)
- `backend/src/rapid_reports_ai/database/models.py`
- `backend/src/rapid_reports_ai/database/crud.py`
- `backend/src/rapid_reports_ai/main.py` (register + login handlers)
- `backend/src/rapid_reports_ai/admin_routes.py` (new — approve/reject endpoints)
- `backend/src/rapid_reports_ai/email_utils.py` (add `send_admin_signup_notification`)
- `backend/tests/test_auth.py` (extended)
- `backend/tests/test_admin.py` (new)
- `backend/tests/test_migrations.py` (new or extended)

Frontend:
- `frontend/src/routes/register/+page.svelte`
- `frontend/src/routes/login/+page.svelte`

Configuration:
- `backend/.env`, `backend/.env.example` — add `ADMIN_NOTIFICATION_EMAIL` (default `hass.ahmad.95@gmail.com`).

## Rollout

1. Ship the migration in a release that also ships the register/login/admin changes (no split-deployment window where FE and BE disagree).
2. Existing users unaffected (grandfathered to `is_approved=TRUE`).
3. First post-deploy sign-up should produce the admin email; verify the approve link works end-to-end before closing the ticket.
4. Monitor for two weeks: any pending users older than 24h get a manual email from admin asking for more context.

## Success criteria

- Existing 11 users can still log in post-migration.
- A new sign-up creates a `is_approved=FALSE` user, fires the admin email, shows the pending-approval banner.
- Clicking the approve link flips the flag; the user can then verify email and log in.
- Clicking the reject link hard-deletes the user; they cannot log in with the same email again (and can sign up fresh if they want).
- All backend tests pass.
