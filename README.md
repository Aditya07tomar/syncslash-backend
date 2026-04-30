---

## **Building the P2P Engine (Mechanism 4)**

[cite_start]The **P2P Settlement Engine**  [cite_start]addresses "Shared Account Messes" [cite: 17] [cite_start]by offloading complex debt simplification to a high-performance **C++ engine**[cite: 23]. [cite_start]It implements a **Minimum Cash Flow algorithm** [cite: 46] [cite_start]to optimize and reduce the total number of peer-to-peer transactions required to settle group balances.

### **Prerequisites**
* **C++ Compiler**: GCC/MinGW (Rev9+ recommended).
* **CMake**: Version 3.12 or higher.
* **Python**: 3.8+ with `pybind11` installed.
* **Environment**: Ensure your compiler and CMake are added to your System PATH.

### **Build Instructions**

1.  **Install pybind11**:
    Ensure the binding library is available in your Python environment:
    ```bash
    pip install pybind11
    ```

2.  **Configure the Build**:
    Navigate to the `backend/cpp_engine` directory and create a build folder:
    ```bash
    mkdir build
    cd build
    ```

3.  **Generate Build Files**:
    Run CMake to configure the project. If using MinGW on Windows, specify the generator and the Python path:
    ```bash
    cmake -G "MinGW Makefiles" -DPYBIND11_FINDPYTHON=ON -Dpybind11_DIR="<path_to_pybind11_cmake>" ..
    ```

4.  **Compile the Engine**:
    Build the source into a native Python extension:
    ```bash
    cmake --build . --config Release
    ```

### **Deployment**
After a successful build, a `.pyd` (Windows) or `.so` (Linux/macOS) file will be generated in the `build` directory. [cite_start]Move this file to the `backend/` root to allow the **FastAPI** application [cite: 21, 58] to import it:
```python
[cite_start]import settlement_engine  # High-performance C++ core [cite: 23]