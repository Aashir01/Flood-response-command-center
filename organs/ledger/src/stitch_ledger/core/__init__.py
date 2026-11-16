"""Pure core logic for ledger-mcp: no network, no MCP imports, no global state.

The tool entry points live in ``stitch_ledger.service`` (dataset, run store, contract mapping);
``optimize.optimize``, ``sensitivity.analyze`` and ``tradeoff.sweep`` are the pure parts.
"""
