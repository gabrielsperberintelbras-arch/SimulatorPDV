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

import os
import sys
import socket
import threading
import random
import time
import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ----------------------------- Paleta visual (preto e verde vibrante, estilo Intelbras) -----------------------------
BG = "#0a0a0a"
BG_HEADER = "#0e0e0e"
BG_PANEL = "#161616"
BG_TILE = "#1b1b1b"
BG_TILE_HOVER = "#1f2b21"
BG_FIELD = "#0a0a0a"
BG_LOG = "#000000"
FG = "#f2f2f2"
FG_DIM = "#8f8f8f"
ACCENT = "#22e06a"          # verde vibrante, igual ao das referencias
ACCENT_DARK = "#149a4a"
ACCENT_SOFT = "#123321"
BORDER = "#272727"
DANGER = "#ef5350"
BTN_DARK = "#1e1e1e"
BTN_DARK_HOVER = "#292929"
CARD_RADIUS = 14

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 18, "bold")
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


def fmt_brl(valor, casas=6):
    """Formata um valor no padrao monetario brasileiro (virgula decimal,
    ponto de milhar), alinhado a direita em `casas` colunas antes da virgula.
    Ex.: fmt_brl(1234.5) -> '1.234,50'"""
    s = f"{valor:,.2f}"
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def linha_pontilhada(rotulo, valor, largura=42):
    """Monta uma linha 'rotulo ..... valor', no estilo cupom fiscal.
    Preenchimento com pontos em vez de espacos: no simulador (fonte
    monoespacada) qualquer um dos dois alinha, mas no overlay real do
    gravador a fonte costuma ser proporcional (cada letra com largura
    diferente) - ai espacos nao alinham nada, enquanto o olho ainda segue
    uma linha de pontos ate o valor mesmo sem alinhamento pixel-perfeito."""
    espaco = largura - len(rotulo) - len(valor) - 2
    pontos = "." * max(3, espaco)
    return f"{rotulo} {pontos} {valor}"


# ============================================================ tooltip ===
class Tooltip:
    """Balão de descrição estilo 'toast' (preto/verde) que aparece ao passar
    o mouse sobre um widget, com um pequeno atraso para não piscar à toa."""

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
        inner = tk.Frame(outer, bg=BG_PANEL)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.text, justify="left", bg=BG_PANEL, fg=FG,
                 font=FONT_SUB, wraplength=280, padx=10, pady=6).pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def tip(widget, text):
    """Atalho para anexar uma Tooltip a um widget."""
    Tooltip(widget, text)
    return widget


# ============================================================ ajuda de erros ===
def diagnosticar_erro(exc):
    """Traduz uma excecao tecnica de rede em (titulo assertivo, solucao sugerida),
    para o usuario nao precisar interpretar stacktrace."""
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
        self.hover = False
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = self.height / 2
        color = ACCENT if self.value else "#3a3a3a"
        if self.hover:
            # halo sutil ao passar o mouse, para dar sensacao de "vivo"
            glow = ACCENT_SOFT if not self.value else ACCENT
            self.create_oval(-2, -2, self.width + 2, self.height + 2, outline=glow, width=2)
        self.create_oval(0, 0, self.height, self.height, fill=color, outline=color)
        self.create_oval(self.width - self.height, 0, self.width, self.height, fill=color, outline=color)
        self.create_rectangle(r, 0, self.width - r, self.height, fill=color, outline=color)
        pad = 2
        knob_d = self.height - 2 * pad
        x0 = (self.width - self.height + pad) if self.value else pad
        self.create_oval(x0, pad, x0 + knob_d, pad + knob_d, fill="#ffffff", outline="#ffffff")

    def _on_enter(self, _e=None):
        self.hover = True
        self._draw()

    def _on_leave(self, _e=None):
        self.hover = False
        self._draw()

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


