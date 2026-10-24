"""Background workers: a second entry point of the backend image (plan section 2).

Run with `python -m app.workers`. Workers have no request and no token; each
event carries its tenant_id (plan G-01).
"""
