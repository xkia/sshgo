import json
import multiprocessing
import os
import tempfile
import unittest
from contextlib import contextmanager

from config_store import ConfigStore, ConfigWriteConflictError, parse_jsonc


def _write_config_in_process(path, index, start_event, result_queue):
    try:
        start_event.wait(5)
        store = ConfigStore(path)
        store.write_json(
            {
                "config": {
                    "import_ssh_config": False,
                    "worker": str(index),
                },
                "hosts": [
                    {
                        "type": "host",
                        "name": f"worker-{index}",
                        "host": f"worker-{index}.example.com",
                        "user": "deploy",
                    }
                ],
            }
        )
        result_queue.put(("ok", index))
    except BaseException as e:
        result_queue.put(("error", index, repr(e)))


class ConfigStoreTests(unittest.TestCase):
    def test_parse_jsonc_supports_comments_and_trailing_commas(self):
        parsed = parse_jsonc(
            """
            {
              // line comment
              "config": {"import_ssh_config": false,},
              # shell-style comment
              "hosts": [
                {
                  "type": "host",
                  "name": "demo",
                  "host": "demo.example.com",
                  "user": "deploy",
                  "password": "pw",
                },
              ],
            }
            """
        )

        self.assertFalse(parsed["config"]["import_ssh_config"])
        self.assertEqual(parsed["hosts"][0]["name"], "demo")

    def test_store_read_and_write_json_uses_backup_rotation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            first = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "first",
                        "host": "first.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            second = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "second",
                        "host": "second.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }

            store.write_json(first)
            store.write_json(second)

            self.assertEqual(store.read()["hosts"][0]["name"], "second")
            with open(store.backup_path(0), "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["hosts"][0]["name"], "first")

    def test_store_restore_backup_uses_validator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            current = {"config": {"import_ssh_config": False}, "hosts": []}
            backup = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "backup",
                        "host": "backup.example.com",
                        "user": "deploy",
                        "password": "pw",
                    }
                ],
            }
            store.write_json(current)
            with open(store.backup_path(0), "w", encoding="utf-8") as f:
                json.dump(backup, f)

            called = []

            def validator(data):
                called.append(data["hosts"][0]["name"])
                return []

            result = store.restore_backup(0, validate_func=validator)

            self.assertEqual(result["target"], path)
            self.assertEqual(store.read()["hosts"][0]["name"], "backup")
            self.assertEqual(called, ["backup"])

    def test_store_write_rotate_and_restore_use_config_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            current = {"config": {"import_ssh_config": False}, "hosts": []}
            updated = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "updated",
                        "host": "updated.example.com",
                        "user": "deploy",
                    }
                ],
            }
            events = []
            real_locked_for = ConfigStore._locked_for

            @classmethod
            @contextmanager
            def fake_locked_for(cls, config_path):
                events.append(("lock", config_path))
                try:
                    yield
                finally:
                    events.append(("unlock", config_path))

            ConfigStore._locked_for = fake_locked_for
            try:
                store.write_json(current)
                store.write_json(updated)
                store.rotate_backups()
                store.restore_backup(0)
            finally:
                ConfigStore._locked_for = real_locked_for

            lock_events = [event for event, _ in events if event == "lock"]
            unlock_events = [event for event, _ in events if event == "unlock"]
            self.assertEqual(len(lock_events), 4)
            self.assertEqual(len(unlock_events), 4)
            self.assertTrue(all(config_path == path for _, config_path in events))

    def test_store_concurrent_writes_keep_config_and_backups_parseable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            store.write_json({"config": {"import_ssh_config": False}, "hosts": []})

            context = multiprocessing.get_context("spawn")
            start_event = context.Event()
            result_queue = context.Queue()
            processes = [
                context.Process(
                    target=_write_config_in_process,
                    args=(path, index, start_event, result_queue),
                )
                for index in range(4)
            ]
            for process in processes:
                process.start()
            start_event.set()
            for process in processes:
                process.join(10)

            results = [result_queue.get(timeout=5) for _ in processes]
            self.assertTrue(
                all(result[0] == "ok" for result in results),
                results,
            )
            self.assertTrue(
                all(process.exitcode == 0 for process in processes),
                [process.exitcode for process in processes],
            )

            active = store.read()
            self.assertIn(active["hosts"][0]["name"], {f"worker-{i}" for i in range(4)})

            backups = store.list_backups()
            self.assertTrue(backups)
            for backup in backups:
                with open(backup["path"], "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                self.assertIn("hosts", parsed)

    def test_store_checked_write_rejects_stale_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hosts.json")
            store = ConfigStore(path)
            initial = {"config": {"import_ssh_config": False}, "hosts": []}
            newer = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "newer",
                        "host": "newer.example.com",
                        "user": "deploy",
                    }
                ],
            }
            stale = {
                "config": {"import_ssh_config": False},
                "hosts": [
                    {
                        "type": "host",
                        "name": "stale",
                        "host": "stale.example.com",
                        "user": "deploy",
                    }
                ],
            }

            store.write_json(initial)
            _, fingerprint = store.read_with_fingerprint()
            store.write_json(newer)

            with self.assertRaises(ConfigWriteConflictError):
                store.write_json(
                    stale,
                    expected_fingerprint=fingerprint,
                    check_conflict=True,
                )

            self.assertEqual(store.read()["hosts"][0]["name"], "newer")


if __name__ == "__main__":
    unittest.main()
