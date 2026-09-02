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

Identidade visual: console técnico de rede (cantos retos, tipografia monoespaçada,
painéis divididos por linhas finas, trilha de canais numerados) — em vez do
dashboard SaaS convencional de cards arredondados.
"""

import os
import sys
import socket
import threading
import random
import time
import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox, filedialog

# ============================================================ paleta ===
BG = "#050705"
BG_RAIL = "#090b09"
BG_PANEL = "#0a0d0b"
BG_FIELD = "#000000"
BG_LOG = "#000000"
FG = "#d6ded8"
FG_DIM = "#5c655f"
FG_DIMMER = "#3c433e"
ACCENT = "#22e06a"
ACCENT_DIM = "#12472a"
ACCENT_SOFT = "#0c2618"
BORDER = "#1a1f1c"
DANGER = "#ef5350"
DANGER_SOFT = "#2a1414"
WARN = "#f5c542"
INFO = "#5aa7dd"
BTN_DARK = "#101312"
BTN_DARK_HOVER = "#171b19"


def _pick_font(candidates, fallback="Courier New"):
    try:
        families = set(tkfont.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in families:
            return name
    return fallback


MONO = "Courier New"   # substituído em tempo de execução por _init_fonts()
FONT = (MONO, 10)
FONT_BOLD = (MONO, 10, "bold")
FONT_SMALL = (MONO, 9)
FONT_TINY = (MONO, 8)
FONT_TITLE = (MONO, 13, "bold")
FONT_SECTION = (MONO, 10, "bold")


def _init_fonts():
    global MONO, FONT, FONT_BOLD, FONT_SMALL, FONT_TINY, FONT_TITLE, FONT_SECTION
    MONO = _pick_font(["Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono",
                        "Courier New"])
    FONT = (MONO, 10)
    FONT_BOLD = (MONO, 10, "bold")
    FONT_SMALL = (MONO, 9)
    FONT_TINY = (MONO, 8)
    FONT_TITLE = (MONO, 13, "bold")
    FONT_SECTION = (MONO, 10, "bold")


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


def fmt_brl(valor, casas=6):
    """Formata um valor no padrao monetario brasileiro (virgula decimal,
    ponto de milhar). Ex.: fmt_brl(1234.5) -> '1.234,50'"""
    s = f"{valor:,.2f}"
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def linha_pontilhada(rotulo, valor, largura=42):
    """Monta uma linha 'rotulo ..... valor', no estilo cupom fiscal."""
    espaco = largura - len(rotulo) - len(valor) - 2
    pontos = "." * max(3, espaco)
    return f"{rotulo} {pontos} {valor}"


# ============================================================ tooltip ===
class Tooltip:
    """Balão de descrição que aparece ao passar o mouse sobre um widget."""

    def __init__(self, widget, text, delay=350):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self.tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.attributes("-topmost", True)
        except Exception:
            pass
        tw.wm_geometry(f"+{x}+{y}")
        outer = tk.Frame(tw, bg=ACCENT)
        outer.pack()
        inner = tk.Frame(outer, bg="#000000")
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.text, justify="left", bg="#000000", fg=FG,
                 font=FONT_SMALL, wraplength=280, padx=10, pady=6).pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def tip(widget, text):
    Tooltip(widget, text)
    return widget


# ============================================================ ajuda de erros ===
def diagnosticar_erro(exc):
    """Traduz uma excecao tecnica de rede em (titulo assertivo, solucao sugerida)."""
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, PermissionError) or "permission" in low or "acesso negado" in low:
        return ("Sem permissão para usar essa porta.",
                "Portas abaixo de 1024 exigem privilégio de administrador. Use uma porta "
                "acima de 1024 (ex.: 9000) ou execute o simulador como administrador.")
    if "address already in use" in low or "only one usage" in low or "10048" in low:
        return ("Essa porta já está em uso.",
                "Feche outra instância do simulador (ou outro programa) que esteja usando "
                "essa porta, ou escolha uma porta diferente na Conexão de rede.")
    if isinstance(exc, socket.timeout) or "timed out" in low:
        return ("O gravador não respondeu a tempo.",
                "Confira o IP e a porta, se o gravador está ligado e na mesma rede, e se o "
                "modo de conexão dele é compatível (gravador em TCP_CLIENT → aqui use TCP "
                "Servidor; gravador em TCP → aqui use TCP Cliente).")
    if "refused" in low or "recusad" in low:
        return ("Conexão recusada pelo gravador.",
                "O IP está certo, mas nada está escutando nessa porta no gravador. Confira a "
                "porta configurada nele e se o modo de conexão bate com o escolhido aqui.")
    if "network is unreachable" in low or "no route to host" in low or "host is down" in low:
        return ("Rede inacessível.",
                "Esse IP não é alcançável a partir deste computador. Confira se os dois "
                "equipamentos estão na mesma rede/VLAN e se não há bloqueio de firewall.")
    if isinstance(exc, (UnicodeEncodeError, UnicodeDecodeError)) or "codec" in low:
        return ("Caractere incompatível com a codificação escolhida.",
                "Troque a Codificação para UTF-8, ou remova acentos e caracteres especiais "
                "do texto do cupom.")
    if "winerror 10061" in low:
        return ("Conexão recusada pelo gravador.",
                "Nada está escutando no IP/porta informados. Verifique a configuração de "
                "rede do gravador.")
    return (f"Falha na comunicação: {msg}",
            "Revise IP, porta e modo de conexão. Se persistir, confirme no manual do "
            "gravador qual modo (TCP servidor/cliente/UDP) ele espera.")


# ============================================================ widgets base ===
class ToggleSwitch(tk.Canvas):
    """Interruptor retangular (não pílula) — [ ON]/[OFF] com trilho reto,
    coerente com o resto da linguagem visual sem cantos arredondados."""

    def __init__(self, parent, command=None, value=False, width=46, height=20, bg=BG_PANEL):
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
        track_color = ACCENT_DIM if self.value else "#1c211e"
        border_color = ACCENT if self.value else BORDER
        self.create_rectangle(0, 0, self.width, self.height, fill=track_color,
                               outline=border_color, width=1)
        knob_w = self.width // 2 - 2
        x0 = self.width - knob_w - 2 if self.value else 2
        knob_color = ACCENT if self.value else FG_DIM
        self.create_rectangle(x0, 2, x0 + knob_w, self.height - 2, fill=knob_color,
                               outline=knob_color)
        label = "ON" if self.value else "OFF"
        lx = (self.width * 0.27) if self.value else (self.width * 0.73)
        self.create_text(lx, self.height / 2, text=label, fill=("#04140a" if self.value else FG_DIM),
                          font=(MONO, 7, "bold"))

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
    """Botão de cantos retos, com colchetes ao redor do texto para reforçar a
    leitura de 'comando executável', no estilo console."""
    label = f"[ {text} ]"
    if primary:
        bg, fg, hover, border = ACCENT, "#04140a", "#3dfb8c", ACCENT
    elif danger:
        bg, fg, hover, border = DANGER_SOFT, DANGER, "#3a1a1a", DANGER
    else:
        bg, fg, hover, border = BTN_DARK, FG, BTN_DARK_HOVER, BORDER
    btn = tk.Button(parent, text=label, command=command, bg=bg, fg=fg,
                     activebackground=hover, activeforeground=fg,
                     relief="flat", bd=0, padx=12, pady=7, font=FONT,
                     cursor="hand2", width=width,
                     highlightthickness=1, highlightbackground=border,
                     highlightcolor=border)
    btn.bind("<Enter>", lambda e: btn.config(bg=hover))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


def panel(parent, title, desc=None):
    """Painel plano (sem cantos arredondados, sem sombra): apenas um traço
    verde à esquerda do título e uma linha fina fechando o rodapé — visual
    de seção de arquivo de configuração, não de 'card' de dashboard."""
    wrap = tk.Frame(parent, bg=BG_PANEL, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=BORDER)
    head = tk.Frame(wrap, bg=BG_PANEL)
    head.pack(fill="x", padx=16, pady=(14, 4 if desc else 10))
    tk.Frame(head, bg=ACCENT, width=3, height=14).pack(side="left", padx=(0, 8))
    tk.Label(head, text=title.upper(), bg=BG_PANEL, fg=FG, font=FONT_SECTION).pack(side="left")
    if desc:
        drow = tk.Frame(wrap, bg=BG_PANEL)
        drow.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(drow, text=desc, bg=BG_PANEL, fg=FG_DIM, font=FONT_SMALL,
                 anchor="w", justify="left").pack(fill="x")
    body = tk.Frame(wrap, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    return wrap, body


def make_cmd_tile(parent, title, command):
    """Bloco clicável estilo 'comando de terminal': texto entre colchetes,
    borda fina que acende em verde ao passar o mouse."""
    tile = tk.Frame(parent, bg=BTN_DARK, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=BORDER, cursor="hand2")
    lbl = tk.Label(tile, text=f"[+] {title}", bg=BTN_DARK, fg=FG, font=FONT_SMALL,
                    anchor="w", padx=10, pady=9)
    lbl.pack(fill="both", expand=True)

    def on_enter(_e=None):
        tile.configure(highlightbackground=ACCENT, highlightcolor=ACCENT)
        lbl.configure(fg=ACCENT)

    def on_leave(_e=None):
        tile.configure(highlightbackground=BORDER, highlightcolor=BORDER)
        lbl.configure(fg=FG)

    for w in (tile, lbl):
        w.bind("<Enter>", on_enter)
        w.bind("<Leave>", on_leave)
        w.bind("<Button-1>", lambda e: command())
    return tile


# ============================================================ aplicacao ===
class PDVSimulator:
    def __init__(self, root):
        _init_fonts()
        self.root = root
        self.root.title("Simulador de PDV - Teste de Overlay (Intelbras)")
        self.root.configure(bg=BG)
        self.root.geometry("1240x820")
        self.root.minsize(1060, 680)

        self.sock = None
        self.conn = None
        self.conn_addr = None
        self.connected = False
        self.server_thread = None
        self.stop_flag = threading.Event()
        self.auto_thread = None
        self.auto_running = False
        self.send_lock = threading.Lock()

        self.store_name_var = tk.StringVar(value="LOJA TESTE INTELBRAS")
        self.store_cnpj_var = tk.StringVar(value="00.000.000/0001-00")
        self.min_delay_warn_var = tk.StringVar(value="600")

        self.stat_packets = 0
        self.stat_lines = 0
        self.stat_packets_var = tk.StringVar(value="0")
        self.stat_lines_var = tk.StringVar(value="0")
        self.stat_last_var = tk.StringVar(value="—")
        self._active_page = None

        self._setup_style()
        self._set_app_icon()
        self._build_ui()
        self._log("Simulador pronto. Configure a conexão e ative o Habilitar.")
        self._tick_clock()

    def _set_app_icon(self):
        base_dir = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        try:
            ico_path = os.path.join(base_dir, "icon.ico")
            png_path = os.path.join(base_dir, "icon.png")
            if os.name == "nt" and os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                self._icon_img = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    # --------------------------------------------------------------- estilo ---
    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, foreground=FG, font=FONT)
        style.configure("Dim.TLabel", background=BG_PANEL, foreground=FG_DIM, font=FONT_SMALL)
        style.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_FIELD,
                         foreground=FG, arrowcolor=FG_DIM, bordercolor=BORDER,
                         lightcolor=BORDER, darkcolor=BORDER, borderwidth=1, font=FONT)
        style.map("TCombobox", fieldbackground=[("readonly", BG_FIELD)],
                   selectbackground=[("readonly", BG_FIELD)],
                   selectforeground=[("readonly", FG)],
                   bordercolor=[("focus", ACCENT), ("active", ACCENT_DIM)],
                   lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)],
                   arrowcolor=[("focus", ACCENT)])
        style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG, insertcolor=ACCENT,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                         borderwidth=1, font=FONT)
        style.map("TEntry", bordercolor=[("focus", ACCENT)],
                   lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        style.configure("TSpinbox", fieldbackground=BG_FIELD, foreground=FG, arrowcolor=FG_DIM,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                         borderwidth=1, font=FONT)
        style.map("TSpinbox", bordercolor=[("focus", ACCENT)],
                   lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)],
                   arrowcolor=[("focus", ACCENT)])
        self.root.option_add("*TCombobox*Listbox.background", BG_FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.font", FONT)

        style.configure("Treeview", background=BG_LOG, fieldbackground=BG_LOG,
                         foreground=FG, borderwidth=0, rowheight=25, font=FONT_SMALL)
        style.map("Treeview", background=[("selected", ACCENT_SOFT)],
                   foreground=[("selected", ACCENT)])
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=FG_DIM,
                         font=FONT_BOLD, borderwidth=0, relief="flat")
        style.map("Treeview.Heading", background=[("active", BG_PANEL)])
        style.layout("Flat.Vertical.TScrollbar",
                      [('Vertical.Scrollbar.trough',
                        {'children': [('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})],
                         'sticky': 'ns'})])
        style.configure("Flat.Vertical.TScrollbar", background=BORDER, troughcolor=BG,
                         bordercolor=BG, relief="flat")
        style.map("Flat.Vertical.TScrollbar", background=[("active", FG_DIMMER)])

    # ------------------------------------------------------------- estrutura ---
    def _build_ui(self):
        self._build_titlebar()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_rail(body)

        pages_container = tk.Frame(body, bg=BG)
        pages_container.grid(row=0, column=1, sticky="nsew")
        pages_container.grid_columnconfigure(0, weight=1)
        pages_container.grid_rowconfigure(0, weight=1)

        self.pages = {}
        self.pages["Enviar Cupom"] = self._build_page_enviar(pages_container)
        self.pages["Log de Eventos"] = self._build_page_log(pages_container)
        self.pages["Configurações"] = self._build_page_config(pages_container)
        self.pages["Sobre"] = self._build_page_sobre(pages_container)
        for pg in self.pages.values():
            pg.grid(row=0, column=0, sticky="nsew")

        self._on_mode_change()
        self._show_page("Enviar Cupom")

    # ------------------------------------------------------------- titlebar ---
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=BG_RAIL, height=40)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=BG_RAIL)
        left.pack(side="left", padx=(14, 0))
        icon_c = tk.Canvas(left, width=20, height=20, bg=BG_RAIL, highlightthickness=0)
        icon_c.pack(side="left", pady=10, padx=(0, 10))
        icon_c.create_rectangle(1, 1, 19, 19, outline=ACCENT, width=1.5)
        icon_c.create_polygon(5, 6, 10, 10, 5, 14, 5, 12, 8, 10, 5, 8, fill=ACCENT, outline="")
        icon_c.create_rectangle(11, 13, 15, 14.5, fill=ACCENT, outline="")

        title_row = tk.Frame(left, bg=BG_RAIL)
        title_row.pack(side="left")
        tk.Label(title_row, text="simulador_pdv", bg=BG_RAIL, fg=FG, font=FONT_TITLE).pack(side="left")
        self.cursor_lbl = tk.Label(title_row, text="▌", bg=BG_RAIL, fg=ACCENT, font=FONT_TITLE)
        self.cursor_lbl.pack(side="left", padx=(2, 0))
        tk.Label(left, text="  overlay de teste · gravadores intelbras", bg=BG_RAIL,
                 fg=FG_DIM, font=FONT_TINY).pack(side="left", padx=(10, 0))

        right = tk.Frame(bar, bg=BG_RAIL)
        right.pack(side="right", padx=14)

        self.clock_var = tk.StringVar(value="--:--:--")
        tk.Label(right, textvariable=self.clock_var, bg=BG_RAIL, fg=FG_DIMMER,
                 font=FONT_SMALL).pack(side="right", padx=(14, 0))

        status_box = tk.Frame(right, bg="#000000", highlightthickness=1,
                               highlightbackground=BORDER, highlightcolor=BORDER)
        status_box.pack(side="right")
        inner = tk.Frame(status_box, bg="#000000")
        inner.pack(padx=10, pady=4)
        self.status_dot_lbl = tk.Label(inner, text="●", bg="#000000", fg=DANGER, font=FONT_SMALL)
        self.status_dot_lbl.pack(side="left", padx=(0, 6))
        self.status_var = tk.StringVar(value="OFFLINE")
        self.status_lbl = tk.Label(inner, textvariable=self.status_var, bg="#000000",
                                    fg=DANGER, font=FONT_BOLD)
        self.status_lbl.pack(side="left")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        self._blink_cursor()

    def _blink_cursor(self):
        try:
            cur = self.cursor_lbl.cget("text")
            self.cursor_lbl.configure(text=(" " if cur == "▌" else "▌"))
        except Exception:
            pass
        self.root.after(600, self._blink_cursor)

    def _tick_clock(self):
        self.clock_var.set(datetime.datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    # ------------------------------------------------------------- trilha lateral ---
    def _build_rail(self, parent):
        rail = tk.Frame(parent, bg=BG_RAIL, width=88)
        rail.grid(row=0, column=0, sticky="ns")
        rail.grid_propagate(False)
        tk.Frame(parent, bg=BORDER, width=1).grid(row=0, column=0, sticky="nse")

        chan_wrap = tk.Frame(rail, bg=BG_RAIL)
        chan_wrap.pack(fill="x", pady=(16, 0))
        channels = [
            ("Enviar Cupom", "01", "envio"),
            ("Log de Eventos", "02", "log"),
            ("Configurações", "03", "cfg"),
            ("Sobre", "04", "info"),
        ]
        self.nav_buttons = {}
        for name, code, sub in channels:
            self.nav_buttons[name] = self._make_channel_tile(chan_wrap, name, code, sub)

        foot = tk.Frame(rail, bg=BG_RAIL)
        foot.pack(side="bottom", fill="x", pady=14)
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(foot, text="intelbras", bg=BG_RAIL, fg=FG_DIM,
                 font=(MONO, 9, "bold")).pack()
        tk.Label(foot, text="v1.0.0", bg=BG_RAIL, fg=FG_DIMMER, font=FONT_TINY).pack(pady=(2, 0))

    def _make_channel_tile(self, parent, name, code, sub):
        cell = tk.Frame(parent, bg=BG_RAIL, cursor="hand2", width=88, height=64)
        cell.pack(fill="x")
        cell.pack_propagate(False)
        accent = tk.Frame(cell, bg=BG_RAIL, width=3)
        accent.pack(side="left", fill="y")
        inner = tk.Frame(cell, bg=BG_RAIL)
        inner.pack(side="left", fill="both", expand=True)
        code_lbl = tk.Label(inner, text=code, bg=BG_RAIL, fg=FG_DIM, font=(MONO, 13, "bold"))
        code_lbl.pack(pady=(12, 0))
        sub_lbl = tk.Label(inner, text=sub, bg=BG_RAIL, fg=FG_DIMMER, font=FONT_TINY)
        sub_lbl.pack()

        cell._accent = accent
        cell._recolor = [inner, code_lbl, sub_lbl]

        def on_click(_e=None):
            self._show_page(name)

        def on_enter(_e=None):
            if self._active_page != name:
                for w in (cell, inner, code_lbl, sub_lbl):
                    w.configure(bg=BTN_DARK_HOVER)
                accent.configure(bg=BTN_DARK_HOVER)

        def on_leave(_e=None):
            if self._active_page != name:
                for w in (cell, inner, code_lbl, sub_lbl):
                    w.configure(bg=BG_RAIL)
                accent.configure(bg=BG_RAIL)

        for w in (cell, inner, code_lbl, sub_lbl):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        tip(cell, name)
        return cell

    def _show_page(self, name):
        self._active_page = name
        for pname, frame in self.pages.items():
            if pname == name:
                frame.tkraise()
        for pname, btn in self.nav_buttons.items():
            active = pname == name
            bg = ACCENT_SOFT if active else BG_RAIL
            code_fg = ACCENT if active else FG_DIM
            sub_fg = ACCENT if active else FG_DIMMER
            btn.configure(bg=bg)
            btn._accent.configure(bg=ACCENT if active else BG_RAIL)
            inner, code_lbl, sub_lbl = btn._recolor
            inner.configure(bg=bg)
            code_lbl.configure(bg=bg, fg=code_fg)
            sub_lbl.configure(bg=bg, fg=sub_fg)

    # ------------------------------------------------------------- página: Enviar Cupom ---
    def _build_page_enviar(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=0)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        left_col = tk.Frame(outer, bg=BG, width=380)
        left_col.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left_col.grid_propagate(False)
        left_col.pack_propagate(False)

        right_col = tk.Frame(outer, bg=BG)
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_columnconfigure(0, weight=1)
        right_col.grid_rowconfigure(0, weight=1)

        # ---- Conexao ----
        conn_wrap, conn_frame = panel(
            left_col, "conexao_de_rede",
            desc="Escolha como o simulador conversa com o gravador: quem inicia a conexão, "
                 "em qual IP/porta, e como o texto é codificado.")
        conn_wrap.pack(fill="x", pady=(0, 10))

        top_row = tk.Frame(conn_frame, bg=BG_PANEL)
        top_row.pack(fill="x", pady=(0, 12))
        tk.Label(top_row, text="habilitar", bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")
        self.enable_toggle = ToggleSwitch(top_row, command=self._on_toggle_enable)
        self.enable_toggle.pack(side="left", padx=(14, 0))
        tip(self.enable_toggle, "Liga ou desliga a conexão com o gravador usando o modo, "
                                  "IP e porta configurados abaixo.")

        tk.Frame(conn_frame, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        grid = tk.Frame(conn_frame, bg=BG_PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        ttk.Label(grid, text="modo_de_conexao", style="Dim.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.mode_display_var = tk.StringVar(value=MODE_DISPLAY_LIST[0])
        self.mode_combo = ttk.Combobox(grid, textvariable=self.mode_display_var,
                                        values=MODE_DISPLAY_LIST, state="readonly")
        self.mode_combo.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 14))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())
        tip(self.mode_combo,
            "TCP Servidor: use quando o gravador está configurado como TCP_CLIENT (ele conecta "
            "aqui).\nTCP Cliente: use quando o gravador está configurado como TCP (ele espera "
            "conexão).\nUDP: envio sem conexão, mais simples porém sem confirmação de entrega.")

        self.ip_label = ttk.Label(grid, text="ip_de_escuta", style="Dim.TLabel")
        self.ip_label.grid(row=2, column=0, sticky="w")
        self.ip_var = tk.StringVar(value="0.0.0.0")
        ip_entry = ttk.Entry(grid, textvariable=self.ip_var, font=FONT)
        ip_entry.grid(row=3, column=0, sticky="we", pady=(2, 14), padx=(0, 6))
        tip(ip_entry, "No modo TCP Servidor, 0.0.0.0 escuta em todas as interfaces de rede "
                       "deste computador. Nos demais modos, informe o IP do gravador.")

        ttk.Label(grid, text="porta", style="Dim.TLabel").grid(row=2, column=1, sticky="w")
        self.port_var = tk.StringVar(value="9000")
        port_entry = ttk.Entry(grid, textvariable=self.port_var, font=FONT)
        port_entry.grid(row=3, column=1, sticky="we", pady=(2, 14))
        tip(port_entry, "Deve ser a mesma porta configurada na tela de overlay de PDV do "
                         "gravador. Prefira portas acima de 1024 para não precisar de "
                         "permissão de administrador.")

        ttk.Label(grid, text="codificacao", style="Dim.TLabel").grid(row=4, column=0, sticky="w")
        self.enc_var = tk.StringVar(value="Unicode (UTF-8)")
        enc_combo = ttk.Combobox(grid, textvariable=self.enc_var, values=list(ENCODINGS.keys()),
                                  state="readonly")
        enc_combo.grid(row=5, column=0, sticky="we", pady=(2, 0), padx=(0, 6))
        tip(enc_combo, "O guia técnico da Intelbras recomenda Unicode (UTF-8) no campo "
                        "'Converter' do gravador. Troque para Latin-1/ASCII apenas se notar "
                        "caracteres estranhos no overlay com UTF-8.")

        ttk.Label(grid, text="terminador", style="Dim.TLabel").grid(row=4, column=1, sticky="w")
        self.term_var = tk.StringVar(value="CRLF (\\r\\n)")
        term_combo = ttk.Combobox(grid, textvariable=self.term_var, values=list(TERMINATORS.keys()),
                                   state="readonly")
        term_combo.grid(row=5, column=1, sticky="we", pady=(2, 0))
        tip(term_combo, "Byte(s) que marcam o fim de cada linha para o gravador. CRLF é o mais "
                         "comum; troque se o overlay não estiver fechando as linhas corretamente.")

        # ---- Envio ----
        send_wrap, send_frame = panel(
            left_col, "envio",
            desc="Envie o cupom para o gravador, de uma vez ou linha a linha, e configure a "
                 "repetição automática.")
        send_wrap.pack(fill="x")

        btn_all = make_button(send_frame, "Enviar Tudo (1 pacote)", self._send_all, primary=True)
        btn_all.pack(fill="x")
        tip(btn_all, "Envia o cupom inteiro em um único pacote. Mais rápido, porém alguns "
                      "gravadores perdem dados nesse modo — veja 'Enviar Linha a Linha'.")
        btn_line = make_button(send_frame, "Enviar Linha a Linha", self._send_line_by_line)
        btn_line.pack(fill="x", pady=(8, 0))
        tip(btn_line, "Envia uma linha por vez, respeitando o atraso configurado abaixo. "
                       "Mais lento, porém mais confiável para gravadores que perdem dados "
                       "com pacotes grandes.")

        delay_row = tk.Frame(send_frame, bg=BG_PANEL)
        delay_row.pack(fill="x", pady=(14, 0))
        ttk.Label(delay_row, text="atraso_entre_linhas_ms", style="Dim.TLabel").pack(side="left")
        self.delay_var = tk.StringVar(value="700")
        delay_spin = ttk.Spinbox(delay_row, from_=0, to=5000, increment=50, textvariable=self.delay_var,
                                  width=6)
        delay_spin.pack(side="right")
        tip(delay_spin, "Tempo de espera entre cada linha enviada. Valores abaixo do limiar "
                         "configurado em Configurações costumam causar perda de dados.")
        self.delay_warn_var = tk.StringVar()
        tk.Label(send_frame, textvariable=self.delay_warn_var,
                 bg=BG_PANEL, fg=WARN, font=FONT_TINY, anchor="w").pack(fill="x", pady=(4, 0))
        self._update_delay_warning()
        self.min_delay_warn_var.trace_add("write", lambda *a: self._update_delay_warning())

        tk.Frame(send_frame, bg=BORDER, height=1).pack(fill="x", pady=(14, 12))

        auto_top = tk.Frame(send_frame, bg=BG_PANEL)
        auto_top.pack(fill="x")
        tk.Label(auto_top, text="repetir_automaticamente", bg=BG_PANEL, fg=FG, font=FONT).pack(side="left")
        self.auto_toggle = ToggleSwitch(auto_top, command=self._on_toggle_auto)
        self.auto_toggle.pack(side="right")
        tip(self.auto_toggle, "Gera e envia uma nova venda aleatória periodicamente.")

        auto_row = tk.Frame(send_frame, bg=BG_PANEL)
        auto_row.pack(fill="x", pady=(10, 0))
        ttk.Label(auto_row, text="a_cada", style="Dim.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value="10")
        ttk.Spinbox(auto_row, from_=1, to=3600, textvariable=self.interval_var, width=6).pack(side="left", padx=(6, 6))
        ttk.Label(auto_row, text="seg", style="Dim.TLabel").pack(side="left")

        auto_row2 = tk.Frame(send_frame, bg=BG_PANEL)
        auto_row2.pack(fill="x", pady=(8, 0))
        ttk.Label(auto_row2, text="enviando:", style="Dim.TLabel").pack(side="left")
        self.auto_send_mode_var = tk.StringVar(value="Linha a linha (recomendado)")
        auto_mode_combo = ttk.Combobox(auto_row2, textvariable=self.auto_send_mode_var,
                                        values=["Linha a linha (recomendado)", "Pacote único"],
                                        state="readonly")
        auto_mode_combo.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # ---- Conteudo a enviar ----
        sale_wrap, sale_frame = panel(
            right_col, "conteudo_a_enviar (recibo / cupom)",
            desc="Monte o texto manualmente com os blocos abaixo, ou gere uma venda aleatória "
                 "pronta para testar o overlay.")
        sale_wrap.grid(row=0, column=0, sticky="nsew")

        sinal_row = tk.Frame(sale_frame, bg=BG_PANEL)
        sinal_row.pack(fill="x", pady=(0, 12))
        ttk.Label(sinal_row, text="sinal_final_de_pdv", style="Dim.TLabel").pack(side="left")
        self.signal_var = tk.StringVar(value="Muito Obrigado!")
        signal_entry = ttk.Entry(sinal_row, textvariable=self.signal_var)
        signal_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tip(signal_entry, "Frase que marca o fim da venda para o Defense IA — precisa ser "
                            "idêntica à configurada no gravador (Configurações > Parâmetros > "
                            "Sinal final de PDV).")

        tiles_row = tk.Frame(sale_frame, bg=BG_PANEL)
        tiles_row.pack(fill="x", pady=(0, 14))
        tile_defs = [
            ("cabeçalho", self._insert_header, "Insere nome da loja, CNPJ e data/hora."),
            ("item", self._insert_item, "Insere um produto aleatório com quantidade e valor."),
            ("total", self._insert_total, "Insere a linha de total a pagar."),
            ("pagamento", self._insert_payment, "Insere a forma de pagamento."),
            ("rodapé", self._insert_footer, "Insere a mensagem de agradecimento final."),
            ("sinal final", self._insert_signal, "Insere o nome da loja + o Sinal final de PDV."),
        ]
        n_cols = 3
        for c in range(n_cols):
            tiles_row.grid_columnconfigure(c, weight=1, uniform="tiles")
        for i, (label, cmd, desc_tile) in enumerate(tile_defs):
            r, c = divmod(i, n_cols)
            t = make_cmd_tile(tiles_row, label, cmd)
            t.grid(row=r, column=c, sticky="nsew",
                   padx=(0 if c == 0 else 6, 0), pady=(0 if r == 0 else 6, 0))
            tip(t, desc_tile)

        gerar_row = tk.Frame(sale_frame, bg=BG_PANEL)
        gerar_row.pack(fill="x", pady=(0, 4))
        clear_btn = make_button(gerar_row, "Limpar", self._clear_text)
        clear_btn.pack(side="left")
        gerar_ref_btn = make_button(gerar_row, "Gerar (modelo NetAssist)", self._generate_netassist_sale)
        gerar_ref_btn.pack(side="right", padx=(8, 0))
        tip(gerar_ref_btn, "Monta a venda no formato exato do guia técnico POS/PDV da "
                             "Intelbras (testado com o NetAssist).")
        gerar_btn = make_button(gerar_row, "Gerar Venda Aleatória", self._generate_random_sale,
                                 primary=True)
        gerar_btn.pack(side="right")

        self.text = scrolledtext.ScrolledText(sale_frame, height=10, bg=BG_FIELD, fg=FG,
                                               insertbackground=ACCENT, font=FONT, wrap="word",
                                               borderwidth=1, relief="solid", highlightbackground=BORDER,
                                               highlightcolor=ACCENT, highlightthickness=1)
        self.text.pack(fill="both", expand=True)

        counter_row = tk.Frame(sale_frame, bg=BG_PANEL)
        counter_row.pack(fill="x", pady=(8, 0))
        self.counter_var = tk.StringVar(value="caracteres: 0  |  linhas: 0")
        tk.Label(counter_row, textvariable=self.counter_var, bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_TINY).pack(side="right")
        self.text.bind("<KeyRelease>", lambda e: self._update_counter())

        self._generate_random_sale()
        return page

    # ------------------------------------------------------------- página: Log ---
    def _build_page_log(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        log_wrap, log_frame = panel(
            outer, "log_de_eventos",
            desc="Cada conexão, envio e erro aparece aqui — erros vêm com uma sugestão de "
                 "solução, não só o código técnico.")
        log_wrap.pack(fill="both", expand=True)

        table_wrap = tk.Frame(log_frame, bg=BG_PANEL, highlightthickness=1,
                               highlightbackground=BORDER, highlightcolor=BORDER)
        table_wrap.pack(fill="both", expand=True)

        columns = ("hora", "tipo", "msg")
        self.log_tree = ttk.Treeview(table_wrap, columns=columns, show="headings")
        self.log_tree.heading("hora", text="hora")
        self.log_tree.heading("tipo", text="tipo")
        self.log_tree.heading("msg", text="mensagem")
        self.log_tree.column("hora", width=90, anchor="w", stretch=False)
        self.log_tree.column("tipo", width=110, anchor="w", stretch=False)
        self.log_tree.column("msg", anchor="w", stretch=True)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.log_tree.yview,
                             style="Flat.Vertical.TScrollbar")
        self.log_tree.configure(yscrollcommand=vsb.set)
        self.log_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.log_tree.tag_configure("enviado", foreground=ACCENT)
        self.log_tree.tag_configure("conectado", foreground=ACCENT)
        self.log_tree.tag_configure("erro", foreground=DANGER)
        self.log_tree.tag_configure("info", foreground=INFO)

        actions_row = tk.Frame(log_frame, bg=BG_PANEL)
        actions_row.pack(fill="x", pady=(10, 0))
        clear_btn = make_button(actions_row, "Limpar log", self._clear_log)
        clear_btn.pack(side="right")
        export_btn = make_button(actions_row, "Exportar", self._export_log)
        export_btn.pack(side="right", padx=(0, 8))

        footer = tk.Frame(log_frame, bg=BG_PANEL)
        footer.pack(fill="x", pady=(10, 0))
        tk.Frame(footer, bg=BORDER, height=1).pack(fill="x", pady=(0, 10))
        stats_row = tk.Frame(footer, bg=BG_PANEL)
        stats_row.pack(fill="x")
        self._stat_block(stats_row, "pacotes_enviados", self.stat_packets_var)
        self._stat_block(stats_row, "linhas_enviadas", self.stat_lines_var)
        self._stat_block(stats_row, "ultimo_envio", self.stat_last_var)

        return page

    def _stat_block(self, parent, label, var):
        block = tk.Frame(parent, bg=BG_PANEL)
        block.pack(side="left", padx=(0, 30))
        tk.Label(block, text=f"{label} ", bg=BG_PANEL, fg=FG_DIM, font=FONT_TINY).pack(side="left")
        tk.Label(block, textvariable=var, bg=BG_PANEL, fg=ACCENT, font=FONT_BOLD).pack(side="left")

    def _clear_log(self):
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)
        self.stat_packets = 0
        self.stat_lines = 0
        self.stat_packets_var.set("0")
        self.stat_lines_var.set("0")
        self.stat_last_var.set("—")

    def _export_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Arquivo de texto", "*.txt")],
            initialfile="log_simulador_pdv.txt", title="Exportar log")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for item in self.log_tree.get_children():
                    hora, tipo, msg = self.log_tree.item(item, "values")
                    f.write(f"[{hora}] {tipo}: {msg}\n")
            messagebox.showinfo("Exportar log", f"Log exportado para:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))

    # ------------------------------------------------------------- página: Config ---
    def _build_page_config(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        wrap, frame = panel(
            outer, "preferencias",
            desc="Valores padrão usados ao gerar cupons de teste e ao avisar sobre atrasos "
                 "de envio arriscados.")
        wrap.pack(fill="x", pady=(0, 10))

        grid = tk.Frame(frame, bg=BG_PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        ttk.Label(grid, text="nome_da_loja (padrão)", style="Dim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.store_name_var).grid(
            row=1, column=0, sticky="we", pady=(2, 14), padx=(0, 6))

        ttk.Label(grid, text="cnpj (padrão)", style="Dim.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(grid, textvariable=self.store_cnpj_var).grid(
            row=1, column=1, sticky="we", pady=(2, 14))

        ttk.Label(grid, text="aviso_de_atraso_minimo (ms)", style="Dim.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(grid, from_=0, to=5000, increment=50, textvariable=self.min_delay_warn_var,
                    width=10).grid(row=3, column=0, sticky="w", pady=(2, 4))

        restore_btn = make_button(frame, "Restaurar padrões", self._restore_defaults)
        restore_btn.pack(anchor="w", pady=(14, 0))

        info_wrap, info_frame = panel(
            outer, "privacidade",
            desc="Este simulador conversa apenas com o gravador na sua rede local — nenhum "
                 "dado é enviado para a Intelbras ou para qualquer serviço externo.")
        info_wrap.pack(fill="x")

        return page

    def _restore_defaults(self):
        self.store_name_var.set("LOJA TESTE INTELBRAS")
        self.store_cnpj_var.set("00.000.000/0001-00")
        self.min_delay_warn_var.set("600")

    # ------------------------------------------------------------- página: Sobre ---
    def _build_page_sobre(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        wrap, frame = panel(
            outer, "sobre_o_simulador_pdv",
            desc="Ferramenta interna de teste para o overlay de POS/PDV dos gravadores "
                 "Intelbras.")
        wrap.pack(fill="x", pady=(0, 10))

        texto = (
            "O Simulador PDV envia um cupom de venda de teste pela rede, do mesmo jeito que "
            "um PDV real faria, para validar se o gravador reconhece e sobrepõe corretamente "
            "as informações de venda no vídeo.\n\n"
            "Como escolher o modo de conexão (compare com a tela \"Modo de conexão\" do "
            "gravador):\n"
            "  gravador em TCP_CLIENT  ->  use TCP Servidor aqui\n"
            "  gravador em TCP         ->  use TCP Cliente aqui\n"
            "  gravador em UDP         ->  use UDP aqui\n\n"
            "Nenhum dado sai da rede local: a comunicação acontece direto entre este "
            "computador e o gravador."
        )
        tk.Label(frame, text=texto, bg=BG_PANEL, fg=FG, font=FONT, justify="left",
                 anchor="w", wraplength=760).pack(fill="x")

        tk.Frame(frame, bg=BORDER, height=1).pack(fill="x", pady=(16, 12))
        tk.Label(frame, text="simulador_pdv — versão 1.0.0", bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_SMALL).pack(anchor="w")
        tk.Label(frame, text="Desenvolvido internamente para testes de integração com "
                              "gravadores Intelbras.", bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_SMALL).pack(anchor="w", pady=(2, 0))

        return page

    def _update_counter(self):
        content = self.text.get("1.0", "end-1c")
        n_chars = len(content)
        n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        self.counter_var.set(f"caracteres: {n_chars}  |  linhas: {n_lines}")

    def _update_delay_warning(self):
        try:
            limiar = int(self.min_delay_warn_var.get())
        except ValueError:
            limiar = 600
        self.delay_warn_var.set(f"⚠ abaixo de ~{limiar}ms o gravador costuma perder dados")

    # ---------------------------------------------------------- helpers ---
    def _current_mode(self):
        return MODE_DISPLAY.get(self.mode_display_var.get(), "server")

    def _on_mode_change(self):
        mode = self._current_mode()
        if mode == "server":
            self.ip_label.config(text="ip_de_escuta")
        else:
            self.ip_label.config(text="ip_do_gravador (dvr)")

    def _log(self, msg):
        def do():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            low = msg.lower()
            if msg.startswith("⚠"):
                kind, tag = "erro", "erro"
                msg_clean = msg.lstrip("⚠ ").strip()
            elif msg.startswith("Enviado") or msg.startswith("Linha enviada"):
                kind, tag = "enviado", "enviado"
                msg_clean = msg
                self.stat_packets += 1 if "pacote" in low else 0
                self.stat_lines += 1 if "linha enviada" in low else 0
                self.stat_packets_var.set(str(self.stat_packets))
                self.stat_lines_var.set(str(self.stat_lines))
                self.stat_last_var.set(ts)
            elif "conectou" in low or msg.startswith("Conectado") or "escutando" in low:
                kind, tag = "conectado", "conectado"
                msg_clean = msg
            else:
                kind, tag = "info", "info"
                msg_clean = msg
            if hasattr(self, "log_tree"):
                self.log_tree.insert("", "end", values=(ts, kind, msg_clean), tags=(tag,))
                children = self.log_tree.get_children()
                if len(children) > 500:
                    self.log_tree.delete(children[0])
                self.log_tree.see(self.log_tree.get_children()[-1])
        self.root.after(0, do)

    def _set_status(self, text, ok):
        def do():
            self.status_var.set(text.upper())
            color = ACCENT if ok else DANGER
            self.status_lbl.configure(fg=color)
            self.status_dot_lbl.configure(fg=color)
        self.root.after(0, do)

    # ------------------------------------------------------- templates ---
    def _insert_header(self):
        self.text.insert("insert", f"{self.store_name_var.get() or 'LOJA TESTE INTELBRAS'}\n"
                          f"CNPJ {self.store_cnpj_var.get() or '00.000.000/0001-00'}\n"
                          f"{datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        self._update_counter()

    def _insert_item(self):
        nome, preco = random.choice(PRODUTOS)
        qtd = random.randint(1, 3)
        rotulo = f"{nome} {qtd}x{fmt_brl(preco)}"
        self.text.insert("insert", linha_pontilhada(rotulo, fmt_brl(qtd * preco)) + "\n")
        self._update_counter()

    def _insert_total(self):
        self.text.insert("insert", linha_pontilhada("TOTAL A PAGAR", fmt_brl(0)) + "\n")
        self._update_counter()

    def _insert_payment(self):
        self.text.insert("insert", random.choice([
            "FORMA DE PAGAMENTO: CARTAO DEBITO\n",
            "FORMA DE PAGAMENTO: CARTAO CREDITO\n",
            "FORMA DE PAGAMENTO: DINHEIRO\n",
            "FORMA DE PAGAMENTO: PIX\n",
        ]))
        self._update_counter()

    def _insert_footer(self):
        self.text.insert("insert", "OBRIGADO PELA PREFERENCIA\nVOLTE SEMPRE\n")
        self._update_counter()

    def _insert_signal(self):
        sinal = self.signal_var.get().strip() or "Muito Obrigado!"
        self.text.insert("insert", f"Mercado XXXXXX\n{sinal}\n")
        self._update_counter()

    def _clear_text(self):
        self.text.delete("1.0", "end")
        self._update_counter()

    def _build_netassist_sale_text(self):
        sep = "-" * 42
        sinal = self.signal_var.get().strip() or "Muito Obrigado!"
        agora = datetime.datetime.now()
        linhas = [sep, f"Caixa {random.randint(1, 20):04d} 01 {agora.strftime('%d/%m/%Y %H:%M:%S')}", sep]

        total = 0.0
        for _ in range(random.randint(2, 5)):
            nome, preco = random.choice(PRODUTOS)
            qtd = random.randint(1, 5)
            subtotal = preco * qtd
            total += subtotal
            linhas.append(f"{nome.title()} {fmt_brl(preco)} X {qtd} {fmt_brl(subtotal)}")
            linhas.append(sep)

        desconto = random.choice([0, 0, 0, 5.0, 10.0])
        recebido = round(total - desconto + random.choice([0, 0, 2, 5, 10]), 2)
        total_imp = round(total - desconto, 2)
        troco = round(max(0.0, recebido - total_imp), 2)

        linhas.append(f"TOTAL : {fmt_brl(total)}")
        linhas.append(f"RECEBIDO {fmt_brl(recebido)}")
        linhas.append(sep)
        if desconto:
            linhas.append(f"DESCONTO {fmt_brl(desconto)}")
            linhas.append(sep)
        linhas.append("Informacoes Adicionais")
        linhas.append("-----------")
        linhas.append(f"TOTAL (IMP) : {fmt_brl(total_imp)}")
        linhas.append(f"TROCO : {fmt_brl(troco)}")
        linhas.append(sep)
        linhas.append("Administrador Caixa Gabriel")
        linhas.append(sep)
        linhas.append("Mercado XXXXXX")
        linhas.append(sinal)
        return "\n".join(linhas) + "\n"

    def _generate_netassist_sale(self):
        self._clear_text()
        self.text.insert("1.0", self._build_netassist_sale_text())
        self._update_counter()

    def _generate_random_sale(self):
        self._clear_text()
        lines = []
        lines.append(self.store_name_var.get() or "LOJA TESTE INTELBRAS")
        lines.append(f"CNPJ {self.store_cnpj_var.get() or '00.000.000/0001-00'}")
        lines.append(datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        lines.append("-" * 32)
        n_itens = random.randint(2, 6)
        total = 0.0
        for _ in range(n_itens):
            nome, preco = random.choice(PRODUTOS)
            qtd = random.randint(1, 3)
            subtotal = qtd * preco
            total += subtotal
            rotulo = f"{nome} {qtd}x{fmt_brl(preco)}"
            lines.append(linha_pontilhada(rotulo, fmt_brl(subtotal)))
        lines.append("-" * 32)
        lines.append(linha_pontilhada("TOTAL A PAGAR", fmt_brl(total)))
        lines.append(random.choice([
            "FORMA DE PAGAMENTO: CARTAO DEBITO",
            "FORMA DE PAGAMENTO: CARTAO CREDITO",
            "FORMA DE PAGAMENTO: DINHEIRO",
            "FORMA DE PAGAMENTO: PIX",
        ]))
        lines.append("OBRIGADO PELA PREFERENCIA")
        self.text.insert("1.0", "\n".join(lines) + "\n")
        self._update_counter()

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
                titulo, solucao = diagnosticar_erro(e)
                self._log(f"⚠ {titulo} {solucao}")
                messagebox.showerror(titulo, solucao)
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
                            data = conn.recv(1, socket.MSG_PEEK)
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
            titulo, solucao = diagnosticar_erro(e)
            self._log(f"⚠ {titulo} {solucao}")
            self._set_status("Erro ao iniciar servidor", False)
            self.root.after(0, lambda: messagebox.showerror(titulo, solucao))
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
            titulo, solucao = diagnosticar_erro(e)
            self._log(f"⚠ {titulo} {solucao}")
            self._set_status("Falha ao conectar", False)
            self.root.after(0, lambda: messagebox.showerror(titulo, solucao))
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
            titulo, solucao = diagnosticar_erro(e)
            self._log(f"⚠ {titulo} {solucao}")
            return False

        try:
            with self.send_lock:
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
            titulo, solucao = diagnosticar_erro(e)
            self._log(f"⚠ {titulo} {solucao}")
            return False

    def _send_all(self):
        content = self.text.get("1.0", "end-1c")
        term = self._get_terminator()
        payload = content if content.endswith(term) or term == "" else content + term
        if self._raw_send(payload):
            self._log(f"Enviado 1 pacote ({len(payload)} caracteres).")

    def _send_line_by_line_sync(self):
        content = self.text.get("1.0", "end-1c")
        lines = content.split("\n")
        try:
            delay = max(0, int(self.delay_var.get())) / 1000.0
        except ValueError:
            delay = 0.7
        term = self._get_terminator()
        for line in lines:
            if not line.strip():
                continue
            ok = self._raw_send(line + term)
            if ok:
                self._log(f"Linha enviada: {line}")
            time.sleep(delay)
        self._log("Envio linha a linha concluído.")

    def _send_line_by_line(self):
        threading.Thread(target=self._send_line_by_line_sync, daemon=True).start()

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
            if self.auto_send_mode_var.get().startswith("Linha"):
                done = threading.Event()

                def worker():
                    self._send_line_by_line_sync()
                    done.set()

                self.root.after(0, lambda: threading.Thread(target=worker, daemon=True).start())
                done.wait(timeout=interval + 5)
            else:
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
