# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)

## Security Notes

- **高风险操作前必须获得用户审批确认**：
  - 删除文件（特别是策略代码、数据文件）
  - 修改系统配置（crontab、systemd、nginx、shell rc 等）
  - 修改策略代码（添加/删除标的如港股等）
  - 执行批量操作（批量删除、批量修改）
  - 发送邮件、推文或任何公开内容
- 修改系统配置前先检查现有状态，保留/合并配置
- 优先使用 `trash` 而非 `rm`
