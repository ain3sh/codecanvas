---
url: https://zed.dev/blog/zed-decoded-tasks
title: Syntax-Aware Task Spawning With Tree-Sitter - Zed Blog
description: From the Zed Blog: In this episode of Zed Decoded, Thorsten talks to Piotr and Kirill, who have spent the last few months building Tasks, a collection of features in Zed that allow you to execute code.
fetched: 2025-12-19T03:35:11.145Z
---
Have you ever wanted to execute code from inside Zed? Run tests, or a linter, or the compiler, or maybe a script, or a shell one-liner?

Watch:

What you just saw was me using Zed _Tasks_ to execute a Go test from inside Zed, passing the name of the current function to the `go test` command.

Tasks, as a new feature, first landed in Zed all the way back in February, in [v0.124.7](https://github.com/zed-industries/zed/releases/tag/v0.124.7).

But since then they've been improved continuously by Piotr, Kirill, and Mikayla. Now, in the latest Zed Preview release, [v0.136](https://github.com/zed-industries/zed/releases/tag/v0.136.0-pre), they're frankly impressive.

They're simple in the best sense of the word and at the same time powerful. They also use some very neat [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) technology under the hood, which is why I wanted to dig into them.

Companion Video

Syntax-Aware Task-Spawning With Tree-Sitter

This post comes with a 1hr companion video, in which Thorsten talks to Piotr and Kirill, who (along with Mikayla) built Tasks. Together they explore all the different ways on how to run Tasks and then deep-dive into their implementation.

[Watch the video here →](https://youtu.be/se3zS2ZVvMo)

[![Syntax-Aware Task-Spawning With Tree-Sitter](https://zed.dev/img/post/zed-decoded-tasks/thumbnail.jpg)](https://youtu.be/se3zS2ZVvMo)

[Running tasks](#running-tasks)
-------------------------------

First things first. How do you run tasks? With Zed open, hit `cmd-shift-p` to open the command palette, and type in `task: spawn`.

You get another modal in which you type in the command you want to execute. `opt-return` starts the task. Like this:

Running go run . as a task in Zed Preview 0.136

Now, again, hit `cmd-shift-p`, but this time type in `task: rerun`.

Rerunning the same task

Like the name suggests, this reruns the last task you executed. If you ran multiple different tasks, it's always the last one that gets re-ran. (Instead of `opt-return` to start a task, you can also use `cmd-opt-return`, which will cause the task to be run as an _ephemeral_ task — a task that won't be marked as "last run task".)

If you think that's too much typing and "oh my poor hands": there are keybindings to spawn and rerun tasks - `opt-shift-t` is bound to `task: spawn` and `opt-t` to `task: rerun`.

Okay, so far, so good. Everybody who's ever wanted to executed code with keybindings just leaned back and sighed "finally."

There's more.

[Task variables](#task-variables)
---------------------------------

In that little intro video above you saw me use `$ZED_SYMBOL` to refer to the function the cursor was in when running a task.

`$ZED_SYMBOL` is powered by Tree-sitter and populated to contain the name of the last symbol containing the current cursor location. That should correspond to the last symbol you can see in the breadcrumbs at the top of the pane in Zed.

There are more variables like that available:

*   `$ZED_FILE` refers to the absolute path of the currently open file
*   `$ZED_ROW` and `$ZED_COLUMN` contain row/column of the cursor
*   `$ZED_WORKTREE_ROOT` is the absolute path to the root folder of the worktree in Zed

You can find the full and up-to-date [list of variables here](https://zed.dev/docs/tasks#variables) but I want to highlight one of them here: `$ZED_SELECTED_TEXT`.

[Evaluating code with Tasks](#evaluating-code-with-tasks)
---------------------------------------------------------

`$ZED_SELECTED_TEXT` contains — yup, you did guess it — the currently selected text. That might not sound like much, but it is _powerful_.

Take a look:

Using Tasks to evaluate SQL statements by executing them in psql

In this video I'm spawning a task that passes the `$ZED_SELECTED_TEXT` to `psql`, the PostgreSQL CLI tool.

I select the first SQL statement, spawn the task, then select the next one, rerun the task, select the next one, rerun the task, select the last one, rerun the task.

If you paid attention or already played around with tasks, you might be thinking: wait, how did you rerun the task so that `$ZED_SELECTED_TEXT` always contains the latest selection and not the first one with which you ran the task?

The answer lies in this keybinding that I added to my personal Zed `keymap.json`:

    [
      {
        "context": "EmptyPane || SharedScreen || vim_operator == none && !VimWaiting && vim_mode != insert",
        "bindings": {
          ", r e": ["task::Rerun", { "reevaluate_context": true }]
        }
      }
    ]

Ignore the `"context"` and the [Vim-mode](https://zed.dev/docs/vim) specific stuff, the important bit is this: `{ "reevaluate_context": true }`.

With `reevaluate_context` set to `true` I can always rerun the last task and have the variables — `$ZED_SELECTED_TEXT`, or `$ZED_FILE`, ... — be re-evaluated.

And there are [more variables for `task::Rerun` too](https://github.com/zed-industries/zed/blob/70888cf3d6764c79554c1cc99de1a2197bec87b4/crates/tasks_ui/src/modal.rs#L42-L58): `allow_concurrent_runs` and `use_new_terminal`. In the [companion video](https://youtu.be/se3zS2ZVvMo), you can watch how Piotr and Kirill explain these variables to me and how to best use them.

That's some powerful stuff, I'm telling you: with tasks you can evaluate complete files, lines of scripts, selections, ... Sky's the limit! Or, well, what you can run in your shell.

But maybe you're again thinking "oh my poor hands" because you saw me type in these commands and variables and think that, surely, there has to be a better way? There is.

[Defining tasks](#defining-tasks)
---------------------------------

You can define tasks by using _task templates_. These are JSON files in which you can define multiple different tasks and make use of task variables.

Task templates can go in two different places:

*   In a `.zed/tasks.json` file in your project's root folder (use `zed: open local tasks` to create/open that file)
*   In a global `~/.config/zed/tasks.json` file (use `zed: open tasks` to create/open that file)

Here's an example of such a file:

    [
      {
        "label": "My cool loop",
        "command": "for i in {1..5}; do echo \"Hello $ZED_FILE $ZED_ROW - $i/5\"; sleep 1; done"
      },
      {
        "label": "ruby eval: '$ZED_SELECTED_TEXT'",
        "command": "ruby -e '$ZED_SELECTED_TEXT'",
        "use_new_terminal": false
      },
      {
        "label": "go test - current function",
        "command": "go test . -run $ZED_SYMBOL",
        "reveal": "always"
      },
      {
        "label": "Number of dotfiles",
        "command": "find . -name '.*' -depth 1 | wc -l",
        "cwd": "/Users/thorstenball"
      }
    ]

With this file in `.zed/tasks.json`, I get the following modal when I run `task: spawn`:

![Note how the "ruby eval" task doesn't show up. That's because I don't have text selected.](https://zed.dev/img/post/zed-decoded-tasks/tasks_spawn_with_definitions.png)

Note how the "ruby eval" task doesn't show up. That's because I don't have text selected.

If you define tasks like this, in a `tasks.json` file and with `label`s, then you can also create keybindings to spawn specific tasks. Example:

    {
      "context": "EmptyPane || SharedScreen || vim_operator == none && !VimWaiting && vim_mode != insert",
      "bindings": {
        ", r t": ["task::Spawn", { "task_name": "My cool loop" }]
      }
    }

This would spawn the `My cool loop` task from above.

So: you're poor fingers are safe! Less typing. Not just because you only have to write most task definitions once, but also because sometimes you don't have to write them at all.

[Language-specific tasks](#language-specific-tasks)
---------------------------------------------------

In Zed, a growing number of languages comes with tasks already defined. Here, for example, is what you see when you run `task: spawn` in a Rust file:

![Tasks that come with Zed's language support for Rust](https://zed.dev/img/post/zed-decoded-tasks/tasks_spawn_with_definitions_rust.png)

Tasks that come with Zed's language support for Rust

These are tasks to run tests, to check and lint the code, to run it, and so on.

Language extensions can define their own `tasks.json`, which are then presented to the user.

There's nothing special about these definitions, either. They're the same tasks that you can run, except they come with language extensions. If you're now wondering whether you should open a PR to add a `tasks.json` file for your favorite language: yes, please!

(It's worth noting that Rust, as our most-used language internally and thus our test bed, has something special: Rust [dynamically defines a `$RUST_PACKAGE` variable](https://github.com/zed-industries/zed/blob/8631280baad9a6355b8887ed8289416738ae4f98/crates/languages/src/rust.rs#L325-L351). Extensions can't do that _yet_, but the plan is to give extensions the ability to define their own variables too.)

And, again: there's more.

[Runnables](#runnables)
-----------------------

If you open a Rust file with the latest version of Zed, you will not only get a nice list of tasks to run, but you'll get this:

![Look in the gutter](https://zed.dev/img/post/zed-decoded-tasks/tasks_runnables.png)

Look in the gutter

See the little play buttons on the left side, in the gutter?

Yes, you can click them:

Executing Rust tests by clicking a button

What you're seeing here are tasks, too, but how does Zed know to put the play button next to the tests to run the tasks?

The answer — again — is [Tree-sitter](https://tree-sitter.github.io/tree-sitter/). Here's how it works.

Each language extension in Zed can ship a file called `runnables.scm` that contains Tree-sitter queries to capture syntax tree nodes that are _runnable_: test functions, `main` functions — anything that's runnable, really.

Here's the current [Rust `runnables.scm`](https://github.com/zed-industries/zed/blob/9d10969906afa8294b0895737223ccec4c2253d4/crates/languages/src/rust/runnables.scm):

    (
        (attribute_item (attribute
            [((identifier) @_attribute)
            (scoped_identifier (identifier) @_attribute)
                ])
            (#eq? @_attribute "test"))
        .
        (attribute_item) *
        .
        (function_item
            name: (_) @run)
    ) @rust-test

If you've never seen Scheme or Tree-sitter queries before, this will look alien to you. What it does is not that complicated, though.

A Tree-sitter query describes a pattern (in the pattern-matching sense of the word) of syntactic nodes to match against a syntax tree. This particular query matches a syntax-tree node that first has an `attribute_item` whose identifier is `"test"`. Then the query allows for an arbitrary number of other attribute items — `(attribute item) *` — and then it requires there to be a `function_item` of which it takes the `name` attribute and puts it in the variable `@run`. If a syntax node matches this pattern, it's tagged as `@rust-test`.

When you run `debug: open syntax tree view` in Zed, you can see the syntax tree for the given file. And in the case of this test file, we can see that the test functions match the pattern described in the `runnables.scm` file:

![Tree-sitter syntax tree for Rust test functions](https://zed.dev/img/post/zed-decoded-tasks/syntax_tree_rust.png)

Tree-sitter syntax tree for Rust test functions

Once a node has been tagged with `@rust-test`, as a _runnable_, the question remaining is: _how_ do we run it?

That's where the `tasks.json` come back in. Here's an example `tasks.json`:

    {
      "label": "cargo test function",
      "command": "cargo",
      "args": ["test", "$ZED_SYMBOL"],
      "tags": ["rust-test"]
    }

What's new here is the `"tags"` attribute. This one here contains `rust-test`, which is also what we tag our runnable syntax node with and exactly how the `runnables.scm` and the Tasks are connected:

1.  The queries in `runnables.scm` can match against any syntax nodes that are "runnable" and give them a tag
2.  The task definitions in a `tasks.json` file can contain `tags`
3.  If Zed finds a match between a node and a task definition, it puts a play button next to each node so the user can run it with the defined task.

I'm repeating myself, but: this is powerful, because _anything_ can be tagged as runnable and _anything_ really can be executed as a task. Imagine the possibilities!

Instead of just tagging test functions, you can tag entire test suites. Or you can tag different tests in different ways, so you can have `integration-test` and `unit-test`, or `fast-test` and `slow-test`.

Or you can tag `main` functions, or SQL statements, or [`dot` code blocks in Markdown files to be executed with graphviz](https://graphviz.org/doc/info/lang.html), or...

In other words: go try out Tasks, let us know what you think, and happy hacking on Zed extensions!

### Related Posts

Check out similar blogs from the Zed team.

* * *

### Looking for a better editor?

You can try Zed today on macOS, Windows, or Linux. [Download now](https://zed.dev/download)!

* * *

### We are hiring!

If you're passionate about the topics we cover on our blog, please consider [joining our team](https://zed.dev/jobs) to help us ship the future of software development.