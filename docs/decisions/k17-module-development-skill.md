# K17. A local skill for module setup and feature work

Purpose: make the workflow for building a new Eneo module available inside its own repository.
Read this when: maintaining the template's agent guidance.
Related: [K12](k12-agent-setup.md), [new module](../guides/new-module.md), [the skill](../../template/.agents/skills/eneo-module/SKILL.md).

Status: Accepted, 2026-10-07. Supersedes K12's restriction on a custom skill.

The template carries one `.agents/skills/eneo-module/SKILL.md`. `AGENTS.md` links it for setup and feature work;
`CLAUDE.md` imports the same file. The skill guides agents to the existing examples, Eneo contract, package
instructions and relevant checks. It adds no runtime dependency or custom MCP server.

Technical facts remain in the existing rules and guides. Copied modules can keep or adapt this workflow without
depending on the kit's temporary build instructions or on speech-to-text. Backend guide links point to the kit
repository because those guides are not copied into every module.
