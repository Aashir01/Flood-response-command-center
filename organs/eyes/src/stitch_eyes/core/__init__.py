"""Pure core logic for eyes-mcp: no network, no MCP imports, no global state.

Modules depend only on NumPy (plus rasterio, shapely, pyproj and SciPy for in-memory geometry),
so the training scripts can import ``preprocess`` and ``metrics`` without the MCP stack.
"""
