"""
modules/auth/ — the authentication & authorization bounded context.

Per the architecture doc's module layout: `router.py` (HTTP layer only),
`service.py` (business logic), `repository.py` (persistence), and
`dependencies.py` (FastAPI dependencies used by OTHER modules too, e.g.
`get_current_active_user`, `require_admin`, once catalog/orders/etc. need
to protect their own endpoints).
"""
