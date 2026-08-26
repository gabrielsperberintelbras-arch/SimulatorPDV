#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulador de PDV - Ferramenta de teste para overlay de POS em DVRs/NVRs Intelbras
====================================================================================
Envia dados de "venda" via rede (TCP servidor, TCP cliente ou UDP) para que o
gravador receba e exiba a sobreposição de PDV, do mesmo jeito que um PDV real faria.

Como escolher o modo de conexão (compare com a tela "Modo de conexão" do gravador):

  - Gravador configurado como TCP_CLIENT  -> aqui use "TCP Servidor" (o simulador
    fica escutando e o gravador se conecta nele).
  - Gravador configurado como TCP         -> aqui use "TCP Cliente" (o simulador
    conecta no IP/porta do gravador).
  - Gravador configurado como UDP         -> aqui use "UDP".

Requer apenas Python 3 padrão (tkinter já vem incluso). Nenhuma dependência externa.
"""

import socket
import threading
import random
import time
import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ----------------------------- Paleta visual (preto e verde, estilo Intelbras) -----------------------------
BG = "#0c0c0c"
BG_HEADER = "#111111"
BG_PANEL = "#161616"
BG_FIELD = "#0a0a0a"
BG_LOG = "#000000"
FG = "#eaeaea"
FG_DIM = "#8f8f8f"
ACCENT = "#22b25c"          # verde do "Habilitar"
ACCENT_DARK = "#178a45"
ACCENT_SOFT = "#153621"
BORDER = "#262626"
DANGER = "#e0524f"
BTN_DARK = "#1e1e1e"
BTN_DARK_HOVER = "#292929"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SUB = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)

ENCODINGS = {
    "Unicode (UTF-8)": "utf-8",
    "Latin-1 (ISO-8859-1)": "latin-1",
    "ASCII": "ascii",
}
TERMINATORS = {
    "CRLF (\\r\\n)": "\r\n",
    "LF (\\n)": "\n",
    "CR (\\r)": "\r",
    "Nenhum": "",
}
MODE_DISPLAY = {
    "TCP Servidor (aguardar conexão do gravador)": "server",
    "TCP Cliente (conectar no gravador)": "client",
    "UDP": "udp",
}
MODE_DISPLAY_LIST = list(MODE_DISPLAY.keys())

PRODUTOS = [
    ("ARROZ TIPO 1 5KG", 24.90), ("FEIJAO CARIOCA 1KG", 8.50),
    ("OLEO DE SOJA 900ML", 7.20), ("ACUCAR REFINADO 1KG", 4.80),
    ("CAFE TORRADO 500G", 14.90), ("LEITE INTEGRAL 1L", 5.30),
    ("SABAO EM PO 1KG", 12.40), ("REFRIGERANTE 2L", 9.99),
    ("BISCOITO RECHEADO", 3.75), ("PAPEL HIGIENICO 12R", 22.50),
    ("DETERGENTE 500ML", 2.60), ("MACARRAO ESPAGUETE 500G", 4.10),
]


# ============================================================ widgets custom ===
class ToggleSwitch(tk.Canvas):
    """Interruptor deslizante verde, no estilo 'Habilitar' da interface do gravador."""

    def __init__(self, parent, command=None, value=False, width=42, height=22, bg=BG_PANEL):
        super().__init__(parent, width=width, height=height, bg=bg,
                          highlightthickness=0, cursor="hand2")
        self.command = command
        self.value = value
        self.width = width
        self.height = height
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = self.height / 2
        color = ACCENT if self.value else "#3a3a3a"
        self.create_oval(0, 0, self.height, self.height, fill=color, outline=color)
        self.create_oval(self.width - self.height, 0, self.width, self.height, fill=color, outline=color)
        self.create_rectangle(r, 0, self.width - r, self.height, fill=color, outline=color)
        pad = 2
        knob_d = self.height - 2 * pad
        x0 = (self.width - self.height + pad) if self.value else pad
        self.create_oval(x0, pad, x0 + knob_d, pad + knob_d, fill="#ffffff", outline="#ffffff")

    def _on_click(self, _event):
        self.set(not self.value, fire=True)

    def set(self, val, fire=False):
        self.value = bool(val)
        self._draw()
        if fire and self.command:
            self.command(self.value)

    def get(self):
        return self.value


def make_button(parent, text, command, primary=False, danger=False, width=None):
    if primary:
        bg, fg, hover = ACCENT, "#ffffff", ACCENT_DARK
    elif danger:
        bg, fg, hover = "#2a1414", DANGER, "#3a1a1a"
    else:
        bg, fg, hover = BTN_DARK, FG, BTN_DARK_HOVER
    btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                     activebackground=hover, activeforeground=fg,
                     relief="flat", bd=0, padx=14, pady=7, font=FONT,
                     cursor="hand2", width=width)
    btn.bind("<Enter>", lambda e: btn.config(bg=hover))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


def section(parent, title):
    """Painel escuro com barra de destaque verde e titulo em maiusculas, estilo card."""
    wrapper = tk.Frame(parent, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
    head = tk.Frame(wrapper, bg=BG_PANEL)
    head.pack(fill="x", padx=16, pady=(14, 6))
    tk.Frame(head, bg=ACCENT, width=4, height=16).pack(side="left", padx=(0, 8))
    tk.Label(head, text=title.upper(), bg=BG_PANEL, fg=ACCENT, font=FONT_SECTION).pack(side="left")
    body = tk.Frame(wrapper, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    return wrapper, body


# ============================================================ aplicacao ===
class PDVSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Simulador de PDV - Teste de Overlay (Intelbras)")
        self.root.configure(bg=BG)
        self.root.geometry("1020x760")
        self.root.minsize(900, 650)

        self.sock = None
        self.conn = None
        self.conn_addr = None
        self.connected = False
        self.server_thread = None
        self.stop_flag = threading.Event()
        self.auto_thread = None
        self.auto_running = False

        self._setup_style()
        self._build_ui()
        self._log("Simulador pronto. Configure a conexão e ative o Habilitar.")

    # --------------------------------------------------------------- estilo ---
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("Dim.TLabel", background=BG_PANEL, foreground=FG_DIM, font=FONT)
        style.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_FIELD,
                         foreground=FG, arrowcolor=FG, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", BG_FIELD)],
                   selectbackground=[("readonly", BG_FIELD)],
                   selectforeground=[("readonly", FG)])
        style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG, insertcolor=FG)
        style.configure("TSpinbox", fieldbackground=BG_FIELD, foreground=FG, arrowcolor=FG)
        self.root.option_add("*TCombobox*Listbox.background", BG_FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    # ---------------------------------------------------------------- header ---
    def _build_header(self):
        header = tk.Frame(self.root, bg=BG_HEADER, height=68)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=BG_HEADER)
        title_box.pack(side="left", padx=20, pady=10)
        title_row = tk.Frame(title_box, bg=BG_HEADER)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="SIMULADOR", bg=BG_HEADER, fg=FG, font=FONT_TITLE).pack(side="left")
        tk.Label(title_row, text=" PDV", bg=BG_HEADER, fg=ACCENT, font=FONT_TITLE).pack(side="left")
        tk.Label(title_box, text="Overlay de teste compatível com gravadores Intelbras",
                 bg=BG_HEADER, fg=FG_DIM, font=FONT_SUB).pack(anchor="w")

        status_box = tk.Frame(header, bg=BG_HEADER)
        status_box.pack(side="right", padx=20)
        self.status_dot = tk.Canvas(status_box, width=12, height=12, bg=BG_HEADER, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self._dot_id = self.status_dot.create_oval(1, 1, 11, 11, fill=DANGER, outline=DANGER)
        self.status_var = tk.StringVar(value="DESCONECTADO")
        self.status_lbl = tk.Label(status_box, textvariable=self.status_var, bg=BG_HEADER,
                                    fg=DANGER, font=FONT_BOLD)
        self.status_lbl.pack(side="left")

        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x")

    # ------------------------------------------------------------------- ui ---
    def _build_ui(self):
        self._build_header()

        outer = tk.Frame(self.root, bg=BG, padx=16, pady=14)
        outer.pack(fill="both", expand=True)

        # ---- Conexao ----
        conn_wrap, conn_frame = section(outer, "Conexão de rede")
        conn_wrap.pack(fill="x", pady=(0, 12))

        top_row = tk.Frame(conn_frame, bg=BG_PANEL)
        top_row.pack(fill="x", pady=(0, 12))
        tk.Label(top_row, text="Habilitar", bg=BG_PANEL, fg=FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.enable_toggle = ToggleSwitch(top_row, command=self._on_toggle_enable)
        self.enable_toggle.pack(side="left", padx=(14, 0))
        tk.Label(top_row, text="liga/desliga o envio para o gravador", bg=BG_PANEL,
                 fg=FG_DIM, font=FONT_SUB).pack(side="left", padx=(12, 0))

        tk.Frame(conn_frame, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        grid = tk.Frame(conn_frame, bg=BG_PANEL)
        grid.pack(fill="x")

        ttk.Label(grid, text="Modo de conexão", style="Dim.TLabel").grid(row=0, column=0, sticky="w")
        self.mode_display_var = tk.StringVar(value=MODE_DISPLAY_LIST[0])
        self.mode_combo = ttk.Combobox(grid, textvariable=self.mode_display_var,
                                        values=MODE_DISPLAY_LIST, state="readonly", width=42)
        self.mode_combo.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        self.ip_label = ttk.Label(grid, text="IP de escuta", style="Dim.TLabel")
        self.ip_label.grid(row=2, column=0, sticky="w")
        self.ip_var = tk.StringVar(value="0.0.0.0")
        ttk.Entry(grid, textvariable=self.ip_var, width=18, font=FONT_MONO).grid(
            row=3, column=0, sticky="w", pady=(2, 14))

        ttk.Label(grid, text="Porta", style="Dim.TLabel").grid(row=2, column=1, sticky="w", padx=(20, 0))
        self.port_var = tk.StringVar(value="9000")
        ttk.Entry(grid, textvariable=self.port_var, width=10, font=FONT_MONO).grid(
            row=3, column=1, sticky="w", padx=(20, 0), pady=(2, 14))

        ttk.Label(grid, text="Codificação", style="Dim.TLabel").grid(row=2, column=2, sticky="w", padx=(20, 0))
        self.enc_var = tk.StringVar(value="Unicode (UTF-8)")
        ttk.Combobox(grid, textvariable=self.enc_var, values=list(ENCODINGS.keys()),
                     state="readonly", width=20).grid(row=3, column=2, sticky="w", padx=(20, 0), pady=(2, 14))

        ttk.Label(grid, text="Terminador de linha", style="Dim.TLabel").grid(row=2, column=3, sticky="w", padx=(20, 0))
        self.term_var = tk.StringVar(value="CRLF (\\r\\n)")
        ttk.Combobox(grid, textvariable=self.term_var, values=list(TERMINATORS.keys()),
                     state="readonly", width=14).grid(row=3, column=3, sticky="w", padx=(20, 0), pady=(2, 14))

        # ---- Composicao da venda ----
        sale_wrap, sale_frame = section(outer, "Conteúdo a enviar (recibo / cupom)")
        sale_wrap.pack(fill="both", expand=True, pady=(0, 12))

        toolbar = tk.Frame(sale_frame, bg=BG_PANEL)
        toolbar.pack(fill="x", pady=(0, 10))
        make_button(toolbar, "+ Cabeçalho", self._insert_header).pack(side="left", padx=(0, 6))
        make_button(toolbar, "+ Item", self._insert_item).pack(side="left", padx=(0, 6))
        make_button(toolbar, "+ Total", self._insert_total).pack(side="left", padx=(0, 6))
        make_button(toolbar, "+ Pagamento", self._insert_payment).pack(side="left", padx=(0, 6))
        make_button(toolbar, "+ Rodapé", self._insert_footer).pack(side="left", padx=(0, 6))
        make_button(toolbar, "Limpar", self._clear_text).pack(side="left", padx=(6, 0))
        make_button(toolbar, "Gerar Venda Aleatória", self._generate_random_sale, primary=True).pack(side="right")

        self.text = scrolledtext.ScrolledText(sale_frame, height=13, bg=BG_FIELD, fg=FG,
                                               insertbackground=FG, font=FONT_MONO, wrap="word",
                                               borderwidth=1, relief="solid", highlightbackground=BORDER,
                                               highlightcolor=ACCENT, highlightthickness=1)
        self.text.pack(fill="both", expand=True)
        self._generate_random_sale()

        # ---- Envio ----
        send_wrap, send_frame = section(outer, "Envio")
        send_wrap.pack(fill="x", pady=(0, 12))

        send_row = tk.Frame(send_frame, bg=BG_PANEL)
        send_row.pack(fill="x")
        make_button(send_row, "Enviar Tudo (1 pacote)", self._send_all, primary=True).pack(side="left")
        make_button(send_row, "Enviar Linha a Linha", self._send_line_by_line).pack(side="left", padx=(8, 0))

        ttk.Label(send_row, text="Atraso entre linhas (ms)", style="Dim.TLabel").pack(side="left", padx=(20, 6))
        self.delay_var = tk.StringVar(value="300")
        ttk.Spinbox(send_row, from_=0, to=5000, increment=50, textvariable=self.delay_var,
                    width=6).pack(side="left")

        auto_row = tk.Frame(send_frame, bg=BG_PANEL)
        auto_row.pack(fill="x", pady=(14, 0))
        tk.Label(auto_row, text="Repetir automaticamente", bg=BG_PANEL, fg=FG, font=FONT).pack(side="left")
        self.auto_toggle = ToggleSwitch(auto_row, command=self._on_toggle_auto)
        self.auto_toggle.pack(side="left", padx=(12, 12))
        ttk.Label(auto_row, text="a cada", style="Dim.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value="10")
        ttk.Spinbox(auto_row, from_=1, to=3600, textvariable=self.interval_var, width=6).pack(side="left", padx=(6, 6))
        ttk.Label(auto_row, text="seg (nova venda aleatória)", style="Dim.TLabel").pack(side="left")

        # ---- Log ----
        log_wrap, log_frame = section(outer, "Log de eventos")
        log_wrap.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(log_frame, height=7, bg=BG_LOG, fg="#63d98a",
                                              font=FONT_MONO, state="disabled", wrap="word",
                                              borderwidth=1, relief="solid", highlightbackground=BORDER,
                                              highlightthickness=1)
        self.log.pack(fill="both", expand=True)

        self._on_mode_change()

    # ---------------------------------------------------------- helpers ---
    def _current_mode(self):
        return MODE_DISPLAY.get(self.mode_display_var.get(), "server")

    def _on_mode_change(self):
        mode = self._current_mode()
        if mode == "server":
            self.ip_label.config(text="IP de escuta")
        else:
            self.ip_label.config(text="IP do gravador (DVR)")

    def _log(self, msg):
        def do():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{ts}] {msg}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, do)

    def _set_status(self, text, ok):
        def do():
            self.status_var.set(text.upper())
            color = ACCENT if ok else DANGER
            self.status_lbl.configure(foreground=color)
            self.status_dot.itemconfig(self._dot_id, fill=color, outline=color)
        self.root.after(0, do)

    # ------------------------------------------------------- templates ---
    def _insert_header(self):
        self.text.insert("insert", "LOJA TESTE INTELBRAS\nCNPJ 00.000.000/0001-00\n"
                          f"{datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")

    def _insert_item(self):
        nome, preco = random.choice(PRODUTOS)
        qtd = random.randint(1, 3)
        self.text.insert("insert", f"{nome:<24}{qtd}x{preco:6.2f} {qtd*preco:8.2f}\n")

    def _insert_total(self):
        self.text.insert("insert", "TOTAL A PAGAR ........... 00.00\n")

    def _insert_payment(self):
        self.text.insert("insert", random.choice([
            "FORMA DE PAGAMENTO: CARTAO DEBITO\n",
            "FORMA DE PAGAMENTO: CARTAO CREDITO\n",
            "FORMA DE PAGAMENTO: DINHEIRO\n",
            "FORMA DE PAGAMENTO: PIX\n",
        ]))

    def _insert_footer(self):
        self.text.insert("insert", "OBRIGADO PELA PREFERENCIA\nVOLTE SEMPRE\n")

    def _clear_text(self):
        self.text.delete("1.0", "end")

    def _generate_random_sale(self):
        self._clear_text()
        lines = []
        lines.append("LOJA TESTE INTELBRAS")
        lines.append("CNPJ 00.000.000/0001-00")
        lines.append(datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        lines.append("-" * 32)
        n_itens = random.randint(2, 6)
        total = 0.0
        for _ in range(n_itens):
            nome, preco = random.choice(PRODUTOS)
            qtd = random.randint(1, 3)
            subtotal = qtd * preco
            total += subtotal
            lines.append(f"{nome:<22}{qtd}x{preco:5.2f}{subtotal:8.2f}")
        lines.append("-" * 32)
        lines.append(f"TOTAL .......................{total:8.2f}")
        lines.append(random.choice([
            "FORMA DE PAGAMENTO: CARTAO DEBITO",
            "FORMA DE PAGAMENTO: CARTAO CREDITO",
            "FORMA DE PAGAMENTO: DINHEIRO",
            "FORMA DE PAGAMENTO: PIX",
        ]))
        lines.append("OBRIGADO PELA PREFERENCIA")
        self.text.insert("1.0", "\n".join(lines) + "\n")

    # ------------------------------------------------------ networking ---
    def _on_toggle_enable(self, value):
        if value:
            self._connect()
        else:
            self._disconnect()

    def _connect(self):
        mode = self._current_mode()
        ip = self.ip_var.get().strip()
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "Porta inválida.")
            self.enable_toggle.set(False)
            return

        self.stop_flag.clear()

        if mode == "server":
            self.server_thread = threading.Thread(target=self._run_tcp_server, args=(ip, port), daemon=True)
            self.server_thread.start()
        elif mode == "client":
            self.server_thread = threading.Thread(target=self._run_tcp_client, args=(ip, port), daemon=True)
            self.server_thread.start()
        else:  # udp
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_target = (ip, port)
                self.connected = True
                self._set_status(f"UDP pronto -> destino {ip}:{port}", True)
                self._log(f"UDP configurado para enviar a {ip}:{port}")
            except Exception as e:
                self._log(f"Erro ao configurar UDP: {e}")
                self.enable_toggle.set(False)

    def _run_tcp_server(self, ip, port):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((ip, port))
            self.sock.listen(1)
            self.sock.settimeout(1.0)
            self._set_status(f"Aguardando conexão em {ip}:{port}...", False)
            self._log(f"Servidor TCP escutando em {ip}:{port}")
            while not self.stop_flag.is_set():
                try:
                    conn, addr = self.sock.accept()
                    self.conn = conn
                    self.conn_addr = addr
                    self.connected = True
                    self._set_status(f"Conectado: {addr[0]}:{addr[1]}", True)
                    self._log(f"Gravador conectou de {addr[0]}:{addr[1]}")
                    while not self.stop_flag.is_set():
                        time.sleep(0.3)
                        try:
                            conn.setblocking(False)
                            data = conn.recv(1)
                            if data == b"":
                                raise ConnectionResetError()
                        except BlockingIOError:
                            pass
                        except (ConnectionResetError, OSError):
                            raise
                except socket.timeout:
                    continue
                except Exception:
                    self.connected = False
                    self._set_status("Conexão encerrada. Aguardando nova conexão...", False)
                    self._log("Conexão com o gravador foi encerrada.")
                    if self.conn:
                        try:
                            self.conn.close()
                        except Exception:
                            pass
                        self.conn = None
        except Exception as e:
            self._log(f"Erro no servidor TCP: {e}")
            self._set_status("Erro ao iniciar servidor", False)
            self.root.after(0, lambda: self.enable_toggle.set(False))
        finally:
            self._cleanup_sockets()

    def _run_tcp_client(self, ip, port):
        try:
            self._set_status(f"Conectando a {ip}:{port}...", False)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((ip, port))
            s.settimeout(None)
            self.sock = s
            self.conn = s
            self.connected = True
            self._set_status(f"Conectado ao gravador {ip}:{port}", True)
            self._log(f"Conectado ao gravador em {ip}:{port}")
            while not self.stop_flag.is_set():
                time.sleep(0.3)
        except Exception as e:
            self._log(f"Erro ao conectar: {e}")
            self._set_status("Falha ao conectar", False)
            self.root.after(0, lambda: self.enable_toggle.set(False))
        finally:
            self._cleanup_sockets()

    def _cleanup_sockets(self):
        self.connected = False
        for attr in ("conn", "sock"):
            s = getattr(self, attr, None)
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        self.conn = None
        self.sock = None

    def _disconnect(self):
        self.stop_flag.set()
        self._cleanup_sockets()
        self._set_status("Desconectado", False)
        self._log("Desconectado pelo usuário.")

    # ------------------------------------------------------- envio ---
    def _get_encoding(self):
        return ENCODINGS.get(self.enc_var.get(), "utf-8")

    def _get_terminator(self):
        return TERMINATORS.get(self.term_var.get(), "\r\n")

    def _raw_send(self, payload_str):
        mode = self._current_mode()
        enc = self._get_encoding()
        try:
            data = payload_str.encode(enc, errors="replace")
        except Exception as e:
            self._log(f"Erro ao codificar texto: {e}")
            return False

        try:
            if mode == "udp":
                if not self.sock:
                    self._log("UDP não configurado. Ative o Habilitar primeiro.")
                    return False
                self.sock.sendto(data, self.udp_target)
            else:
                if not self.connected or not self.conn:
                    self._log("Não há conexão ativa. Ative o Habilitar e aguarde conectar.")
                    return False
                self.conn.sendall(data)
            return True
        except Exception as e:
            self._log(f"Erro ao enviar: {e}")
            return False

    def _send_all(self):
        content = self.text.get("1.0", "end-1c")
        term = self._get_terminator()
        payload = content if content.endswith(term) or term == "" else content + term
        if self._raw_send(payload):
            self._log(f"Enviado 1 pacote ({len(payload)} caracteres).")

    def _send_line_by_line(self):
        content = self.text.get("1.0", "end-1c")
        lines = content.split("\n")
        try:
            delay = max(0, int(self.delay_var.get())) / 1000.0
        except ValueError:
            delay = 0.3
        term = self._get_terminator()

        def worker():
            for line in lines:
                if not line.strip():
                    continue
                ok = self._raw_send(line + term)
                if ok:
                    self._log(f"Linha enviada: {line}")
                time.sleep(delay)
            self._log("Envio linha a linha concluído.")

        threading.Thread(target=worker, daemon=True).start()

    def _on_toggle_auto(self, value):
        if value:
            self.auto_running = True
            self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.auto_thread.start()
            self._log("Envio automático ativado.")
        else:
            self.auto_running = False
            self._log("Envio automático desativado.")

    def _auto_loop(self):
        while self.auto_running:
            try:
                interval = max(1, int(self.interval_var.get()))
            except ValueError:
                interval = 10
            self.root.after(0, self._generate_random_sale)
            time.sleep(0.2)
            self.root.after(0, self._send_all)
            for _ in range(interval * 10):
                if not self.auto_running:
                    return
                time.sleep(0.1)


def main():
    root = tk.Tk()
    app = PDVSimulator(root)

    def on_close():
        app.auto_running = False
        app._disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
