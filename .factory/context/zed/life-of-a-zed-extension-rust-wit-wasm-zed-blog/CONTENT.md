---
url: https://zed.dev/blog/zed-decoded-extensions
title: Life of a Zed Extension: Rust, WIT, Wasm - Zed Blog
description: From the Zed Blog: In this episode of Zed Decoded, Thorsten talks to Max and Marshall, who have built Zed's extension system, asking them to explain to him: what happens when I install an extension? How does it all work?
fetched: 2025-12-19T03:19:09.293Z
---
Earlier this year, [extensions landed in Zed](https://zed.dev/extensions), adding the ability to add more languages, themes, snippets, and slash commands to Zed.

The extension system was built by [Max](https://zed.dev/team#max-brunsfeld) and [Marshall](https://zed.dev/team#marshall-bowers) and in April, Max wrote an [excellent blog post](https://zed.dev/blog/language-extensions-part-1) about some of the intricate engineering challenges behind extensions and how they overcame them. It also explains that extensions are run as [WebAssembly](https://webassembly.org/) (Wasm) modules and why and how Tree-sitter is used within Wasm.

Half a year later, that's still all I really know about how our extensions work — not a lot, considering how much more there is to know. I know, for example, that extensions are written in Rust, but how are they compiled and when? I know extensions can provide language servers to Zed, but how _exactly_ does that work? And how _exactly_ do we run them as Wasm modules inside Zed? How does it all fit together? I need to know!

Two weeks ago, I finally had the chance to sit down with Marshall and Max and ask them everything I wanted to know about extensions. To kick us down the rabbit hole, I asked them: what exactly happens when I install an extension in Zed?

Companion Video

Life of a Zed Extension: Rust, WIT, Wasm

This post comes with a 1hr companion video, in which Marshall, Max, and Thorsten explore extensions in Zed, digging through the codebase to see how Rust, Wasm, WIT and extensions fit together and end up running in Zed.

[Watch the video here →](https://youtu.be/Ft58q9E0G5Y)

[![Life of a Zed Extension: Rust, WIT, Wasm](https://zed.dev/img/post/zed-decoded-extensions/thumbnail.jpg)](https://youtu.be/Ft58q9E0G5Y)

[The Question](#the-question)
-----------------------------

The extension I used as an example to ask "what happens when I install this?" was the [zed-metals](https://github.com/scalameta/metals-zed) extension. It adds support for Scala to Zed by adding the Scala Tree-sitter parser, [Tree-sitter queries](https://github.com/scalameta/metals-zed/tree/2cafe1f067bcff9c8cba8829f5c33017b8308d76/languages/scala), and — the interesting bit for me in that conversation — it also adds support for the [Metals language server](https://github.com/scalameta/metals).

And it's _written in Rust_! Yes, here, take a look:

![Screenshot of the single Rust file in the metals-zed repository](https://zed.dev/img/post/zed-decoded-extensions/zed_metals.png)

Screenshot of the single Rust file in the metals-zed repository

There's not a lot more in that repository. There's an `extension.toml` file with metadata about the extension, the Tree-sitter queries, and this single Rust file.

So the question I wanted to answer was this one: when I install this extension, when and how and where is the Rust code in that `lib.rs` file compiled and how does it end up being executed in Zed when I use the `zed-metals` extension?

In [our conversation](https://youtu.be/Ft58q9E0G5Y) Max and Marshall patiently walked me through the all of the code involved so that I can now report: we figured it out!

[Installing Extensions](#installing-extensions)
-----------------------------------------------

When you open Zed, hit `cmd-p`/`ctrl-p` and type in `zed: extensions`. You'll see this:

![The zed: extensions view in Zed](https://zed.dev/img/post/zed-decoded-extensions/zed_extensions_view.png)

The zed: extensions view in Zed

This extensions view shows all extensions available in Zed and which ones you have installed.

So, first things first: where does that list of extensions come from? Its ur-origin is this repository: [github.com/zed-industries/extensions](https://github.com/zed-industries/extensions).

![The list of repositories in the zed-industries/extensions repository](https://zed.dev/img/post/zed-decoded-extensions/zed_extensions_repo.png)

The list of repositories in the zed-industries/extensions repository

This repository is the source of truth for which extensions exist in Zed. It contains references to all other repositories of Zed extensions.

(Did you just have a visceral reaction and thought "yuck! the extension registry is a repository?". Hey, we're with you! When I asked Max and Marshall what they think will have to change about the extension system in the future, Max said that this repository will likely have to go. It doesn't scale, but it worked very well so far.)

The repository and the list of extensions it contains is mirrored regularly to [zed.dev](https://zed.dev/), on which we run our Zed API. I'm using "mirrored" loosely here: not the actual contents git repository is mirrored, only its contents (you'll see). And when you run `zed: extensions`, your Zed sends a request to zed.dev's API and ask it for the list of extensions.

So then what happens when you decide to install an extensions by clicking on the `Install` button?

It first has to be downloaded, of course. But the question is: _what_ is being downloaded? The _Rust code_? Do you download and compile Rust code?

Turns out, no, you don't. And this is where things become fun.

### [From the `extensions` repository to your Zed](#from-the-extensions-repository-to-your-zed)

The `extensions` repository contains [a CI step](https://github.com/zed-industries/extensions/blob/5493e434c7afa9dbdfdf329fe23675f5538005e3/.github/workflows/ci.yml#L44-L72) that ends up executing the "extensions CLI", a small CLI program that lives in the Zed repository [in the `extensions_cli` crate](https://github.com/zed-industries/zed/tree/5168fc27a17dca0f1dac52f4431376eabfd18782/crates/extension_cli).

It's made up of a [a single file](https://github.com/zed-industries/zed/blob/e87fe6726f29a68b9ee86f99ab9f88f1204209bf/crates/extension_cli/src/main.rs#L68) and its main job is to accept a directory containing a Zed extension and compile it.

Lucky for us explorers, we don't need to use a CI system to that. We can run the binary manually on our machine. Here's what that looks like when I use it (the binary is called `zed-extension` here) to compile `metals-zed`:

    $ mkdir output
    $ zed-extension --source-dir ./metals-zed --output ./output --scratch-dir $(mktemp -d)
    info: downloading component 'rust-std' for 'wasm32-wasip1'
    info: installing component 'rust-std' for 'wasm32-wasip1'
     
    $ ls -1 ./output
    archive.tar.gz
    manifest.json

That produced two files: `archive.tar.gz` and `manifest.json`.

The `manifest.json` contains the metadata you see in the `zed: extension` view inside Zed:

    $ cat ./output/manifest.json | jq .
    {
      "name": "Scala",
      "version": "0.1.0",
      "description": "Scala support.",
      "authors": [
        "Igal Tabachnik <[email protected]>",
        "Jamie Thompson <[email protected]>",
     
      ],
      "repository": "https://github.com/scalameta/metals-zed",
      "schema_version": 1,
      "wasm_api_version": "0.0.6"
    }

It's generated from [the `extension.toml`](https://github.com/scalameta/metals-zed/blob/2cafe1f067bcff9c8cba8829f5c33017b8308d76/extension.toml) in the repository.

So what's in `archive.tar.gz`?

    $ tar -ztf ./output/archive.tar.gz
    ./
    ./extension.toml
    ./extension.wasm
    ./languages/
    ./grammars/
    ./grammars/scala.wasm
    ./languages/scala/
    ./languages/scala/outline.scm
    ./languages/scala/indents.scm
    ./languages/scala/highlights.scm
    ./languages/scala/config.toml
    ./languages/scala/overrides.scm
    ./languages/scala/injections.scm
    ./languages/scala/runnables.scm
    ./languages/scala/brackets.scm

There's an `extension.toml` file that's _nearly_ the same [as the one in the extension repository](https://github.com/scalameta/metals-zed/blob/2cafe1f067bcff9c8cba8829f5c33017b8308d76/extension.toml), but contains some more metadata added at compile-time, including _the version of the Zed extension Rust API the extension was compiled against_ — keep that in the back of your head, we'll come back to it.

The `extension.wasm` file is the [`lib.rs` file we saw earlier](https://github.com/scalameta/metals-zed/blob/2cafe1f067bcff9c8cba8829f5c33017b8308d76/src/lib.rs), the Rust code, compiled into Wasm.

The `grammars/scala.wasm` is the Tree-sitter grammars compiled into Wasm. ([Max's blog post](https://zed.dev/blog/language-extensions-part-1) explains how Tree-sitter and Wasm are compiled here.)

And then there's a bunch of Scheme files — `outline.scm`, `highlights.scm`, ... — that contain Tree-sitter queries which Zed executes at runtime to, for example, get syntax highlighting for a Scala file.

So, what we know so far: an extension is compiled with a small CLI tool and that compilation results in two files. A `manifest.json` with metadata and an archive that contains two Wasm files and a bunch of small Scheme files.

In CI, the next thing that would happen after compiling the extension, is that both files are uploaded to a place that's reachable from the zed.dev API. The code for that lives in the `zed-industries/extensions` repository, as some neatly-written JavaScript code in [package-extensions.js](https://github.com/zed-industries/extensions/blob/7007e36546d4f09ef24c9f562738866f7fd3954c/src/package-extensions.js#L39).

The code goes through all the extensions in the repository, [compiles them with the `extensions_cli` from the Zed repository](https://github.com/zed-industries/extensions/blob/7007e36546d4f09ef24c9f562738866f7fd3954c/src/package-extensions.js#L169-L186) (just like I showed you), and uploads the resulting `archive.tar.gz` and `manifest.json` files to an S3 bucket.

And _that_ bucket — not the `zed-industries/extensions` repository — is what gets mirrored by zed.dev and made accessible through its API. Every few minutes, zed.dev fetches the `manifest.json` files from the S3 bucket and stores their contents in a database, along with the URL of the `archive.tar.gz` files.

We have our first answer: when you install an extension, you don't compile Rust code. You download and unpack an archive that contains Wasm and Scheme code.

But that's skipping over quite a few things. I mean, what exactly happens when an extension is compiled from Rust to Wasm?

[Compiling an extension](#compiling-an-extension)
-------------------------------------------------

Let's take a look at a very simple Zed extension written in Rust:

    use zed_extension_api::{self as zed, Result};
     
    struct MyExtension;
     
    impl MyExtension {
        const SERVER_BINARY_NAME: &'static str = "my-language-server";
    }
     
    impl zed::Extension for MyExtension {
        fn new() -> Self {
            Self
        }
     
        fn language_server_command(
            &mut self,
            _language_server_id: &zed::LanguageServerId,
            worktree: &zed::Worktree,
        ) -> Result<zed::Command> {
            let path = worktree
                .which(Self::SERVER_BINARY_NAME)
                .ok_or_else(|| format!("Could not find {} binary", Self::SERVER_BINARY_NAME))?;
     
            Ok(zed::Command {
                command: path,
                args: vec!["--use-printf-debugging".to_string()],
                env: worktree.shell_env(),
            })
        }
    }
     
    zed::register_extension!(MyExtension);

This is a fictional extension I just threw together. All it does is to define how to run the also fictional `my-language-server` binary: it looks up the location of the binary in the `$PATH` of Zed worktree that's open and returns some arguments with which to run it.

But `MyExtension` is an empty struct. It doesn't even have any fields. What makes it a Zed extension is the fact that it implements the `zed::Extension` trait — where does that come from?

It's a dependency added in the `Cargo.toml` of my fictional extension, down there, on the last line:

    [package]
    name = "test-extension"
    version = "0.1.0"
    edition = "2021"
     
    [lib]
    crate-type = ["cdylib"]
     
    [dependencies]
    zed_extension_api = "0.0.6"

Then next question then is: what is in that `zed_extension_api` crate? It can't just be Rust code, right? Because after all, we want the extension to compile down to and run as Wasm.

And that's where things become _really_ interesting!

[The extension\_api crate](#the-extension_api-crate)
----------------------------------------------------

The `zed::Extension` trait is defined in the [`extension_api` crate](https://github.com/zed-industries/zed/tree/5168fc27a17dca0f1dac52f4431376eabfd18782/crates/extension_api) in the Zed repository, [in the `extension_api.rs` file](https://github.com/zed-industries/zed/blob/5168fc27a17dca0f1dac52f4431376eabfd18782/crates/extension_api/src/extension_api.rs#L61), which looks — on first glance — pretty normal:

    // Excerpt from `extension_api.rs`
     
    /// A Zed extension.
    pub trait Extension: Send + Sync {
        /// Returns a new instance of the extension.
        fn new() -> Self
        where
            Self: Sized;
     
        /// Returns the command used to start the language server for the specified
        /// language.
        fn language_server_command(
            &mut self,
            _language_server_id: &LanguageServerId,
            _worktree: &Worktree,
        ) -> Result<Command> {
            Err("`language_server_command` not implemented".to_string())
        }
     
        /// Returns the initialization options to pass to the specified language server.
        fn language_server_initialization_options(
            &mut self,
            _language_server_id: &LanguageServerId,
            _worktree: &Worktree,
        ) -> Result<Option<serde_json::Value>> {
            Ok(None)
        }
     
        // [...]
    }

It's a normal Rust trait that defines a bunch of methods with default implementations that extensions can choose to implement. It's hand-written (you'll find out in a few moments why I make that distinction) and defines the outer-most layer of our extension API. From the perspective of an extension's author, this trait is all they have to interact with.

In the same file, there are more type definitions, which we've seen in the fictional extension from above too. `LanguageServerId`, for example. That's defined [here](https://github.com/zed-industries/zed/blob/a56f946a7d0734839f820d2943dabe7fa09a4b22/crates/extension_api/src/extension_api.rs#L286-L288), like this:

    /// The ID of a language server.
    #[derive(Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Clone)]
    pub struct LanguageServerId(String);

Again: normal looking Rust.

But then, if you look around that file and try to jump to some definitions, you'll notice that there are some definitions that are _not_ hand-written — they don't even show up in the file. `Worktree`, for example, which we also saw above in our fictional code. Where is that defined?

And this is where the Rust rubber hits the Wasm road. Or where the Wasm rubber hits the Rust road. Or Wasm sky meets Rust sea. Or Rust style meets Wasm substance — you get the idea, we're close to figuring things out.

Because those types are defined at _compile time_! That's right. The types spring forth from [this little paragraph](https://github.com/zed-industries/zed/blob/5168fc27a17dca0f1dac52f4431376eabfd18782/crates/extension_api/src/extension_api.rs#L184-L191) in the same `extension_api.rs` file, at compile time:

    // Excerpt from extension_api.rs
     
    mod wit {
        wit_bindgen::generate!({
            skip: ["init-extension"],
            path: "./wit/since_v0.2.0",
        });
    }

Now what does this paragraph do? To answer that, we have to take a step back.

[Marshall and Max explained to me](https://youtu.be/Ft58q9E0G5Y) that extensions are built on the [WebAssembly Component Model](https://component-model.bytecodealliance.org/), which I've never heard of but have since researched. There's _a lot_ we could talk about here, but to keep us focused, I'm going to skip over quite a few details here and mention only what's essential for our exploration: the WebAssembly Component Model allows us to define interfaces — APIs — between Wasm modules and between Wasm modules and the host in which they're executed. It allows us to define types that can be shared between Wasm modules and their host.

To put it in practical terms: without the Wasm Component Model, if you want to interact with a Wasm module — say by running it in a Wasm host and passing data to it, or calling a function in it and taking data out — all data that crosses the Wasm module boundary has to be represented as integers or floats, basically. (And if you want a Wasm module to interact with more than your own tools, it's convention to use the [C ABI](https://github.com/WebAssembly/tool-conventions/blob/main/BasicCABI.md).)

Integers and floats are cool, don't get me wrong, but so are strings and structs. And the Wasm Component Model allows us to pass strings, structs, arrays — all that fancy stuff — to Wasm modules and get them back again. It allows us to pass something like `struct Animal { name: String, age: u8 }` or the `Worktree` from above to a Wasm module.

It requires that the types you want to exchange with a Wasm module are defined ahead of time, using an IDL (an Interface Definition Language) called [WIT, short for `Wasm Interface Type`](https://component-model.bytecodealliance.org/design/wit.html).

So, taking a step forward again, and looking at that code above, let's see what these 4 lines do:

    wit_bindgen::generate!({
        skip: ["init-extension"],
        path: "./wit/since_v0.2.0",
    });

The `generate!` macro comes from the [wit\_bindgen](https://github.com/bytecodealliance/wit-bindgen) crate. It takes in the files in the `./wit/since_v0.2.0` directory, which contain WIT definitions, and turns them into Wasm compatible types in Rust.

Here's an excerpt from the [`./wit/since_v0.2.0/extension.wit` file](https://github.com/zed-industries/zed/blob/6341ad2f7ac92c86b1fb3a5e0e01c1758b04cd92/crates/extension_api/wit/since_v0.2.0/extension.wit):

    package zed:extension;
     
    world extension {
        /// A command.
        record command {
            /// The command to execute.
            command: string,
            /// The arguments to pass to the command.
            args: list<string>,
            /// The environment variables to set for the command.
            env: env-vars,
        }
     
        /// A Zed worktree.
        resource worktree {
            /// Returns the ID of the worktree.
            id: func() -> u64;
            /// Returns the root path of the worktree.
            root-path: func() -> string;
            /// Returns the textual contents of the specified file in the worktree.
            read-text-file: func(path: string) -> result<string, string>;
            /// Returns the path to the given binary name, if one is present on the `$PATH`.
            which: func(binary-name: string) -> option<string>;
            /// Returns the current shell environment.
            shell-env: func() -> env-vars;
        }
     
        /// Returns the command used to start up the language server.
        export language-server-command: func(language-server-id: string, worktree: borrow<worktree>) -> result<command, string>;
     
        /// [... other definitions ...]
    }

A `command` record, a `worktree` resource, and a `language-server-command` function. `language-server-command` — sounds familiar, right? That's because the fictional extension I showed you above contained an implementation of this method that's part of the `zed::Extension` API:

    fn language_server_command(
        &mut self,
        language_server_id: &LanguageServerId,
        worktree: &Worktree,
    ) -> Result<Command> {
        // ...
    }

Now how does this fit together — the definitions in `*.wit` files and the Rust code?

To answer that, let's ignore the `&Worktree` and the `Result<Command>` types and focus on `&LanguageServerId`, which is easier to understand, because it is, as we saw above, only a [newtype](https://doc.rust-lang.org/rust-by-example/generics/new_types.html) around a `String`:

    pub struct LanguageServerId(String);

And in the code I just showed you, in `./wit/since_v0.2.0/extension.wit` file, the `language-server-id` is also just a `string`:

    export language-server-command: func(language-server-id: string, worktree: borrow<worktree>) -> result<command, string>;

That means we have a `String` on the Rust side (wrapped in another type that [gets added at runtime](https://github.com/zed-industries/zed/blob/5168fc27a17dca0f1dac52f4431376eabfd18782/crates/extension_api/src/extension_api.rs#L202-L203)) and a `string` in the WIT file.

But Wasm modules don't know about strings! They only know about numbers and pointers to numbers (which are, technically, also numbers — don't send me angry letters).

To bridge that gap, `wit_bindgen::generate!` turns WIT definitions into Rust type definitions that are valid Rust code on one side (so we can work with them when writing an extension), but Wasm-compatible, C-ABI-exporting code on the other side.

We can use [`cargo expand`](https://github.com/dtolnay/cargo-expand) to see how the `wit_bindgen::generate!` macro does that at compile time. Here's what `wit_bindgen` generates for the `language-server-command` function:

    #[export_name = "language-server-command"]
    unsafe extern "C" fn export_language_server_command(
        arg0: *mut u8,
        arg1: usize,
        arg2: i32,
    ) -> *mut u8 {
        self::_export_language_server_command_cabi::<Component>(arg0, arg1, arg2)
    }
     
    unsafe fn _export_language_server_command_cabi<T: Guest>(
        arg0: *mut u8,
        arg1: usize,
        arg2: i32,
    ) -> *mut u8 {
        let handle1;
        let len0 = arg1;
        let bytes0 = _rt::Vec::from_raw_parts(arg0.cast(), len0, len0);
        let result2 = T::language_server_command(
            _rt::string_lift(bytes0),
            {
                handle1 = Worktree::from_handle(arg2 as u32);
                &handle1
            },
        );
     
        // [... a lot more code that only deals with numbers ...]
    }

The best way to understand this is to read it from the inside out: right there, in the middle of `_export_language_server_command_cabi` you can see it calling `T::language_server_command` — that's the call into the Rust code of our extension!

But since the Wasm module has to expose a C ABI compatible function — that's the `extern "C" fn export_language_server_command` — it can't use `String` and `&Workspace`. C and Wasm modules don't know about those types.

The solution is to turn the types we have - `String` and `&Worktree` — into C ABI compatible types that Wasm modules can understand. The `String` gets turned into two arguments: `arg0: *mut u8`, pointing to the data of the string, and `arg1`, the length of the string. The `borrow<worktree>`, a reference to a `Worktree`, is a `i32` — a pointer.

In other words: `wit_bindgen::generate!` generates C ABI and Wasm module compatible wrapper code around our Rust code, based on the WIT definitions. That happens for all types and functions inside the WIT files, at compile time. And then, together with the code of the extension, it's all compiled down to Wasm.

At this point, let's pause and admit to ourselves that, yes, this is a bit of a mind-bender. Maybe more than a bit.

But, leaving aside different tools, macros, and ABIs, the short version is this:

*   Zed wants to execute Zed extensions that are Wasm modules and that implement the `zed::Extension` trait defined in Rust in the `extension_api` crate.
*   Zed extensions, written in Rust, can implement the `zed::Extension` trait.
*   To turn an extension that implements this trait into a Wasm module that adheres to the pre-defined interface, we use WIT and `wit_bindgen!` to generate Rust code that, when compiled down to Wasm together with the rest of the extension, exposes a Wasm module compatible API that calls into our once-written-in-Rust extension code.

Even shorter: extensions are written in Rust against a pre-defined interface and compiled into Wasm modules that can then be executed in Zed.

Now, how does that part work, the executing in Zed?

[Running Wasm in Zed](#running-wasm-in-zed)
-------------------------------------------

Here's the life of a Zed extension so far:

We've defined an extension API, we wrote an extension that implements this API, we compiled it into Wasm, we uploaded that Wasm module, we clicked on the "Install extension" button, we downloaded the archive that contains the Wasm code — what next?

First, the downloaded extension [archive is extracted](https://github.com/zed-industries/zed/blob/ea460014ab502bb56515745a733f56246efcc237/crates/extension/src/extension_store.rs#L682), the files it contained put into the right places, and the extension added to a

[... Content truncated. 15156 characters remaining ...]