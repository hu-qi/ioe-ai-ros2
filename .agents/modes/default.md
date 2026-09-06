# Default Mode

The default behavior profile for the app_mgr_object project.

## Prompt Composition

- Base prompt: project-level guidance
- Project prompt: `.agents/prompts/project.md`
- Snippets: none

## Enabled Skills

- `deploy-app-mgr` — Deploy app_mgr_object to a new Ubuntu host (Humble/Jazzy).

## Policy Binding

- `default` — Standard filesystem/exec access for a ROS2 Python project.

## Tool Intent

- allow: bash, file read/write within repo, SSH to deployment targets
- deny: force push, destructive git operations without confirmation
