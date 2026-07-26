"""
workers/ — reserved for background task processing (e.g. Celery or RQ),
per the CommerceOS architecture doc (email sending, invoice generation,
low-stock alerts, etc.).

This milestone is backend-foundation only: no task queue is wired up yet,
and no tasks exist. The folder is created now (per the architecture's
folder structure) so later milestones have an established home for
worker code instead of it being bolted on ad hoc. Intentionally empty
beyond this marker file.
"""
