"""
modules/products/ — the product catalog bounded context.

Follows the same internal layout as `modules/auth/`: `router.py` (HTTP
layer only), `service.py` (business logic), `repository.py`
(persistence). Authorization is NOT reimplemented here — this module
imports and reuses `get_current_active_user`/`_require_role` from
`modules/auth/dependencies`, since catalog management is just another
consumer of the existing auth system, not a reason to duplicate it.
"""
