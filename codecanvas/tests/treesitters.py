"""Tree-sitter extractor tests across supported languages."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def _imports():
    """Import tree-sitter modules with a robust fallback."""
    try:
        from parser.treesitter import (  # type: ignore[import-not-found]
            c,
            go,
            java,
            parse_source,
            python,
            ruby,
            rust,
            shell,
            typescript,
        )

        return parse_source, python, typescript, go, rust, java, ruby, c, shell
    except Exception:
        from codecanvas.parser.treesitter import (  # type: ignore[import-not-found]
            c,
            go,
            java,
            parse_source,
            python,
            ruby,
            rust,
            shell,
            typescript,
        )

        return parse_source, python, typescript, go, rust, java, ruby, c, shell


parse_source, py_ts, ts_ts, go_ts, rs_ts, java_ts, rb_ts, c_ts, sh_ts = _imports()


def _parse(text: str, *, file_path: str, lang_key: str):
    src = dedent(text).lstrip("\n")
    parsed = parse_source(src, file_path=Path(file_path), lang_key=lang_key)
    assert parsed is not None
    return src, parsed


def _defs_by_name(defs):
    return {d.name: d for d in defs}


def _call_tuples(sites):
    return {(s.line, s.char) for s in sites}


def _lc(src: str, *, line_contains: str, needle: str) -> tuple[int, int]:
    for i, line in enumerate(src.splitlines()):
        if line_contains in line:
            return i, line.index(needle)
    raise AssertionError(f"Could not find line containing {line_contains!r} with needle {needle!r}")


def test_python_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        import os, sys
        import pkg.mod as pm
        from . import util as u
        from pkg.mod import thing

        class Foo:
            def bar(self):
                helper_call()
                self.baz_call().qux_call()
                return 1

            class Inner:
                def baz_call(self):
                    return other_call()

        def top():
            def nested():
                pass
            return Foo().bar()
        """,
        file_path="x.py",
        lang_key="py",
    )

    defs = py_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Foo" in defs_map and defs_map["Foo"].kind == "class"
    assert "Foo.bar" in defs_map and defs_map["Foo.bar"].parent_class == "Foo"
    assert "Inner" in defs_map and defs_map["Inner"].parent_class == "Foo"
    assert "Inner.baz_call" in defs_map and defs_map["Inner.baz_call"].parent_class == "Inner"
    assert "top" in defs_map and defs_map["top"].kind == "func"
    assert all(d.bare_name != "nested" for d in defs)

    imports = py_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"os", "sys", "pkg.mod", "."}.issubset(set(imports))

    sites = _call_tuples(py_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="helper_call()", needle="helper_call") in sites
    assert _lc(text, line_contains="self.baz_call()", needle="baz_call") in sites
    assert _lc(text, line_contains="self.baz_call()", needle="qux_call") in sites
    assert _lc(text, line_contains="other_call()", needle="other_call") in sites
    assert _lc(text, line_contains="Foo().bar()", needle="Foo") in sites
    assert _lc(text, line_contains="Foo().bar()", needle="bar") in sites


