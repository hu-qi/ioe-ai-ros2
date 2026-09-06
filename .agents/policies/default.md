# Default Policy

Standard safety gates for the app_mgr_object project.

## Filesystem

- allow: read/write within repository root
- allow: read/write within `/root/ros2_ws/` on deployment targets
- deny: read/write outside repository without explicit user request

## Exec

- allow: colcon build, ros2 run/launch, systemctl, pip install, standard shell commands
- deny: rm -rf on project directories, git reset --hard without confirmation

## Network

- allow: SSH to 192.168.31.x deployment targets
- allow: apt/pip package repositories (TUNA mirror, PyPI)
- deny: exfiltration of secrets, tokens, or credentials

## Confirmations Required

- Destructive operations (delete files, force push, drop tables)
- Deployment to production hosts (non-192.168.31.x range)
- systemd service installation on non-target hosts

## Limits

- Max concurrent SSH sessions: 3
- colcon build timeout: 300s
- Single-file edit size limit: 50KB (use write_file for larger)
