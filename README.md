# Company Leave Request System

## IT 363 Activity: Role Based Access Control (RBAC)

FastAPI + HTML + CSS + SQLite

## Features

- Role-Based Access Control (RBAC)
- Role identification (based on account role)
- Module permission checks in backend routes
- Permission authorization enforced per route/action
- Employee leave request submission + status tracking
- Supervisor approval/rejection
- Admin user management (CRUD) + reports

## Roles

- Employee: can submit leave requests and view their own requests + status
- Supervisor: can view all requests and approve/reject them
- Admin: can manage users, view all requests, and view reports

## Permission Table

| Module / Action                  | Employee | Supervisor | Admin |
| -------------------------------- | -------- | ---------- | ----- |
| Submit leave request             | ✅       | ❌         | ❌    |
| View own leave requests + status | ✅       | ❌         | ❌    |
| View all leave requests          | ❌       | ✅         | ✅    |
| Approve / Reject requests        | ❌       | ✅         | ❌    |
| Manage users (CRUD)              | ❌       | ❌         | ✅    |
| View reports                     | ❌       | ❌         | ✅    |

## Basic Flow

1. Employee submits a leave request (date range + reason). Status starts as **Pending**.
2. Supervisor reviews all requests and approves/rejects.
3. Employee checks their own requests and sees status updates.
4. Admin manages users (CRUD) and views summary reports.

## Key Routes

- Employee
  - `GET /leave/new` (submit request form)
  - `POST /leave/new` (submit request)
  - `GET /leave/mine` (view own requests)
- Supervisor/Admin
  - `GET /leave` (view all requests)
  - `POST /leave/{request_id}/decide` (approve/reject)
- Admin only
  - `GET /users` (user CRUD: create/edit/delete)
  - `GET /reports` (summary counts)

## Quick Run

1. Install dependencies:
   - `py -m pip install -r requirements.txt`
2. Start app:
   - `py -m uvicorn app:app --reload`
3. Open browser:
   - `http://127.0.0.1:8000/login`

## Security

- Passwords are stored as **hashed** values (salted SHA-256).

## Test Accounts

- admin / poiuytrewq
- employee / poiuytrewq
- supervisor / poiuytrewq

## Notes

Database file is auto-created as `leave_requests.db`.

This system is a simple information system (IS) that demonstrates role-based access control:

- **Role Identification**
  - After login, the user's id is stored in the session (`request.session["user_id"]`).
  - Each request resolves the current user (and their role) using `get_current_user()`.

- **Module Permission**
  - Permissions are defined in a role → module → actions map in `ROLE_PERMISSIONS` (in `app.py`).
  - Example: `employee` has `leave.submit` and `leave.view_own`, but not `leave.view_all`.

- **Permission Authorization**
  - Protected routes call `ensure_permission(user, module, action)` to enforce access.
  - Example: employees can only view `/leave/mine`, while supervisors/admins can access `/leave` and change statuses.
