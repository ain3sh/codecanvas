---
url: https://tree-sitter.github.io/tree-sitter/using-parsers
title: Using Parsers - Tree-sitter
description: Press ← or → to navigate between chapters
fetched: 2025-12-19T03:19:53.095Z
---
Keyboard shortcuts
------------------

Press ← or → to navigate between chapters

Press S or / to search in the book

Press ? to show this help

Press Esc to hide this help

Tree-sitter
-----------

[Using Parsers](#using-parsers)
-------------------------------

This guide covers the fundamental concepts of using Tree-sitter, which is applicable across all programming languages. Although we'll explore some C-specific details that are valuable for direct C API usage or creating new language bindings, the core concepts remain the same.

Tree-sitter's parsing functionality is implemented through its C API, with all functions documented in the [tree\_sitter/api.h](https://github.com/tree-sitter/tree-sitter/blob/master/lib/include/tree_sitter/api.h) header file, but if you're working in another language, you can use one of the following bindings found [here](https://tree-sitter.github.io/tree-sitter/index.html#language-bindings), each providing idiomatic access to Tree-sitter's functionality. Of these bindings, the official ones have their own API docs hosted online at the following pages:

*   [Go](https://pkg.go.dev/github.com/tree-sitter/go-tree-sitter)
*   [Java](https://tree-sitter.github.io/java-tree-sitter)
*   [JavaScript (Node.js)](https://tree-sitter.github.io/node-tree-sitter)
*   [Kotlin](https://tree-sitter.github.io/kotlin-tree-sitter)
*   [Python](https://tree-sitter.github.io/py-tree-sitter)
*   [Rust](https://docs.rs/tree-sitter)
*   [Zig](https://tree-sitter.github.io/zig-tree-sitter)

[](https://tree-sitter.github.io/tree-sitter/index.html "Previous chapter")[](https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html "Next chapter")

[](https://tree-sitter.github.io/tree-sitter/index.html "Previous chapter")[](https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html "Next chapter")