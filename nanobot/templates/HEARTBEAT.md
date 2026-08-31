# Heartbeat Tasks

<!--
This file is checked periodically by the studio-agent heartbeat runner (when gateway.heartbeat.enabled is true).
Use this file for recurring background checks that should stay quiet unless there is actionable news to report.
Completed or one-time tasks should be removed.
-->

## Active Tasks

<!-- Add periodic background tasks below -->

<!-- Example: Poll Inbound Leads & Operational Sheets
- **Poll Inbound Leads & Operational Sheets:**
  - Run `run_skill_script(skill_name="poll-lead-sheets", script_name="poll_lead_sheets.py")`.
  - If the result indicates `has_new_entries: true`:
    - For each entry in `new_entries`, format a structured lead summary (Name, Contact, Interests, Availability, Notes).
    - Call `message(chat_id="<staff_group_chat_id>", channel="<channel_name>", content=...)` to notify staff.
  - If `has_new_entries: false` (or no actionable updates), do nothing.
-->

<!-- Example: Shift Handover & Daily Follow-up Check
- **Daily Front Desk Handover & Pending Follow-ups:**
  - Review `kb/front_desk_handover.md` for open action items due today.
  - If there are unresolved urgent items before shift change, notify staff channel.
-->
