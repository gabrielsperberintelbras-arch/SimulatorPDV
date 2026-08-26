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

# ----------------------------- Paleta visual (estilo Intelbras) -----------------------------
BG = "#121212"
BG_PANEL = "#1b1b1b"
BG_FIELD = "#0e0e0e"
FG = "#e6e6e6"
FG_DIM = "#9a9a9a"
ACCENT = "#2fae52"      # verde do "Habilitar"
ACCENT_DARK = "#1f7a39"
BORDER = "#2c2c2c"
FONT = ("Segoe UI", 10)
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

PRODUTOS = [
    ("ARROZ TIPO 1 5KG", 24.90), ("FEIJAO CARIOCA 1KG", 8.50),
    ("OLEO DE SOJA 900ML", 7.20), ("ACUCAR REFINADO 1KG", 4.80),
    ("CAFE TORRADO 500G", 14.90), ("LEITE INTEGRAL 1L", 5.30),
    ("SABAO EM PO 1KG", 12.40), ("REFRIGERANTE 2L", 9.99),
    ("BISCOITO RECHEADO", 3.75), ("PAPEL HIGIENICO 12R", 22.50),
    ("DETERGENTE 500ML", 2.60), ("MACARRAO ESPAGUETE 500G", 4.10),
]


class PDVSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Simulador de PDV - Teste de Overlay (Intelbras)")
        self.root.configure(bg=BG)
        self.root.geometry("980x700")
        self.root.minsize(880, 620)

        self.sock = None            # socket base (servidor/cliente/udp)
        self.conn = None            # conexão aceita (modo servidor)
        self.conn_addr = None
        self.connected = False
        self.server_thread = None
        self.stop_flag = threading.Event()
        self.auto_thread = None
        self.auto_running = False

        self._setup_style()
        self._build_ui()
        self._log("Simulador pronto. Configure a conexão e clique em Iniciar.")

    # --------------------------------------------------------------- UI ---
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("Dim.TLabel", background=BG_PANEL, foreground=FG_DIM, font=FONT)
        style.configure("TButton", font=FONT, padding=6)
        style.configure("Accent.TButton", background=ACCENT, foreground="white")
        style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
        style.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_FIELD, foreground=FG)
        style.configure("TSpinbox", fieldbackground=BG_FIELD, foreground=FG)
        style.configure("TRadiobutton", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("TCheckbutton", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("TLabelframe", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("TLabelframe.Label", background=BG_PANEL, foreground=ACCENT, font=(FONT[0], 10, "bold"))

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        # ---- Conexão ----
        conn_frame = ttk.Labelframe(outer, text="Conexão de Rede", padding=12)
        conn_frame.pack(fill="x", pady=(0, 10))

        self.mode_var = tk.StringVar(value="server")
        modes = [("TCP Servidor (aguardar conexão do gravador)", "server"),
                 ("TCP Cliente (conectar no gravador)", "client"),
                 ("UDP", "udp")]
        for i, (text, val) in enumerate(modes):
            ttk.Radiobutton(conn_frame, text=text, variable=self.mode_var, value=val,
                             command=self._on_mode_change).grid(row=0, column=i, sticky="w", padx=(0, 16))

        self.ip_label = ttk.Label(conn_frame, text="IP de escuta:")
        self.ip_label.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.ip_var = tk.StringVar(value="0.0.0.0")
        ttk.Entry(conn_frame, textvariable=self.ip_var, width=18, font=FONT_MONO).grid(
            row=2, column=0, sticky="w")

        ttk.Label(conn_frame, text="Porta:").grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.port_var = tk.StringVar(value="9000")
        ttk.Entry(conn_frame, textvariable=self.port_var, width=10, font=FONT_MONO).grid(
            row=2, column=1, sticky="w")

        ttk.Label(conn_frame, text="Codificação:").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(10, 0))
        self.enc_var = tk.StringVar(value="Unicode (UTF-8)")
        ttk.Combobox(conn_frame, textvariable=self.enc_var, values=list(ENCODINGS.keys()),
                     state="readonly", width=20).grid(row=2, column=2, sticky="w", padx=(16, 0))

        ttk.Label(conn_frame, text="Terminador de linha:").grid(row=1, column=3, sticky="w", padx=(16, 0), pady=(10, 0))
        self.term_var = tk.StringVar(value="CRLF (\\r\\n)")
        ttk.Combobox(conn_frame, textvariable=self.term_var, values=list(TERMINATORS.keys()),
                     state="readonly", width=14).grid(row=2, column=3, sticky="w", padx=(16, 0))

        self.start_btn = ttk.Button(conn_frame, text="Iniciar", style="Accent.TButton", command=self._toggle_connection)
        self.start_btn.grid(row=2, column=4, sticky="w", padx=(20, 0))

        self.status_var = tk.StringVar(value="Desconectado")
        self.status_lbl = ttk.Label(conn_frame, textvariable=self.status_var, foreground="#e05555")
        self.status_lbl.grid(row=2, column=5, sticky="w", padx=(16, 0))

        # ---- Composição da venda ----
        text_frame = ttk.Labelframe(outer, text="Conteudo a Enviar (recibo / cupom)", padding=12)
        text_frame.pack(fill="both", expand=True, pady=(0, 10))

        toolbar = ttk.Frame(text_frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="+ Cabecalho", command=self._insert_header).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="+ Item", command=self._insert_item).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="+ Total", command=self._insert_total).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="+ Pagamento", command=self._insert_payment).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="+ Rodape", command=self._insert_footer).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Limpar", command=self._clear_text).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Gerar Venda Aleatoria", command=self._generate_random_sale).pack(side="right")

        self.text = scrolledtext.ScrolledText(text_frame, height=14, bg=BG_FIELD, fg=FG,
                                               insertbackground=FG, font=FONT_MONO, wrap="word",
                                               borderwidth=1, relief="solid")
        self.text.pack(fill="both", expand=True)
        self._generate_random_sale()

        # ---- Envio ----
        send_frame = ttk.Frame(outer)
        send_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(send_frame, text="Enviar Tudo (1 pacote)", style="Accent.TButton",
                   command=self._send_all).pack(side="left")
        ttk.Button(send_frame, text="Enviar Linha a Linha", command=self._send_line_by_line).pack(side="left", padx=(8, 0))

        ttk.Label(send_frame, text="Atraso entre linhas (ms):").pack(side="left", padx=(16, 4))
        self.delay_var = tk.StringVar(value="300")
        ttk.Spinbox(send_frame, from_=0, to=5000, increment=50, textvariable=self.delay_var,
                    width=6).pack(side="left")

        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(send_frame, text="Repetir automaticamente a cada", variable=self.auto_var,
                         command=self._toggle_auto).pack(side="left", padx=(20, 4))
        self.interval_var = tk.StringVar(value="10")
        ttk.Spinbox(send_frame, from_=1, to=3600, textvariable=self.interval_var, width=6).pack(side="left")
        ttk.Label(send_frame, text="seg (nova venda aleatoria)").pack(side="left", padx=(4, 0))

        # ---- Log ----
        log_frame = ttk.Labelframe(outer, text="Log de eventos", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(log_frame, height=8, bg="#000000", fg="#7bd88f",
                                              font=FONT_MONO, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

        self._on_mode_change()

    # ---------------------------------------------------------- helpers ---
    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "server":
            self.ip_label.config(text="IP de escuta:")
            if self.ip_var.get() not in ("0.0.0.0",):
                pass
        else:
            self.ip_label.config(text="IP do gravador (DVR):")

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
            self.status_var.set(text)
            self.status_lbl.configure(foreground=("#2fae52" if ok else "#e05555"))
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
    def _toggle_connection(self):
        if self.connected or (self.server_thread and self.server_thread.is_alive()):
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        mode = self.mode_var.get()
        ip = self.ip_var.get().strip()
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "Porta invalida.")
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
                self.start_btn.config(text="Parar")
            except Exception as e:
                self._log(f"Erro ao configurar UDP: {e}")

    def _run_tcp_server(self, ip, port):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((ip, port))
            self.sock.listen(1)
            self.sock.settimeout(1.0)
            self._set_status(f"Aguardando conexao em {ip}:{port}...", False)
            self._log(f"Servidor TCP escutando em {ip}:{port}")
            self.start_btn.config(text="Parar")
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
                    self._set_status("Conexao encerrada. Aguardando nova conexao...", False)
                    self._log("Conexao com o gravador foi encerrada.")
                    if self.conn:
                        try:
                            self.conn.close()
                        except Exception:
                            pass
                        self.conn = None
        except Exception as e:
            self._log(f"Erro no servidor TCP: {e}")
            self._set_status("Erro ao iniciar servidor", False)
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
            self.start_btn.config(text="Parar")
            while not self.stop_flag.is_set():
                time.sleep(0.3)
        except Exception as e:
            self._log(f"Erro ao conectar: {e}")
            self._set_status("Falha ao conectar", False)
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
        self.root.after(0, lambda: self.start_btn.config(text="Iniciar"))

    def _disconnect(self):
        self.stop_flag.set()
        self._cleanup_sockets()
        self._set_status("Desconectado", False)
        self._log("Desconectado pelo usuario.")

    # ------------------------------------------------------- envio ---
    def _get_encoding(self):
        return ENCODINGS.get(self.enc_var.get(), "utf-8")

    def _get_terminator(self):
        return TERMINATORS.get(self.term_var.get(), "\r\n")

    def _raw_send(self, payload_str):
        mode = self.mode_var.get()
        enc = self._get_encoding()
        try:
            data = payload_str.encode(enc, errors="replace")
        except Exception as e:
            self._log(f"Erro ao codificar texto: {e}")
            return False

        try:
            if mode == "udp":
                if not self.sock:
                    self._log("UDP nao configurado. Clique em Iniciar primeiro.")
                    return False
                self.sock.sendto(data, self.udp_target)
            else:
                if not self.connected or not self.conn:
                    self._log("Nao ha conexao ativa. Inicie e aguarde conectar.")
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
            self._log("Envio linha a linha concluido.")

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_auto(self):
        if self.auto_var.get():
            self.auto_running = True
            self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.auto_thread.start()
            self._log("Envio automatico ativado.")
        else:
            self.auto_running = False
            self._log("Envio automatico desativado.")

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