class RoundedCard(tk.Frame):
    """Cartao com cantos arredondados de verdade, desenhado em canvas (estilo dos
    cards do dashboard: fundo escuro, cantos suaves, sem bordas retas duras).
    A altura acompanha automaticamente o conteudo colocado em self.inner; a
    largura acompanha o espaco dado pelo pack/grid do pai (use fill='x' ou sticky='nsew')."""

    def __init__(self, parent, bg=BG_PANEL, radius=CARD_RADIUS, outer_bg=None):
        outer_bg = outer_bg or parent["bg"]
        super().__init__(parent, bg=outer_bg, highlightthickness=0)
        self.bg = bg
        self.radius = radius
        self.canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(2, 2, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_height)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

    def _sync_height(self, _event=None):
        h = self.inner.winfo_reqheight() + 4
        if int(self.canvas.cget("height") or 0) != h:
            self.canvas.configure(height=h)
        self._redraw()

    def _redraw(self):
        self.update_idletasks()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        self.canvas.delete("bg")
        r = min(self.radius, w // 2, h // 2)
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h,
               w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.canvas.create_polygon(pts, fill=self.bg, outline=self.bg, smooth=True, tags="bg")
        self.canvas.tag_lower("bg")
        self.canvas.coords(self._win, 2, 2)
        self.canvas.itemconfig(self._win, width=w - 4)


def section(parent, title, desc=None, icon=None):
    """Card arredondado com barra de destaque verde, titulo em maiusculas,
    icone opcional e, opcionalmente, uma linha de descricao."""
    card = RoundedCard(parent, bg=BG_PANEL, outer_bg=BG)
    head = tk.Frame(card.inner, bg=BG_PANEL)
    head.pack(fill="x", padx=18, pady=(16, 4 if desc else 8))
    tk.Frame(head, bg=ACCENT, width=4, height=16).pack(side="left", padx=(0, 8))
    if icon:
        tk.Label(head, text=icon, bg=BG_PANEL, fg=ACCENT, font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))
    tk.Label(head, text=title.upper(), bg=BG_PANEL, fg=ACCENT, font=FONT_SECTION).pack(side="left")
    if desc:
        desc_row = tk.Frame(card.inner, bg=BG_PANEL)
        desc_row.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(desc_row, text=desc, bg=BG_PANEL, fg=FG_DIM, font=FONT_SUB,
                 anchor="w", justify="left").pack(fill="x")
    body = tk.Frame(card.inner, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    return card, body


def make_tile(parent, title, command):
    """Tile clicavel no estilo dos cards do dashboard (titulo em negrito + linha fina
    embaixo, destaca em verde ao passar o mouse). Largura flexivel (definida pelo
    grid do pai via sticky='nsew'); apenas a altura e fixa, para nao transbordar
    do card quando ha varios tiles numa linha estreita."""
    tile = RoundedCard(parent, bg=BG_TILE, radius=10, outer_bg=BG_PANEL)
    tile.configure(height=58)
    tile.pack_propagate(False)
    inner = tile.inner
    lbl = tk.Label(inner, text=title, bg=BG_TILE, fg=FG, font=("Segoe UI", 9, "bold"),
                    anchor="w", wraplength=110, justify="left")
    lbl.pack(fill="x", padx=12, pady=(10, 4))
    underline = tk.Frame(inner, bg=FG_DIM, height=2, width=24)
    underline.pack(anchor="w", padx=12)

    widgets = [tile, tile.canvas, inner, lbl, underline]

    def on_enter(_e=None):
        tile.bg = BG_TILE_HOVER
        inner.configure(bg=BG_TILE_HOVER)
        lbl.configure(bg=BG_TILE_HOVER)
        underline.configure(bg=ACCENT)
        tile._redraw()

    def on_leave(_e=None):
        tile.bg = BG_TILE
        inner.configure(bg=BG_TILE)
        lbl.configure(bg=BG_TILE)
        underline.configure(bg=FG_DIM)
        tile._redraw()

    for w in widgets:
        w.configure(cursor="hand2") if hasattr(w, "configure") else None
        w.bind("<Enter>", on_enter)
        w.bind("<Leave>", on_leave)
        w.bind("<Button-1>", lambda e: command())

    return tile


# ============================================================ aplicacao ===
class PDVSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Simulador de PDV - Teste de Overlay (Intelbras)")
        self.root.configure(bg=BG)
        self.root.geometry("1180x800")
        self.root.minsize(1040, 680)

        self.sock = None
        self.conn = None
        self.conn_addr = None
        self.connected = False
        self.server_thread = None
        self.stop_flag = threading.Event()
        self.auto_thread = None
        self.auto_running = False
        self.send_lock = threading.Lock()

        # Preferencias configuraveis na pagina "Configuracoes"
        self.store_name_var = tk.StringVar(value="LOJA TESTE INTELBRAS")
        self.store_cnpj_var = tk.StringVar(value="00.000.000/0001-00")
        self.min_delay_warn_var = tk.StringVar(value="600")

        # Estatisticas do log
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
        self._pulse_status()

    def _set_app_icon(self):
        """Define o ícone da janela (barra de título/taskbar) a partir de
        icon.ico (Windows) ou icon.png (demais plataformas), se existirem ao
        lado do script. No .exe compilado, o ícone já vem embutido via
        --icon no PyInstaller, então essa chamada é só um reforço para quando
        o script roda direto com 'python pdv_simulator.py'."""
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
            pass  # ausencia do arquivo de icone nunca deve travar o simulador

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
                         foreground=FG, arrowcolor=FG, bordercolor=BORDER,
                         lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
        style.map("TCombobox", fieldbackground=[("readonly", BG_FIELD)],
                   selectbackground=[("readonly", BG_FIELD)],
                   selectforeground=[("readonly", FG)],
                   bordercolor=[("focus", ACCENT), ("active", ACCENT_DARK)],
                   lightcolor=[("focus", ACCENT)],
                   darkcolor=[("focus", ACCENT)],
                   arrowcolor=[("focus", ACCENT)])
        style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG, insertcolor=FG,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
        style.map("TEntry",
                   bordercolor=[("focus", ACCENT)],
                   lightcolor=[("focus", ACCENT)],
                   darkcolor=[("focus", ACCENT)])
        style.configure("TSpinbox", fieldbackground=BG_FIELD, foreground=FG, arrowcolor=FG,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
        style.map("TSpinbox",
                   bordercolor=[("focus", ACCENT)],
                   lightcolor=[("focus", ACCENT)],
                   darkcolor=[("focus", ACCENT)],
                   arrowcolor=[("focus", ACCENT)])
        self.root.option_add("*TCombobox*Listbox.background", BG_FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        # Treeview (tabela do log) e Scrollbar com tema escuro
        style.configure("Treeview", background=BG_LOG, fieldbackground=BG_LOG,
                         foreground=FG, borderwidth=0, rowheight=27, font=FONT)
        style.map("Treeview", background=[("selected", ACCENT_SOFT)],
                   foreground=[("selected", FG)])
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=FG_DIM,
                         font=FONT_BOLD, borderwidth=0, relief="flat")
        style.map("Treeview.Heading", background=[("active", BG_PANEL)])
        style.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
                         bordercolor=BG, arrowcolor=FG_DIM, relief="flat", arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", BTN_DARK_HOVER)])

    # ---------------------------------------------------------------- header ---
    def _build_logo_mark(self, parent, size=40):
        """Desenha, em vetor (canvas), a mesma marca do ícone do app: um
        quadrado preto com borda verde e um prompt '>_' — assim o cabeçalho
        sempre exibe a marca corretamente, mesmo sem o arquivo de ícone."""
        c = tk.Canvas(parent, width=size, height=size, bg=BG_HEADER, highlightthickness=0)
        pad = 3
        c.create_rectangle(pad, pad, size - pad, size - pad, outline=ACCENT, width=2,
                            fill=BG)
        cx, cy = size * 0.42, size * 0.5
        s = size * 0.16
        c.create_polygon(cx - s, cy - s, cx + s * 0.4, cy, cx - s, cy + s,
                          cx - s * 0.4, cy + s, cx + s * 0.9, cy, cx - s * 0.4, cy - s,
                          fill=ACCENT, outline="")
        c.create_rectangle(cx + s * 0.3, cy + s * 0.55, cx + s * 1.7, cy + s * 0.85,
                            fill=ACCENT, outline="")
        return c

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG_HEADER, height=76)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=BG_HEADER)
        title_box.pack(side="left", padx=(20, 0), pady=12)
        self._build_logo_mark(title_box).pack(side="left", padx=(0, 12))
        text_box = tk.Frame(title_box, bg=BG_HEADER)
        text_box.pack(side="left")
        title_row = tk.Frame(text_box, bg=BG_HEADER)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="simulador", bg=BG_HEADER, fg=FG, font=FONT_TITLE).pack(side="left")
        tk.Label(title_row, text="pdv", bg=BG_HEADER, fg=ACCENT, font=FONT_TITLE).pack(side="left")
        tk.Label(text_box, text="Overlay de teste compatível com gravadores Intelbras",
                 bg=BG_HEADER, fg=FG_DIM, font=FONT_SUB).pack(anchor="w")

        status_pill = RoundedCard(header, bg=BG_PANEL, radius=16, outer_bg=BG_HEADER)
        status_pill.configure(width=290, height=34)
        status_pill.pack_propagate(False)
        status_pill.pack(side="right", padx=24)
        status_box = status_pill.inner
        status_box.pack(fill="both", expand=True)
        inner_pad = tk.Frame(status_box, bg=BG_PANEL)
        inner_pad.place(relx=0.5, rely=0.5, anchor="center")
        self.status_dot = tk.Canvas(inner_pad, width=10, height=10, bg=BG_PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self._dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=DANGER, outline=DANGER)
        self.status_var = tk.StringVar(value="DESCONECTADO")
        self.status_lbl = tk.Label(inner_pad, textvariable=self.status_var, bg=BG_PANEL,
                                    fg=DANGER, font=FONT_BOLD)
        self.status_lbl.pack(side="left")

        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x")

    # ------------------------------------------------------------------- ui ---
    def _build_ui(self):
        self._build_header()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_sidebar(body)

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

    # ------------------------------------------------------- navegação ---
    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=BG_HEADER, width=224)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        tk.Frame(parent, bg=BORDER, width=1).grid(row=0, column=0, sticky="nse")

        nav_wrap = tk.Frame(sidebar, bg=BG_HEADER)
        nav_wrap.pack(fill="x", pady=(20, 0), padx=12)
        nav_items = [
            ("Enviar Cupom", "⇪"),
            ("Log de Eventos", "🗒"),
            ("Configurações", "⚙"),
            ("Sobre", "ℹ"),
        ]
        self.nav_buttons = {}
        for name, icon in nav_items:
            self.nav_buttons[name] = self._make_nav_button(nav_wrap, name, icon)

        foot = tk.Frame(sidebar, bg=BG_HEADER)
        foot.pack(side="bottom", fill="x", padx=16, pady=18)
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x", pady=(0, 12))
        tk.Label(foot, text="intelbras", bg=BG_HEADER, fg=FG,
                 font=("Segoe UI", 13, "bold", "italic")).pack(anchor="w")
        tk.Label(foot, text="Tecnologia que conecta.", bg=BG_HEADER, fg=FG_DIM,
                 font=FONT_SUB).pack(anchor="w", pady=(2, 8))
        tk.Label(foot, text="Simulador PDV v1.0.0", bg=BG_HEADER, fg="#5a5a5a",
                 font=("Segoe UI", 8)).pack(anchor="w")

    def _make_nav_button(self, parent, name, icon):
        row = tk.Frame(parent, bg=BG_HEADER, cursor="hand2")
        row.pack(fill="x", pady=3)
        accent = tk.Frame(row, bg=BG_HEADER, width=3)
        accent.pack(side="left", fill="y")
        content = tk.Frame(row, bg=BG_HEADER)
        content.pack(side="left", fill="both", expand=True, padx=(11, 6), pady=9)
        icon_lbl = tk.Label(content, text=icon, bg=BG_HEADER, fg=FG_DIM, font=("Segoe UI", 11))
        icon_lbl.pack(side="left", padx=(0, 10))
        text_lbl = tk.Label(content, text=name, bg=BG_HEADER, fg=FG_DIM, font=FONT)
        text_lbl.pack(side="left")

        row._accent = accent
        row._recolor_widgets = [content, icon_lbl, text_lbl]

        def on_click(_e=None):
            self._show_page(name)

        def on_enter(_e=None):
            if self._active_page != name:
                for w in [row] + row._recolor_widgets:
                    w.configure(bg=BG_TILE_HOVER)
                accent.configure(bg=BG_TILE_HOVER)

        def on_leave(_e=None):
            if self._active_page != name:
                for w in [row] + row._recolor_widgets:
                    w.configure(bg=BG_HEADER)
                accent.configure(bg=BG_HEADER)

        for w in [row, content, icon_lbl, text_lbl]:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        return row

    def _show_page(self, name):
        self._active_page = name
        for pname, frame in self.pages.items():
            if pname == name:
                frame.tkraise()
        for pname, btn in self.nav_buttons.items():
            active = pname == name
            bg = ACCENT_SOFT if active else BG_HEADER
            fgcolor = ACCENT if active else FG_DIM
            btn.configure(bg=bg)
            btn._accent.configure(bg=ACCENT if active else BG_HEADER)
            for w in btn._recolor_widgets:
                w.configure(bg=bg)
                try:
                    w.configure(fg=fgcolor)
                except tk.TclError:
                    pass

    # ------------------------------------------------------- página: Enviar Cupom ---
    def _build_page_enviar(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=0)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        left_col = tk.Frame(outer, bg=BG, width=400)
        left_col.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        left_col.grid_propagate(False)
        left_col.pack_propagate(False)

        right_col = tk.Frame(outer, bg=BG)
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_columnconfigure(0, weight=1)
        right_col.grid_rowconfigure(0, weight=1)

        # ---- Conexao ----
        conn_wrap, conn_frame = section(
            left_col, "Conexão de rede", icon="🔌",
            desc="Escolha como o simulador conversa com o gravador Intelbras: quem inicia a "
                 "conexão, em qual IP/porta, e como o texto é codificado.")
        conn_wrap.pack(fill="x", pady=(0, 12))


        top_row = tk.Frame(conn_frame, bg=BG_PANEL)
        top_row.pack(fill="x", pady=(0, 12))
        tk.Label(top_row, text="Habilitar", bg=BG_PANEL, fg=FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.enable_toggle = ToggleSwitch(top_row, command=self._on_toggle_enable)
        self.enable_toggle.pack(side="left", padx=(14, 0))
        tip(self.enable_toggle, "Liga ou desliga a conexão com o gravador usando o modo, "
                                  "IP e porta configurados abaixo.")

        tk.Frame(conn_frame, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        grid = tk.Frame(conn_frame, bg=BG_PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        ttk.Label(grid, text="Modo de conexão", style="Dim.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.mode_display_var = tk.StringVar(value=MODE_DISPLAY_LIST[0])
        self.mode_combo = ttk.Combobox(grid, textvariable=self.mode_display_var,
                                        values=MODE_DISPLAY_LIST, state="readonly")
        self.mode_combo.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 14))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())
        tip(self.mode_combo,
            "TCP Servidor: use quando o gravador está configurado como TCP_CLIENT (ele conecta "
            "aqui).\nTCP Cliente: use quando o gravador está configurado como TCP (ele espera "
            "conexão).\nUDP: envio sem conexão, mais simples porém sem confirmação de entrega.")

        self.ip_label = ttk.Label(grid, text="IP de escuta", style="Dim.TLabel")
        self.ip_label.grid(row=2, column=0, sticky="w")
        self.ip_var = tk.StringVar(value="0.0.0.0")
        ip_entry = ttk.Entry(grid, textvariable=self.ip_var, font=FONT_MONO)
        ip_entry.grid(row=3, column=0, sticky="we", pady=(2, 14), padx=(0, 6))
        tip(ip_entry, "No modo TCP Servidor, 0.0.0.0 escuta em todas as interfaces de rede "
                       "deste computador. Nos demais modos, informe o IP do gravador.")

        ttk.Label(grid, text="Porta", style="Dim.TLabel").grid(row=2, column=1, sticky="w")
        self.port_var = tk.StringVar(value="9000")
        port_entry = ttk.Entry(grid, textvariable=self.port_var, font=FONT_MONO)
        port_entry.grid(row=3, column=1, sticky="we", pady=(2, 14))
        tip(port_entry, "Deve ser a mesma porta configurada na tela de overlay de PDV do "
                         "gravador. Prefira portas acima de 1024 para não precisar de "
                         "permissão de administrador.")

        ttk.Label(grid, text="Codificação", style="Dim.TLabel").grid(row=4, column=0, sticky="w")
        self.enc_var = tk.StringVar(value="Unicode (UTF-8)")
        enc_combo = ttk.Combobox(grid, textvariable=self.enc_var, values=list(ENCODINGS.keys()),
                                  state="readonly")
        enc_combo.grid(row=5, column=0, sticky="we", pady=(2, 0), padx=(0, 6))
        tip(enc_combo, "O guia técnico da Intelbras recomenda Unicode (UTF-8) no campo "
                        "'Converter' do gravador — é a opção documentada oficialmente. Troque "
                        "para Latin-1/ASCII apenas se notar caracteres estranhos no overlay "
                        "com UTF-8.")

        ttk.Label(grid, text="Terminador", style="Dim.TLabel").grid(row=4, column=1, sticky="w")
        self.term_var = tk.StringVar(value="CRLF (\\r\\n)")
        term_combo = ttk.Combobox(grid, textvariable=self.term_var, values=list(TERMINATORS.keys()),
                                   state="readonly")
        term_combo.grid(row=5, column=1, sticky="we", pady=(2, 0))
        tip(term_combo, "Byte(s) que marcam o fim de cada linha para o gravador. CRLF é o mais "
                         "comum em protocolos seriais adaptados para rede; troque se o overlay "
                         "não estiver fechando as linhas corretamente.")

        # ---- Envio (mesma coluna, abaixo da conexao) ----
        send_wrap, send_frame = section(
            left_col, "Envio", icon="📤",
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
        ttk.Label(delay_row, text="Atraso entre linhas (ms)", style="Dim.TLabel").pack(side="left")
        self.delay_var = tk.StringVar(value="700")
        delay_spin = ttk.Spinbox(delay_row, from_=0, to=5000, increment=50, textvariable=self.delay_var,
                                  width=6)
        delay_spin.pack(side="right")
        tip(delay_spin, "Tempo de espera entre cada linha enviada. Valores abaixo do limiar "
                         "configurado em Configurações costumam causar perda de dados em "
                         "alguns gravadores.")
        self.delay_warn_var = tk.StringVar()
        tk.Label(send_frame, textvariable=self.delay_warn_var,
                 bg=BG_PANEL, fg="#f5c542", font=FONT_SUB, anchor="w").pack(fill="x", pady=(4, 0))
        self._update_delay_warning()
        self.min_delay_warn_var.trace_add("write", lambda *a: self._update_delay_warning())

        tk.Frame(send_frame, bg=BORDER, height=1).pack(fill="x", pady=(14, 12))

        auto_top = tk.Frame(send_frame, bg=BG_PANEL)
        auto_top.pack(fill="x")
        tk.Label(auto_top, text="Repetir automaticamente", bg=BG_PANEL, fg=FG, font=FONT).pack(side="left")
        self.auto_toggle = ToggleSwitch(auto_top, command=self._on_toggle_auto)
        self.auto_toggle.pack(side="right")
        tip(self.auto_toggle, "Gera e envia uma nova venda aleatória periodicamente, sem "
                                "precisar clicar nos botões de envio a cada vez.")

        auto_row = tk.Frame(send_frame, bg=BG_PANEL)
        auto_row.pack(fill="x", pady=(10, 0))
        ttk.Label(auto_row, text="a cada", style="Dim.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value="10")
        ttk.Spinbox(auto_row, from_=1, to=3600, textvariable=self.interval_var, width=6).pack(side="left", padx=(6, 6))
        ttk.Label(auto_row, text="seg", style="Dim.TLabel").pack(side="left")

        auto_row2 = tk.Frame(send_frame, bg=BG_PANEL)
        auto_row2.pack(fill="x", pady=(8, 0))
        ttk.Label(auto_row2, text="Enviando:", style="Dim.TLabel").pack(side="left")
        self.auto_send_mode_var = tk.StringVar(value="Linha a linha (recomendado)")
        auto_mode_combo = ttk.Combobox(auto_row2, textvariable=self.auto_send_mode_var,
                                        values=["Linha a linha (recomendado)", "Pacote único"],
                                        state="readonly")
        auto_mode_combo.pack(side="left", padx=(8, 0), fill="x", expand=True)
        tip(auto_mode_combo, "Linha a linha evita a perda de dados relatada em pacote único; "
                               "use Pacote único só se o seu gravador aceitar bem esse formato.")

        # ---- Composicao da venda (coluna direita, topo) ----
        sale_wrap, sale_frame = section(
            right_col, "Conteúdo a enviar (recibo / cupom)", icon="🧾",
            desc="Monte o texto do cupom manualmente com os blocos abaixo, ou gere uma venda "
                 "aleatória pronta para testar o overlay.")
        sale_wrap.grid(row=0, column=0, sticky="nsew", pady=(0, 12))

        sinal_row = tk.Frame(sale_frame, bg=BG_PANEL)
        sinal_row.pack(fill="x", pady=(0, 12))
        ttk.Label(sinal_row, text="Sinal final de PDV", style="Dim.TLabel").pack(side="left")
        self.signal_var = tk.StringVar(value="Muito Obrigado!")
        signal_entry = ttk.Entry(sinal_row, textvariable=self.signal_var)
        signal_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tip(signal_entry, "Frase que marca o fim da venda para o Defense IA (Configurações > "
                            "Parâmetros > Sinal final de PDV no gravador precisa ter exatamente "
                            "essa mesma frase). Sem ela bater, o software não sabe quando a "
                            "análise dos itens deve começar.")

        tiles_row = tk.Frame(sale_frame, bg=BG_PANEL)
        tiles_row.pack(fill="x", pady=(0, 14))
        tile_defs = [
            ("+ Cabeçalho", self._insert_header, "Insere nome da loja, CNPJ e data/hora."),
            ("+ Item", self._insert_item, "Insere um produto aleatório com quantidade e valor."),
            ("+ Total", self._insert_total, "Insere a linha de total a pagar."),
            ("+ Pagamento", self._insert_payment, "Insere a forma de pagamento (cartão, dinheiro, PIX)."),
            ("+ Rodapé", self._insert_footer, "Insere a mensagem de agradecimento final."),
            ("+ Sinal final", self._insert_signal, "Insere o nome da loja + o Sinal final de "
                                                     "PDV configurado acima (usado pelo Defense "
                                                     "IA para saber que a venda terminou)."),
            ("Limpar tudo", self._clear_text, "Apaga todo o texto do cupom."),
        ]
        n_cols = 3
        for c in range(n_cols):
            tiles_row.grid_columnconfigure(c, weight=1, uniform="tiles")
        for i, (label, cmd, desc_tile) in enumerate(tile_defs):
            r, c = divmod(i, n_cols)
            tile = make_tile(tiles_row, label, cmd)
            tile.grid(row=r, column=c, sticky="nsew",
                      padx=(0 if c == 0 else 6, 0), pady=(0 if r == 0 else 6, 0))
            tip(tile, desc_tile)

        gerar_row = tk.Frame(sale_frame, bg=BG_PANEL)
        gerar_row.pack(fill="x", pady=(0, 4))
        gerar_ref_btn = make_button(gerar_row, "Gerar (modelo Intelbras/NetAssist)",
                                     self._generate_netassist_sale)
        gerar_ref_btn.pack(side="right", padx=(8, 0))
        tip(gerar_ref_btn, "Monta a venda no formato exato do guia técnico POS/PDV da "
                             "Intelbras (linhas separadas por traços, 'TOTAL :', 'DESCONTO', "
                             "'TROCO', 'Administrador Caixa' e o Sinal final de PDV) — útil se "
                             "seu Defense IA está configurado no perfil 'General' com esses "
                             "rótulos.")
        gerar_btn = make_button(gerar_row, "Gerar Venda Aleatória", self._generate_random_sale,
                                 primary=True)
        gerar_btn.pack(side="right")
        tip(gerar_btn, "Substitui o cupom atual por uma venda completa e aleatória "
                        "(cabeçalho, 2 a 6 itens, total e pagamento, com líder de pontos — "
                        "mais legível em overlays de fonte proporcional).")

        self.text = scrolledtext.ScrolledText(sale_frame, height=10, bg=BG_FIELD, fg=FG,
                                               insertbackground=FG, font=FONT_MONO, wrap="word",
                                               borderwidth=1, relief="solid", highlightbackground=BORDER,
                                               highlightcolor=ACCENT, highlightthickness=1)
        self.text.pack(fill="both", expand=True)

        counter_row = tk.Frame(sale_frame, bg=BG_PANEL)
        counter_row.pack(fill="x", pady=(8, 0))
        self.counter_var = tk.StringVar(value="Caracteres: 0  |  Linhas: 0")
        tk.Label(counter_row, textvariable=self.counter_var, bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_SUB).pack(side="right")
        self.text.bind("<KeyRelease>", lambda e: self._update_counter())

        self._generate_random_sale()

        return page

    # ------------------------------------------------------- página: Log de Eventos ---
    def _build_page_log(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        log_wrap, log_frame = section(
            outer, "Log de eventos", icon="📋",
            desc="Cada conexão, envio e erro aparece aqui — erros vêm com uma sugestão de "
                 "solução, não só o código técnico.")
        log_wrap.pack(fill="both", expand=True)

        table_wrap = tk.Frame(log_frame, bg=BG_PANEL)
        table_wrap.pack(fill="both", expand=True)

        columns = ("hora", "tipo", "msg")
        self.log_tree = ttk.Treeview(table_wrap, columns=columns, show="headings")
        self.log_tree.heading("hora", text="Hora")
        self.log_tree.heading("tipo", text="Tipo")
        self.log_tree.heading("msg", text="Mensagem")
        self.log_tree.column("hora", width=90, anchor="w", stretch=False)
        self.log_tree.column("tipo", width=110, anchor="w", stretch=False)
        self.log_tree.column("msg", anchor="w", stretch=True)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=vsb.set)
        self.log_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.log_tree.tag_configure("enviado", foreground="#63d98a")
        self.log_tree.tag_configure("conectado", foreground="#63d98a")
        self.log_tree.tag_configure("erro", foreground=DANGER)
        self.log_tree.tag_configure("info", foreground="#6aa9e0")

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
        self._stat_block(stats_row, "📎", "Pacotes enviados:", self.stat_packets_var)
        self._stat_block(stats_row, "📃", "Linhas enviadas:", self.stat_lines_var)
        self._stat_block(stats_row, "🕒", "Último envio:", self.stat_last_var)

        return page

    def _stat_block(self, parent, icon, label, var):
        block = tk.Frame(parent, bg=BG_PANEL)
        block.pack(side="left", padx=(0, 26))
        tk.Label(block, text=icon, bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        tk.Label(block, text=label, bg=BG_PANEL, fg=FG_DIM, font=FONT_SUB).pack(side="left", padx=(0, 4))
        tk.Label(block, textvariable=var, bg=BG_PANEL, fg=FG, font=FONT_BOLD).pack(side="left")

    def _clear_log(self):
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)
        self.stat_packets = 0
        self.stat_lines = 0
        self.stat_packets_var.set("0")
        self.stat_lines_var.set("0")
        self.stat_last_var.set("—")

    def _export_log(self):
        from tkinter import filedialog
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

    # ------------------------------------------------------- página: Configurações ---
    def _build_page_config(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        wrap, frame = section(
            outer, "Preferências", icon="⚙",
            desc="Valores padrão usados ao gerar cupons de teste e ao avisar sobre atrasos "
                 "de envio arriscados.")
        wrap.pack(fill="x", pady=(0, 12))

        grid = tk.Frame(frame, bg=BG_PANEL)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        ttk.Label(grid, text="Nome da loja (padrão)", style="Dim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.store_name_var).grid(
            row=1, column=0, sticky="we", pady=(2, 14), padx=(0, 6))

        ttk.Label(grid, text="CNPJ (padrão)", style="Dim.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(grid, textvariable=self.store_cnpj_var).grid(
            row=1, column=1, sticky="we", pady=(2, 14))

        ttk.Label(grid, text="Aviso de atraso mínimo (ms)", style="Dim.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(grid, from_=0, to=5000, increment=50, textvariable=self.min_delay_warn_var,
                    width=10).grid(row=3, column=0, sticky="w", pady=(2, 4))

        restore_btn = make_button(frame, "Restaurar padrões", self._restore_defaults)
        restore_btn.pack(anchor="w", pady=(14, 0))

        info_wrap, info_frame = section(
            outer, "Privacidade", icon="🔒",
            desc="Este simulador conversa apenas com o gravador na sua rede local — nenhum "
                 "dado é enviado para a Intelbras ou para qualquer serviço externo.")
        info_wrap.pack(fill="x")

        return page

    def _restore_defaults(self):
        self.store_name_var.set("LOJA TESTE INTELBRAS")
        self.store_cnpj_var.set("00.000.000/0001-00")
        self.min_delay_warn_var.set("600")

    # ------------------------------------------------------- página: Sobre ---
    def _build_page_sobre(self, parent):
        page = tk.Frame(parent, bg=BG)
        outer = tk.Frame(page, bg=BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        wrap, frame = section(
            outer, "Sobre o Simulador PDV", icon="ℹ",
            desc="Ferramenta interna de teste para o overlay de POS/PDV dos gravadores "
                 "Intelbras.")
        wrap.pack(fill="x", pady=(0, 12))

        texto = (
            "O Simulador PDV envia um cupom de venda de teste pela rede, do mesmo jeito que "
            "um PDV real faria, para validar se o gravador reconhece e sobrepõe corretamente "
            "as informações de venda no vídeo.\n\n"
            "Como escolher o modo de conexão (compare com a tela \"Modo de conexão\" do "
            "gravador):\n"
            "•  Gravador em TCP_CLIENT  →  use TCP Servidor aqui (o simulador espera o "
            "gravador conectar).\n"
            "•  Gravador em TCP  →  use TCP Cliente aqui (o simulador conecta no gravador).\n"
            "•  Gravador em UDP  →  use UDP aqui.\n\n"
            "Nenhum dado sai da rede local: a comunicação acontece direto entre este "
            "computador e o gravador."
        )
        tk.Label(frame, text=texto, bg=BG_PANEL, fg=FG, font=FONT, justify="left",
                 anchor="w", wraplength=760).pack(fill="x")

        tk.Frame(frame, bg=BORDER, height=1).pack(fill="x", pady=(16, 12))
        tk.Label(frame, text="Simulador PDV — versão 1.0.0", bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_SUB).pack(anchor="w")
        tk.Label(frame, text="Desenvolvido internamente para testes de integração com "
                              "gravadores Intelbras.", bg=BG_PANEL, fg=FG_DIM,
                 font=FONT_SUB).pack(anchor="w", pady=(2, 0))

        return page

    def _update_counter(self):
        content = self.text.get("1.0", "end-1c")
        n_chars = len(content)
        n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        self.counter_var.set(f"Caracteres: {n_chars}  |  Linhas: {n_lines}")

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
            self.ip_label.config(text="IP de escuta")
        else:
            self.ip_label.config(text="IP do gravador (DVR)")

    def _log(self, msg):
        def do():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            low = msg.lower()
            if msg.startswith("⚠"):
                kind, tag = "Erro", "erro"
                msg_clean = msg.lstrip("⚠ ").strip()
            elif msg.startswith("Enviado") or msg.startswith("Linha enviada"):
                kind, tag = "Enviado", "enviado"
                msg_clean = msg
                self.stat_packets += 1 if "pacote" in low else 0
                self.stat_lines += 1 if "linha enviada" in low else 0
                self.stat_packets_var.set(str(self.stat_packets))
                self.stat_lines_var.set(str(self.stat_lines))
                self.stat_last_var.set(ts)
            elif "conectou" in low or msg.startswith("Conectado") or "escutando" in low:
                kind, tag = "Conectado", "conectado"
                msg_clean = msg
            else:
                kind, tag = "Info", "info"
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
            self.status_lbl.configure(foreground=color)
            self.status_dot.itemconfig(self._dot_id, fill=color, outline=color)
        self.root.after(0, do)

    def _pulse_status(self):
        """Faz o ponto de status 'respirar' suavemente quando conectado, para
        a interface parecer viva em vez de estatica."""
        try:
            if self.connected:
                self._pulse_on = not getattr(self, "_pulse_on", False)
                color = ACCENT if self._pulse_on else ACCENT_DARK
                self.status_dot.itemconfig(self._dot_id, fill=color, outline=color)
        except Exception:
            pass
        self.root.after(650, self._pulse_status)

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
        """Insere o par 'nome da loja + Sinal final de PDV' — no guia da Intelbras
        é exatamente essa frase final que o Defense IA usa para saber que os
        itens da venda terminaram e a análise pode começar."""
        sinal = self.signal_var.get().strip() or "Muito Obrigado!"
        self.text.insert("insert", f"Mercado XXXXXX\n{sinal}\n")
        self._update_counter()

    def _clear_text(self):
        self.text.delete("1.0", "end")
        self._update_counter()

    def _build_netassist_sale_text(self):
        """Monta uma venda no formato exato do guia técnico POS/PDV da Intelbras
        (exemplo testado com o NetAssist): linhas separadas por traços, rótulos
        'TOTAL :', 'DESCONTO', 'Informacoes Adicionais', 'TOTAL (IMP) :', 'TROCO :',
        'Administrador Caixa <nome>' e o Sinal final de PDV configurado acima."""
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
                            # MSG_PEEK: apenas espia se ha bytes/desconexao, sem
                            # consumir dados que o gravador porventura envie de volta.
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
        """Envia o conteudo linha a linha, bloqueando ate terminar. Chamar
        sempre de uma thread separada (nunca da thread principal da UI)."""
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
                # Envio linha a linha (com atraso) e mais confiavel para o
                # gravador: envia e so segue o loop apos o envio terminar.
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
