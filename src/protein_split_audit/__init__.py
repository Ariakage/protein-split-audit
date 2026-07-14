from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("protein-split-audit")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
