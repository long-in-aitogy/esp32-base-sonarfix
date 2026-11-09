# API documentation

The repository Doxygen configuration is in [`Doxyfile`](../Doxyfile).

It documents all functions, structs, classes, and members under `include/` and
`src/`, except code in directories named `backend`.

Generate the HTML documentation with:

```text
doxygen Doxyfile
```

The generated site is written to `docs/api/html/index.html`. Generated output
is not source code and should not be committed.

The generated API pages include caller and callee graphs. Standard-library
namespaces (`std` and `__gnu_cxx`) are excluded from those graphs. Graphs
require Graphviz's `dot` executable to be installed and available on `PATH`.
