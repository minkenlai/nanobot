import json
import time
import uuid
from pathlib import Path


def run_catchup():
    # Use relative path for portability
    jobs_file = Path("cron/jobs.json")
    if not jobs_file.exists():
        print("No jobs.json found.")
        return

    try:
        data = json.loads(jobs_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading jobs.json: {e}")
        return

    now_ms = int(time.time() * 1000)
    grace_period_ms = 7 * 24 * 60 * 60 * 1000  # 7 days

    missed_jobs = []

    for job in data.get("jobs", []):
        if not job.get("enabled", True):
            continue

        schedule = job.get("schedule", {})
        if schedule.get("kind") == "at":
            at_ms = schedule.get("atMs")
            if at_ms and at_ms <= now_ms:
                if (now_ms - at_ms) <= grace_period_ms:
                    missed_jobs.append(job)
                else:
                    # Past grace period, disable it
                    job["enabled"] = False
                    if "state" not in job:
                        job["state"] = {}
                    job["state"]["nextRunAtMs"] = None

    if not missed_jobs:
        print("No missed jobs found.")
        # Still save in case we disabled old jobs
        jobs_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    print(f"Found {len(missed_jobs)} missed jobs.")

    if len(missed_jobs) > 3:
        print("Avalanche control triggered. Creating summary job.")
        summary_message = f"⏰ [Missed Reminders Summary]\\nYou missed {len(missed_jobs)} reminders while offline:\\n"
        for job in missed_jobs:
            payload = job.get("payload", {})
            summary_message += f"- {job.get('name', 'Unnamed')}: {payload.get('message', '')}\\n"

            # Disable original jobs
            job["enabled"] = False
            if "state" not in job:
                job["state"] = {}
            job["state"]["nextRunAtMs"] = None

        # Create summary job
        summary_job = {
            "id": str(uuid.uuid4())[:8],
            "name": "Missed Reminders Summary",
            "enabled": True,
            "schedule": {"kind": "at", "atMs": now_ms},
            "payload": {"kind": "agent_turn", "message": summary_message, "deliver": True},
            "state": {"nextRunAtMs": now_ms, "runHistory": []},
            "createdAtMs": now_ms,
            "updatedAtMs": now_ms,
            "deleteAfterRun": True,
        }
        data["jobs"].append(summary_job)
    else:
        print("Rescheduling missed jobs for immediate execution.")
        for job in missed_jobs:
            payload = job.get("payload", {})
            msg = payload.get("message", "")
            if not msg.startswith("⏰ [Missed Reminder]"):
                payload["message"] = f"⏰ [Missed Reminder] {msg}"

            job["schedule"]["atMs"] = now_ms
            if "state" not in job:
                job["state"] = {}
            job["state"]["nextRunAtMs"] = now_ms

    # Save updated jobs
    jobs_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Successfully updated jobs.json with anacron catch-up.")


if __name__ == "__main__":
    run_catchup()
