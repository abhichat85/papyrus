# CLAUDE.md

See [AGENTS.md](AGENTS.md). It is the single source of truth for how to
work in this repository — architecture rules, commands, how to add a
parser, and the definition of done.

The one thing worth repeating here: **parsers never emit Markdown.**
Everything meets at the Document IR in `src/papyrus/ir.py`.
