"""Giorgio: chat desktop, allegati reali e agente interrompibile."""
from pathlib import Path
import difflib
import json
import multiprocessing as mp
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from tkinter.scrolledtext import ScrolledText

from core.app_worker import work_request
from core.attachments import SUPPORTED
from core.backup import BackupManager
from core.executor import apply_approved, fingerprint
from core.security import safe_project_path
from core.session import SessionStore, SessionError
from core.ollama_client import OllamaClient
from core.ollama_status import inspect_ollama
from core.chat_format import split_fenced
from core.task_queue import move as move_task, remove as remove_task, update as update_task, label as task_label, QueueEditError

BASE = Path(__file__).resolve().parent
SETTINGS = Path(os.environ.get('APPDATA', str(Path.home() / '.config'))) / 'GiorgioCodex' / 'settings.json'


def make_root():
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk()
    except (ImportError, tk.TclError):
        return tk.Tk()


class GiorgioApp:
    def __init__(self, root):
        self.root = root
        root.title('Giorgio Codex')
        root.geometry('1280x820')
        root.minsize(980, 650)
        root.configure(bg='#0b0a14')
        self.process = self.events = self.pending = None
        self.attachments, self.projects, self.history, self.logs = [], [], [], []
        self.reply, self.reply_started = '', False
        self.reply_content_start = None
        self.code_buttons = []
        self.transcript_text = ''
        self.model = 'qwen2.5-coder:7b'
        self.response_length = 'Breve'
        self.last_backup = None
        self.restorable_states = {}
        self.task_queue = []
        self.active_job = None
        self.session_ready = False
        self.session_enabled = True
        self.save_timer = None
        self.poll_timer = None
        self.closing = False
        self.ollama_events = queue.Queue()
        self.ollama_check_running = False
        self.ollama_check_id = 0
        self.ollama_timer = None
        self.available_models = []
        self.queue_window = None
        self.queue_list = None
        self.queue_editor = None
        self.queue_mode = None
        self.queue_model = None
        self.queue_response_style = None
        self.session_store = SessionStore(SETTINGS.with_name('session.json'))
        self._load_settings()
        self.mode = tk.StringVar(value='Agente')
        self.response_style = tk.StringVar(value=self.response_length)
        self.state = tk.StringVar(value='Pronto · Ollama non ancora verificato')
        self.project_path = tk.StringVar(value='Nessun progetto selezionato')
        self.model_label = tk.StringVar(value='Ollama · controllo in corso…')
        fonts = set(tkfont.families(root))
        self.ui_font = 'Segoe UI' if 'Segoe UI' in fonts else 'DejaVu Sans'
        self.code_font = 'Consolas' if 'Consolas' in fonts else 'DejaVu Sans Mono'
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#0b0a14')
        style.configure('TLabel', background='#0b0a14', foreground='#f5f3ff', font=(self.ui_font, 10))
        style.configure('TButton', background='#191827', foreground='#f5f3ff', bordercolor='#39334d', padding=(12, 10), font=(self.ui_font, 10))
        style.map('TButton', background=[('active', '#343047')], foreground=[('disabled', '#777187')])
        style.configure('Primary.TButton', background='#8b5cf6', foreground='white')
        style.map('Primary.TButton', background=[('active', '#6d42d8'), ('disabled', '#403050')])
        style.configure('Project.TButton', background='#f59e0b', foreground='#160f03', font=(self.ui_font, 11, 'bold'))
        style.map('Project.TButton', background=[('active', '#d97706')])
        style.configure('TCombobox', fieldbackground='#191827', foreground='#f5f3ff', arrowcolor='#f5f3ff')
        top = tk.Frame(root, bg='#101426', height=46)
        top.pack(fill='x')
        tk.Label(top, text=' G  Giorgio Codex', bg='#101426', fg='#f5f3ff', font=(self.ui_font, 13, 'bold')).pack(side='left', padx=16, pady=10)
        ttk.Button(top, text='Impostazioni', command=self.settings).pack(side='right', padx=14)
        ttk.Button(top, text='Esporta chat', command=self.export_chat).pack(side='right')
        body = ttk.Frame(root, padding=18)
        body.pack(fill='both', expand=True)
        sidebar = ttk.Frame(body, width=280, padding=(0, 0, 20, 0))
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text='GIORGIO CODEX', font=(self.ui_font, 20, 'bold')).pack(anchor='w', pady=(12, 0))
        ttk.Label(sidebar, text='IL TUO AGENTE LOCALE', foreground='#a78bfa').pack(anchor='w', pady=(0, 24))
        self.add_project_button = ttk.Button(sidebar, text='Scegli progetto', style='Project.TButton', command=self.add_project)
        self.add_project_button.pack(fill='x')
        self.new_chat_button = ttk.Button(sidebar, text='+ Nuova conversazione', command=self.new_chat)
        self.new_chat_button.pack(fill='x', pady=10)
        ttk.Label(sidebar, text='PROGETTO ATTIVO', foreground='#a5a0c0').pack(anchor='w', pady=(14, 6))
        ttk.Label(sidebar, textvariable=self.project_path, wraplength=240).pack(anchor='w')
        self.project_list = tk.Listbox(sidebar, height=4, font=(self.ui_font, 11), bg='#191827', fg='#f5f3ff', bd=0, highlightthickness=0, selectbackground='#49356e', selectforeground='white', exportselection=False)
        self.project_list.pack(fill='x', pady=12)
        self.project_list.bind('<<ListboxSelect>>', self.select_project)
        ttk.Label(sidebar, text='FILE DEL PROGETTO', foreground='#a5a0c0').pack(anchor='w', pady=(8, 6))
        self.file_list = tk.Listbox(sidebar, height=9, font=(self.ui_font, 10), bg='#101426', fg='#ddd8eb', bd=0, highlightthickness=0, selectbackground='#49356e', exportselection=False)
        self.file_list.pack(fill='both', expand=True)
        self.file_list.bind('<Double-Button-1>', self.view_file)
        self.probe_button = ttk.Button(sidebar, text='Prova scrittura verificata', command=self.probe_write)
        self.probe_button.pack(fill='x', pady=(12, 6))
        self.restore_button = ttk.Button(sidebar, text='Ripristina correzione', command=self.restore, state='disabled')
        self.restore_button.pack(fill='x')
        panel = ttk.Frame(body)
        panel.pack(side='left', fill='both', expand=True)
        header = ttk.Frame(panel, padding=(0, 10, 0, 16))
        header.pack(fill='x')
        ttk.Label(header, text='Sessione con Giorgio', font=(self.ui_font, 25, 'bold')).pack(anchor='w')
        ttk.Label(header, text='Analizza, modifica e controlla il tuo codice in locale.', foreground='#a5a0c0').pack(anchor='w', pady=5)
        controls = ttk.Frame(header)
        controls.pack(fill='x', pady=(8, 0))
        self.mode_select = ttk.Combobox(controls, textvariable=self.mode, values=['Chat', 'Agente', 'Studio'], state='readonly', width=11)
        self.mode_select.pack(side='left')
        self.length_select = ttk.Combobox(controls, textvariable=self.response_style,
                                          values=['Breve', 'Normale', 'Dettagliata'],
                                          state='readonly', width=11)
        self.length_select.pack(side='left', padx=(8, 0))
        self.length_select.bind('<<ComboboxSelected>>', lambda _event: self.save_response_style())
        ttk.Label(controls, textvariable=self.model_label, foreground='#a5a0c0').pack(side='left', padx=16)
        self.ollama_button = ttk.Button(controls, text='Controlla Ollama', command=lambda: self.check_ollama(force=True))
        self.ollama_button.pack(side='right')
        self.status_label = tk.Label(controls, textvariable=self.state, bg='#0b0a14', fg='#f59e0b', font=(self.ui_font, 10), wraplength=420)
        self.status_label.pack(side='right', padx=10)
        footer = ttk.Frame(panel)
        footer.pack(side='bottom', fill='x')
        self.chat = ScrolledText(panel, wrap='word', font=(self.ui_font, 12), bg='#0f0e19', fg='#f5f3ff', insertbackground='white', relief='flat', padx=24, pady=22, state='disabled', highlightthickness=1, highlightbackground='#39334d')
        self.chat.pack(fill='both', expand=True)
        self.chat.tag_configure('author', font=(self.ui_font, 12, 'bold'), foreground='#a78bfa')
        self.chat.tag_configure('notice', foreground='#a5a0c0', font=(self.ui_font, 10))
        self.chat.tag_configure('code', foreground='#d8d2ed', background='#191827', font=(self.code_font, 10), lmargin1=18, lmargin2=18, rmargin=18, spacing1=5, spacing3=7)
        self.chat.tag_configure('code_language', foreground='#a78bfa', background='#191827', font=(self.ui_font, 9, 'bold'), lmargin1=18, lmargin2=18, rmargin=18, spacing1=8)
        self.proposal_bar = ttk.Frame(footer, padding=(0, 8))
        self.preview_button = ttk.Button(self.proposal_bar, text='Vedi modifiche', command=self.preview)
        self.preview_button.pack(side='left')
        self.apply_button = ttk.Button(self.proposal_bar, text='Applica modifiche', style='Primary.TButton', command=self.apply)
        self.apply_button.pack(side='left', padx=8)
        ttk.Button(self.proposal_bar, text='Rifiuta', command=self.reject).pack(side='left')
        self.chips = ttk.Frame(footer, padding=(0, 6))
        self.chips.pack(fill='x')
        composer = ttk.Frame(footer, padding=(0, 8))
        composer.pack(fill='x')
        self.input = tk.Text(composer, height=3, wrap='word', font=(self.ui_font, 12), bg='#191827', fg='#f5f3ff', insertbackground='white', relief='flat', padx=14, pady=10, highlightthickness=1, highlightbackground='#39334d')
        self.input.pack(side='left', fill='x', expand=True)
        self.input.bind('<Return>', self.on_return)
        self.attach_button = ttk.Button(composer, text='Allega', command=self.attachment_menu)
        self.attach_button.pack(side='left', padx=8)
        self.send_button = ttk.Button(composer, text='Invia ↑', style='Primary.TButton', command=self.send_or_stop)
        self.send_button.pack(side='left')
        queue_controls = ttk.Frame(footer)
        queue_controls.pack(anchor='e', pady=4)
        ttk.Button(queue_controls, text='Metti in coda', command=self.enqueue).pack(side='left', padx=(0, 6))
        self.queue_manage_button = ttk.Button(queue_controls, text='Gestisci coda (0)', command=self.open_queue)
        self.queue_manage_button.pack(side='left', padx=(0, 6))
        self.next_button = ttk.Button(queue_controls, text='Avvia prossimo', command=self.run_next)
        self.next_button.pack(side='left')
        ttk.Label(footer, text='Invio per inviare · Maiusc+Invio per andare a capo · Esc per interrompere', foreground='#a5a0c0').pack(anchor='w')
        ttk.Label(footer, text='REGISTRO ATTIVITÀ', foreground='#a5a0c0').pack(anchor='w', pady=(10, 4))
        self.activity = ScrolledText(footer, height=3, wrap='word', font=(self.code_font, 9), bg='#101426', fg='#b8b0ce', relief='flat', state='disabled')
        self.activity.pack(fill='x')
        self.refresh_projects()
        self.project_list.selection_set(0)
        self.say('Giorgio', 'Ciao Gabriele. Scrivimi una domanda, allega un file oppure scegli un progetto su cui lavorare.')
        try:
            self.chat.drop_target_register('DND_Files')
            self.chat.dnd_bind('<<Drop>>', self.drop)
        except (AttributeError, tk.TclError):
            pass
        root.bind('<Escape>', lambda event: self.stop())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_timer = root.after(80, self.poll)
        self.input.focus_set()
        self.restore_session()
        self.session_ready = True
        self.input.bind('<<Modified>>', self.draft_changed)
        self.mode.trace_add('write', lambda *_: self.schedule_save())
        self.refresh_queue_controls()
        self.schedule_save()
        self.check_ollama()

    def check_ollama(self, force=False):
        if self.closing or self.ollama_check_running:
            return
        if self.process is not None and not force:
            self.schedule_ollama_check(15000)
            return
        self.ollama_check_running = True
        self.ollama_check_id += 1
        check_id, selected = self.ollama_check_id, self.model
        self.state.set('Controllo Ollama…')
        self.status_label.configure(fg='#f59e0b')
        self.ollama_button.configure(state='disabled')
        def worker():
            result = inspect_ollama(selected, lambda: OllamaClient(
                model=selected, request_timeout=4, connection_timeout=4)._connection_client)
            self.ollama_events.put((check_id, result))
        threading.Thread(target=worker, daemon=True, name='giorgio-ollama-check').start()

    def schedule_ollama_check(self, milliseconds=60000):
        if self.closing:
            return
        if self.ollama_timer is not None:
            self.root.after_cancel(self.ollama_timer)
        self.ollama_timer = self.root.after(milliseconds, self.check_ollama)

    def poll_ollama(self):
        try:
            while True:
                check_id, result = self.ollama_events.get_nowait()
                if check_id != self.ollama_check_id:
                    continue
                self.ollama_check_running = False
                self.ollama_button.configure(state='normal')
                self.available_models = result['models']
                self.model_label.set('Ollama · ' + self.model)
                if self.process is None:
                    self.state.set(result['message'])
                self.status_label.configure(fg='#53d3aa' if result['connected'] and self.model in result['models'] else '#f59e0b' if result['connected'] else '#f87171')
                detail = result.get('detail')
                log = result['message'] + (f' · {detail}' if detail else '')
                if not self.logs or self.logs[-1] != log:
                    self.logs.append(log)
                    self.update_activity()
                self.schedule_ollama_check()
        except queue.Empty:
            pass

    def draft_changed(self, event=None):
        if self.input.edit_modified():
            self.input.edit_modified(False)
            self.schedule_save()

    def schedule_save(self):
        if self.closing or not self.session_ready or not self.session_enabled:
            return
        if self.save_timer is not None:
            return
        self.save_timer = self.root.after(750, self.save_session)

    def save_session(self):
        if self.save_timer is not None:
            self.root.after_cancel(self.save_timer)
        self.save_timer = None
        if not self.session_ready or not self.session_enabled:
            return
        snapshot = {
            'version': 1, 'mode': self.mode.get(), 'project': self.current_project(),
            'draft': self.input.get('1.0', 'end-1c'),
            'transcript': self.transcript_text[-250000:],
            'history': [{'role': m['role'], 'content': m['content'][-40000:]} for m in self.history[-40:]],
            'queue': list(self.task_queue), 'attachments': list(self.attachments),
            'logs': [str(line)[:2000] for line in self.logs[-80:]],
            'active_job': self.active_job,
        }
        try:
            self.session_store.save(snapshot)
        except (OSError, SessionError) as exc:
            warning = 'Sessione non salvata: ' + str(exc)
            if not self.logs or self.logs[-1] != warning:
                self.logs.append(warning)
                self.update_activity()

    def restore_session(self):
        try:
            saved = self.session_store.load()
        except (OSError, SessionError) as exc:
            self.logs.append(str(exc))
            self.say('', str(exc))
            self.update_activity()
            # Se non è stato possibile preservare il file, non sovrascriverlo.
            self.session_enabled = not self.session_store.path.exists()
            return
        if not saved:
            return
        self.history = saved['history']
        self.task_queue = saved['queue']
        self.logs = saved['logs']
        self.mode.set(saved['mode'])
        project = saved['project']
        project_available = bool(project and Path(project).is_dir())
        if project_available and project not in self.projects:
            self.projects.append(project)
            self.refresh_projects()
        index = self.projects.index(project) + 1 if project_available else 0
        self.project_list.selection_clear(0, 'end')
        self.project_list.selection_set(index)
        self.refresh_files()
        self.input.insert('1.0', saved['draft'])
        self.attachments = saved['attachments']
        self.render_chips()
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.code_buttons.clear()
        self.transcript_text = saved['transcript']
        self.render_chat_text(self.transcript_text)
        self.chat.configure(state='disabled')
        if project and not project_available:
            self.history.clear()
            self.say('', 'Il progetto precedente non è disponibile. Storico escluso dal contesto: scegli la cartella prima di riprendere.')
        interrupted = saved['active_job']
        if interrupted:
            self.task_queue.insert(0, interrupted)
            self.history.clear()
            self.say('', 'Un incarico era in corso alla chiusura: è stato rimesso in testa alla coda. Puoi riavviarlo manualmente.')
        self.refresh_queue_controls()
        self.say('', 'Sessione recuperata. Le proposte di modifica vanno richieste di nuovo; nessun incarico parte automaticamente.')
        self.update_activity()

    def refresh_queue_controls(self):
        count = len(self.task_queue)
        self.queue_manage_button.configure(text=f'Gestisci coda ({count})')
        self.next_button.configure(state='normal' if count and self.process is None else 'disabled')
        self.refresh_queue_window()

    def open_queue(self):
        if self.queue_window is not None and self.queue_window.winfo_exists():
            self.queue_window.deiconify()
            self.queue_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.queue_window = window
        window.title('Coda attività')
        window.geometry('820x560')
        window.minsize(680, 460)
        window.configure(bg='#0b0a14')
        window.protocol('WM_DELETE_WINDOW', self.close_queue_window)
        ttk.Label(window, text='Attività in attesa', font=(self.ui_font, 18, 'bold'), padding=12).pack(anchor='w')
        self.queue_list = tk.Listbox(window, height=10, font=(self.ui_font, 10), bg='#101426', fg='#f5f3ff', selectbackground='#49356e', selectforeground='white', exportselection=False, bd=0)
        self.queue_list.pack(fill='both', expand=True, padx=12)
        self.queue_list.bind('<<ListboxSelect>>', self.load_queue_selection)
        form = ttk.Frame(window, padding=12)
        form.pack(fill='x')
        self.queue_editor = tk.Text(form, height=5, wrap='word', font=(self.ui_font, 10), bg='#191827', fg='#f5f3ff', insertbackground='white', relief='flat')
        self.queue_editor.pack(fill='x')
        row = ttk.Frame(form)
        row.pack(fill='x', pady=(8, 0))
        self.queue_mode = tk.StringVar(value='Agente')
        ttk.Combobox(row, textvariable=self.queue_mode, values=['Chat', 'Agente', 'Studio'], state='readonly', width=10).pack(side='left')
        self.queue_model = tk.StringVar(value=self.model)
        ttk.Entry(row, textvariable=self.queue_model, width=28).pack(side='left', padx=8)
        self.queue_response_style = tk.StringVar(value='Breve')
        ttk.Combobox(row, textvariable=self.queue_response_style,
                     values=['Breve', 'Normale', 'Dettagliata'],
                     state='readonly', width=11).pack(side='left', padx=(0, 8))
        ttk.Button(row, text='Salva modifiche', command=self.save_queue_selection).pack(side='left')
        buttons = ttk.Frame(window, padding=(12, 0, 12, 12))
        buttons.pack(fill='x')
        ttk.Button(buttons, text='↑ Su', command=lambda: self.move_queue_selection(-1)).pack(side='left')
        ttk.Button(buttons, text='↓ Giù', command=lambda: self.move_queue_selection(1)).pack(side='left', padx=6)
        ttk.Button(buttons, text='Rimuovi', command=self.remove_queue_selection).pack(side='left')
        ttk.Button(buttons, text='Avvia selezionato', style='Primary.TButton', command=self.start_queue_selection).pack(side='right')
        self.refresh_queue_window(select=0)

    def close_queue_window(self):
        if self.queue_window is not None and self.queue_window.winfo_exists():
            self.queue_window.destroy()
        self.queue_window = self.queue_list = self.queue_editor = None
        self.queue_mode = self.queue_model = None
        self.queue_response_style = None

    def selected_queue_index(self):
        if self.queue_list is None:
            return None
        selected = self.queue_list.curselection()
        return selected[0] if selected else None

    def refresh_queue_window(self, select=None):
        if self.queue_list is None or not self.queue_list.winfo_exists():
            return
        previous = self.selected_queue_index() if select is None else select
        self.queue_list.delete(0, 'end')
        for job in self.task_queue:
            self.queue_list.insert('end', task_label(job))
        if self.task_queue and previous is not None:
            target = min(previous, len(self.task_queue) - 1)
            self.queue_list.selection_set(target)
            self.queue_list.see(target)
            self.load_queue_selection()
        elif self.queue_editor is not None:
            self.queue_editor.delete('1.0', 'end')

    def load_queue_selection(self, event=None):
        index = self.selected_queue_index()
        if index is None or index >= len(self.task_queue):
            return
        job = self.task_queue[index]
        self.queue_editor.delete('1.0', 'end')
        self.queue_editor.insert('1.0', job['request'])
        self.queue_mode.set(job['mode'])
        self.queue_model.set(job['model'])
        self.queue_response_style.set(job.get('response_style', 'Breve'))

    def queue_edit_allowed(self):
        if self.process is not None:
            messagebox.showinfo('Coda attività', 'Attendi la fine del lavoro in corso prima di modificare la coda.')
            return False
        return True

    def save_queue_selection(self):
        if not self.queue_edit_allowed():
            return
        index = self.selected_queue_index()
        if index is None:
            return
        try:
            update_task(self.task_queue, index, self.queue_editor.get('1.0', 'end-1c'),
                        self.queue_mode.get(), self.queue_model.get(),
                        self.queue_response_style.get())
        except QueueEditError as exc:
            messagebox.showerror('Coda attività', str(exc))
            return
        self.logs.append('Incarico in coda aggiornato.')
        self.refresh_queue_controls()
        self.refresh_queue_window(select=index)
        self.update_activity()
        self.schedule_save()

    def move_queue_selection(self, offset):
        if not self.queue_edit_allowed():
            return
        index = self.selected_queue_index()
        if index is None:
            return
        try:
            target = move_task(self.task_queue, index, offset)
        except QueueEditError as exc:
            messagebox.showerror('Coda attività', str(exc))
            return
        self.refresh_queue_controls()
        self.refresh_queue_window(select=target)
        self.schedule_save()

    def remove_queue_selection(self):
        if not self.queue_edit_allowed():
            return
        index = self.selected_queue_index()
        if index is None:
            return
        try:
            removed = remove_task(self.task_queue, index)
        except QueueEditError as exc:
            messagebox.showerror('Coda attività', str(exc))
            return
        self.logs.append('Rimosso dalla coda: ' + removed['request'][:100])
        self.refresh_queue_controls()
        self.refresh_queue_window(select=min(index, len(self.task_queue) - 1) if self.task_queue else None)
        self.update_activity()
        self.schedule_save()

    def start_queue_selection(self):
        if not self.queue_edit_allowed():
            return
        if self.pending:
            messagebox.showinfo('Modifiche in attesa', 'Applica o rifiuta la proposta corrente prima del prossimo lavoro.')
            return
        index = self.selected_queue_index()
        if index is None:
            return
        # Porta l'incarico in testa senza alterare l'ordine relativo degli altri.
        selected = self.task_queue.pop(index)
        self.task_queue.insert(0, selected)
        self.refresh_queue_controls()
        self.close_queue_window()
        self.run_next()

    def enqueue(self):
        text = self.input.get('1.0', 'end-1c').strip()
        if not text:
            return
        if len(text) > 20000 or len(self.task_queue) >= 100:
            self.say('', 'Coda non aggiornata: massimo 100 incarichi e 20.000 caratteri per richiesta.')
            return
        self.task_queue.append({'request': text, 'project': self.current_project(),
                                'attachments': list(self.attachments), 'history': [],
                                'model': self.model, 'mode': self.mode.get(),
                                'response_style': self.response_style.get()})
        self.input.delete('1.0', 'end')
        self.logs.append('In coda: ' + text[:100])
        self.refresh_queue_controls()
        self.update_activity()
        self.schedule_save()

    def run_next(self):
        if self.process is not None or not self.task_queue:
            return
        if self.pending:
            messagebox.showinfo('Modifiche in attesa', 'Applica o rifiuta la proposta corrente prima del prossimo lavoro.')
            return
        job = self.task_queue[0]
        project = job['project']
        if project and not Path(project).is_dir():
            self.say('', 'Incarico non avviato: la cartella del progetto non è disponibile. La richiesta resta in coda.')
            return
        if project and project not in self.projects:
            self.projects.append(project)
            self.refresh_projects()
            self.save_settings()
        previous_history = list(self.history)
        previous_mode = self.mode.get()
        self.task_queue.pop(0)
        index = self.projects.index(project) + 1 if project in self.projects else 0
        self.project_list.selection_clear(0, 'end')
        self.project_list.selection_set(index)
        self.select_project()
        self.history = []
        self.refresh_queue_controls()
        self.mode.set(job['mode'])
        if not self.start_job(job, from_queue=True):
            self.history = previous_history
            self.mode.set(previous_mode)
            self.schedule_save()

    def update_activity(self):
        self.activity.configure(state='normal')
        self.activity.delete('1.0', 'end')
        self.activity.insert('end', '\n'.join(self.logs[-80:]))
        self.activity.configure(state='disabled')
        self.activity.see('end')
        self.schedule_save()

    def refresh_files(self):
        from core.project import ProjectManager
        project = self.current_project()
        self.project_path.set(project or 'Nessun progetto selezionato')
        self.file_list.delete(0, 'end')
        if project:
            try:
                for path in ProjectManager(Path(project).parent).list_files(Path(project), max_files=300):
                    self.file_list.insert('end', path)
            except Exception as exc:
                self.logs.append('Elenco file: ' + str(exc))

    def view_file(self, event=None):
        selected = self.file_list.curselection()
        project = self.current_project()
        if not project or not selected:
            return
        try:
            path = safe_project_path(Path(project), self.file_list.get(selected[0]))
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('File troppo grande per questa anteprima (massimo 2 MB).')
            content = path.read_text(encoding='utf-8')
            window = tk.Toplevel(self.root)
            window.title(path.name + ' · sola lettura')
            window.geometry('850x600')
            viewer = ScrolledText(window, font=(self.code_font, 10), bg='#101426', fg='#f5f3ff', wrap='none')
            viewer.pack(fill='both', expand=True)
            viewer.insert('end', content)
            viewer.configure(state='disabled')
        except Exception as exc:
            messagebox.showerror('Anteprima file', str(exc))

    def probe_write(self):
        project = self.current_project()
        if self.process is not None:
            return
        if not project:
            messagebox.showinfo('Prova scrittura', 'Scegli prima la cartella del progetto.')
            return
        try:
            result = apply_approved(project, [{'type': 'create', 'path': 'test_giorgio.txt', 'content': 'Giorgio: scrittura e rilettura verificate.\n', 'reason': 'Prova richiesta dal pulsante'}], {'test_giorgio.txt': None})
            self.last_backup = (project, str(BackupManager(project).latest_backup()))
            self.restorable_states = {'test_giorgio.txt': fingerprint(Path(project) / 'test_giorgio.txt')}
            self.restore_button.configure(state='normal')
            self.say('Giorgio', result + '\nPercorso: ' + str(Path(project) / 'test_giorgio.txt'))
            self.logs.append('Prova scrittura riuscita: test_giorgio.txt')
            self.refresh_files()
            self.update_activity()
        except Exception as exc:
            self.say('Giorgio', 'Prova non completata: ' + str(exc))

    def export_chat(self):
        filename = filedialog.asksaveasfilename(title='Esporta conversazione', defaultextension='.txt', filetypes=[('Testo', '*.txt')])
        if filename:
            try:
                Path(filename).write_text(self.transcript_text.rstrip() + '\n', encoding='utf-8')
                self.logs.append('Conversazione esportata: ' + filename)
                self.update_activity()
            except OSError as exc:
                messagebox.showerror('Esportazione', str(exc))

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Impostazioni non valide.')
            self.projects = [str(Path(p).resolve()) for p in data.get('projects', []) if Path(p).is_dir()]
            self.model = str(data.get('model', self.model))
            style = data.get('response_style', self.response_length)
            if style in {'Breve', 'Normale', 'Dettagliata'}:
                self.response_length = style
        except (OSError, ValueError, TypeError):
            pass
        demo = BASE / 'test_workspace' / 'ProgettoProva'
        if demo.is_dir() and str(demo) not in self.projects:
            self.projects.append(str(demo))

    def save_settings(self):
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps({'projects': self.projects, 'model': self.model,
                                            'response_style': self.response_style.get()}, indent=2), encoding='utf-8')
        except OSError as exc:
            self.logs.append(f'Impostazioni non salvate: {exc}')

    def save_response_style(self):
        if self.response_style.get() not in {'Breve', 'Normale', 'Dettagliata'}:
            self.response_style.set('Breve')
        self.save_settings()

    def copy_code(self, code, button=None):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.root.update_idletasks()
            if button is not None and button.winfo_exists():
                button.configure(text='Copiato ✓')
        except tk.TclError as exc:
            self.logs.append('Copia codice non riuscita: ' + str(exc))
            self.update_activity()

    def insert_formatted(self, text):
        for kind, language, content in split_fenced(text):
            if kind == 'text':
                self.chat.insert('end', content)
                continue
            self.chat.insert('end', language + '  ', 'code_language')
            button = ttk.Button(self.chat, text='Copia')
            button.configure(command=lambda value=content, widget=button: self.copy_code(value, widget))
            self.code_buttons.append(button)
            self.chat.window_create('end', window=button, padx=6, pady=3)
            self.chat.insert('end', '\n' + content + '\n', 'code')

    def render_chat_text(self, text):
        self.insert_formatted(text)

    def finalize_reply_view(self):
        if not self.reply_started or self.reply_content_start is None:
            return
        self.chat.configure(state='normal')
        self.chat.delete(self.reply_content_start, 'end')
        self.insert_formatted(self.reply)
        self.chat.insert('end', '\n\n')
        self.chat.configure(state='disabled')
        self.chat.see('end')
        self.transcript_text += 'Giorgio\n' + self.reply + '\n\n'
        self.reply_content_start = None
        self.schedule_save()

    def say(self, author, text):
        self.transcript_text += ((author + '\n') if author else '') + text + '\n\n'
        self.chat.configure(state='normal')
        if author:
            self.chat.insert('end', author + '\n', 'author')
        if author:
            self.insert_formatted(text)
            self.chat.insert('end', '\n\n')
        else:
            self.chat.insert('end', text + '\n\n', 'notice')
        self.chat.configure(state='disabled')
        self.chat.see('end')
        self.schedule_save()

    def append_text(self, text):
        self.chat.configure(state='normal')
        if not self.reply_started:
            self.chat.insert('end', 'Giorgio\n', 'author')
            self.reply_content_start = self.chat.index('end-1c')
            self.reply_started = True
        self.chat.insert('end', text)
        self.chat.configure(state='disabled')
        self.chat.see('end')
        self.reply += text
        self.schedule_save()

    def refresh_projects(self):
        self.project_list.delete(0, 'end')
        self.project_list.insert('end', 'Chat e allegati')
        names = [Path(p).name for p in self.projects]
        for path in self.projects:
            label = Path(path).name
            if names.count(label) > 1:
                label += ' · ' + Path(path).parent.name
            self.project_list.insert('end', label)

    def current_project(self):
        selection = self.project_list.curselection()
        return self.projects[selection[0] - 1] if selection and selection[0] > 0 else None

    def select_project(self, event=None):
        self.reject()
        self.history.clear()
        self.last_backup = None
        self.restore_button.configure(state='disabled')
        project = self.current_project()
        self.state.set('Progetto: ' + Path(project).name if project else 'Chat e allegati')
        self.refresh_files()
        self.schedule_save()

    def add_project(self):
        path = filedialog.askdirectory(title='Scegli la cartella del progetto')
        if path:
            path = str(Path(path).resolve())
            if path not in self.projects:
                self.projects.append(path)
                self.refresh_projects()
                self.save_settings()
            self.project_list.selection_clear(0, 'end')
            self.project_list.selection_set(self.projects.index(path) + 1)
            self.select_project()

    def new_chat(self):
        self.history.clear()
        self.attachments.clear()
        self.transcript_text = ''
        self.render_chips()
        self.reject()
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.code_buttons.clear()
        self.chat.configure(state='disabled')
        self.say('Giorgio', 'Nuova conversazione. Su cosa lavoriamo?')

    def attachment_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label='Carica file…', command=self.add_files)
        menu.add_command(label='Carica cartella…', command=self.add_folder)
        menu.tk_popup(self.attach_button.winfo_rootx(), self.attach_button.winfo_rooty() + self.attach_button.winfo_height())

    def add_files(self):
        files = filedialog.askopenfilenames(title='Allega file', filetypes=[('File leggibili', ' '.join('*' + ext for ext in sorted(SUPPORTED))), ('Tutti i file', '*.*')])
        self.accept_paths(files)

    def add_folder(self):
        path = filedialog.askdirectory(title='Allega i file di una cartella (massimo 20)')
        if path:
            self.accept_paths([path])

    def accept_paths(self, paths):
        skipped = 0
        for value in paths:
            path = Path(value)
            if path.is_dir():
                candidates = []
                for directory, dirs, files in os.walk(path, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.giorgio_backups'} and not Path(directory, d).is_symlink()]
                    for name in sorted(files):
                        candidate = Path(directory, name)
                        if candidate.suffix.lower() in SUPPORTED and not candidate.is_symlink():
                            candidates.append(candidate)
                            if len(candidates) >= 21:
                                break
                    if len(candidates) >= 21:
                        break
            else:
                candidates = [path]
            for candidate in candidates:
                if candidate.suffix.lower() not in SUPPORTED:
                    skipped += 1
                    continue
                filename = str(candidate.resolve())
                if filename not in self.attachments:
                    if len(self.attachments) >= 20:
                        skipped += 1
                    else:
                        self.attachments.append(filename)
        self.render_chips()
        if skipped:
            self.say('', f'{skipped} file esclusi: formato non supportato o limite di 20 allegati. Le immagini richiedono un modello vision.')

    def drop(self, event):
        if self.process is None:
            self.accept_paths(self.root.tk.splitlist(event.data))
        return event.action

    def render_chips(self):
        self.schedule_save()
        for child in self.chips.winfo_children():
            child.destroy()
        for i, filename in enumerate(self.attachments):
            frame = ttk.Frame(self.chips)
            frame.grid(row=i // 3, column=i % 3, sticky='w', padx=(0, 10), pady=2)
            ttk.Label(frame, text=Path(filename).name[:30]).pack(side='left')
            ttk.Button(frame, text='×', width=2, command=lambda p=filename: self.remove_attachment(p)).pack(side='left')

    def remove_attachment(self, path):
        if self.process is None:
            self.attachments.remove(path)
            self.render_chips()

    def on_return(self, event):
        if event.state & 0x1:
            return None
        if self.process is None:
            self.send_or_stop()
        return 'break'

    def set_busy(self, busy):
        self.send_button.configure(text='Stop ■' if busy else 'Invia ↑')
        state = 'disabled' if busy else 'normal'
        self.project_list.configure(state=state)
        for button in (self.add_project_button, self.new_chat_button, self.attach_button, self.probe_button, self.next_button):
            button.configure(state=state)
        self.restore_button.configure(state='normal' if not busy and self.last_backup else 'disabled')
        self.mode_select.configure(state='disabled' if busy else 'readonly')
        self.length_select.configure(state='disabled' if busy else 'readonly')
        self.refresh_queue_controls()

    def send_or_stop(self):
        if self.process is not None:
            self.stop()
            return
        text = self.input.get('1.0', 'end-1c').strip()
        if not text:
            return
        if len(self.task_queue) >= 100:
            self.say('', 'La coda è piena: avvia un incarico in attesa prima di inviare altro lavoro.')
            return
        if len(text) > 20000:
            self.say('', 'Richiesta troppo lunga: massimo 20.000 caratteri. Allega il documento invece di incollarlo.')
            return
        self.reject()
        self.reply = ''
        self.reply_started = False
        self.reply_content_start = None
        project = self.current_project()
        job = {'request': text, 'project': project, 'attachments': list(self.attachments),
               'history': list(self.history), 'model': self.model, 'mode': self.mode.get(),
               'response_style': self.response_style.get()}
        self.start_job(job)

    def start_job(self, job, from_queue=False):
        self.active_job = dict(job)
        text = job['request']
        try:
            context = mp.get_context('spawn')
            self.events = context.Queue()
            self.process = context.Process(target=work_request, args=(self.events, job), daemon=True)
            self.process.start()
        except Exception as exc:
            if self.events is not None:
                self.events.close()
            self.events = None
            self.process = None
            if from_queue:
                self.task_queue.insert(0, job)
                self.refresh_queue_controls()
            self.active_job = None
            self.say('Giorgio', f'Avvio non riuscito: {exc}')
            self.schedule_save()
            return False
        self.reply = ''
        self.reply_started = False
        self.reply_content_start = None
        self.logs.append('Avvio ' + job.get('mode', 'Agente') + ': ' + text[:100])
        self.model_label.set('Ollama · ' + job['model'])
        self.update_activity()
        self.say('Tu', text)
        self.history.append({'role': 'user', 'content': text})
        if not from_queue:
            self.input.delete('1.0', 'end')
        self.set_busy(True)
        self.state.set('Sto lavorando…')
        return True

    def poll(self):
        if self.closing:
            return
        if self.poll_timer is not None:
            self.root.after_cancel(self.poll_timer)
            self.poll_timer = None
        self.poll_ollama()
        terminal = False
        received = False
        if self.events is not None:
            try:
                for _ in range(150):
                    kind, value = self.events.get_nowait()
                    received = True
                    if kind == 'status':
                        self.logs.append(value)
                        if 'Qwen sta generando:' in value:
                            self.state.set('Sto preparando la risposta… ' + value.split('Qwen sta generando:', 1)[1].strip())
                        elif 'read_file' in value or 'sola lettura' in value:
                            self.state.set('Sto controllando i file del progetto…')
                        elif 'decidendo' in value:
                            self.state.set('Sto cercando le informazioni utili…')
                        else:
                            self.state.set(value.replace('[Giorgio] ', ''))
                    elif kind == 'attachment':
                        suffix = ' · lettura limitata' if value['limited'] else ''
                        self.say('', f"Letto {value['name']}: {value['characters']} caratteri{suffix}. Uso estratti pertinenti alla domanda.")
                    elif kind == 'warning':
                        self.say('', value)
                    elif kind == 'text':
                        self.append_text(value)
                    elif kind == 'plan':
                        self.pending = value if value['operations'] else None
                        self.say('Giorgio', '\n\n'.join(p for p in (value['summary'], value['analysis']) if p))
                        if self.pending:
                            self.say('', f"Proposte per {len(value['operations'])} file. Controlla le modifiche e premi Applica modifiche per applicarle.")
                            supported = all(op['type'] in {'create', 'modify'} for op in value['operations'])
                            self.apply_button.configure(state='normal' if supported else 'disabled')
                            if not supported:
                                self.say('', 'La proposta include spostamenti o eliminazioni: questa versione può solo mostrarli.')
                            self.proposal_bar.pack(fill='x', before=self.chips)
                        self.history.append({'role': 'assistant', 'content': value['summary'] + '\n' + value['analysis']})
                        terminal = True
                        break
                    elif kind == 'error':
                        if self.reply_started:
                            self.append_text('\n\n')
                            self.transcript_text += 'Giorgio\n' + self.reply + '\n[Risposta interrotta da errore]\n\n'
                            self.reply_content_start = None
                        self.say('Giorgio', 'Operazione non completata: ' + value)
                        terminal = True
                        break
                    elif kind == 'done':
                        self.finalize_reply_view()
                        self.history.append({'role': 'assistant', 'content': self.reply})
                        terminal = True
                        break
            except queue.Empty:
                pass
            if terminal:
                self.finish()
            elif self.process is not None and not self.process.is_alive() and not received:
                self.say('Giorgio', 'Il processo è terminato senza risposta. Controlla i dettagli e le dipendenze.')
                self.finish()
        self.update_activity()
        self.poll_timer = self.root.after(80, self.poll)

    def finish(self):
        if self.process is not None:
            self.process.join(timeout=0.2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
            if not self.process.is_alive():
                self.process.close()
        if self.events is not None:
            self.events.close()
        self.events = None
        self.process = None
        self.active_job = None
        self.set_busy(False)
        self.schedule_save()
        self.state.set('Pronto')
        self.model_label.set('Ollama · ' + self.model)

    def stop(self):
        if self.process is None:
            return
        self.process.terminate()
        self.process.join(timeout=0.5)
        if self.reply_started:
            self.append_text('\n\n')
            self.transcript_text += 'Giorgio\n' + self.reply + '\n[Risposta interrotta]\n\n'
            self.reply_content_start = None
            self.history.append({'role': 'assistant', 'content': self.reply + '\n[Risposta interrotta]'})
        self.finish()
        self.reject()
        self.say('', 'Operazione interrotta. Nessuna modifica applicata. Puoi correggere la richiesta e inviarla di nuovo.')

    def reject(self):
        self.pending = None
        self.proposal_bar.pack_forget()

    def preview(self):
        if not self.pending:
            return
        window = tk.Toplevel(self.root)
        window.title('Modifiche proposte · ' + Path(self.pending['project']).name)
        window.geometry('850x620')
        text = ScrolledText(window, wrap='none', font=(self.code_font, 10))
        text.pack(fill='both', expand=True, padx=12, pady=12)
        root = Path(self.pending['project'])
        for operation in self.pending['operations']:
            text.insert('end', f"\n{operation['type'].upper()}: {operation['path']}\n{operation['reason']}\n")
            if operation['type'] in {'create', 'modify'}:
                path = safe_project_path(root, operation['path'])
                old = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
                new = operation['content'] or ''
                text.insert('end', ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                               fromfile='prima/' + operation['path'], tofile='dopo/' + operation['path'])))
                text.insert('end', '\n')
            elif operation.get('destination'):
                text.insert('end', 'Destinazione: ' + operation['destination'] + '\n')
        text.configure(state='disabled')
        ttk.Button(window, text='Chiudi anteprima', command=window.destroy).pack(pady=(0, 12))

    def apply(self):
        if self.process is not None or not self.pending:
            return
        plan = self.pending
        self.apply_button.configure(state='disabled')
        self.state.set('Salvo la correzione e il backup…')
        self.root.update_idletasks()
        try:
            result = apply_approved(plan['project'], plan['operations'], plan['expected'])
            self.last_backup = (plan['project'], str(BackupManager(plan['project']).latest_backup()))
            self.restorable_states = {op['path']: fingerprint(safe_project_path(Path(plan['project']), op['path'])) for op in plan['operations']}
            self.say('Giorgio', result)
            self.logs.append(result)
            self.refresh_files()
            self.update_activity()
            self.restore_button.configure(state='normal')
            self.reject()
        except Exception as exc:
            self.say('Giorgio', 'Correzione non completata: ' + str(exc))
            self.reject()
        self.state.set('Pronto')

    def restore(self):
        if self.process is not None or not self.last_backup:
            return
        root, saved = self.last_backup
        try:
            for path, state in self.restorable_states.items():
                if fingerprint(safe_project_path(Path(root), path)) != state:
                    raise ValueError('Un file è stato modificato dopo la correzione. Ripristino automatico bloccato per conservarlo.')
            if not messagebox.askyesno('Ripristina correzione', 'Vuoi annullare l’ultima correzione di Giorgio e ripristinare i file del backup?'):
                return
            BackupManager(root).restore(saved)
            self.refresh_files()
            self.say('Giorgio', 'Ultima correzione annullata. File originali ripristinati.')
            self.last_backup = None
            self.restore_button.configure(state='disabled')
        except Exception as exc:
            messagebox.showerror('Ripristino', str(exc))

    def settings(self):
        window = tk.Toplevel(self.root)
        window.title('Impostazioni e dettagli')
        window.geometry('740x500')
        ttk.Label(window, text='Modello Ollama', padding=12).pack(anchor='w')
        model_value = tk.StringVar(value=self.model)
        values = list(self.available_models)
        if self.model not in values:
            values.insert(0, self.model)
        entry = ttk.Combobox(window, textvariable=model_value, values=values, state='normal')
        entry.pack(fill='x', padx=12)
        ttk.Label(window, text=('Modelli rilevati: ' + str(len(self.available_models)) if self.available_models else 'Nessun modello rilevato: premi Controlla Ollama nella finestra principale.'), padding=12).pack(anchor='w')
        def save():
            model = model_value.get().strip()
            if len(model) > 200:
                messagebox.showerror('Modello', 'Nome del modello troppo lungo (massimo 200 caratteri).')
                return
            if model and self.process is None:
                self.model = model
                self.save_settings()
                self.model_label.set('Ollama · ' + self.model)
                window.destroy()
                self.check_ollama(force=True)
        ttk.Button(window, text='Usa questo modello', command=save, state='disabled' if self.process else 'normal').pack(anchor='w', padx=12, pady=8)
        ttk.Label(window, text='Allegati: testo, codice, CSV, PDF con testo e Word.\nImmagini, OCR ed Excel non sono ancora supportati.', padding=12).pack(anchor='w')
        log = ScrolledText(window, font=(self.code_font, 9), wrap='word')
        log.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        log.insert('end', '\n'.join(self.logs[-120:]))
        log.configure(state='disabled')

    def close(self):
        self.closing = True
        self.close_queue_window()
        if self.ollama_timer is not None:
            self.root.after_cancel(self.ollama_timer)
            self.ollama_timer = None
        if self.poll_timer is not None:
            self.root.after_cancel(self.poll_timer)
            self.poll_timer = None
        if self.process is not None:
            self.stop()
        self.save_settings()
        if self.save_timer is not None:
            self.root.after_cancel(self.save_timer)
            self.save_timer = None
        self.save_session()
        self.root.destroy()


if __name__ == '__main__':
    mp.freeze_support()
    app_root = make_root()
    GiorgioApp(app_root)
    app_root.mainloop()
