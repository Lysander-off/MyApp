import json, os, csv
from datetime import datetime
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.dropdown import DropDown
from kivy.uix.slider import Slider
from kivy.graphics import Line, Color, Rectangle
from kivy.properties import NumericProperty, StringProperty

from plyer import fingerprint

DEFAULT_NECESSITY_MAP = {
    "nourriture": 100,
    "logement": 100,
    "matériel artistique": 80,
    "transport": 70,
    "loisir": 30,
}

def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def parse_date(date_str):
    return datetime.strptime(date_str, "%d/%m/%Y %H:%M")

class GraphWidget(Widget):
    def draw_graph(self, balances):
        self.canvas.clear()
        if not balances:
            return
        max_val = max(max(balances), 1)
        min_val = min(min(balances), 0)
        width = max(self.width - 40, 40)
        height = max(self.height - 40, 40)
        step_x = width / max(len(balances) - 1, 1)
        scale_y = height / (max_val - min_val) if max_val != min_val else 1

        points = []
        for i, val in enumerate(balances):
            x = 20 + i * step_x
            y = 20 + (val - min_val) * scale_y
            points.extend([x, y])

        with self.canvas:
            Color(0.95, 0.95, 0.95, 1)
            Rectangle(pos=self.pos, size=self.size)
            Color(0, 0, 0, 1)
            Line(points=[20, 20, 20, 20 + height], width=1)
            Line(points=[20, 20, 20 + width, 20], width=1)
            Color(0.2, 0.6, 1, 1)
            Line(points=points, width=2)
            Color(1, 0, 0, 1)
            for i in range(0, len(points), 2):
                Line(circle=(points[i], points[i + 1], 4), width=1)

