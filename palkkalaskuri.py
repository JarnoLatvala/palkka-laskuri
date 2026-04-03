"""
Palkkalaskuri – ICS-pohjainen työvuoropalkanlaskuri
Finnish shift salary calculator with ICS calendar import
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timezone, timedelta
import re
import os

# ── Color palette ──────────────────────────────────────────────────────────────
BG       = "#0f1117"
BG2      = "#181c27"
BG3      = "#1e2333"
ACCENT   = "#4fd1c5"   # teal
ACCENT2  = "#f6ad55"   # amber
RED      = "#fc8181"
GREEN    = "#68d391"
TEXT     = "#e2e8f0"
TEXT_DIM = "#718096"
BORDER   = "#2d3748"


# ── ICS parser ─────────────────────────────────────────────────────────────────
def parse_ics(content: str):
    """Return list of (summary, start_utc, end_utc) from ICS content."""
    events = []
    in_event = False
    summary = start = end = None

    for line in content.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            summary = start = end = None
        elif line == "END:VEVENT" and in_event:
            if start and end:
                events.append((summary or "", start, end))
            in_event = False
        elif in_event:
            if line.startswith("SUMMARY:"):
                summary = line[8:]
            elif line.startswith("DTSTART:"):
                start = _parse_dt(line[8:])
            elif line.startswith("DTEND:"):
                end = _parse_dt(line[6:])
    return events


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ")
        return dt.replace(tzinfo=timezone.utc)
    if "T" in s:
        return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)


# ── Shift analysis ─────────────────────────────────────────────────────────────
EVENING_START = 18   # 18:00 local
EVENING_END   = 23   # 23:00 local
NIGHT_START   = 23   # 23:00 local
NIGHT_END     = 6    # 06:00 local (next day)

LOCAL_OFFSET = timedelta(hours=3)   # Finland UTC+3 (EEST); adjust if needed


def _to_local(dt: datetime) -> datetime:
    return dt + LOCAL_OFFSET


def minutes_in_ranges(start_utc: datetime, end_utc: datetime):
    """
    Returns (normal_min, evening_min, night_min) for a shift.
    Evening  18-23, night 23-06.
    A minute counts as the HIGHEST category (night > evening > normal).
    """
    total = int((end_utc - start_utc).total_seconds() // 60)
    night_min = evening_min = 0

    cursor = start_utc
    step = timedelta(minutes=1)
    # For speed, iterate in 15-min blocks
    block = timedelta(minutes=15)
    cursor = start_utc
    while cursor < end_utc:
        blk_end = min(cursor + block, end_utc)
        blk_mins = int((blk_end - cursor).total_seconds() // 60)
        local_h = _to_local(cursor).hour
        if local_h >= NIGHT_START or local_h < NIGHT_END:
            night_min += blk_mins
        elif local_h >= EVENING_START:
            evening_min += blk_mins
        cursor = blk_end

    normal_min = total - evening_min - night_min
    return max(normal_min, 0), evening_min, night_min


def is_sunday(start_utc: datetime) -> bool:
    return _to_local(start_utc).weekday() == 6   # 6 = Sunday


# ── Main application ────────────────────────────────────────────────────────────
class PalkkalaskuriApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Palkkalaskuri")
        self.geometry("920x780")
        self.configure(bg=BG)
        self.resizable(True, True)

        self.events = []          # parsed ICS events
        self.result = {}          # last calculation result

        self._build_styles()
        self._build_ui()

    # ── Styles ─────────────────────────────────────────────────────────────────
    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame",       background=BG)
        style.configure("Card.TFrame",  background=BG2, relief="flat")
        style.configure("TLabel",       background=BG,  foreground=TEXT,
                        font=("Courier New", 10))
        style.configure("Card.TLabel",  background=BG2, foreground=TEXT,
                        font=("Courier New", 10))
        style.configure("Head.TLabel",  background=BG,  foreground=ACCENT,
                        font=("Courier New", 13, "bold"))
        style.configure("Sub.TLabel",   background=BG2, foreground=TEXT_DIM,
                        font=("Courier New", 9))
        style.configure("TEntry",
                        fieldbackground=BG3, foreground=TEXT,
                        insertcolor=ACCENT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER,
                        font=("Courier New", 10))
        style.configure("Accent.TButton",
                        background=ACCENT, foreground=BG,
                        font=("Courier New", 10, "bold"),
                        borderwidth=0, padding=8)
        style.map("Accent.TButton",
                  background=[("active", "#38b2ac"), ("pressed", "#2c7a7b")])
        style.configure("TScrollbar",
                        background=BG3, troughcolor=BG2,
                        bordercolor=BORDER, arrowcolor=TEXT_DIM)

    # ── UI layout ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="◈ PALKKALASKURI", bg=BG, fg=ACCENT,
                 font=("Courier New", 18, "bold")).pack(side="left")
        tk.Label(hdr, text="ICS-pohjainen työvuoropalkanlaskuri",
                 bg=BG, fg=TEXT_DIM, font=("Courier New", 9)).pack(side="left", padx=12)

        # Two-column body
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        body.columnconfigure(0, weight=1, minsize=340)
        body.columnconfigure(1, weight=1, minsize=340)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

    # ── Left panel ─────────────────────────────────────────────────────────────
    def _build_left(self, parent):
        left = tk.Frame(parent, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # ICS section
        self._section(left, "01 · KALENTERI")
        cal_card = self._card(left)

        self.file_label = tk.Label(cal_card, text="Ei tiedostoa valittu",
                                   bg=BG2, fg=TEXT_DIM,
                                   font=("Courier New", 9), wraplength=280, justify="left")
        self.file_label.pack(anchor="w", padx=12, pady=(10, 4))

        btn_row = tk.Frame(cal_card, bg=BG2)
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        self._btn(btn_row, "Valitse .ics-tiedosto", self._load_ics).pack(side="left")
        self._btn(btn_row, "Tyhjennä", self._clear_ics, dim=True).pack(side="left", padx=(8, 0))

        self.event_count = tk.Label(cal_card, text="", bg=BG2, fg=ACCENT,
                                    font=("Courier New", 9, "bold"))
        self.event_count.pack(anchor="w", padx=12, pady=(0, 8))

        # Wage section
        self._section(left, "02 · PERUSPALKKA")
        wage_card = self._card(left)
        self._row(wage_card, "Tuntipalkka (€/h)", "hourly_wage", "12.50")
        self._row(wage_card, "UTC-offset (h, FI kesä=+3)", "utc_offset", "3")

        # Bonuses section
        self._section(left, "03 · LISÄT (% tuntipalkasta)")
        bonus_card = self._card(left)
        self._row(bonus_card, "Iltalisä  (18–23)",      "evening_pct", "15")
        self._row(bonus_card, "Yölisä    (23–06)",       "night_pct",   "30")
        self._row(bonus_card, "Sunnuntailisä (100% = kaksinkertainen)", "sunday_pct",  "100")

        # Deductions section
        self._section(left, "04 · VÄHENNYKSET (%)")
        ded_card = self._card(left)
        self._row(ded_card, "Vero",                        "tax_pct",   "22")
        self._row(ded_card, "Työttömyysvakuutusmaksu",     "unemp_pct", "1.50")
        self._row(ded_card, "Työeläkemaksu (TyEL)",        "pension_pct","7.15")

        # Calculate button
        tk.Frame(left, bg=BG, height=12).pack()
        self._btn(left, "⟳  LASKE PALKKA", self._calculate,
                  accent=True, fullwidth=True).pack(fill="x")

    # ── Right panel ────────────────────────────────────────────────────────────
    def _build_right(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self._section(right, "05 · TULOKSET")

        result_card = self._card(right)
        result_card.pack_configure(fill="both", expand=True)

        # Summary numbers
        nums = tk.Frame(result_card, bg=BG2)
        nums.pack(fill="x", padx=12, pady=12)
        nums.columnconfigure(0, weight=1)
        nums.columnconfigure(1, weight=1)

        def stat(parent, label, attr, color=TEXT):
            f = tk.Frame(parent, bg=BG3, padx=10, pady=8)
            tk.Label(f, text=label, bg=BG3, fg=TEXT_DIM,
                     font=("Courier New", 8)).pack(anchor="w")
            lbl = tk.Label(f, text="—", bg=BG3, fg=color,
                           font=("Courier New", 14, "bold"))
            lbl.pack(anchor="w")
            setattr(self, attr, lbl)
            return f

        stat(nums, "Bruttopalkka",   "lbl_gross",  ACCENT ).grid(row=0,column=0,sticky="ew",padx=(0,4),pady=2)
        stat(nums, "Nettopalkka",    "lbl_net",    GREEN  ).grid(row=0,column=1,sticky="ew",padx=(4,0),pady=2)
        stat(nums, "Tunnit yhteensä","lbl_hours",  TEXT   ).grid(row=1,column=0,sticky="ew",padx=(0,4),pady=2)
        stat(nums, "Vähennykset yht","lbl_deductions",RED ).grid(row=1,column=1,sticky="ew",padx=(4,0),pady=2)

        # Breakdown table
        self._section(right, "06 · ERITTELY", spacing=False)
        table_card = self._card(right)
        table_card.pack_configure(fill="both", expand=True)

        cols = ("Päivämäärä","Vuoro","Tunnit","Brutto","Lisät","Sunnuntai")
        self.tree = ttk.Treeview(table_card, columns=cols, show="headings",
                                  height=12)
        widths = [95, 130, 55, 70, 60, 70]
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")

        style = ttk.Style()
        style.configure("Treeview",
                        background=BG3, foreground=TEXT,
                        fieldbackground=BG3, rowheight=22,
                        font=("Courier New", 8))
        style.configure("Treeview.Heading",
                        background=BG2, foreground=ACCENT,
                        font=("Courier New", 8, "bold"))
        style.map("Treeview",
                  background=[("selected", "#2d3a50")],
                  foreground=[("selected", ACCENT)])

        sb = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8, padx=(0, 8))

    # ── Helper widgets ─────────────────────────────────────────────────────────
    def _section(self, parent, title, spacing=True):
        if spacing:
            tk.Frame(parent, bg=BG, height=10).pack()
        tk.Label(parent, text=title, bg=BG, fg=ACCENT2,
                 font=("Courier New", 9, "bold")).pack(anchor="w")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))

    def _card(self, parent):
        f = tk.Frame(parent, bg=BG2, bd=0, relief="flat",
                     highlightbackground=BORDER, highlightthickness=1)
        f.pack(fill="x", pady=(0, 2))
        return f

    def _row(self, card, label, key, default):
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=12, pady=3)
        tk.Label(row, text=label, bg=BG2, fg=TEXT_DIM,
                 font=("Courier New", 9), width=32, anchor="w").pack(side="left")
        var = tk.StringVar(value=default)
        setattr(self, f"var_{key}", var)
        e = tk.Entry(row, textvariable=var, width=9,
                     bg=BG3, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", bd=4,
                     font=("Courier New", 10))
        e.pack(side="right")

    def _btn(self, parent, text, cmd, accent=False, dim=False, fullwidth=False):
        fg  = BG   if accent else (TEXT_DIM if dim else TEXT)
        bg  = ACCENT if accent else BG3
        abg = "#38b2ac" if accent else BORDER
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                      relief="flat", bd=0, padx=12, pady=6,
                      font=("Courier New", 9, "bold" if accent else "normal"),
                      cursor="hand2")
        return b

    # ── Logic ──────────────────────────────────────────────────────────────────
    def _load_ics(self):
        path = filedialog.askopenfilename(
            title="Valitse ICS-kalenteri",
            filetypes=[("iCalendar", "*.ics"), ("Kaikki tiedostot", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.events = parse_ics(content)
            self.file_label.config(text=os.path.basename(path), fg=TEXT)
            self.event_count.config(
                text=f"✓  {len(self.events)} tapahtumaa löydetty")
        except Exception as e:
            messagebox.showerror("Virhe", f"Tiedostoa ei voitu lukea:\n{e}")

    def _clear_ics(self):
        self.events = []
        self.file_label.config(text="Ei tiedostoa valittu", fg=TEXT_DIM)
        self.event_count.config(text="")
        for row in self.tree.get_children():
            self.tree.delete(row)
        for lbl in (self.lbl_gross, self.lbl_net, self.lbl_hours, self.lbl_deductions):
            lbl.config(text="—")

    def _get(self, key, default=0.0):
        try:
            return float(getattr(self, f"var_{key}").get().replace(",", "."))
        except ValueError:
            return default

    def _calculate(self):
        if not self.events:
            messagebox.showwarning("Ei dataa", "Lataa ensin .ics-kalenteri.")
            return

        global LOCAL_OFFSET
        offset_h = self._get("utc_offset", 3)
        LOCAL_OFFSET = timedelta(hours=offset_h)

        hourly     = self._get("hourly_wage", 12.5)
        ev_pct     = self._get("evening_pct", 15) / 100
        ni_pct     = self._get("night_pct",   30) / 100
        su_pct     = self._get("sunday_pct", 100) / 100
        tax_pct    = self._get("tax_pct",     22) / 100
        unemp_pct  = self._get("unemp_pct",  1.5) / 100
        pension_pct= self._get("pension_pct",7.15)/ 100

        for row in self.tree.get_children():
            self.tree.delete(row)

        total_gross = 0.0
        total_mins  = 0

        for summary, start, end in sorted(self.events, key=lambda x: x[1]):
            mins_total = int((end - start).total_seconds() // 60)
            normal_m, evening_m, night_m = minutes_in_ranges(start, end)
            sunday = is_sunday(start)

            base    = (mins_total / 60) * hourly
            ev_add  = (evening_m  / 60) * hourly * ev_pct
            ni_add  = (night_m    / 60) * hourly * ni_pct
            su_add  = base * su_pct if sunday else 0.0
            gross   = base + ev_add + ni_add + su_add

            total_gross += gross
            total_mins  += mins_total

            date_str = _to_local(start).strftime("%d.%m.%Y")
            h_str    = f"{mins_total//60}h {mins_total%60:02d}min"
            adds_str = f"+{ev_add+ni_add:.2f}€"
            su_str   = f"+{su_add:.2f}€" if sunday else "—"

            tag = "sunday" if sunday else ""
            self.tree.insert("", "end",
                             values=(date_str, summary, h_str,
                                     f"{gross:.2f}€", adds_str, su_str),
                             tags=(tag,))

        self.tree.tag_configure("sunday", foreground=ACCENT2)

        deductions = total_gross * (tax_pct + unemp_pct + pension_pct)
        net        = total_gross - deductions
        hours_dec  = total_mins / 60

        self.lbl_gross.config(text=f"{total_gross:.2f} €")
        self.lbl_net.config(text=f"{net:.2f} €")
        self.lbl_hours.config(text=f"{hours_dec:.1f} h")
        self.lbl_deductions.config(text=f"-{deductions:.2f} €")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = PalkkalaskuriApp()
    app.mainloop()