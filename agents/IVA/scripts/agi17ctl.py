"""AGI 1.7 Live Control CLI (`agi17ctl`).

Allows an operator or parent process to inspect live task status, submit
mid-run instructions to the SQLite `CommandInbox`, or trigger orphan
reconciliation while an AGI 1.7 mission is running.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.AGI_1_7.engine.agi17.task_control.task_manager import DurableTaskManager


def main() -> int:
    parser = argparse.ArgumentParser(description="AGI 1.7 Live Command & Task Control CLI")
    parser.add_argument(
        "--db-path",
        default=r"D:\AGI_Storage\AGI_1_7\state\agi17_tasks.db",
        help="Path to SQLite WAL TaskStore DB",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # status
    p_status = sub.add_parser("status", help="Show live task counts and active tasks")
    p_status.add_argument("--task-id", default=None, help="Specific task_id to inspect")

    # send
    p_send = sub.add_parser("send", help="Submit a live instruction to CommandInbox")
    p_send.add_argument("--type", required=True, help="Instruction type (e.g., ADD_CHILD_TASK, PAUSE_CURRENT_AND_SWITCH, CANCEL_AND_REPLACE)")
    p_send.add_argument("--target-task-id", default=None, help="Target task ID")
    p_send.add_argument("--payload-json", default="{}", help="JSON payload string")

    # reconcile
    sub.add_parser("reconcile", help="Reconcile orphaned RUNNING tasks after restart")

    args = parser.parse_args()
    mgr = DurableTaskManager(db_path=args.db_path)

    if args.subcommand == "status":
        if args.task_id:
            rec = mgr.store.get_task(args.task_id)
            print(json.dumps(rec or {"error": "Task not found"}, indent=2))
        else:
            counts = mgr.store.count_by_state()
            tasks = mgr.store.list_tasks()
            print(
                json.dumps(
                    {
                        "total_tasks": len(tasks),
                        "counts_by_state": counts,
                        "recent_tasks": [
                            {
                                "task_id": t["task_id"],
                                "parent_task_id": t["parent_task_id"],
                                "title": t["title"],
                                "state": t["state"],
                                "specialist_role": t["specialist_role"],
                            }
                            for t in tasks[-15:]
                        ],
                    },
                    indent=2,
                )
            )
        return 0

    if args.subcommand == "send":
        payload = json.loads(args.payload_json)
        cmd_id = mgr.inbox.submit(
            instruction_type=args.type,
            target_task_id=args.target_task_id,
            payload=payload,
        )
        print(
            json.dumps(
                {
                    "status": "QUEUED_IN_COMMAND_INBOX",
                    "command_id": cmd_id,
                    "instruction_type": args.type,
                    "target_task_id": args.target_task_id,
                    "payload": payload,
                },
                indent=2,
            )
        )
        return 0

    if args.subcommand == "reconcile":
        actions = mgr.reconcile_after_restart()
        print(json.dumps({"reconciled_count": len(actions), "actions": actions}, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
