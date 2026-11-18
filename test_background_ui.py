import threading
import time
import tkinter as tk
import unittest

from bookmark_app import BookmarkApp


class BackgroundUiBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as error:
            raise unittest.SkipTest(f'Tkinter display unavailable: {error}')

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.app = BookmarkApp(self.root)
        self.main_thread_id = threading.get_ident()

    def tearDown(self):
        for child in list(self.root.children.values()):
            child.destroy()

    def wait_for_events(self, events, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and len(events) < count:
            self.root.update()
            time.sleep(0.01)

    def test_result_and_progress_callbacks_run_on_main_thread(self):
        events = []
        worker_thread_ids = []

        def worker(report_progress):
            worker_thread_ids.append(threading.get_ident())
            report_progress('started')
            return 'done'

        self.app.run_background(
            worker,
            on_success=lambda result: events.append(
                ('success', result, threading.get_ident())
            ),
            on_progress=lambda progress: events.append(
                ('progress', progress, threading.get_ident())
            ),
        )

        self.wait_for_events(events, 2)

        self.assertNotEqual(worker_thread_ids[0], self.main_thread_id)
        self.assertEqual(
            [event[:2] for event in events],
            [('progress', 'started'), ('success', 'done')],
        )
        self.assertTrue(
            all(event[2] == self.main_thread_id for event in events)
        )
        self.assertEqual(self.app._active_background_tasks, 0)

    def test_worker_error_is_delivered_on_main_thread(self):
        events = []

        def worker(report_progress):
            self.assertTrue(callable(report_progress))
            raise RuntimeError('expected failure')

        def unexpected_success(result):
            self.fail(f'Unexpected successful result: {result}')

        self.app.run_background(
            worker,
            on_success=unexpected_success,
            on_error=lambda error: events.append(
                (str(error), threading.get_ident())
            ),
        )

        self.wait_for_events(events, 1)

        self.assertEqual(events, [('expected failure', self.main_thread_id)])
        self.assertEqual(self.app._active_background_tasks, 0)
        self.assertIsNone(self.app._ui_poll_id)


if __name__ == '__main__':
    unittest.main()