class BudgetManager(BoxLayout):
    balance = NumericProperty(0)
    history = []
    current_city_filter = None
    current_reason_filter = None
    settings = {
        "ceil_day": 0.0,
        "ceil_week": 0.0,
        "ceil_month": 0.0,
        "pin_code": "0000",
        "necessity_map": DEFAULT_NECESSITY_MAP.copy()
    }
    unlock_status = StringProperty("locked")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = 10
        self.spacing = 10

        self.load_data()
        self.load_settings()

        # --- Zone saisie ---
        input_layout = GridLayout(cols=2, row_force_default=True, row_default_height=50,
                                  spacing=5, size_hint_y=None, height=160)
        input_layout.add_widget(Label(text="Montant (€):"))
        self.amount_input = TextInput(multiline=False, input_filter="float")
        input_layout.add_widget(self.amount_input)

        input_layout.add_widget(Label(text="Motif:"))
        self.reason_input = TextInput(multiline=False, hint_text="ex: nourriture, transport…")
        input_layout.add_widget(self.reason_input)

        input_layout.add_widget(Label(text="Ville:"))
        self.city_input = TextInput(multiline=False, hint_text="ex: Paris, Lyon…")
        input_layout.add_widget(self.city_input)

        self.add_widget(input_layout)

        # --- Filtres ---
        self.city_filter_spinner = Spinner(text="Toutes les villes", values=self.get_city_list(), size_hint_y=None, height=50)
        self.city_filter_spinner.bind(text=self.on_city_filter)
        self.add_widget(self.city_filter_spinner)

        self.reason_filter_spinner = Spinner(text="Tous les motifs", values=self.get_reason_list(), size_hint_y=None, height=50)
        self.reason_filter_spinner.bind(text=self.on_reason_filter)
        self.add_widget(self.reason_filter_spinner)

        # --- Menu déroulant ---
        dropdown = DropDown()
        actions = [
            ("Ajouter Gain", self.add_income),
            ("Ajouter Dépense", self.add_expense),
            ("Réinitialiser", self.reset_budget),
            ("Exporter CSV", self.export_csv),
            ("Compte rendu", self.show_report),
            ("Paramètres", self.open_settings)
        ]
        for text, func in actions:
            btn = Button(text=text, size_hint_y=None, height=44)
            btn.bind(on_release=lambda btn, f=func: (f(btn), dropdown.dismiss()))
            dropdown.add_widget(btn)

        mainbutton = Button(text='Menu', size_hint_y=None, height=50)
        mainbutton.bind(on_release=dropdown.open)
        self.add_widget(mainbutton)

        # --- Solde ---
        self.balance_label = Label(text=f"Solde restant: {self.balance:.2f} €", font_size=24, size_hint_y=None, height=50)
        self.add_widget(self.balance_label)

        # --- Graphique ---
        self.graph = GraphWidget(size_hint_y=0.6)
        self.add_widget(self.graph)
        self.update_graph()
        self.bind(size=self.update_graph)

        # --- Déverrouillage ---
        self.request_unlock()

    # --- Fonctions utilitaires ---
    def get_city_list(self):
        cities = set(h["city"] for h in self.history if h.get("city"))
        return ["Toutes les villes"] + sorted(cities)

    def get_reason_list(self):
        reasons = set(h["reason"] for h in self.history if h.get("reason"))
        return ["Tous les motifs"] + sorted(reasons)

    def on_city_filter(self, spinner, text):
        self.current_city_filter = None if text == "Toutes les villes" else text
        self.update_graph()

    def on_reason_filter(self, spinner, text):
        self.current_reason_filter = None if text == "Tous les motifs" else text
        self.update_graph()

    def calculate_necessity(self, amount, reason):
        key = (reason or "").strip().lower()
        return int(self.settings.get("necessity_map", {}).get(key, 50))

    # --- Sauvegarde / Chargement ---
    def save_data(self):
        self.history = self.history or []
        data = {"balance": self.balance, "history": self.history}
        path = os.path.join(App.get_running_app().user_data_dir, "budget_data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load_data(self):
        path = os.path.join(App.get_running_app().user_data_dir, "budget_data.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except:
                    data = {"balance": 0, "history": []}
            self.balance = data.get("balance", 0)
            self.history = data.get("history", [])

    def save_settings(self):
        path = os.path.join(App.get_running_app().user_data_dir, "budget_settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False)

    def load_settings(self):
        path = os.path.join(App.get_running_app().user_data_dir, "budget_settings.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    s = json.load(f)
                except:
                    s = {}
            self.settings.update(s or {})
            if "necessity_map" not in self.settings:
                self.settings["necessity_map"] = DEFAULT_NECESSITY_MAP.copy()

    # --- Déverrouillage empreinte ---
    def request_unlock(self):
        def callback(success):
            if success:
                self.unlock_status = "unlocked"
                self.alert("✅ Déverrouillé", "Empreinte reconnue")
            else:
                self.unlock_with_pin()
        try:
            fingerprint.authenticate(callback)
        except:
            self.unlock_with_pin()

    def unlock_with_pin(self):
        content = BoxLayout(orientation="vertical", padding=10, spacing=10)
        label = Label(text="Entrez le PIN fallback:")
        pin_input = TextInput(multiline=False, password=True)
        btn = Button(text="Valider")
        content.add_widget(label)
        content.add_widget(pin_input)
        content.add_widget(btn)
        popup = Popup(title="Sécurité", content=content, size_hint=(0.7, 0.4))

        def check_pin(instance):
            if pin_input.text.strip() == self.settings.get("pin_code", "0000"):
                self.unlock_status = "unlocked"
                popup.dismiss()
                self.alert("✅ Déverrouillé", "PIN correct")
            else:
                label.text = "❌ Mauvais code, réessayez"

        btn.bind(on_release=check_pin)
        popup.open()

    # --- Transactions ---
    def safe_float(self, value):
        try:
            return float(value)
        except:
            return 0.0

    def add_transaction(self, amount, reason, city):
        if self.unlock_status != "unlocked":
            self.alert("🔒 Verrouillé", "Déverrouille d'abord")
            return
        if amount == 0:
            return
        date = now_str()
        necessity = self.calculate_necessity(amount, reason)
        self.history.append({"amount": amount, "reason": reason or "", "city": city or "", "date": date, "necessity": necessity})
        self.balance += amount
        if hasattr(self, "city_filter_spinner"):
            self.city_filter_spinner.values = self.get_city_list()
        if hasattr(self, "reason_filter_spinner"):
            self.reason_filter_spinner.values = self.get_reason_list()
        self.update_graph()
        self.save_data()
        self.amount_input.text = ""
        self.reason_input.text = ""
        self.city_input.text = ""

    def add_income(self, instance):
        self.add_transaction(self.safe_float(self.amount_input.text), self.reason_input.text, self.city_input.text)

    def add_expense(self, instance):
        self.add_transaction(-abs(self.safe_float(self.amount_input.text)), self.reason_input.text, self.city_input.text)

    # --- Graphique ---
    def update_graph(self, *args):
        balances = []
        current = 0
        for h in self.history:
            if ((self.current_city_filter is None or h.get("city") == self.current_city_filter) and
                (self.current_reason_filter is None or h.get("reason") == self.current_reason_filter)):
                current += h["amount"]
                balances.append(current)
        self.graph.draw_graph(balances)
        self.balance_label.text = f"Solde restant: {current:.2f} €"

    # --- Compte rendu ---
    def show_report(self, instance):
        total_gains = sum(h['amount'] for h in self.history if h['amount'] > 0)
        total_expenses = sum(-h['amount'] for h in self.history if h['amount'] < 0)
        by_reason = {}
        for h in self.history:
            if h['amount'] < 0:
                r = h.get('reason', '(sans motif)')
                by_reason[r] = by_reason.get(r, 0) + (-h['amount'])
        total_exp_for_pct = sum(by_reason.values()) or 1.0
        report_lines = [
            "--- Compte Rendu ---",
            f"Solde total: {self.balance:.2f} €",
            f"Total gains: {total_gains:.2f} €",
            f"Total dépenses: {total_expenses:.2f} €",
            f"Transactions: {len(self.history)}",
            "Classement dépenses:"
        ]
        for reason, amt in sorted(by_reason.items(), key=lambda x: x[1], reverse=True):
            pct = (amt / total_exp_for_pct) * 100.0
            report_lines.append(f" - {reason}: {amt:.2f} € ({pct:.1f}%)")
        report_text = "\n".join(report_lines)
        scroll = ScrollView(size_hint=(1, 1))
        label = Label(text=report_text, size_hint_y=None, valign='top', halign='left')
        label.bind(texture_size=label.setter('size'))
        label.text_size = (self.width * 0.85, None)
        scroll.add_widget(label)
        Popup(title="Compte Rendu", content=scroll, size_hint=(0.9, 0.9)).open()

    # --- Export CSV ---
    def export_csv(self, instance):
        try:
            path = os.path.join(App.get_running_app().user_data_dir, "budget_export.csv")
            with open(path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Date", "Montant", "Motif", "Ville", "Nécessité (%)"])
                for h in self.history:
                    writer.writerow([h["date"], h["amount"], h["reason"], h["city"], h.get("necessity", 0)])
            self.alert("✅ Export CSV", f"Historique exporté dans {path}")
        except Exception as e:
            self.alert("❌ Erreur", str(e))

    # --- Réinitialiser ---
    def reset_budget(self, instance):
        self.history = []
        self.balance = 0
        if hasattr(self, "city_filter_spinner"):
            self.city_filter_spinner.values = self.get_city_list()
        if hasattr(self, "reason_filter_spinner"):
            self.reason_filter_spinner.values = self.get_reason_list()
        self.update_graph()
        self.save_data()

    # --- Paramètres ---
    def open_settings(self, instance):
        layout = GridLayout(cols=2, row_force_default=True, row_default_height=50, spacing=5, size_hint_y=None)
        layout.bind(minimum_height=layout.setter('height'))
        sliders = {}
        for text, key, maxval in [("Plafond jour (€)", "ceil_day", 1000),
                                  ("Plafond semaine (€)", "ceil_week", 5000),
                                  ("Plafond mois (€)", "ceil_month", 20000)]:
            layout.add_widget(Label(text=text))
            s = Slider(min=0, max=maxval, value=self.settings.get(key, 0), step=1)
            sliders[key] = s
            layout.add_widget(s)
        layout.add_widget(Label(text="Code PIN:"))
        pin_input = TextInput(text=self.settings.get("pin_code", "0000"), multiline=False, password=True)
        layout.add_widget(pin_input)
        layout.add_widget(Label(text="Mapping nécessité (JSON):"))
        map_input = TextInput(text=json.dumps(self.settings.get("necessity_map", DEFAULT_NECESSITY_MAP), ensure_ascii=False),
                              multiline=True, size_hint_y=None, height=150)
        layout.add_widget(map_input)
        btn_save = Button(text="Sauvegarder", size_hint_y=None, height=50)
        layout.add_widget(Label()); layout.add_widget(btn_save)
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(layout)
        popup = Popup(title="Paramètres", content=scroll, size_hint=(0.9, 0.9))

        def save_settings(instance):
            for key, s in sliders.items():
                self.settings[key] = s.value
            self.settings["pin_code"] = pin_input.text.strip()
            try:
                self.settings["necessity_map"] = json.loads(map_input.text)
            except:
                self.settings["necessity_map"] = DEFAULT_NECESSITY_MAP.copy()
            self.save_settings()
            popup.dismiss()
            self.alert("✅ Paramètres sauvegardés", "Vos réglages ont été sauvegardés")

        btn_save.bind(on_release=save_settings)
        popup.open()

    # --- Alert ---
    def alert(self, title, message):
        Popup(title=title, content=Label(text=message), size_hint=(0.7, 0.4)).open()


class StreetArtistBudgetApp(App):
    def build(self):
        return BudgetManager()


if __name__ == "__main__":
    StreetArtistBudgetApp().run()