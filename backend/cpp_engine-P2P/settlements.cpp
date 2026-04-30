#include <iostream>
#include <vector>
#include <string>
#include <map>
#include <set>
#include <cmath>
#include <iomanip>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

using namespace std;
namespace py = pybind11;

struct Transaction {
    string debtor;
    string creditor;
    double amount;
};

vector<Transaction> settle_debts(const map<string, double>& net_balances) {
    vector<Transaction> transactions;
    set<pair<double, string>> active_balances;

    for (const auto& [name, amount] : net_balances) {
        if (abs(amount) > 0.01) {
            active_balances.insert({amount, name});
        }
    }

    while (active_balances.size() > 1) {
        auto first = active_balances.begin(); 
        double debt = first->first;
        string debtor = first->second;

        auto last = prev(active_balances.end()); 
        double credit = last->first;
        string creditor = last->second;

        active_balances.erase(first);
        active_balances.erase(last);

        double settled_amount = min(abs(debt), credit);
        settled_amount = round(settled_amount * 100.0) / 100.0;

        transactions.push_back({debtor, creditor, settled_amount});

        debt += settled_amount;
        credit -= settled_amount;

        if (abs(debt) > 0.01) {
            active_balances.insert({debt, debtor});
        }
        if (abs(credit) > 0.01) {
            active_balances.insert({credit, creditor});
        }
    }

    return transactions;
}

PYBIND11_MODULE(settlement_engine, m) {
    m.doc() = "SyncSlash C++ Engine for P2P Settlement via Minimum Cash Flow";
    
    py::class_<Transaction>(m, "Transaction")
        .def_readonly("from_user", &Transaction::debtor)
        .def_readonly("to_user", &Transaction::creditor)
        .def_readonly("amount", &Transaction::amount);

    m.def("settle_debts", &settle_debts, "Calculates the minimum cash flow to settle group debts.");
}