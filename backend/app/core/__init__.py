"""
core/ — cross-cutting technical concerns with zero business logic.

Per the CommerceOS architecture doc, this package is the single home for
things every other part of the app depends on but that have nothing to do
with commerce domain rules: configuration loading, logging setup, and the
shared exception hierarchy. No feature module should duplicate any of this.
"""
