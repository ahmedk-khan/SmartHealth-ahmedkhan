"""
SmartHealth Application Package

Exports critical core modules to enable clean circular-dependency-free imports:
  from app import db              # Direct access to database session factory
  from app.db import SessionLocal # Explicit database session import
"""

from app import db

__all__ = ["db"]
