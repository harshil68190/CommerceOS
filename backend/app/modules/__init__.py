"""
modules/ — one package per bounded context (auth, and in future
milestones: catalog, inventory, orders, coupons, reviews, admin,
analytics), each following the same internal layout: router -> service ->
repository. This is the layer where the majority of CommerceOS's
business logic lives.
"""
