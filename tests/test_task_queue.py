import unittest

from core.task_queue import move, remove, update, label, QueueEditError


def jobs():
    return [
        {'request': 'primo lavoro', 'mode': 'Chat', 'model': 'm1', 'project': None, 'attachments': [], 'history': []},
        {'request': 'secondo lavoro', 'mode': 'Agente', 'model': 'm2', 'project': r'C:\Progetti\Demo', 'attachments': [], 'history': []},
        {'request': 'terzo lavoro', 'mode': 'Studio', 'model': 'm3', 'project': '/tmp/Studio', 'attachments': [], 'history': []},
    ]


class TaskQueueTests(unittest.TestCase):
    def test_move_up_and_down(self):
        items = jobs()
        self.assertEqual(move(items, 1, -1), 0)
        self.assertEqual([j['request'] for j in items], ['secondo lavoro', 'primo lavoro', 'terzo lavoro'])
        self.assertEqual(move(items, 0, 1), 1)
        self.assertEqual([j['request'] for j in items], ['primo lavoro', 'secondo lavoro', 'terzo lavoro'])

    def test_move_at_boundary_does_nothing(self):
        items = jobs()
        self.assertEqual(move(items, 0, -1), 0)
        self.assertEqual(move(items, 2, 1), 2)
        self.assertEqual(items, jobs())

    def test_remove_returns_exact_job(self):
        items = jobs()
        removed = remove(items, 1)
        self.assertEqual(removed['request'], 'secondo lavoro')
        self.assertEqual(len(items), 2)

    def test_update_preserves_project_and_attachments(self):
        items = jobs()
        items[1]['attachments'] = ['a.py']
        changed = update(items, 1, '  richiesta nuova  ', 'Studio', ' qwen:7b ')
        self.assertEqual(changed['request'], 'richiesta nuova')
        self.assertEqual(changed['mode'], 'Studio')
        self.assertEqual(changed['model'], 'qwen:7b')
        self.assertEqual(changed['project'], r'C:\Progetti\Demo')
        self.assertEqual(changed['attachments'], ['a.py'])
        self.assertEqual(changed['history'], [])

    def test_update_can_change_response_style(self):
        items = jobs()
        changed = update(items, 0, 'richiesta', 'Chat', 'm1', 'Dettagliata')
        self.assertEqual(changed['response_style'], 'Dettagliata')

    def test_invalid_edit_does_not_change_job(self):
        for request, mode, model, style in [('', 'Chat', 'm', 'Breve'),
                                             ('ok', 'Altro', 'm', 'Breve'),
                                             ('ok', 'Chat', '', 'Breve'),
                                             ('ok', 'Chat', 'm', 'Infinita')]:
            items = jobs()
            original = dict(items[0])
            with self.assertRaises(QueueEditError):
                update(items, 0, request, mode, model, style)
            self.assertEqual(items[0], original)

    def test_invalid_indices_are_rejected(self):
        for action in (lambda x: move(x, 8, 1), lambda x: remove(x, -1),
                       lambda x: update(x, 4, 'ok', 'Chat', 'm')):
            with self.assertRaises(QueueEditError):
                action(jobs())

    def test_label_is_short_and_identifies_context(self):
        text = label(jobs()[1], width=10)
        self.assertIn('Agente', text)
        self.assertIn('Breve', text)
        self.assertIn('Demo', text)
        self.assertIn('…', text)


if __name__ == '__main__':
    unittest.main()
