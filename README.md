# Simple Digital Suggestion Box System
## IT 363 Activity: Role Based Access Control

FastAPI + HTML + CSS + SQLite

## Features

- Role-Based Access Control (RBAC)
- Role identification (based on account role)
- Module permission checks in backend routes
- Permission authorization enforced per route/action
- Modules:
  - Suggestions
  - Responses
  - Users

## Roles

- Admin: manage suggestions, responses, users
- Student: submit suggestions, view responses
- Reviewer: view suggestions, reply to suggestions

## Permission Table

| Role     | Suggestions | Responses | Users     |
|----------|-------------|-----------|-----------|
| Admin    | Manage      | Manage    | Manage    |
| Student  | Submit      | View      | No access |
| Reviewer | View        | Reply     | No access |

## Basic Flow

1. Student submits a suggestion.
2. Reviewer reads the suggestion.
3. Reviewer writes a response.
4. Student views the response.
5. Admin manages users and monitors the system.

## Quick Run

1. Install dependencies:
   - `py -m pip install -r requirements.txt`
2. Start app:
   - `py -m uvicorn app:app --reload`
3. Open browser:
   - `http://127.0.0.1:8000/login`

## Test Accounts

- admin / poiuytrewq
- student / poiuytrewq
- reviewer / poiuytrewq

## Notes

- Database file is auto-created as `suggestion_box.db`.
- This is intentionally simple code for school activity use.
