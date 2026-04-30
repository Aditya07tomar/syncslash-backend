cmake_minimum_required(VERSION 3.12)
project(SyncSlashEngine)

find_package(pybind11 REQUIRED)

# Compile the C++ code into a Python extension module named 'settlement_engine'
pybind11_add_module(settlement_engine settlement.cpp)

# Optimize for high performance
target_compile_options(settlement_engine PRIVATE -O3)