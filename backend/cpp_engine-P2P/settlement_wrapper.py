"""
settlement_wrapper.py — Bridge between FastAPI and the C++ Settlement Engine

Tries to load the compiled C++ pybind11 module (settlement_engine).
Falls back to a pure Python implementation of the same Minimum Cash Flow algorithm.
Both produce identical results.
"""
import sys
import os

# Add this directory to path so we can import the compiled .so
_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

# Try to import the C++ compiled module
try:
    import settlement_engine as _cpp_engine
    CPP_AVAILABLE = True
    print("✅ C++ Settlement Engine loaded (pybind11)")
except ImportError as e:
    CPP_AVAILABLE = False
    print(f"⚠️ C++ module not available ({e}) — using Python fallback")


class Transaction:
    """Mirrors the C++ Transaction struct."""
    def __init__(self, from_user: str, to_user: str, amount: float):
        self.from_user = from_user
        self.to_user = to_user
        self.amount = amount

    def to_dict(self):
        return {
            "from_user": self.from_user,
            "to_user": self.to_user,
            "amount": self.amount
        }


def _settle_debts_python(net_balances: dict) -> list:
    """
    Pure Python Minimum Cash Flow algorithm.
    Identical logic to settlements.cpp.
    """
    transactions = []
    active = [(amount, name) for name, amount in net_balances.items() if abs(amount) > 0.01]
    active.sort()

    while len(active) > 1:
        debt, debtor = active[0]
        credit, creditor = active[-1]
        active = active[1:-1]

        settled_amount = round(min(abs(debt), credit), 2)
        transactions.append(Transaction(debtor, creditor, settled_amount))

        debt += settled_amount
        credit -= settled_amount

        if abs(debt) > 0.01:
            active.append((debt, debtor))
            active.sort()
        if abs(credit) > 0.01:
            active.append((credit, creditor))
            active.sort()

    return transactions


def settle_debts(net_balances: dict) -> list:
    """Uses C++ engine if available, else Python fallback."""
    if CPP_AVAILABLE:
        cpp_results = _cpp_engine.settle_debts(net_balances)
        return [Transaction(t.from_user, t.to_user, t.amount) for t in cpp_results]
    else:
        return _settle_debts_python(net_balances)


def settle_debts_as_dicts(net_balances: dict) -> list:
    """Returns list of dicts (JSON-serializable)."""
    return [t.to_dict() for t in settle_debts(net_balances)]