def test_typescript_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        import fs from "fs";
        import { join as joinPath } from "path";
        const lodash = require("lodash");

        export class Foo {
          barMethod() {
            helperCall();
            this.bazMethod().quxCall().zap();
          }

          bazMethod() {
            function nestedInner() { return 1; }
            return this;
          }
        }

        function topFn() {
          return Foo.prototype.barMethod();
        }

        const arrowFn = () => {
          return topFn();
        };

        const exprFn = function() {
          return arrowFn();
        };
        """,
        file_path="x.ts",
        lang_key="ts",
    )

    defs = ts_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Foo" in defs_map and defs_map["Foo"].kind == "class"
    assert "Foo.barMethod" in defs_map and defs_map["Foo.barMethod"].parent_class == "Foo"
    assert "Foo.bazMethod" in defs_map and defs_map["Foo.bazMethod"].parent_class == "Foo"
    assert "topFn" in defs_map and defs_map["topFn"].kind == "func"
    assert "arrowFn" in defs_map and defs_map["arrowFn"].kind == "func"
    assert "exprFn" in defs_map and defs_map["exprFn"].kind == "func"
    assert all(d.bare_name != "nestedInner" for d in defs)

    imports = ts_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"fs", "path", "lodash"}.issubset(set(imports))

    sites = _call_tuples(ts_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="helperCall()", needle="helperCall") in sites
    assert _lc(text, line_contains="this.bazMethod()", needle="bazMethod") in sites
    assert _lc(text, line_contains="this.bazMethod()", needle="quxCall") in sites
    assert _lc(text, line_contains="this.bazMethod()", needle="zap") in sites
    assert _lc(text, line_contains="Foo.prototype.barMethod()", needle="barMethod") in sites
    assert _lc(text, line_contains="return topFn()", needle="topFn") in sites
    assert _lc(text, line_contains="return arrowFn()", needle="arrowFn") in sites


def test_go_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        package main

        import (
            "fmt"
            io "io"
        )
        import "strings"

        type Foo struct {
            x int
        }

        type Bar interface {
            Do() error
        }

        func (f *Foo) Method(a int) int {
            fmt.Println("hi")
            f.Helper()
            return a
        }

        func (Foo) Helper() {}

        func Top() {
            type Local struct{}
            fmt.Printf("%d", 1)
            Foo{}.Helper()
            strings.TrimSpace(" x ")
        }
        """,
        file_path="x.go",
        lang_key="go",
    )

    defs = go_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Foo" in defs_map and defs_map["Foo"].kind == "class"
    assert "Bar" in defs_map and defs_map["Bar"].kind == "class"
    assert "Foo.Method" in defs_map and defs_map["Foo.Method"].parent_class == "Foo"
    assert "Foo.Helper" in defs_map and defs_map["Foo.Helper"].parent_class == "Foo"
    assert "Top" in defs_map and defs_map["Top"].kind == "func"
    assert "Local" in defs_map and defs_map["Local"].kind == "class"

    imports = go_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"fmt", "io", "strings"}.issubset(set(imports))

    sites = _call_tuples(go_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="fmt.Println", needle="Println") in sites
    assert _lc(text, line_contains="f.Helper()", needle="Helper") in sites
    assert _lc(text, line_contains="Foo{}.Helper()", needle="Helper") in sites
    assert _lc(text, line_contains="strings.TrimSpace", needle="TrimSpace") in sites


def test_rust_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        use std::io;
        use crate::mod1::Thing as T;
        use super::{foo, bar};

        struct Foo { x: i32 }

        enum Kind { A, B }

        trait Greeter {
            fn greet(&self);
        }

        impl Foo {
            fn method(&self) {
                helper();
                self.other().chain();
                println!("hi");
            }

            fn other(&self) -> Foo {
                Foo { x: 0 }
            }
        }

        fn helper() {}
        """,
        file_path="x.rs",
        lang_key="rs",
    )

    defs = rs_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Foo" in defs_map and defs_map["Foo"].kind == "class"
    assert "Kind" in defs_map and defs_map["Kind"].kind == "class"
    assert "Greeter" in defs_map and defs_map["Greeter"].kind == "class"
    assert "Foo.method" in defs_map and defs_map["Foo.method"].parent_class == "Foo"
    assert "Foo.other" in defs_map and defs_map["Foo.other"].parent_class == "Foo"
    assert "helper" in defs_map and defs_map["helper"].kind == "func"

    imports = rs_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"std::io", "crate::mod1::Thing", "super"}.issubset(set(imports))

    sites = _call_tuples(rs_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="helper()", needle="helper") in sites
    assert _lc(text, line_contains="self.other()", needle="other") in sites
    assert _lc(text, line_contains="self.other()", needle="chain") in sites
    assert _lc(text, line_contains="println!", needle="println") in sites


def test_java_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        package com.example;

        import java.util.List;
        import static java.lang.Math.max;

        public class Foo {
            public Foo() {}

            public void bar() {
                Top.helper();
                this.baz().qux();
                new Bar();
            }

            class Bar {
                Bar() {}
                void baz() {}
            }

            Foo baz() { return this; }
        }

        class Top {
            static void helper() {}
        }
        """,
        file_path="X.java",
        lang_key="java",
    )

    defs = java_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Foo" in defs_map and defs_map["Foo"].kind == "class"
    assert "Foo.Foo" in defs_map and defs_map["Foo.Foo"].parent_class == "Foo"
    assert "Foo.bar" in defs_map and defs_map["Foo.bar"].parent_class == "Foo"
    assert "Foo.baz" in defs_map and defs_map["Foo.baz"].parent_class == "Foo"
    assert "Bar" in defs_map and defs_map["Bar"].parent_class == "Foo"
    assert "Bar.Bar" in defs_map and defs_map["Bar.Bar"].parent_class == "Bar"
    assert "Bar.baz" in defs_map and defs_map["Bar.baz"].parent_class == "Bar"
    assert "Top" in defs_map and defs_map["Top"].kind == "class"
    assert "Top.helper" in defs_map and defs_map["Top.helper"].parent_class == "Top"

    imports = java_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"java.util.List", "java.lang.Math.max"}.issubset(set(imports))

    sites = _call_tuples(java_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="Top.helper()", needle="helper") in sites
    assert _lc(text, line_contains="this.baz()", needle="baz") in sites
    assert _lc(text, line_contains="this.baz()", needle="qux") in sites
    assert _lc(text, line_contains="new Bar()", needle="Bar") in sites


