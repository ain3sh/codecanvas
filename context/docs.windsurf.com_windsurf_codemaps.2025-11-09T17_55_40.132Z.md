[Skip to main content](https://docs.windsurf.com/windsurf/codemaps#content-area)

[Windsurf Docs home page![light logo](https://mintcdn.com/codeium/vRt4FQOyBeZpD2Pu/assets/windsurf-black-logo.svg?fit=max&auto=format&n=vRt4FQOyBeZpD2Pu&q=85&s=abb974bcee271bbefa761ce192454ff2)![dark logo](https://mintcdn.com/codeium/qJj_RRojefb93yIg/assets/windsurf-white-logo.svg?fit=max&auto=format&n=qJj_RRojefb93yIg&q=85&s=fc71ab128989a56e2dd2f8d1ad216b0c)](https://windsurf.com/)

![US](https://d3gk2c5xim1je2.cloudfront.net/flags/US.svg)

English

Search...

Ctrl K

- [Feature Request](https://codeium.canny.io/feature-requests/)
- [Download](https://windsurf.com/download)
- [Download](https://windsurf.com/download)

Search...

Navigation

Editor

Codemaps (Beta)

[Windsurf](https://docs.windsurf.com/windsurf/getting-started) [Windsurf Plugins](https://docs.windsurf.com/plugins/getting-started) [Windsurf Reviews](https://docs.windsurf.com/windsurf-reviews/windsurf-reviews)

- [Discord Community](https://discord.com/invite/3XFf78nAx5)
- [Windsurf Blog](https://windsurf.com/blog)
- [Support](https://windsurf.com/support)

##### Editor

- Getting Started

- [Models](https://docs.windsurf.com/windsurf/models)
- [Tab](https://docs.windsurf.com/tab/overview)
- [Command](https://docs.windsurf.com/command/windsurf-overview)
- [Code Lenses](https://docs.windsurf.com/command/windsurf-related-features)
- [Terminal](https://docs.windsurf.com/windsurf/terminal)
- [Browser Previews](https://docs.windsurf.com/windsurf/previews)
- [AI Commit Messages](https://docs.windsurf.com/windsurf/ai-commit-message)
- [DeepWiki](https://docs.windsurf.com/windsurf/deepwiki)
- [Codemaps (Beta)](https://docs.windsurf.com/windsurf/codemaps)
- [Vibe and Replace](https://docs.windsurf.com/windsurf/vibe-and-replace)
- [Advanced](https://docs.windsurf.com/windsurf/advanced)

##### Cascade

- [Overview](https://docs.windsurf.com/windsurf/cascade/cascade)
- [App Deploys](https://docs.windsurf.com/windsurf/cascade/app-deploys)
- [Web and Docs Search](https://docs.windsurf.com/windsurf/cascade/web-search)
- [Memories & Rules](https://docs.windsurf.com/windsurf/cascade/memories)
- [Workflows](https://docs.windsurf.com/windsurf/cascade/workflows)
- [Model Context Protocol (MCP)](https://docs.windsurf.com/windsurf/cascade/mcp)
- [Cascade Hooks (Beta)](https://docs.windsurf.com/windsurf/cascade/hooks)

##### Accounts

- [Usage](https://docs.windsurf.com/windsurf/accounts/usage)
- [Analytics](https://docs.windsurf.com/windsurf/accounts/analytics)
- Teams & Enterprise


##### Context Awareness

- [Overview](https://docs.windsurf.com/context-awareness/windsurf-overview)
- [Fast Context](https://docs.windsurf.com/context-awareness/fast-context)
- [Windsurf Ignore](https://docs.windsurf.com/context-awareness/windsurf-ignore)

##### Troubleshooting

- [Common Issues](https://docs.windsurf.com/troubleshooting/windsurf-common-issues)
- [Gathering Logs](https://docs.windsurf.com/troubleshooting/windsurf-gathering-logs)

##### Security

- [Reporting](https://docs.windsurf.com/security/reporting)

On this page

- [What are Codemaps?](https://docs.windsurf.com/windsurf/codemaps#what-are-codemaps%3F)
- [Accessing Codemaps](https://docs.windsurf.com/windsurf/codemaps#accessing-codemaps)
- [Creating a Codemap](https://docs.windsurf.com/windsurf/codemaps#creating-a-codemap)
- [Sharing Codemaps](https://docs.windsurf.com/windsurf/codemaps#sharing-codemaps)
- [Using Codemaps with Cascade](https://docs.windsurf.com/windsurf/codemaps#using-codemaps-with-cascade)

Editor

# Codemaps (Beta)

Hierarchical maps for codebase understanding.

Powered by a specialized agent, Codemaps are shareable artifacts that bridge the gap between human comprehension and AI reasoning, making it possible to navigate, discuss, and modify large codebases with precision and context.

Codemaps is currently in Beta and subject to change in future releases.

## [​](https://docs.windsurf.com/windsurf/codemaps\#what-are-codemaps%3F)  What are Codemaps?

While [DeepWiki](https://docs.windsurf.com/windsurf/deepwiki) provides symbol-level documentation, Codemaps help with codebase understanding by mapping how everything works together—showing the order in which code and files are executed and how different components relate to each other.To navigate a Codemap, click on any node to instantly jump to that file and function. Each node in the Codemap links directly to the corresponding location in your code.

## [​](https://docs.windsurf.com/windsurf/codemaps\#accessing-codemaps)  Accessing Codemaps

You can access Codemaps in one of two ways:

- **Activity Bar**: Find the Codemaps interface in the Activity Bar (left side panel)
- **Command Palette**: Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux) and search for “Focus on Codemaps View”

## [​](https://docs.windsurf.com/windsurf/codemaps\#creating-a-codemap)  Creating a Codemap

To create a new Codemap:

1. Open the Codemaps panel
2. Create a new Codemap by:
   - Selecting a suggested topic (suggestions are based on your recent navigation history)
   - Typing your own custom prompt
   - Generating from Cascade: Create new Codemaps from the bottom of a Cascade conversation
3. The Codemap agent explores your repository, identify relevant files and functions, and generate a hierarchical view

## [​](https://docs.windsurf.com/windsurf/codemaps\#sharing-codemaps)  Sharing Codemaps

You can share Codemaps with teammates as links that can be viewed in a browser.

For enterprise customers, sharing Codemaps requires opt-in because they need to be stored on our servers. By default, Codemaps are only available within your Team and require authentication to view.

## [​](https://docs.windsurf.com/windsurf/codemaps\#using-codemaps-with-cascade)  Using Codemaps with Cascade

You can include Codemap information as context in your [Cascade](https://docs.windsurf.com/windsurf/cascade) conversations by using `@-mention` to reference a Codemap.

[DeepWiki](https://docs.windsurf.com/windsurf/deepwiki) [Vibe and Replace](https://docs.windsurf.com/windsurf/vibe-and-replace)

Ctrl+I

[twitter](https://x.com/windsurf) [discord](https://discord.com/invite/3XFf78nAx5)

[Powered by Mintlify](https://www.mintlify.com/?utm_campaign=poweredBy&utm_medium=referral&utm_source=codeium)

Assistant

Responses are generated using AI and may contain mistakes.