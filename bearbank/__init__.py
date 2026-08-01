"""
BearBank — the demo estate AutoSRE is shown against.

Two independent 5-service estates, one per tenant, that call each other over
real HTTP so Jaeger builds a genuine dependency DAG and the knowledge graph has
architecture to reason about.

    demo/bearbank/
      topology.py  — both estates; the single source of truth
      faults.py    — three fault mechanics, composed into five scenarios
      service.py   — one generic service, ten deployments

See docs/DEMO.md for the scenarios and what each one demonstrates.
"""