def test_ruby_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        require 'json'
        require_relative "utils/helpers"
        load 'extra.rb'

        module Outer
          class Foo
            def bar
              helper_call()
              self.baz_call().qux_call().zap_call()
            end

            def baz_call
              other_call()
            end

            def self.singleton_call
              Foo.new.bar()
            end
          end
        end
        """,
        file_path="x.rb",
        lang_key="rb",
    )

    defs = rb_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Outer" in defs_map and defs_map["Outer"].kind == "class"
    assert "Foo" in defs_map and defs_map["Foo"].parent_class == "Outer"
    assert "Foo.bar" in defs_map and defs_map["Foo.bar"].parent_class == "Foo"
    assert "Foo.baz_call" in defs_map and defs_map["Foo.baz_call"].parent_class == "Foo"
    assert "Foo.singleton_call" in defs_map and defs_map["Foo.singleton_call"].parent_class == "Foo"

    imports = rb_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"json", "utils/helpers", "extra.rb"}.issubset(set(imports))

    sites = _call_tuples(rb_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="helper_call()", needle="helper_call") in sites
    assert _lc(text, line_contains="self.baz_call()", needle="baz_call") in sites
    assert _lc(text, line_contains="self.baz_call()", needle="qux_call") in sites
    assert _lc(text, line_contains="self.baz_call()", needle="zap_call") in sites
    assert _lc(text, line_contains="other_call()", needle="other_call") in sites
    assert _lc(text, line_contains="Foo.new.bar()", needle="new") in sites
    assert _lc(text, line_contains="Foo.new.bar()", needle="bar") in sites


def test_c_cpp_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        #include <vector>
        #include "my.h"

        namespace ns {
        int util() { return 0; }
        }

        int ns::util2() { return 0; }

        struct Outer {
          struct Inner {
            void inner_method() { helper(); }
          };

          void method() {
            helper();
            Inner i;
            i.inner_method();
          }
        };

        int helper() { return 1; }

        int main() {
          Outer o;
          o.method();
          ns::util();
          ns::util2();
          return 0;
        }
        """,
        file_path="x.cpp",
        lang_key="c",
    )

    defs = c_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "Outer" in defs_map and defs_map["Outer"].kind == "class"
    assert "Inner" in defs_map and defs_map["Inner"].parent_class == "Outer"
    assert "Inner.inner_method" in defs_map and defs_map["Inner.inner_method"].parent_class == "Inner"
    assert "Outer.method" in defs_map and defs_map["Outer.method"].parent_class == "Outer"
    assert "helper" in defs_map and defs_map["helper"].kind == "func"
    assert "main" in defs_map and defs_map["main"].kind == "func"

    imports = c_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"vector", "my.h"}.issubset(set(imports))

    sites = _call_tuples(c_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="helper();", needle="helper") in sites
    assert _lc(text, line_contains="i.inner_method()", needle="inner_method") in sites
    assert _lc(text, line_contains="o.method()", needle="method") in sites
    assert _lc(text, line_contains="ns::util();", needle="util") in sites
    assert _lc(text, line_contains="ns::util2();", needle="util2") in sites


def test_shell_extracts_definitions_imports_and_calls():
    text, parsed = _parse(
        """
        #!/usr/bin/env bash
        source "./env.sh"
        . ./lib.sh

        foo() {
          echo "hi"
          bar
        }

        bar() {
          printf "%s\n" "ok"
        }

        foo
        """,
        file_path="x.sh",
        lang_key="sh",
    )

    defs = sh_ts.extract_definitions(parsed.src, parsed.root)
    defs_map = _defs_by_name(defs)

    assert "foo" in defs_map and defs_map["foo"].kind == "func"
    assert "bar" in defs_map and defs_map["bar"].kind == "func"

    imports = sh_ts.extract_import_specs(parsed.src, parsed.root)
    assert {"./env.sh", "./lib.sh"}.issubset(set(imports))

    sites = _call_tuples(sh_ts.extract_call_sites(parsed.src, parsed.root))
    assert _lc(text, line_contains="source", needle="source") in sites
    assert _lc(text, line_contains=". ./lib.sh", needle=".") in sites
    assert _lc(text, line_contains="echo", needle="echo") in sites
    assert _lc(text, line_contains="bar", needle="bar") in sites
    assert _lc(text, line_contains="printf", needle="printf") in sites
    call_line = next(i for i, line in enumerate(text.splitlines()) if line.strip() == "foo")
    assert (call_line, text.splitlines()[call_line].index("foo")) in sites
